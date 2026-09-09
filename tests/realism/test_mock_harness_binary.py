"""Auth-free realism gate: a *real* ``claude`` binary, fed a mock model, still
resolves ``git`` to the shim and stamps the bot.

The sibling :mod:`test_real_harness_binary` proves the same claim with a live,
authenticated ``omp`` -- but that needs credentials, quota and network egress,
so it can only run on a self-hosted runner. This module removes every one of
those dependencies while keeping the *real* harness binary in the loop:

* it starts a loopback mock LLM endpoint (:mod:`mock_llm`) that speaks the
  Anthropic Messages API and returns one canned ``Bash`` tool call -- a
  ``git commit`` -- then a stop turn;
* it launches the real ``claude`` binary in print mode, pointed at that mock
  with a **dummy** API key (``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_API_KEY``), so
  no credential is validated and nothing leaves ``127.0.0.1``;
* ``claude`` runs the command through its own Bash tool runtime, which spawns
  ``git`` -- and PATH's ``git`` is the shim.

The only ground truth asserted is the resulting commit's author/committer, read
back with real Git. Because this needs neither auth nor network, it runs on a
stock GitHub-hosted runner -- see the ``realism-hosted`` job in
``.github/workflows/realism-hosted.yml``, which is validated locally with
``act``/``gh act``.

Opt in with::

    GIT_SHIM_REALISM_MOCK=1 uvx pytest tests/realism -m realism_mock -v

(optionally ``CLAUDE_BIN=/path/to/claude`` when it is not on ``PATH``). Once
opted in, a missing binary or a non-shim ``git`` on ``PATH`` is a hard failure,
never a skip, so a misconfigured runner cannot go green having proven nothing.
The un-opted-in case is the only skip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Import the mock from this directory (tests/ is not an installed package).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_llm  # noqa: E402

pytestmark = pytest.mark.realism_mock

# Environment as it looked at import time, before conftest's autouse ``clean_env``
# strips ``GIT_*``/``CLAUDE_*``. The launched harness needs the operator's real
# profile, so subprocesses are built from this pristine copy, not ``os.environ``.
_PRISTINE_ENV: dict[str, str] = dict(os.environ)

_TRUTHY = {"1", "true", "yes", "on"}
_OPT_IN = _PRISTINE_ENV.get("GIT_SHIM_REALISM_MOCK", "").strip().lower() in _TRUTHY

_BOT_NAME = "CI Realism Bot"
_BOT_EMAIL = "ci-bot@test-org.invalid"
_HUMAN_NAME = "Human Operator"
_HUMAN_EMAIL = "human@example.invalid"
_SUBJECT = "realism-gate empty commit"
_ORIGIN = "https://github.com/DgxSparkLabs/realism-gate.git"

_CONFIG = f"""\
[settings]
default_mode = "auto"
custom_agent_markers = ["CLAUDECODE", "OMPCODE", "AI_AGENT"]

