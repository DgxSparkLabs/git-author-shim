"""Contract tests for process execution fidelity (T018).

The shim stands between the caller and the real Git binary on every single
invocation, so the delegation itself is a contract:

* the child's exit code is the shim's exit code, verbatim;
* ``stdout`` and ``stderr`` stay distinct streams and ``stdin`` reaches the child;
* argv and the environment are forwarded untouched apart from documented additions;
* terminating signals reach the child instead of killing the wrapper first.

Most assertions drive the real console-script code path via
``python -m git_author_shim`` so that exit codes, stream separation and signal
delivery are observed at the operating-system level rather than mocked.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_SENTINEL = "__GIT_SHIM_CONTINUATION"


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
    stdin: str = "",
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the ``git`` shim entry point in a real child process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=shim_env() if env is None else env,
        cwd=None if cwd is None else str(cwd),
        check=False,
        timeout=120,
    )


# --------------------------------------------------------------------------------------
# Exit code propagation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [0, 1, 2, 37, 128])
def test_child_exit_code_is_propagated_verbatim(fake_git, code):
    fake_git.set_exit_code(code)

    assert run_shim("status").returncode == code


def test_main_returns_the_child_exit_code(fake_git):
    from git_author_shim.__main__ import main

    fake_git.set_exit_code(37)

    assert main(["status"]) == 37


def test_git_shim_cli_forwards_status_to_run_git(fake_git):
    from git_author_shim.cli import main

    fake_git.set_exit_code(0)

    assert main(["status"]) == 0
    assert fake_git.last_call.argv == ["status"]


def test_git_shim_cli_forwards_commit_and_propagates_exit_code(fake_git):
    from git_author_shim.cli import main

    fake_git.set_exit_code(17)

    assert main(["commit", "-m", "test"]) == 17
    assert fake_git.last_call.argv == ["commit", "-m", "test"]


def test_missing_real_git_fails_with_an_actionable_message(tmp_path):
    empty = tmp_path / "empty-path"
    empty.mkdir()

    result = run_shim("status", env=shim_env(PATH=str(empty)))

    assert result.returncode == 1
    assert "GIT_SHIM_REAL_PATH" in result.stderr


# --------------------------------------------------------------------------------------
# Stdio fidelity
# --------------------------------------------------------------------------------------


def test_stdout_and_stderr_remain_separate_streams(fake_git):
    fake_git.set_stdout("payload-on-stdout\n")
    fake_git.set_stderr("payload-on-stderr\n")

    result = run_shim("status")

    assert result.stdout == "payload-on-stdout\n"
    assert result.stderr == "payload-on-stderr\n"


def test_stdin_is_forwarded_to_the_child(fake_git):
    run_shim("hash-object", "--stdin", stdin="blob contents\nsecond line\n")

    assert fake_git.last_call.stdin == "blob contents\nsecond line\n"


# --------------------------------------------------------------------------------------
# Unmanaged argv / environment / cwd passthrough
# --------------------------------------------------------------------------------------


def test_unmanaged_arguments_are_forwarded_verbatim(fake_git):
    argv = [
        "log",
        "--oneline",
        "-n",
        "3",
        "--pretty=format:%H %s",
        "--",
        "a path with spaces.txt",
    ]

    run_shim(*argv)

    assert fake_git.last_call.argv == argv


def test_unmanaged_environment_variables_are_forwarded(fake_git):
    run_shim("status", env=shim_env(UNMANAGED_TEST_VAR="keep-me"))

    assert fake_git.last_call.env["UNMANAGED_TEST_VAR"] == "keep-me"


def test_recursion_sentinel_is_added_for_the_child_only(fake_git):
    run_shim("status")

    assert fake_git.last_call.env[_SENTINEL] == "1"
    assert _SENTINEL not in os.environ


def test_child_runs_in_the_callers_working_directory(fake_git, tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    run_shim("status", cwd=workdir)

    assert Path(fake_git.last_call.cwd).resolve() == workdir.resolve()


# --------------------------------------------------------------------------------------
# Signal forwarding
# --------------------------------------------------------------------------------------


class _RecordingProcess:
    """Stands in for ``subprocess.Popen`` while exercising the signal forwarder."""

    def __init__(self) -> None:
        self.signals: list[int] = []

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)


def test_terminating_signals_are_taken_over_and_restored():
    from git_author_shim import cli

    forwarded = cli.forwardable_signals()
    assert signal.SIGINT in forwarded
    assert signal.SIGTERM in forwarded

    before = {signum: signal.getsignal(signum) for signum in forwarded}
    process = _RecordingProcess()

    with cli.SignalForwarder(process):
        for signum in forwarded:
            handler = signal.getsignal(signum)
            assert handler is not before[signum]
            handler(signum, None)

    assert {signum: signal.getsignal(signum) for signum in forwarded} == before
    if os.name == "nt":
        # The Windows console broadcasts Ctrl+C/Ctrl+Break to every process attached
        # to it, child included; the wrapper only has to survive long enough to
        # report the child's real exit status.
        assert process.signals == []
    else:
        assert process.signals == list(forwarded)


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX signal delivery; Windows uses console control events",
)
def test_sigterm_reaches_the_child_git_process(tmp_path):
    marker = tmp_path / "child-got-sigterm"
    ready = tmp_path / "child-ready"
    trapping_git = tmp_path / "trapping-git"
    trapping_git.write_text(
        "#!/bin/sh\n"
        f"trap 'printf terminated > \"{marker}\"; exit 42' TERM\n"
        f'printf ready > "{ready}"\n'
        "while true; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    trapping_git.chmod(0o755)

    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", "commit"],
        env=shim_env(GIT_SHIM_REAL_PATH=str(trapping_git)),
        cwd=str(tmp_path),
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None, "shim exited before the child was ready"
            time.sleep(0.02)
        assert ready.exists(), "child git never started"

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 42
    finally:
        if process.poll() is None:  # pragma: no cover - only on assertion failure
            process.kill()
            process.wait(timeout=30)

    assert marker.read_text(encoding="utf-8") == "terminated"


# --------------------------------------------------------------------------------------
# Agent-mode execution vectors
# --------------------------------------------------------------------------------------


def _write_identity_config(isolated_env, key_file: Path) -> Path:
    return isolated_env.write_config(
        "[[identities]]\n"
        'id = "acme"\n'
        'name = "Acme Bot"\n'
        'email = "bot@acme.invalid"\n'
        'match_patterns = ["github.com/acme/*"]\n'
        "\n"
        "[identities.ssh]\n"
        f"key_file = {json.dumps(str(key_file))}\n"
    )


def test_agent_mode_injects_bot_identity_and_isolated_ssh_command(
    isolated_env, temp_repo, fake_git, tmp_path
):
    key_file = tmp_path / "bot_ed25519"
    key_file.write_text("not-a-real-key\n", encoding="utf-8")
    _write_identity_config(isolated_env, key_file)
    repo = temp_repo("acme-app", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim(
        "commit",
        "-m",
        "bot work",
        env=shim_env(AGENT_ID="agent-worker-9"),
        cwd=repo.path,
    )

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == ["commit", "-m", "bot work"]
    assert call.env["GIT_AUTHOR_NAME"] == "Acme Bot"
    assert call.env["GIT_AUTHOR_EMAIL"] == "bot@acme.invalid"
    assert call.env["GIT_COMMITTER_NAME"] == "Acme Bot"
    assert call.env["GIT_COMMITTER_EMAIL"] == "bot@acme.invalid"
    ssh_command = call.env["GIT_SSH_COMMAND"]
    assert str(key_file).replace("\\", "/") in ssh_command
    assert "IdentitiesOnly=yes" in ssh_command


def test_agent_mode_refuses_writes_without_a_matching_identity(
    isolated_env, temp_repo, fake_git, tmp_path
):
    _write_identity_config(isolated_env, tmp_path / "bot_ed25519")
    repo = temp_repo("foreign", remotes={"origin": "git@github.com:someone/else.git"})

    result = run_shim(
        "commit",
        "-m",
        "bot work",
        env=shim_env(AGENT_ID="agent-worker-9"),
        cwd=repo.path,
    )

    assert result.returncode == 1
    assert "github.com/someone/else" in result.stderr
    assert fake_git.call_count == 0


def test_agent_mode_still_passes_reads_through_without_a_matching_identity(
    isolated_env, temp_repo, fake_git, tmp_path
):
    _write_identity_config(isolated_env, tmp_path / "bot_ed25519")
    repo = temp_repo("foreign-read", remotes={"origin": "git@github.com:someone/else.git"})

    result = run_shim("status", env=shim_env(AGENT_ID="agent-worker-9"), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == ["status"]
    assert "GIT_AUTHOR_NAME" not in call.env
    assert "GIT_SSH_COMMAND" not in call.env
