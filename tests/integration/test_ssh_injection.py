"""Integration tests for end-to-end SSH bot commit and push (T020/T021).

These exercise the whole pipeline in a real child process: global configuration ->
remote matching -> identity stamping -> ``GIT_SSH_COMMAND`` construction -> the
environment the child Git actually receives. The builder-level spellings of
``build_ssh_command`` are covered by ``tests/unit/test_credential_injector.py``;
what is asserted here is that the value survives configuration parsing, ``~``
expansion and process spawning intact on the running platform.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

#: The null device Git's SSH invocation must be pinned to on this platform, so the
#: operator's ``~/.ssh/config`` cannot contribute an additional identity.
_NULL_DEVICE = "NUL" if os.name == "nt" else "/dev/null"

_SSH_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
"""


def shim_env(**overrides: str | None) -> dict[str, str]:
    """Copy the (already sanitized) test environment for a shim subprocess."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["GIT_SHIM_SHADOW"] = "1"
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def run_shim(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the ``git`` shim entry point in a real child process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        input="",
        capture_output=True,
        text=True,
        env=shim_env() if env is None else env,
        cwd=None if cwd is None else str(cwd),
        check=False,
        timeout=120,
    )


def agent_env(isolated_env, **overrides: str | None) -> dict[str, str]:
    """Environment of an agent-driven invocation with no ambient Git identity."""
    return shim_env(
        AGENT_ID="agent-worker-1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(isolated_env.home / ".gitconfig-absent"),
        **overrides,
    )


def write_key(isolated_env, relative: str) -> Path:
    """Create a placeholder private key inside the isolated profile."""
    key = isolated_env.home / relative
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-real-key\n", encoding="utf-8")
    return key


def recorded_signature(repo) -> str:
    """``author|committer`` of the repository's tip commit, via the real Git."""
    return repo.git("log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout.strip()


def test_agent_commit_stamps_the_bot_as_author_and_committer(isolated_env, temp_repo):
    isolated_env.write_config(_SSH_CONFIG)
    write_key(isolated_env, ".ssh/acme_bot_ed25519")
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim(
        "commit",
        "--allow-empty",
        "-m",
        "agent work",
        env=agent_env(isolated_env, GIT_SHIM_REAL_PATH=repo.git_binary),
        cwd=repo.path,
    )

    assert result.returncode == 0, result.stderr
    assert recorded_signature(repo) == ("Acme Bot <bot@acme.invalid>|Acme Bot <bot@acme.invalid>")


def test_agent_commit_outranks_a_repository_configured_human_identity(isolated_env, temp_repo):
    isolated_env.write_config(_SSH_CONFIG)
    write_key(isolated_env, ".ssh/acme_bot_ed25519")
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})
    repo.config("user.name", "Operator")
    repo.config("user.email", "operator@example.invalid")

    result = run_shim(
        "commit",
        "--allow-empty",
        "-m",
        "agent work",
        env=agent_env(isolated_env, GIT_SHIM_REAL_PATH=repo.git_binary),
        cwd=repo.path,
    )

    assert result.returncode == 0, result.stderr
    assert recorded_signature(repo) == ("Acme Bot <bot@acme.invalid>|Acme Bot <bot@acme.invalid>")


def test_agent_push_invokes_ssh_with_the_isolated_bot_key(isolated_env, fake_git, temp_repo):
    isolated_env.write_config(_SSH_CONFIG)
    key = write_key(isolated_env, ".ssh/acme_bot_ed25519")
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim("push", "origin", "main", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == ["push", "origin", "main"]
    command = call.env["GIT_SSH_COMMAND"]
    assert command == (
        f"ssh -i {str(key).replace(os.sep, '/')} -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new -F {_NULL_DEVICE}"
    )


def test_injected_ssh_command_survives_native_paths_with_spaces(isolated_env, fake_git, temp_repo):
    key = write_key(isolated_env, ".ssh/acme bot/id_ed25519")
    isolated_env.write_config(
        _SSH_CONFIG.replace('"~/.ssh/acme_bot_ed25519"', '"~/.ssh/acme bot/id_ed25519"')
    )
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim("push", "origin", "main", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    command = fake_git.last_call.env["GIT_SSH_COMMAND"]
    # Git evaluates GIT_SSH_COMMAND in a POSIX-like shell on every platform, so a
    # Windows key path must arrive forward-slashed and quoted rather than escaped away.
    assert "\\" not in command
    assert f"-i '{str(key).replace(os.sep, '/')}'" in command
    assert command.endswith(f"-F {_NULL_DEVICE}")


def test_agent_reads_get_the_bot_key_without_an_authorship_stamp(isolated_env, fake_git, temp_repo):
    isolated_env.write_config(_SSH_CONFIG)
    write_key(isolated_env, ".ssh/acme_bot_ed25519")
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim("fetch", "origin", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert "GIT_SSH_COMMAND" in call.env
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME"):
        assert name not in call.env
