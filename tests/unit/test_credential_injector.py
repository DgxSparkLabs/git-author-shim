"""Unit tests for SSH credential command generation (T016)."""

from __future__ import annotations

from pathlib import Path

from git_author_shim.credential_injector import build_ssh_command


def test_build_ssh_command_isolates_the_requested_identity() -> None:
    command = build_ssh_command(Path("/home/bot/.ssh/id_ed25519"), os_name="posix")

    assert command.startswith("ssh -i /home/bot/.ssh/id_ed25519")
    assert "-o IdentitiesOnly=yes" in command
    assert "-o StrictHostKeyChecking=accept-new" in command
    assert command.endswith("-F /dev/null")


def test_build_ssh_command_uses_windows_null_device_and_forward_slashes() -> None:
    command = build_ssh_command(r"C:\keys\bot_key", os_name="nt")

    assert "-i C:/keys/bot_key" in command
    assert command.endswith("-F NUL")
    assert "\\" not in command


def test_build_ssh_command_shell_quotes_paths_with_spaces() -> None:
    command = build_ssh_command(r"C:\Users\Bot Account\.ssh\bot key", os_name="nt")

    assert "-i 'C:/Users/Bot Account/.ssh/bot key'" in command
    assert "-o IdentitiesOnly=yes" in command


def test_build_ssh_command_shell_quotes_single_quotes() -> None:
    command = build_ssh_command("/home/bot's keys/id", os_name="posix")

    assert "-i '/home/bot'\"'\"'s keys/id'" in command


def test_build_ssh_command_can_disable_strict_host_checking() -> None:
    command = build_ssh_command(
        "/home/bot/.ssh/id_ed25519",
        strict_host_checking=False,
        os_name="posix",
    )

    assert "-o StrictHostKeyChecking=no" in command
