"""Execution engine and operator CLI for the Git author identity shim.

Every ``git`` invocation an operator or an agent makes flows through this module,
so only ``os`` and ``sys`` are imported eagerly. ``subprocess``, ``signal``,
``argparse``, ``json``, the configuration loader (and its ``tomllib``
dependency) and the credential builders are imported inside the branch that
needs them. The explicit ``UV_SHIM_GIT_MODE=human`` fast path therefore reaches
the real Git binary without reading a single configuration byte.

Repository inspection (remotes, tracked upstream, repository-local config) is
done by reading the repository's own ``config``/``HEAD`` files rather than by
spawning ``git config --list``: remotes are never defined in system or global
scope, and a second process on the critical path would dominate the shim's
latency budget.
"""

import os
import sys

_IS_WINDOWS = os.name == "nt"

MODE_ENV = "UV_SHIM_GIT_MODE"
EXPLAIN_ENV = "UV_SHIM_GIT_EXPLAIN"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_AUTHOR_ENV = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE")

#: Git global options selecting which repository is operated on.
_REPO_OPTIONS = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})
#: Remaining Git global options that consume a following argument.
_VALUED_OPTIONS = frozenset(
    {"-c", "--config-env", "--exec-path", "--super-prefix", "--attr-source"}
)


class ShimError(Exception):
    """A shim-level failure that must abort the invocation before Git runs."""


# --------------------------------------------------------------------------------------
# Signal forwarding
# --------------------------------------------------------------------------------------


def forwardable_signals() -> tuple[int, ...]:
    """Terminating signals the shim takes over while a child Git is running."""
    import signal

    names = ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGBREAK")
    return tuple(getattr(signal, name) for name in names if getattr(signal, name, None) is not None)


class SignalForwarder:
    """Relay terminating signals to the child Git process for its lifetime.

    On POSIX the signal is re-sent to the child, so ``kill`` against the shim's
    own pid still terminates Git. On Windows the console has already broadcast
    ``Ctrl+C``/``Ctrl+Break`` to every process attached to it, child included;
    there the handler only has to keep this process alive long enough to report
    the child's real exit status instead of dying with ``KeyboardInterrupt``.
    """

    __slots__ = ("_process", "_restore")

    def __init__(self, process: object) -> None:
        self._process = process
        self._restore: dict[int, object] = {}

    def __enter__(self) -> "SignalForwarder":
        import signal

        for signum in forwardable_signals():
            try:
                self._restore[signum] = signal.signal(signum, self._forward)
            except (OSError, ValueError):
                continue  # not settable on this platform
        return self

    def __exit__(self, *exc_info: object) -> bool:
        import signal

        for signum, handler in self._restore.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                continue
        self._restore.clear()
        return False

    def _forward(self, signum: int, frame: object) -> None:
        if _IS_WINDOWS:
            return
        try:
            self._process.send_signal(signum)
        except (OSError, ValueError):
            pass  # the child already exited


# --------------------------------------------------------------------------------------
# Repository inspection
# --------------------------------------------------------------------------------------


def _global_options(argv: list[str]) -> tuple[str, str | None]:
    """Return ``(effective_cwd, explicit_git_dir)`` from Git's global options.

    ``-C`` may repeat and each occurrence is relative to the previous one, and
    ``--git-dir`` is relative to the ``-C`` directories seen before it, so the
    options are applied in argv order.
    """
    cwd = os.getcwd()
    git_dir: str | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--" or not argument.startswith("-"):
            break
        name, separator, value = argument.partition("=")
        if not separator and (name in _REPO_OPTIONS or name in _VALUED_OPTIONS):
            if index + 1 >= len(argv):
                break
            value = argv[index + 1]
            index += 1
        if value:
            if name == "-C":
                cwd = os.path.abspath(os.path.join(cwd, value))
            elif name == "--git-dir":
                git_dir = os.path.abspath(os.path.join(cwd, value))
        index += 1
    return cwd, git_dir


def _resolve_git_file(path: str) -> str | None:
    """Follow a ``.git`` *file* (``gitdir: <path>``) into the real Git directory."""
    try:
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return None
    key, separator, target = content.strip().partition(":")
    if key != "gitdir" or not separator or not target.strip():
        return None
    return os.path.abspath(os.path.join(os.path.dirname(path), target.strip()))


