"""Classify Git writes and preserve authorship when existing changes are carried."""

import os

from .data_models import CommitClass

_WRITE_COMMANDS = frozenset(
    {"commit", "push", "tag", "stash", "notes", "merge", "revert", "cherry-pick", "rebase", "am"}
)
_ORIGINATING_COMMANDS = frozenset({"commit", "merge", "revert", "stash", "notes"})
_CARRYING_COMMANDS = frozenset({"cherry-pick", "rebase", "am"})
_GLOBAL_VALUE_OPTIONS = frozenset(
    {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
)
_COMMIT_VALUE_OPTIONS = frozenset(
    {
        "-m",
        "--message",
        "-F",
        "--file",
        "--author",
        "--date",
        "--template",
        "-t",
        "--cleanup",
        "--pathspec-from-file",
        "--trailer",
        "--fixup",
        "--squash",
    }
)
_STATE_NAMES = ("CHERRY_PICK_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "MERGE_HEAD")
_CARRYING_STATE = frozenset(_STATE_NAMES[:-1])


def _command_index(argv) -> int:
    """Find the subcommand without treating global option values as commands."""
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in _GLOBAL_VALUE_OPTIONS:
            index += 2
        elif arg.startswith("-"):
            index += 1
        else:
            return index
    return len(argv)


def is_write_command(argv) -> bool:
    """Whether Git arguments (excluding the executable) name a gated write."""
    index = _command_index(argv)
    return index < len(argv) and argv[index] in _WRITE_COMMANDS


def _probe_sequencer_state(cwd, git_options) -> frozenset[str]:
    import subprocess

    from .real_git_discovery import find_real_git

    args = [find_real_git(), *git_options, "rev-parse", "--git-dir"]
    for name in _STATE_NAMES:
        args.extend(("--git-path", name))
    proc = subprocess.run(
        args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False
    )
    if proc.returncode:
        # Not every invocation occurs inside a repository. Leave Git to report it.
        return frozenset()
    paths = proc.stdout.splitlines()
    if len(paths) != len(_STATE_NAMES) + 1:
        return frozenset()

    # Git's relative output is rooted at its effective cwd, including repeated -C.
    base = os.path.abspath(cwd if cwd is not None else os.curdir)
    index = 0
    while index < len(git_options):
        arg = git_options[index]
        if arg == "-C":
            base = os.path.join(base, git_options[index + 1])
        elif arg.startswith("-C"):
            base = os.path.join(base, arg[2:])
        index += 2 if arg in _GLOBAL_VALUE_OPTIONS else 1
    return frozenset(
        name
        for name, path in zip(_STATE_NAMES, paths[1:], strict=True)
        if path and os.path.exists(os.path.join(base, path))
    )


def probe_sequencer_state(cwd=None) -> frozenset[str]:
    """Return existing state names from one batched, bare-safe Git path probe.

    Resolved paths honor GIT_DIR, submodules and linked worktrees. Git prints paths
    for absent state too, so each returned path must pass an existence check.
    """
    return _probe_sequencer_state(cwd, ())


def classify_commit(argv, cwd=None) -> CommitClass | None:
    """Return authorship policy, or None for commands that do not create commits.

    Explicit --author remains Git's argv-level override; callers must not remove
    or rewrite it. Reset-author overrides reuse/amend and sequencer state. Global
    Git options are retained for probing, so cwd denotes the invocation's base
    directory, not a pre-resolved -C directory.
    """
    index = _command_index(argv)
    if index == len(argv):
        return None
    command = argv[index]
    if command in _CARRYING_COMMANDS:
        return CommitClass.CARRYING
    if command not in _ORIGINATING_COMMANDS:
        return None
    if command in ("stash", "notes"):
        return CommitClass.ORIGINATING

    if command == "commit":
        carrying = False
        option_index = index + 1
        while option_index < len(argv):
            arg = argv[option_index]
            if arg == "--":
                break
            if arg == "--reset-author":
                return CommitClass.ORIGINATING
            if arg in ("-c", "-C", "--reuse-message", "--reedit-message"):
                carrying = True
                option_index += 2
                continue
            if arg == "--amend" or arg.startswith(
                ("-c", "-C", "--reuse-message=", "--reedit-message=")
            ):
                carrying = True
            option_index += 2 if arg in _COMMIT_VALUE_OPTIONS else 1
        if carrying:
            return CommitClass.CARRYING

    state = _probe_sequencer_state(cwd, argv[:index]) if index else probe_sequencer_state(cwd)
    return CommitClass.CARRYING if state & _CARRYING_STATE else CommitClass.ORIGINATING
