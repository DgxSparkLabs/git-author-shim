"""Real-Git integration tests for originating and carrying authorship (T036/T037)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
_BOT = "Acme Bot <bot@acme.invalid>"
_HUMAN = "Human Developer <human@example.invalid>"
_CALLER = "Caller Override <caller@example.invalid>"


def _shim_env(real_git: str, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["UV_SHIM_GIT_REAL_PATH"] = real_git
    env["UV_SHIM_GIT_MODE"] = "agent"
    env.update(overrides)
    return env


def _run_shim(
    repo, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        cwd=repo.path,
        env=_shim_env(repo.git_binary) if env is None else env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _configure_identity(isolated_env) -> None:
    isolated_env.write_config(
        "[[identities]]\n"
        'id = "acme"\n'
        'name = "Acme Bot"\n'
        'email = "bot@acme.invalid"\n'
        'match_patterns = ["github.com/acme/*"]\n'
    )


def _commit_as(repo, path: str, contents: str, message: str, name: str, email: str) -> str:
    (repo.path / path).write_text(contents, encoding="utf-8")
    repo.git("add", path)
    env = {
        **repo.git_env,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    subprocess.run(  # noqa: S603
        [repo.git_binary, "commit", "-m", message],
        cwd=repo.path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return repo.git("rev-parse", "HEAD").stdout.strip()


def _attribution(repo, revision: str = "HEAD") -> str:
    return repo.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", revision).stdout.strip()


def test_cherry_pick_preserves_human_author_and_sets_bot_committer(isolated_env, temp_repo) -> None:
    _configure_identity(isolated_env)
    repo = temp_repo("cherry", remotes={"origin": "https://github.com/acme/app.git"})
    repo.git("switch", "-c", "human-work")
    human_commit = _commit_as(
        repo,
        "human.txt",
        "human work\n",
        "human change",
        "Human Developer",
        "human@example.invalid",
    )
    repo.git("switch", "main")

    result = _run_shim(repo, "cherry-pick", human_commit)

    assert result.returncode == 0, result.stderr
    assert _attribution(repo) == f"{_HUMAN}|{_BOT}"


def test_rebase_conflict_completed_by_bare_commit_preserves_human_author(
    isolated_env, temp_repo
) -> None:
    _configure_identity(isolated_env)
    repo = temp_repo("rebase-conflict", remotes={"origin": "https://github.com/acme/app.git"})
    (repo.path / "conflict.txt").write_text("base\n", encoding="utf-8")
    repo.git("add", "conflict.txt")
    repo.commit("base", allow_empty=False)
    repo.git("switch", "-c", "human-work")
    _commit_as(
        repo,
        "conflict.txt",
        "human version\n",
        "human conflict",
        "Human Developer",
        "human@example.invalid",
    )
    repo.git("switch", "main")
    _commit_as(
        repo,
        "conflict.txt",
        "main version\n",
        "main conflict",
        "Main Maintainer",
        "main@example.invalid",
    )
    repo.git("switch", "human-work")

    rebase = _run_shim(repo, "rebase", "main")
    assert rebase.returncode != 0
    assert "CONFLICT" in rebase.stdout + rebase.stderr
    (repo.path / "conflict.txt").write_text("resolved\n", encoding="utf-8")
    repo.git("add", "conflict.txt")

    commit = _run_shim(repo, "commit", env=_shim_env(repo.git_binary, GIT_EDITOR="true"))

    assert commit.returncode == 0, commit.stderr
    assert _attribution(repo) == f"{_HUMAN}|{_BOT}"
    completed = _run_shim(repo, "rebase", "--continue")
    assert completed.returncode == 0, completed.stderr


def test_fresh_commit_overwrites_caller_author_and_committer_with_bot(
    isolated_env, temp_repo
) -> None:
    _configure_identity(isolated_env)
    repo = temp_repo("fresh", remotes={"origin": "https://github.com/acme/app.git"})
    (repo.path / "fresh.txt").write_text("fresh\n", encoding="utf-8")
    repo.git("add", "fresh.txt")
    env = _shim_env(
        repo.git_binary,
        GIT_AUTHOR_NAME="Caller Override",
        GIT_AUTHOR_EMAIL="caller@example.invalid",
        GIT_AUTHOR_DATE="2001-02-03T04:05:06+00:00",
        GIT_COMMITTER_NAME="Caller Override",
        GIT_COMMITTER_EMAIL="caller@example.invalid",
    )

    result = _run_shim(repo, "commit", "-m", "fresh bot work", env=env)

    assert result.returncode == 0, result.stderr
    assert _attribution(repo) == f"{_BOT}|{_BOT}"
    assert _CALLER not in _attribution(repo)
    assert not repo.git("show", "-s", "--format=%aI").stdout.startswith("2001-02-03")


def test_carrying_commit_removes_caller_author_environment(isolated_env, temp_repo) -> None:
    _configure_identity(isolated_env)
    repo = temp_repo("carrying-env", remotes={"origin": "https://github.com/acme/app.git"})
    repo.git("switch", "-c", "human-work")
    human_commit = _commit_as(
        repo,
        "carried.txt",
        "carried\n",
        "carried human change",
        "Human Developer",
        "human@example.invalid",
    )
    repo.git("switch", "main")
    env = _shim_env(
        repo.git_binary,
        GIT_AUTHOR_NAME="Caller Override",
        GIT_AUTHOR_EMAIL="caller@example.invalid",
        GIT_AUTHOR_DATE="2001-02-03T04:05:06+00:00",
        GIT_COMMITTER_NAME="Caller Override",
        GIT_COMMITTER_EMAIL="caller@example.invalid",
    )

    result = _run_shim(repo, "cherry-pick", human_commit, env=env)

    assert result.returncode == 0, result.stderr
    assert _attribution(repo) == f"{_HUMAN}|{_BOT}"
    assert _CALLER not in _attribution(repo)