def _locate_repository(argv: list[str], env) -> tuple[str | None, str | None]:
    """Return ``(git_dir, worktree_root)`` for this invocation, or ``(None, None)``."""
    cwd, explicit = _global_options(argv)
    candidate = explicit or env.get("GIT_DIR")
    if candidate:
        git_dir = os.path.abspath(os.path.join(cwd, candidate))
        return git_dir, cwd if os.path.isdir(git_dir) else None

    directory = cwd
    while True:
        dot_git = os.path.join(directory, ".git")
        if os.path.isdir(dot_git):
            return dot_git, directory
        if os.path.isfile(dot_git):
            return _resolve_git_file(dot_git), directory
        if os.path.isfile(os.path.join(directory, "HEAD")) and os.path.isdir(
            os.path.join(directory, "objects")
        ):
            return directory, None  # bare repository
        parent = os.path.dirname(directory)
        if parent == directory:
            return None, None
        directory = parent


def _common_dir(git_dir: str) -> str:
    """Linked worktrees keep ``config`` in the shared common directory."""
    marker = os.path.join(git_dir, "commondir")
    try:
        with open(marker, encoding="utf-8") as handle:
            relative = handle.read().strip()
    except OSError:
        return git_dir
    return os.path.abspath(os.path.join(git_dir, relative)) if relative else git_dir


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_git_config(
    path: str,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, str],
    list[tuple[str, str]],
    list[tuple[str, str]],
]:
    """Extract remote destinations, branch tracking, and URL rewrite rules."""

    remotes: dict[str, str] = {}
    push_urls: dict[str, str] = {}
    branch_remotes: dict[str, str] = {}
    instead_of: list[tuple[str, str]] = []
    push_instead_of: list[tuple[str, str]] = []
    empty = (remotes, push_urls, branch_remotes, instead_of, push_instead_of)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return empty

    section: str | None = None
    subsection: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            end = line.find("]")
            if end == -1:
                continue
            name, _, rest = line[1:end].strip().partition(" ")
            section = name.lower()
            subsection = _unquote(rest.strip()) or None
            continue
        if subsection is None or section not in ("remote", "branch", "url"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip().lower()
        value = _unquote(value.strip())
        if not value:
            continue
        if section == "remote":
            if key == "url":
                remotes[subsection] = value
            elif key == "pushurl":
                push_urls[subsection] = value
        elif section == "branch" and key == "remote":
            branch_remotes[subsection] = value
        elif section == "url":
            if key == "insteadof":
                instead_of.append((value, subsection))
            elif key == "pushinsteadof":
                push_instead_of.append((value, subsection))
    return empty


def _current_branch(git_dir: str) -> str | None:
    try:
        with open(os.path.join(git_dir, "HEAD"), encoding="utf-8") as handle:
            head = handle.read().strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    return head[len(prefix) :] if head.startswith(prefix) else None


def _tracked_remote(git_dir: str, branch_remotes: dict[str, str]) -> str | None:
    if not branch_remotes:
        return None
    branch = _current_branch(git_dir)
    return None if branch is None else branch_remotes.get(branch)


def _primary_remote(remotes: dict[str, str], tracked: str | None) -> str | None:
    """The remote a local write is attributed to (mirrors the matcher's policy)."""
    if tracked is not None and tracked in remotes:
        return tracked
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return next(iter(remotes))
    return None


def _command_index(argv: list[str]) -> int | None:
    """Locate the Git subcommand after global options."""

    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            return index + 1 if index + 1 < len(argv) else None
        if not argument.startswith("-"):
            return index
        name, separator, _ = argument.partition("=")
        if not separator and (name in _REPO_OPTIONS or name in _VALUED_OPTIONS):
            index += 2
        else:
            index += 1
    return None


def _command_name(argv: list[str]) -> str | None:
    index = _command_index(argv)
    return None if index is None else argv[index]


def _rewrite_url(url: str, rules: list[tuple[str, str]]) -> str:
    """Apply Git's longest-prefix URL rewrite rule without contacting a host."""

    matches = [
        (len(prefix), position, prefix, replacement)
        for position, (prefix, replacement) in enumerate(rules)
        if url.startswith(prefix)
    ]
    if not matches:
        return url
    _, _, prefix, replacement = max(matches)
    return replacement + url[len(prefix) :]


def _push_destination(
    argv: list[str],
    remotes: dict[str, str],
    push_urls: dict[str, str],
    primary: str | None,
    instead_of: list[tuple[str, str]],
    push_instead_of: list[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Return the effective push URL and configured remote name, if any."""

    index = _command_index(argv)
    if index is None or argv[index] != "push":
        return None, None

    repository: str | None = None
    option_index = index + 1
    value_options = frozenset({"--receive-pack", "--exec", "-e", "--push-option", "-o"})
    while option_index < len(argv):
        argument = argv[option_index]
        if argument == "--":
            repository = argv[option_index + 1] if option_index + 1 < len(argv) else None
            break
        name, separator, value = argument.partition("=")
        if name == "--repo":
            if separator:
                repository = value
            elif option_index + 1 < len(argv):
                repository = argv[option_index + 1]
            break
        if argument.startswith("-"):
            option_index += 2 if not separator and name in value_options else 1
            continue
        repository = argument
        break

    remote_name = repository if repository in remotes or repository in push_urls else None
    if repository is None:
        remote_name = primary
    if remote_name is not None:
        explicit_push_url = remote_name in push_urls
        url = push_urls.get(remote_name, remotes.get(remote_name))
    else:
        explicit_push_url = False
        url = repository
    if url is None:
        return None, remote_name
    rules = instead_of if explicit_push_url else [*instead_of, *push_instead_of]
    return _rewrite_url(url, rules), remote_name


def _transport(url: str | None) -> str:
    """Classify a remote URL's transport without contacting it."""
    if not url:
        return "local"
    lowered = url.lower()
    if lowered.startswith(("https://", "http://")):
        return "https"
    if lowered.startswith(("ssh://", "git+ssh://")):
        return "ssh"
    if lowered.startswith("file://"):
        return "local"
    if "://" in lowered:
        return "unknown"
    host, separator, _ = url.split("/", 1)[0].partition(":")
    # ``C:/repos/x`` is a local Windows path; ``git@host:org/repo`` is scp-like SSH.
    return "ssh" if separator and len(host) > 1 else "local"


# --------------------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------------------


class Resolution:
    """A resolved invocation: the inspectable plan plus its execution vectors."""

    __slots__ = ("plan", "detected_marker", "canonical_url", "env_updates", "git_options")

    def __init__(
        self,
        plan,
        *,
        detected_marker: str | None = None,
        canonical_url: str | None = None,
        env_updates: dict[str, str | None] | None = None,
        git_options: list[str] | None = None,
    ) -> None:
        self.plan = plan
        self.detected_marker = detected_marker
        self.canonical_url = canonical_url
        self.env_updates: dict[str, str | None] = env_updates or {}
        self.git_options: list[str] = git_options or []


def resolve(argv: list[str], env=None) -> Resolution:
    """Decide identity, credentials and refusals for one Git invocation."""
    environ = os.environ if env is None else env

    from uv_shims.git.agent_detection import resolve_identity_mode
    from uv_shims.git.commit_authorship_classifier import is_write_command
    from uv_shims.git.config import ConfigError, default_config_path, load_config
    from uv_shims.git.data_models import IdentityMode, InvocationPlan

    config_path = default_config_path(environ)
    try:
        config = load_config(config_path)
    except ConfigError as error:
        raise ShimError(str(error)) from error
    try:
        mode, marker = resolve_identity_mode(config, environ)
    except ValueError as error:
        raise ShimError(f"{MODE_ENV} must be one of: auto, agent, human") from error

    is_write = is_write_command(argv)
    if mode is not IdentityMode.AGENT:
        return Resolution(
            InvocationPlan(mode=IdentityMode.HUMAN, is_write=is_write),
            detected_marker=marker,
        )
    return _resolve_agent(argv, environ, config, config_path, marker, is_write)


def _identity_id(identity) -> str:
    return getattr(identity, "id", str(identity))


def _refusal_reason(result, canonical: str | None, remotes: dict[str, str], config_path) -> str:
    remedy = (
        f"add an [[identities]] entry whose match_patterns cover it in {config_path}, "
        f"or rerun with {MODE_ENV}=human"
    )
    if result.is_ambiguous:
        names = ", ".join(sorted(_identity_id(item) for item in result.candidates))
        return (
            f"{canonical} matches multiple bot identities with equal specificity "
            f"({names}); make one match_patterns entry more specific in {config_path}"
        )
    if result.is_conflict:
        names = ", ".join(sorted(_identity_id(item) for item in result.candidates))
        return (
            f"this repository's remotes resolve to conflicting bot identities ({names}); "
            "set the branch's upstream remote or name a single identity in .git-shim.toml"
        )
    if not remotes:
        return (
            "this repository has no remote, so no bot identity can be matched; "
            f"add a remote or rerun with {MODE_ENV}=human"
        )
    return f"no bot identity matches {canonical}; {remedy}"


def _select_local_identity(config, worktree_root: str | None):
    """Honor a *trusted* repository-local ``.git-shim.toml`` (US8)."""
    if worktree_root is None:
        return None, None, None

    from uv_shims.git.config import ConfigError, load_local_config
    from uv_shims.git.repo_config_trust import LOCAL_CONFIG_NAME

    path = os.path.join(worktree_root, LOCAL_CONFIG_NAME)
    if not os.path.isfile(path):
        return None, None, None
    try:
        local = load_local_config(path)
    except ConfigError as error:
        raise ShimError(str(error)) from error
    if local is None:  # absent from the trust registry, or tampered with
        return None, None, None

    identity = None
    if local.identity is not None:
        identity = next((item for item in config.identities if item.id == local.identity), None)
        if identity is None:
            raise ShimError(
                f"{path} selects unknown identity {local.identity!r}; "
                "add it to the global configuration or update the local file"
            )
    return identity, local.name, local.email


def _https_source(credential) -> str:
    if credential.token_env_var is not None:
        return f"env:{credential.token_env_var}"
    if credential.token_file is not None:
        return f"file:{credential.token_file}"
    return "command"


def _sequencer_author(argv: list[str], env) -> tuple[str, str, str] | None:
    """Read the original author of a conflicted cherry-pick/rebase commit."""

    index = _command_index(argv)
    if index is None or argv[index] != "commit":
        return None

    import subprocess

    real_git = _real_git(env)
    prefix = argv[:index]
    for revision in ("REBASE_HEAD", "CHERRY_PICK_HEAD"):
        process = subprocess.run(  # noqa: S603
            [
                real_git,
                *prefix,
                "show",
                "-s",
                "--format=%an%x00%ae%x00%aI",
                revision,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=dict(env),
            check=False,
        )
        if process.returncode == 0:
            fields = process.stdout.rstrip("\r\n").split("\0")
            if len(fields) == 3 and all(fields):
                return fields[0], fields[1], fields[2]
    return None


def _resolve_agent(argv, env, config, config_path, marker, is_write) -> Resolution:
    from uv_shims.git.data_models import CommitClass, IdentityMode, InvocationPlan
    from uv_shims.git.repo_identity_matcher import canonicalize_url, match_identity

    git_dir, worktree_root = _locate_repository(argv, env)
    remotes: dict[str, str] = {}
    push_urls: dict[str, str] = {}
    branch_remotes: dict[str, str] = {}
    instead_of: list[tuple[str, str]] = []
    push_instead_of: list[tuple[str, str]] = []
    if git_dir is not None:
        config_file = os.path.join(_common_dir(git_dir), "config")
        remotes, push_urls, branch_remotes, instead_of, push_instead_of = _parse_git_config(
            config_file
        )
    tracked = _tracked_remote(git_dir, branch_remotes) if git_dir is not None else None
    primary = _primary_remote(remotes, tracked)
    is_push = _command_name(argv) == "push"

    destination, destination_remote = _push_destination(
        argv, remotes, push_urls, primary, instead_of, push_instead_of
    )
    if is_push:
        selection_name = destination_remote or "<push-destination>"
        selection_remotes = {selection_name: destination} if destination is not None else {}
        selection_primary = selection_name
        url = destination
    else:
        selection_remotes = remotes
        selection_primary = tracked
        url = remotes.get(primary) if primary is not None else None

    transport = _transport(url)
    canonical = None
    if url:
        try:
            canonical = canonicalize_url(url)
        except ValueError:
            canonical = None
    host = None if canonical is None else canonical.host
    canonical_url = None if canonical is None else canonical.canonical

    def refuse(reason: str, matched_identity=None) -> Resolution:
        return Resolution(
            InvocationPlan(
                mode=IdentityMode.AGENT,
                is_write=is_write,
                matched_identity=matched_identity,
                target_host=host,
                transport=transport,
                fail_closed=is_write,
                failure_reason=reason,
            ),
            detected_marker=marker,
            canonical_url=canonical_url,
        )

    identity, override_name, override_email = _select_local_identity(config, worktree_root)
    if identity is None:
        result = match_identity(selection_remotes, config.identities, selection_primary)
        identity = result.identity
    elif is_push:
        result = match_identity(selection_remotes, (identity,), selection_primary)
        identity = result.identity
    else:
        result = None
    if identity is None:
        safe_target = canonical_url
        if safe_target is None and (primary is not None or destination_remote is not None):
            remote_name = destination_remote or primary
            safe_target = f"remote {remote_name!r} with an invalid URL"
        reason = _refusal_reason(result, safe_target, selection_remotes, config_path)
        return refuse(reason)

    name = override_name or identity.name
    email = override_email or identity.email

    env_updates: dict[str, str | None] = {}
    git_options: list[str] = []
    commit_class = None
    author = None
    committer = None

    if is_write:
        from uv_shims.git.commit_authorship_classifier import classify_commit

        commit_class = classify_commit(argv)
        if commit_class is CommitClass.CARRYING:
            # Drop any caller-set author so Git restores the replayed commit's own.
            for variable in _AUTHOR_ENV:
                env_updates[variable] = None
            original = _sequencer_author(argv, env)
            if original is not None:
                env_updates["GIT_AUTHOR_NAME"] = original[0]
                env_updates["GIT_AUTHOR_EMAIL"] = original[1]
                env_updates["GIT_AUTHOR_DATE"] = original[2]
        else:
            env_updates["GIT_AUTHOR_NAME"] = name
            env_updates["GIT_AUTHOR_EMAIL"] = email
            env_updates["GIT_AUTHOR_DATE"] = None
            author = (name, email)
        env_updates["GIT_COMMITTER_NAME"] = name
        env_updates["GIT_COMMITTER_EMAIL"] = email
        committer = (name, email)

    credential_source = None
    if transport == "ssh":
        if identity.ssh is None:
            if is_push:
                return refuse(
                    f"identity {identity.id!r} has no SSH credential for {canonical_url}",
                    identity,
                )
        else:
            from uv_shims.git.credential_injector import build_ssh_command

            key_file = os.path.expanduser(os.fspath(identity.ssh.key_file))
            env_updates["GIT_SSH_COMMAND"] = build_ssh_command(
                key_file, strict_host_checking=identity.ssh.strict_host_checking
            )
            credential_source = f"ssh:{key_file}"
    elif transport == "https":
        if identity.https is None:
            if is_push:
                return refuse(
                    f"identity {identity.id!r} has no HTTPS credential for {canonical_url}",
                    identity,
                )
        elif host:
            from uv_shims.git.credential_injector import (
                CredentialError,
                build_https_credential_flags,
            )

            try:
                git_options.extend(build_https_credential_flags(identity, host))
            except CredentialError as error:
                return refuse(str(error), identity)
            credential_source = _https_source(identity.https)

    return Resolution(
        InvocationPlan(
            mode=IdentityMode.AGENT,
            is_write=is_write,
            matched_identity=identity,
            commit_class=commit_class,
            author=author,
            committer=committer,
            target_host=host,
            transport=transport,
            credential_source=credential_source,
        ),
        detected_marker=marker,
        canonical_url=canonical_url,
        env_updates=env_updates,
        git_options=git_options,
    )


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------


def _real_git(env) -> str:
    from uv_shims.git.real_git_discovery import find_real_git

    try:
        return find_real_git(env=env)
    except FileNotFoundError as error:
        raise ShimError(str(error)) from error


def _preflight_credentials(resolution: Resolution, argv: list[str]) -> None:
    """Verify referenced credentials immediately before a network write."""

    if _command_name(argv) != "push" or resolution.plan.transport != "ssh":
        return
    identity = resolution.plan.matched_identity
    if identity is None or identity.ssh is None:
        return

    from uv_shims.git.credential_injector import CredentialError, validate_ssh_key

    try:
        validate_ssh_key(identity.ssh.key_file)
    except CredentialError as error:
        raise ShimError(str(error)) from error


def _spawn(
    real_git: str,
    argv: list[str],
    env,
    *,
    env_updates: dict[str, str | None] | None = None,
    git_options: list[str] | None = None,
) -> int:
    """Run the real Git binary with inherited stdio and return its exit code.

    ``Popen`` rather than ``subprocess.run`` because the child handle is needed
    to forward terminating signals; ``wait()`` propagates the exit status just as
    faithfully, including on Windows where ``os.execv`` would lose it.
    """
    import subprocess

    from uv_shims.git.real_git_discovery import inject_continuation

    child_env = inject_continuation(env)
    for name, value in (env_updates or {}).items():
        if value is None:
            child_env.pop(name, None)
        else:
            child_env[name] = value

    command = [real_git, *(git_options or ()), *argv]
    try:
        process = subprocess.Popen(command, env=child_env)  # noqa: S603
    except OSError as error:
        raise ShimError(f"cannot execute {real_git}: {error}") from error
    with SignalForwarder(process):
        return process.wait()


def _fail(message: str) -> int:
    sys.stderr.write(f"git-shim: {message}\n")
    return 1


def run_git(argv: list[str] | None = None, env=None) -> int:
    """Execute one ``git`` invocation through the shim and return its exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    explain = environ.get(EXPLAIN_ENV, "").strip().lower() in _TRUTHY

    try:
        from uv_shims.git.real_git_discovery import is_continuation

        if is_continuation(environ) and not explain:
            if environ.get(MODE_ENV) == "human":
                return _spawn(_real_git(environ), arguments, environ)
            from uv_shims.git.commit_authorship_classifier import is_write_command

            if not is_write_command(arguments):
                return _spawn(_real_git(environ), arguments, environ)
            resolution = resolve(arguments, environ)
            if resolution.plan.fail_closed:
                return _fail(resolution.plan.failure_reason)
            _preflight_credentials(resolution, arguments)
            credential_updates = {
                name: value
                for name, value in resolution.env_updates.items()
                if name not in (*_AUTHOR_ENV, "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
            }
            return _spawn(
                _real_git(environ),
                arguments,
                environ,
                env_updates=credential_updates,
                git_options=resolution.git_options,
            )

        if environ.get(MODE_ENV) == "human" and not explain:
            # Fast path: nothing is read, nothing is injected, nothing is mutated.
            return _spawn(_real_git(environ), arguments, environ)

        resolution = resolve(arguments, environ)
        if explain:
            sys.stdout.write(render_plan(resolution))
            return 0
        if resolution.plan.fail_closed:
            return _fail(resolution.plan.failure_reason)
        _preflight_credentials(resolution, arguments)
        return _spawn(
            _real_git(environ),
            arguments,
            environ,
            env_updates=resolution.env_updates,
            git_options=resolution.git_options,
        )
    except ShimError as error:
        return _fail(str(error))


# --------------------------------------------------------------------------------------
# ``git-shim`` operator CLI
# --------------------------------------------------------------------------------------


def _person(pair: tuple[str, str] | None) -> str:
    return "-" if pair is None else f"{pair[0]} <{pair[1]}>"


def _person_object(pair: tuple[str, str] | None) -> dict[str, str]:
    return {} if pair is None else {"name": pair[0], "email": pair[1]}


def _operation_label(plan) -> str:
    if not plan.is_write:
        return "read"
    return "write" if plan.commit_class is None else f"{plan.commit_class} commit"


def render_plan(resolution: Resolution) -> str:
    """Render a resolved plan as operator-facing text; secrets are never included."""
    plan = resolution.plan
    identity = plan.matched_identity
    marker = resolution.detected_marker
    detected = "" if marker is None else f" (detected via {marker})"
    lines = [
        "=== Git Author Identity Shim: Resolved Plan ===",
        f"Mode:            {plan.mode}{detected}",
        f"Repository:      {resolution.canonical_url or '-'}",
        f"Target Host:     {plan.target_host or '-'}",
        f"Matched Profile: {'-' if identity is None else identity.id}",
        f"Operation:       {_operation_label(plan)}",
        f"Author:          {_person(plan.author)}",
        f"Committer:       {_person(plan.committer)}",
        f"Transport:       {plan.transport or '-'}",
        f"Credential:      {plan.credential_source or '-'}",
        f"Write Permitted: {'NO' if plan.fail_closed else 'YES'}",
    ]
    if plan.failure_reason:
        lines.append(f"Reason:          {plan.failure_reason}")
    lines.append("=" * 47)
    return "\n".join(lines) + "\n"


def plan_as_dict(resolution: Resolution) -> dict:
    """Render a resolved plan as the JSON object documented in ``contracts/cli.md``."""
    plan = resolution.plan
    identity = plan.matched_identity
    ssh_key = None
    if identity is not None and identity.ssh is not None:
        ssh_key = os.fspath(identity.ssh.key_file)
    operation = "read"
    if plan.is_write:
        operation = "unknown" if plan.commit_class is None else str(plan.commit_class)
    https_source = None
    if plan.credential_source and not plan.credential_source.startswith("ssh:"):
        https_source = plan.credential_source
    return {
        "mode": str(plan.mode),
        "detected_marker": resolution.detected_marker,
        "matched_identity_id": None if identity is None else identity.id,
        "repository_canonical_url": resolution.canonical_url,
        "target_host": plan.target_host,
        "is_write": plan.is_write,
        "operation_class": operation,
        "author": _person_object(plan.author),
        "committer": _person_object(plan.committer),
        "transport": plan.transport or "unknown",
        "ssh_key_path": ssh_key,
        "https_token_source": https_source,
        "write_permitted": not plan.fail_closed,
        "failure_reason": plan.failure_reason,
    }


def _explain(git_args: list[str], as_json: bool) -> int:
    resolution = resolve(list(git_args), os.environ)
    if as_json:
        import json

        sys.stdout.write(json.dumps(plan_as_dict(resolution), indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_plan(resolution))
    return 0


def _list_identities() -> int:
    from uv_shims.git.config import ConfigError, default_config_path, load_config

    try:
        config = load_config(default_config_path(os.environ))
    except ConfigError as error:
        raise ShimError(str(error)) from error
    if not config.identities:
        sys.stdout.write("no bot identities configured\n")
        return 0
    for identity in config.identities:
        patterns = ", ".join(identity.match_patterns)
        sys.stdout.write(f"{identity.id}\t{identity.name} <{identity.email}>\t{patterns}\n")
    return 0


def _set_trust(command: str, path: str | None) -> int:
    from uv_shims.git.repo_config_trust import (
        LOCAL_CONFIG_NAME,
        TrustError,
        trust_config,
        untrust_config,
    )

    target = path or LOCAL_CONFIG_NAME
    try:
        if command == "trust":
            sys.stdout.write(f"trusted {target} (sha256:{trust_config(target)})\n")
        elif untrust_config(target):
            sys.stdout.write(f"untrusted {target}\n")
        else:
            sys.stdout.write(f"not trusted: {target}\n")
    except TrustError as error:
        sys.stderr.write(f"git-shim: {error}\n")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """``git-shim`` operator CLI: inspect plans and manage the trust registry."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="git-shim",
        description="Inspect and manage the Git author identity shim.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    explain = subcommands.add_parser("explain", help="show the resolved plan without running Git")
    explain.add_argument(
        "--json", action="store_true", dest="as_json", help="emit machine-readable JSON"
    )
    # ``REMAINDER`` so option-like Git arguments (``-m``, ``--amend``) are captured
    # for the plan instead of being rejected as unknown ``git-shim`` options.
    explain.add_argument(
        "git_args",
        nargs=argparse.REMAINDER,
        metavar="GIT_ARG",
        help="Git arguments to resolve a plan for",
    )

    subcommands.add_parser("list-identities", help="list the configured bot identities")

    for name, help_text in (
        ("trust", "record a repository-local .git-shim.toml as trusted"),
        ("untrust", "revoke trust for a repository-local .git-shim.toml"),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("path", nargs="?", default=None, help="path to .git-shim.toml")

    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        if args.command == "explain":
            return _explain(args.git_args, args.as_json)
        if args.command == "list-identities":
            return _list_identities()
        return _set_trust(args.command, args.path)
    except ShimError as error:
        return _fail(str(error))


if __name__ == "__main__":
    sys.exit(main())
