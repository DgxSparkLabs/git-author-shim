"""Executable discovery must never select the shim, including through aliases."""

import os
import sys

import pytest

from git_author_shim import real_git_discovery as discovery


@pytest.fixture
def executable(tmp_path):
    def create(directory, name=None):
        path = tmp_path / directory / (name or ("git.exe" if os.name == "nt" else "git"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test executable\n")
        path.chmod(0o755)
        return path

    return create


def test_path_order_and_missing_directories(executable, tmp_path):
    first = executable("first")
    second = executable("second")
    env = {"PATH": os.pathsep.join(map(str, [tmp_path / "missing", first.parent, second.parent]))}
    assert discovery.find_real_git(shim_path=tmp_path / "shim", env=env) == str(first)


def test_skips_shim_and_continues_search(executable):
    shim = executable("shim")
    real = executable("real")
    env = {"PATH": os.pathsep.join(map(str, [shim.parent, real.parent]))}
    assert discovery.find_real_git(shim_path=shim, env=env) == str(real)


def test_default_shim_path_uses_invoked_executable(executable, monkeypatch):
    shim = executable("shim")
    real = executable("real")
    monkeypatch.setattr(sys, "argv", [str(shim), "status"])
    env = {"PATH": os.pathsep.join(map(str, [shim.parent, real.parent]))}
    assert discovery.find_real_git(env=env) == str(real)


def test_skips_hard_link_to_shim(executable, tmp_path):
    shim = executable("shim")
    alias = tmp_path / "alias" / shim.name
    alias.parent.mkdir()
    os.link(shim, alias)
    real = executable("real")
    env = {"PATH": os.pathsep.join(map(str, [alias.parent, real.parent]))}
    assert discovery.find_real_git(shim_path=shim, env=env) == str(real)


def test_explicit_override_takes_precedence_over_path(executable):
    override = executable("chosen")
    other = executable("other")
    env = {"UV_SHIM_GIT_REAL_PATH": str(override), "PATH": str(other.parent)}
    assert discovery.find_real_git(shim_path=other, env=env) == str(override)


def test_invalid_override_does_not_silently_fall_back(executable, tmp_path):
    real = executable("real")
    env = {"UV_SHIM_GIT_REAL_PATH": str(tmp_path / "missing"), "PATH": str(real.parent)}
    with pytest.raises(FileNotFoundError):
        discovery.find_real_git(shim_path=tmp_path / "shim", env=env)


def test_override_cannot_select_the_shim(executable):
    shim = executable("shim")
    real = executable("real")
    env = {"UV_SHIM_GIT_REAL_PATH": str(shim), "PATH": str(real.parent)}
    with pytest.raises(FileNotFoundError):
        discovery.find_real_git(shim_path=shim, env=env)


def test_no_real_git_raises_instead_of_returning_shim(executable):
    shim = executable("shim")
    with pytest.raises(FileNotFoundError):
        discovery.find_real_git(shim_path=shim, env={"PATH": str(shim.parent)})


def test_explicit_empty_environment_does_not_use_parent_path(executable, monkeypatch):
    real = executable("real")
    monkeypatch.setenv("PATH", str(real.parent))
    with pytest.raises(FileNotFoundError):
        discovery.find_real_git(shim_path=real.parent / "shim", env={})
    assert discovery.find_real_git(shim_path=real.parent / "shim") == str(real)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable permission contract")
def test_posix_rejects_non_executable_and_directory(executable, tmp_path):
    non_executable = executable("non-executable")
    non_executable.chmod(0o644)
    directory = tmp_path / "directory" / "git"
    directory.mkdir(parents=True)
    real = executable("real")
    env = {
        "PATH": os.pathsep.join(map(str, [non_executable.parent, directory.parent, real.parent]))
    }
    assert discovery.find_real_git(shim_path=tmp_path / "shim", env=env) == str(real)


@pytest.mark.parametrize("extension", [".exe", ".cmd", ".bat"])
def test_windows_pathext_finds_supported_executable(extension, executable, tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "_IS_WINDOWS", True)
    real = executable("real", "git" + extension)
    env = {"PATH": str(real.parent), "PATHEXT": ".EXE;.CMD;.BAT"}
    assert discovery.find_real_git(shim_path=tmp_path / "shim", env=env) == str(real)


def test_windows_pathext_order_and_shim_exclusion(executable, monkeypatch):
    monkeypatch.setattr(discovery, "_IS_WINDOWS", True)
    shim = executable("bin with spaces", "git.exe")
    command = executable("bin with spaces", "git.cmd")
    executable("bin with spaces", "git.bat")
    env = {"PATH": f'"{shim.parent}"', "PATHEXT": ".EXE;.CMD;.BAT"}
    assert discovery.find_real_git(shim_path=shim, env=env) == str(command)


def test_windows_uses_standard_extensions_when_pathext_missing(executable, tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "_IS_WINDOWS", True)
    real = executable("real", "git.cmd")
    assert discovery.find_real_git(
        shim_path=tmp_path / "shim", env={"PATH": str(real.parent)}
    ) == str(real)


@pytest.mark.parametrize(
    "value, expected", [(None, False), ("0", False), ("true", False), ("1", True)]
)
def test_continuation_requires_exact_sentinel(value, expected):
    env = {} if value is None else {"__UV_SHIM_GIT_CONTINUATION": value}
    assert discovery.is_continuation(env) is expected


def test_continuation_defaults_to_process_environment(monkeypatch):
    monkeypatch.setenv("__UV_SHIM_GIT_CONTINUATION", "1")
    assert discovery.is_continuation() is True
    assert discovery.is_continuation({}) is False


def test_inject_continuation_preserves_parent_and_child_identity():
    parent = {"GIT_AUTHOR_NAME": "Existing Author", "GIT_COMMITTER_NAME": "Bot"}
    child = discovery.inject_continuation(parent)
    assert child == {**parent, "__UV_SHIM_GIT_CONTINUATION": "1"}
    assert "__UV_SHIM_GIT_CONTINUATION" not in parent
    assert discovery.is_continuation(child) is True
