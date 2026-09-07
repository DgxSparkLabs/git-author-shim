"""Bot attribution applies to every stash commit and the notes commit itself."""

import pytest

from git_author_shim.cli import run_git

_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]
"""
_BOT = "Acme Bot <bot@acme.invalid>|Acme Bot <bot@acme.invalid>"


@pytest.fixture
def bot_repo(isolated_env, temp_repo, monkeypatch):
    isolated_env.write_config(_CONFIG)
    repo = temp_repo(remotes={"origin": "https://github.com/acme/app.git"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("GIT_SHIM_MODE", "agent")
    monkeypatch.setenv("GIT_SHIM_REAL_PATH", repo.git_binary)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Human Operator")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "human@example.invalid")
    return repo


def test_stash_push_attributes_worktree_index_and_untracked_commits(bot_repo):
    repo = bot_repo
    tracked = repo.path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    repo.git("add", "tracked.txt")
    repo.commit("tracked base")
    base = repo.git("rev-parse", "HEAD").stdout.strip()
    tracked.write_text("staged\n", encoding="utf-8")
    repo.git("add", "tracked.txt")
    tracked.write_text("unstaged\n", encoding="utf-8")
    (repo.path / "untracked.txt").write_text("new file\n", encoding="utf-8")

    assert run_git(["stash", "push", "--include-untracked", "-m", "agent work"]) == 0

    for revision in ("refs/stash", "refs/stash^2", "refs/stash^3"):
        assert (
            repo.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", revision).stdout.strip() == _BOT
        )
    assert repo.git("rev-parse", "refs/stash^1").stdout.strip() == base
    assert repo.git("status", "--porcelain").stdout == ""


def test_notes_add_attributes_notes_commit_without_rewriting_target(bot_repo):
    repo = bot_repo
    original = repo.git("cat-file", "commit", "HEAD").stdout

    assert run_git(["notes", "add", "-m", "Reviewed by automation", "HEAD"]) == 0

    assert (
        repo.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", "refs/notes/commits").stdout.strip()
        == _BOT
    )
    assert repo.git("notes", "show", "HEAD").stdout.strip() == "Reviewed by automation"
    assert repo.git("cat-file", "commit", "HEAD").stdout == original
