"""Read/write taxonomy contracts for the write identity gate."""

import pytest

from uv_shims.git.commit_authorship_classifier import is_write_command


@pytest.mark.parametrize("command", ["status", "log", "diff", "fetch", "show", "branch"])
def test_read_commands_do_not_require_write_identity(command):
    assert is_write_command([command]) is False


@pytest.mark.parametrize(
    "command",
    ["commit", "push", "tag", "stash", "notes", "merge", "revert", "cherry-pick", "rebase", "am"],
)
def test_write_commands_require_write_identity(command):
    assert is_write_command([command]) is True


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["-c", "alias.check=push", "status"], False),
        (["-C", "status", "commit"], True),
        (["--git-dir", "push", "show"], False),
        (["--work-tree=tree", "--no-pager", "push"], True),
        (["--config-env", "user.name=NAME", "commit"], True),
        (["-cuser.name=Bot", "-Crepo", "merge"], True),
        (["log", "--", "commit"], False),
        ([], False),
        (["--version"], False),
    ],
)
def test_only_subcommand_controls_write_gate(argv, expected):
    assert is_write_command(argv) is expected
