"""Integration tests for the fail-closed write policy (T030/T031).

An unconfigured repository must stay fully usable for inspection while every
attributable write is refused before Git is ever started -- a partially applied
write is worse than a refused one. The refusal text is asserted verbatim because it
is the operator's only remedy, and the human override is asserted against a real
commit object rather than against injected environment variables.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

_REMOTE = "git@github.com:acme/app.git"
_CANONICAL = "github.com/acme/app"

_FOREIGN_CONFIG = """[[identities]]
id = "other"
name = "Other Bot"
email = "bot@other.invalid"
match_patterns = ["gitlab.com/other/*"]
"""


def shim_env(**overrides: str | None) -> dict[str, str]:
    """Copy the (already sanitized) test environment for a shim subprocess."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
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


def unmatched_remedy(isolated_env, canonical: str = _CANONICAL) -> str:
    """The exact refusal the shim must print for an unmatched remote."""
    return (
        f"git-shim: no bot identity matches {canonical}; "
        f"add an [[identities]] entry whose match_patterns cover it in "
        f"{isolated_env.config_path}, or rerun with UV_SHIM_GIT_MODE=human\n"
    )


@pytest.mark.parametrize("read_command", [("status",), ("log", "--oneline")])
def test_reads_succeed_in_an_unconfigured_repository(
    isolated_env, fake_git, temp_repo, read_command
):
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})

    result = run_shim(*read_command, env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == list(read_command)
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME", "GIT_SSH_COMMAND"):
        assert name not in call.env


@pytest.mark.parametrize(
    "write_command",
    [("commit", "--allow-empty", "-m", "agent work"), ("push", "origin", "main")],
)
def test_writes_are_refused_before_git_runs_in_an_unconfigured_repository(
    isolated_env, fake_git, temp_repo, write_command
):
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})

    result = run_shim(*write_command, env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 1
    assert result.stderr == unmatched_remedy(isolated_env)
    assert result.stdout == ""
    assert fake_git.call_count == 0


def test_refusal_survives_a_configuration_that_matches_other_repositories(
    isolated_env, fake_git, temp_repo
):
    isolated_env.write_config(_FOREIGN_CONFIG)
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})

    result = run_shim("commit", "-m", "agent work", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 1
    assert result.stderr == unmatched_remedy(isolated_env)
    assert fake_git.call_count == 0


def test_repository_without_a_remote_names_the_missing_remote(isolated_env, fake_git, temp_repo):
    repo = temp_repo("local-only")

    result = run_shim("commit", "-m", "agent work", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 1
    assert result.stderr == (
        "git-shim: this repository has no remote, so no bot identity can be matched; "
        "add a remote or rerun with UV_SHIM_GIT_MODE=human\n"
    )
    assert fake_git.call_count == 0


def test_human_mode_allows_writes_under_the_operator_identity(isolated_env, temp_repo):
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})
    repo.config("user.name", "Operator")
    repo.config("user.email", "operator@example.invalid")
    env = agent_env(
        isolated_env,
        UV_SHIM_GIT_MODE="human",
        UV_SHIM_GIT_REAL_PATH=repo.git_binary,
    )

    result = run_shim("commit", "--allow-empty", "-m", "operator work", env=env, cwd=repo.path)

    assert result.returncode == 0, result.stderr
    recorded = repo.git("log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout.strip()
    assert recorded == "Operator <operator@example.invalid>|Operator <operator@example.invalid>"
