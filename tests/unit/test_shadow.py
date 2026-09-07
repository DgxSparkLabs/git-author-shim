"""Unit tests for optional PATH shadowing of system Git."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from git_author_shim import cli
from git_author_shim.shadow import (
    SHADOW_ENV,
    ShadowError,
    disable,
    enable,
    git_launcher_name,
    is_shadow_enabled,
    resolve_shim_executable,
    status_text,
)


def _dummy_install(tmp_path: Path) -> Path:
    """Simulate a uv-installed pair of console-script trampolines."""

    shim = tmp_path / ("git-shim.exe" if os.name == "nt" else "git-shim")
    git = tmp_path / git_launcher_name()
    shim.write_bytes(b"shim-launcher")
    git.write_bytes(b"git-launcher")
    shim.chmod(0o755)
    git.chmod(0o755)
    return shim


def test_enable_disable_round_trip(tmp_path: Path) -> None:
    shim = _dummy_install(tmp_path)
    target = tmp_path / git_launcher_name()

    assert is_shadow_enabled(str(shim)) is False
    assert "disabled" in status_text(shim)

    enabled = enable(shim)
    assert "enabled git shadow" in enabled
    assert target.exists()
    assert is_shadow_enabled(str(shim)) is True
    assert "(enabled)" in status_text(shim)

    disabled = disable(shim)
    assert "disabled git shadow" in disabled
    assert target.exists()
    assert is_shadow_enabled(str(shim)) is False
    assert "passthrough" in status_text(shim)


def test_enable_requires_the_uv_git_trampoline(tmp_path: Path) -> None:
    shim = tmp_path / ("git-shim.exe" if os.name == "nt" else "git-shim")
    shim.write_bytes(b"shim-launcher")
    shim.chmod(0o755)
    with pytest.raises(ShadowError, match="git launcher not found"):
        enable(shim)


def test_env_override_forces_passthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shim = _dummy_install(tmp_path)
    enable(shim)
    monkeypatch.setenv(SHADOW_ENV, "0")
    assert is_shadow_enabled(str(shim)) is False
    monkeypatch.setenv(SHADOW_ENV, "1")
    disable(shim)
    assert is_shadow_enabled(str(shim)) is True


def test_invoked_as_git_forwards_explain_to_run_git(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", [str(Path("tools") / git_launcher_name()), "explain"])
    monkeypatch.setattr(cli, "run_git", lambda argv=None, env=None: seen.append(list(argv)) or 0)

    assert cli.main() == 0
    assert seen == [["explain"]]


@pytest.mark.skipif(os.name != "nt", reason="Windows argv0 omits .exe")
def test_windows_resolves_git_shim_without_exe_suffix(tmp_path: Path) -> None:
    real = _dummy_install(tmp_path)
    found = resolve_shim_executable(str(tmp_path / "git-shim"))
    assert found == real.resolve()
