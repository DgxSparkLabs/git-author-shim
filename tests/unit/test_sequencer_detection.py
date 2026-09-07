"""Resolved sequencer paths and commit authorship precedence contracts."""

from pathlib import Path

import pytest

from git_author_shim.commit_authorship_classifier import classify_commit, probe_sequencer_state
from git_author_shim.data_models import CommitClass

STATE_NAMES = ("CHERRY_PICK_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "MERGE_HEAD")


def test_probe_batches_names_and_filters_nonexistent_paths(fake_git, tmp_path, monkeypatch):
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", str(fake_git.path))
    state_dir = tmp_path / "resolved state"
    state_dir.mkdir()
    (state_dir / "CHERRY_PICK_HEAD").write_text("commit-id", encoding="utf-8")
    (state_dir / "rebase-merge").mkdir()
    # Git prints every requested path, even for state that does not exist.
    paths = [f"resolved state/{name}" for name in STATE_NAMES]
    fake_git.set_stdout("elsewhere.git\n" + "\n".join(paths) + "\n")

    assert probe_sequencer_state(tmp_path) == frozenset({"CHERRY_PICK_HEAD", "rebase-merge"})
    assert fake_git.call_count == 1
    assert fake_git.last_call.argv == [
        "rev-parse",
        "--git-dir",
        "--git-path",
        "CHERRY_PICK_HEAD",
        "--git-path",
        "REBASE_HEAD",
        "--git-path",
        "rebase-merge",
        "--git-path",
        "rebase-apply",
        "--git-path",
        "MERGE_HEAD",
    ]


def test_probe_handles_bare_repository_without_worktree_probe(temp_repo, monkeypatch):
    repo = temp_repo(bare=True)
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    assert probe_sequencer_state(repo.path) == frozenset()
    (repo.path / "MERGE_HEAD").write_text("commit-id", encoding="utf-8")
    assert probe_sequencer_state(repo.path) == frozenset({"MERGE_HEAD"})
    assert classify_commit(["commit"], repo.path) is CommitClass.ORIGINATING


def test_probe_uses_linked_worktree_state_not_main_repository(temp_repo, tmp_path, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    linked = tmp_path / "linked"
    repo.git("worktree", "add", "-b", "linked", str(linked))
    resolved = repo.git("-C", str(linked), "rev-parse", "--git-path", "CHERRY_PICK_HEAD")
    Path(resolved.stdout.strip()).write_text("commit-id", encoding="utf-8")

    assert probe_sequencer_state(repo.path) == frozenset()
    assert probe_sequencer_state(linked) == frozenset({"CHERRY_PICK_HEAD"})
    assert classify_commit(["commit"], linked) is CommitClass.CARRYING


def test_probe_outside_repository_returns_no_state(temp_repo, tmp_path, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    assert probe_sequencer_state(tmp_path) == frozenset()


@pytest.mark.parametrize("command", ["commit", "merge", "revert", "stash", "notes"])
def test_fresh_changes_are_originating(command, temp_repo, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    assert classify_commit([command], repo.path) is CommitClass.ORIGINATING


@pytest.mark.parametrize(
    "argv",
    [
        ["cherry-pick", "HEAD"],
        ["rebase", "main"],
        ["am", "patch.mbox"],
        ["commit", "--amend"],
        ["commit", "-c", "HEAD"],
        ["commit", "-CHEAD"],
        ["commit", "--reuse-message=HEAD"],
        ["commit", "--reedit-message", "HEAD"],
    ],
)
def test_reused_changes_are_carrying(argv, tmp_path):
    assert classify_commit(argv, tmp_path) is CommitClass.CARRYING


@pytest.mark.parametrize("state", STATE_NAMES)
def test_commit_resumes_resolved_sequencer_state(state, temp_repo, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    path = repo.git_dir / state
    if state.startswith("rebase-"):
        path.mkdir()
    else:
        path.write_text("commit-id", encoding="utf-8")
    expected = CommitClass.ORIGINATING if state == "MERGE_HEAD" else CommitClass.CARRYING
    assert classify_commit(["commit"], repo.path) is expected


def test_reset_author_beats_reuse_amend_and_sequencer(temp_repo, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    (repo.git_dir / "CHERRY_PICK_HEAD").write_text("commit-id", encoding="utf-8")
    assert (
        classify_commit(["commit", "--amend", "-C", "HEAD", "--reset-author"], repo.path)
        is CommitClass.ORIGINATING
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--", "--amend"],
        ["-m", "--amend"],
        ["--message", "--reset-author", "--amend"],
        ["--author", "--amend"],
    ],
)
def test_paths_and_option_values_are_not_authorship_flags(args, temp_repo, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    expected = CommitClass.CARRYING if "--message" in args else CommitClass.ORIGINATING
    assert classify_commit(["commit", *args], repo.path) is expected


def test_global_config_and_directory_options_do_not_reuse_authorship(temp_repo, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    assert (
        classify_commit(["-c", "user.name=Bot", "-C", str(repo.path), "commit"])
        is CommitClass.ORIGINATING
    )
    (repo.git_dir / "CHERRY_PICK_HEAD").write_text("commit-id", encoding="utf-8")
    assert (
        classify_commit(["-C", repo.path.name, "commit"], repo.path.parent) is CommitClass.CARRYING
    )


def test_git_dir_environment_and_default_cwd_are_honored(temp_repo, tmp_path, monkeypatch):
    repo = temp_repo()
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    monkeypatch.setenv("GIT_DIR", str(repo.git_dir))
    monkeypatch.chdir(tmp_path)
    (repo.git_dir / "REBASE_HEAD").write_text("commit-id", encoding="utf-8")
    assert probe_sequencer_state() == frozenset({"REBASE_HEAD"})
    assert classify_commit(["commit"]) is CommitClass.CARRYING


def test_non_commit_commands_never_probe_git(fake_git, monkeypatch):
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", str(fake_git.path))
    for command in ("status", "log", "diff", "fetch", "show", "branch", "push", "tag"):
        assert classify_commit([command]) is None
    assert fake_git.calls == []


@pytest.mark.parametrize("argv", [[], ["--version"], ["-C"], ["--git-dir"]])
def test_no_subcommand_leaves_argument_errors_to_git(argv, fake_git, monkeypatch):
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", str(fake_git.path))
    assert classify_commit(argv) is None
    assert fake_git.calls == []
