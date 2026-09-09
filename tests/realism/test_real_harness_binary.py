"""Realism gate: a *real* agent-harness binary must resolve to the shim and stamp the bot.

Every other test simulates a harness. ``tests/integration/test_e2e_agent_detection.py``
sets a marker env var and calls the shim in-process; ``tests/unit`` exercises the
functions directly. Nothing there launches ``omp``/``claude`` themselves. This module
does: it starts the actual ``omp`` executable non-interactively (``omp -p``) and lets
*it* spawn ``git`` through its own tool runtime. The only ground truth asserted is the
resulting commit's author/committer, read back with real Git -- not the model's prose.

Why this cannot be a normal test:

* it needs the harness installed AND authenticated, and it reaches the network;
* it costs a model round-trip (seconds + quota);

so it is skipped unless explicitly opted in::

    GIT_SHIM_REALISM=1 uvx pytest tests/realism -m realism -v

(optionally ``OMP_BIN=/path/to/omp`` when the binary is not on ``PATH``). Once opted in,
a missing binary or a non-shim ``git`` on ``PATH`` is a hard failure, never a skip, so a
misconfigured runner cannot go green having proven nothing; the un-opted-in case is the
only skip. The test forces ``GIT_SHIM_SHADOW=1`` so an installed shim engages regardless
of its marker file. CI runs this only on a self-hosted runner that has the binary and
credentials -- see the ``realism`` job in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.realism

# The environment as it looked at import time, before conftest's autouse ``clean_env``
# fixture strips ``GIT_*``/``CLAUDE_*`` and before any monkeypatching. The launched
# harness needs the operator's real profile (``HOME``/``APPDATA``/auth), so every
# subprocess below is built from this pristine copy rather than the sanitized ``os.environ``.
_PRISTINE_ENV: dict[str, str] = dict(os.environ)

_TRUTHY = {"1", "true", "yes", "on"}
_OPT_IN = _PRISTINE_ENV.get("GIT_SHIM_REALISM", "").strip().lower() in _TRUTHY

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


def _omp_binary() -> str | None:
    override = _PRISTINE_ENV.get("OMP_BIN")
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("omp")


def _is_shim_dir(directory: str) -> bool:
    base = Path(directory)
    return (base / "git-shim").exists() or (base / "git-shim.exe").exists()


def _single_shim_path() -> str:
    """A ``PATH`` carrying at most one shim directory.

    Two shim installs visible at once is the exact condition that recurses (the trap the
    recursion fix addresses): the shim's real-git discovery could pick the *other* shim.
    Keep the first shim dir, drop any others; leave every non-shim dir untouched.
    """
    entries = [d for d in _PRISTINE_ENV.get("PATH", "").split(os.pathsep) if d]
    shim_dirs = [d for d in entries if _is_shim_dir(d)]
    if len(shim_dirs) <= 1:
        return _PRISTINE_ENV.get("PATH", "")
    drop = set(shim_dirs[1:])
    return os.pathsep.join(d for d in entries if d not in drop)


def _run_git(git: str, repo: Path, *args: str, config: Path) -> subprocess.CompletedProcess[str]:
    """Drive the on-``PATH`` git in explicit *human* mode for setup and read-back only.

    Human mode is pure passthrough to real Git (no identity injection); a plain, non-shim
    git simply ignores the flag. This never influences what is under test -- the agent
    commit -- it only provides a shim-independent way to create and inspect the repo.
    """
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


@pytest.mark.skipif(not _OPT_IN, reason="opt-in realism gate; set GIT_SHIM_REALISM=1")
def test_real_omp_binary_commit_is_stamped_with_the_bot(tmp_path: Path) -> None:
    """The real ``omp`` binary, deciding to run ``git`` itself, is intercepted and stamped."""
    omp = _omp_binary()
    if omp is None:
        pytest.fail("GIT_SHIM_REALISM is set but omp was not found (put it on PATH or set OMP_BIN)")
    git = shutil.which("git")
    if git is None:
        pytest.fail("GIT_SHIM_REALISM is set but no git is on PATH")

    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "config.toml"
    config.write_text(_CONFIG, encoding="utf-8")

    _run_git(git, repo, "init", config=config)
    _run_git(git, repo, "config", "user.name", _HUMAN_NAME, config=config)
    _run_git(git, repo, "config", "user.email", _HUMAN_EMAIL, config=config)
    # A same-host origin that matches the bot identity but points nowhere real, so host
    # matching fires while a stray push cannot reach anything.
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
            "GIT_SHIM_REALISM is set but the on-PATH git is not the shim; install it "
            "(`uv tool install .`) and put its bin first on PATH so `git` is the trampoline"
        )

    # Launch the REAL omp binary, non-interactively. GIT_SHIM_MODE / AGENT_ID are removed:
    # agent mode can only arise from omp self-exporting OMPCODE/CLAUDECODE into the git it
    # spawns, matched against custom_agent_markers -- i.e. genuine auto-detection.
    env = dict(_PRISTINE_ENV)
    for name in ("GIT_SHIM_MODE", "AGENT_ID", "GIT_SHIM_EXPLAIN"):
        env.pop(name, None)
    env["GIT_SHIM_CONFIG"] = str(config)
    env["GIT_SHIM_SHADOW"] = "1"
    env["PATH"] = _single_shim_path()

    instruction = (
        "Run exactly this one shell command and nothing else, then stop: "
        f'git commit --allow-empty -m "{_SUBJECT}"'
    )
    result = subprocess.run(
        [omp, "-p", "--no-session", "--no-pty", "--auto-approve", "--cwd", str(repo), instruction],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"omp exited {result.returncode}\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # Ground truth: read the commit back with git in human mode (no injection at read time).
    head = _run_git(git, repo, "log", "-1", "--format=%an|%ae|%cn|%ce|%s", config=config)
    fields = head.stdout.strip().split("|")
    assert len(fields) == 5, (
        f"unexpected git log output {head.stdout!r}; omp said: {result.stdout!r}"
    )
    author_name, author_email, committer_name, committer_email, subject = fields

    assert subject == _SUBJECT, (
        f"omp did not create the requested commit (subject {subject!r}); "
        f"omp said: {result.stdout!r}"
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