[[identities]]
id = "ci-bot"
name = "{_BOT_NAME}"
email = "{_BOT_EMAIL}"
match_patterns = ["github.com/DgxSparkLabs/*"]
"""

# ``claude`` self-exports these into its Bash tool children (verified: CLAUDECODE=1
# and AI_AGENT=claude-code_...). They are stripped from the *parent* env handed to
# claude so the git child's markers can only come from claude itself -- genuine
# auto-detection, not leakage from the CI process.
_STRIP = (
    "GIT_SHIM_MODE", "GIT_SHIM_EXPLAIN", "AGENT_ID", "CLAUDECODE", "OMPCODE",
    "CLAUDE_CODE", "AI_AGENT", "CURSOR_AGENT", "OPENAI_AGENT", "CODEX_SANDBOX",
    "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
)

# Traffic that would otherwise reach the real Anthropic edge even with a custom
# base URL (fast-mode probe, telemetry, autoupdater). Disabled so the run is
# genuinely offline. Source: https://code.claude.com/docs/en/network-config
_OFFLINE = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
}


def _claude_binary() -> str | None:
    override = _PRISTINE_ENV.get("CLAUDE_BIN")
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("claude", path=_PRISTINE_ENV.get("PATH"))


def _is_shim_dir(directory: str) -> bool:
    base = Path(directory)
    return (base / "git-shim").exists() or (base / "git-shim.exe").exists()


def _single_shim_path() -> str:
    """A ``PATH`` carrying at most one shim directory (two shims recurse)."""
    entries = [d for d in _PRISTINE_ENV.get("PATH", "").split(os.pathsep) if d]
    shim_dirs = [d for d in entries if _is_shim_dir(d)]
    if len(shim_dirs) <= 1:
        return _PRISTINE_ENV.get("PATH", "")
    drop = set(shim_dirs[1:])
    return os.pathsep.join(d for d in entries if d not in drop)


def _run_git(git: str, repo: Path, *args: str, config: Path) -> subprocess.CompletedProcess[str]:
    """Drive the on-``PATH`` git in explicit *human* mode for setup and read-back only."""
    env = dict(_PRISTINE_ENV)
    env.pop("AGENT_ID", None)
    env["GIT_SHIM_MODE"] = "human"
    env["GIT_SHIM_CONFIG"] = str(config)
    env["GIT_SHIM_SHADOW"] = "1"
    return subprocess.run(
        [git, "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


@pytest.mark.skipif(not _OPT_IN, reason="opt-in realism gate; set GIT_SHIM_REALISM_MOCK=1")
def test_real_claude_binary_with_mock_model_is_stamped_with_the_bot(tmp_path: Path) -> None:
    """The real ``claude`` binary, fed a mock model with a dummy key, still hits the shim."""
    claude = _claude_binary()
    if claude is None:
        pytest.fail(
            "GIT_SHIM_REALISM_MOCK is set but claude was not found "
            "(put it on PATH or set CLAUDE_BIN)"
        )
    git = shutil.which("git", path=_single_shim_path())
    if git is None:
        pytest.fail("GIT_SHIM_REALISM_MOCK is set but no git is on PATH")

    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(_CONFIG, encoding="utf-8")

    _run_git(git, repo, "init", config=config)
    _run_git(git, repo, "config", "user.name", _HUMAN_NAME, config=config)
    _run_git(git, repo, "config", "user.email", _HUMAN_EMAIL, config=config)
    # Same-host origin that matches the bot identity but points nowhere real.
    _run_git(git, repo, "remote", "add", "origin", _ORIGIN, config=config)

    # Substrate check: the on-PATH git must actually be the shim, or the drive is vacuous.
    probe_env = {k: v for k, v in _PRISTINE_ENV.items() if k != "GIT_SHIM_MODE"}
    probe_env["GIT_SHIM_EXPLAIN"] = "1"
    probe_env["GIT_SHIM_SHADOW"] = "1"
    probe_env["GIT_SHIM_CONFIG"] = str(config)
    probe = subprocess.run(
        [git, "-C", str(repo), "status"],
        env=probe_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if "Resolved Plan" not in probe.stdout:
        pytest.fail(
            "GIT_SHIM_REALISM_MOCK is set but the on-PATH git is not the shim; install it "
            "(`uv tool install .`) and put its bin first on PATH so `git` is the trampoline"
        )

    # Loopback mock model: one canned Bash `git commit`, then stop. No auth, no egress.
    server, _thread = mock_llm.serve_in_thread(
        command=f'git commit --allow-empty -m "{_SUBJECT}"'
    )
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    env = dict(_PRISTINE_ENV)
    for name in _STRIP:
        env.pop(name, None)
    env.update(_OFFLINE)
    env["PATH"] = _single_shim_path()
    env["GIT_SHIM_SHADOW"] = "1"
    env["GIT_SHIM_CONFIG"] = str(config)
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_API_KEY"] = "dummy"
    # Isolate claude's own state from the operator's real profile/credentials.
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude-config")
    # ``--dangerously-skip-permissions`` refuses to run as root ("cannot be used with
    # root/sudo privileges") unless the environment is flagged as a sandbox. Hosted
    # runners use a non-root user so this is moot there, but container CI (e.g. `act`)
    # runs as root; IS_SANDBOX=1 is claude's sanctioned escape and is harmless otherwise.
    env["IS_SANDBOX"] = "1"

    instruction = (
        "Run exactly this one shell command and nothing else, then stop: "
        f'git commit --allow-empty -m "{_SUBJECT}"'
    )
    try:
        result = subprocess.run(
            [
                claude, "--bare", "-p", "--dangerously-skip-permissions",
                "--allowedTools", "Bash(git *)", "--max-turns", "2",
                "--model", "claude-sonnet-4-6", instruction,
            ],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        server.shutdown()

    assert result.returncode == 0, (
        f"claude exited {result.returncode}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # The auth-free claim only holds if claude's model turn went to *our* loopback
    # mock, not a real API: prove the endpoint was actually contacted.
    message_posts = [
        p for (m, p) in server.request_log
        if m == "POST" and p.startswith("/v1/messages")
    ]
    assert message_posts, (
        "claude never POSTed to the mock's /v1/messages -- it did not route through "
        f"ANTHROPIC_BASE_URL, so the auth-free path is unproven. "
        f"claude stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    head = _run_git(git, repo, "log", "-1", "--format=%an|%ae|%cn|%ce|%s", config=config)
    fields = head.stdout.strip().split("|")
    assert len(fields) == 5, (
        f"unexpected git log output {head.stdout!r}; claude said: {result.stdout!r}"
    )
    author_name, author_email, committer_name, committer_email, subject = fields

    assert subject == _SUBJECT, (
        f"claude did not create the requested commit (subject {subject!r}); "
        f"claude said: {result.stdout!r}"
    )
    assert author_email == _BOT_EMAIL, (
        f"author not stamped with the bot: {author_name} <{author_email}>"
    )
    assert committer_email == _BOT_EMAIL, (
        f"committer not stamped with the bot: {committer_name} <{committer_email}>"
    )
    # The shim rewrites the child git's identity env, never the repository's own config.
    local_email = _run_git(git, repo, "config", "user.email", config=config)
    assert local_email.stdout.strip() == _HUMAN_EMAIL
