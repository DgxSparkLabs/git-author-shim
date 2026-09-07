"""Enable or disable PATH shadowing through the installed ``git`` trampoline.

``uv tool install`` / ``uv sync`` install every ``[project.scripts]`` entry and
create a real ``git.exe`` (Windows) or ``git`` (POSIX) trampoline that
``CreateProcessW`` / ``execve`` can run without a shell. This module does not
create or delete that trampoline. It writes a marker that the ``git`` entry
point reads: when shadow is disabled, ``git`` passes through to real Git with
no identity injection.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_IS_WINDOWS = os.name == "nt"
_MARKER_NAME = ".git-shim-shadow"
_LAUNCHER_STEMS = frozenset({"git-shim", "git"})
SHADOW_ENV = "GIT_SHIM_SHADOW"
_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSY = frozenset({"0", "false", "no", "off", "disabled"})


class ShadowError(Exception):
    """A ``git-shim shadow`` failure that must not touch the trampoline."""


def git_launcher_name() -> str:
    return "git.exe" if _IS_WINDOWS else "git"


def _stem(path: Path) -> str:
    name = path.name.lower() if _IS_WINDOWS else path.name
    if _IS_WINDOWS:
        root, ext = os.path.splitext(name)
        if ext in {".exe", ".cmd", ".bat"}:
            return root
    return name


def _existing_executable(path: Path) -> Path | None:
    if path.is_file():
        return path
    if not _IS_WINDOWS:
        return None
    if path.suffix.lower() in {".exe", ".cmd", ".bat"}:
        return None
    for ext in (".exe", ".cmd", ".bat"):
        candidate = path.with_name(path.name + ext)
        if candidate.is_file():
            return candidate
    return None


def _real_shim(path: Path) -> Path:
    located = _existing_executable(path)
    if located is None:
        try:
            located = _existing_executable(path.resolve())
        except OSError:
            located = None
    if located is None:
        raise ShadowError(f"git-shim executable not found at {path}")
    return located.resolve()


def resolve_shim_executable(argv0: str) -> Path:
    """Return the ``git-shim`` or ``git`` launcher this process should manage."""

    invoked = Path(argv0)
    if _stem(invoked) in _LAUNCHER_STEMS:
        try:
            return _real_shim(invoked)
        except ShadowError:
            pass
    scripts = Path(sys.executable).resolve().parent
    names = ("git-shim.exe", "git-shim", "git.exe", "git") if _IS_WINDOWS else ("git-shim", "git")
    for name in names:
        candidate = scripts / name
        if candidate.is_file():
            return candidate.resolve()
    raise ShadowError(
        "could not locate the git-shim executable; run this command as `git-shim shadow ...`"
    )


def shadow_git_path(shim: Path) -> Path:
    return shim.with_name(git_launcher_name())


def _marker_path(shim: Path) -> Path:
    return shim.with_name(_MARKER_NAME)


def _read_marker(marker: Path) -> str | None:
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip().lower()


def is_shadow_enabled(argv0: str | None = None, env=None) -> bool:
    """True when the ``git`` trampoline should run the full shim.

    Precedence: ``GIT_SHIM_SHADOW`` (truthy/falsy), then the marker file beside
    the launcher. Missing marker defaults to enabled — ``uv`` installs ``git``
    as the shim.
    """

    environment = os.environ if env is None else env
    override = environment.get(SHADOW_ENV, "").strip().lower()
    if override in _FALSY:
        return False
    if override in _TRUTHY:
        return True
    try:
        launcher = resolve_shim_executable(argv0 or sys.argv[0])
    except ShadowError:
        return True
    state = _read_marker(_marker_path(launcher))
    if state is None:
        return True
    return state not in _FALSY


def enable(shim: Path) -> str:
    """Record that the installed ``git`` trampoline should run the full shim."""

    shim = _real_shim(shim)
    target = shadow_git_path(shim)
    if not target.is_file():
        raise ShadowError(
            f"git launcher not found at {target}; reinstall git-author-shim so the "
            "package can create the git console script"
        )
    _marker_path(shim).write_text("enabled\n", encoding="utf-8")
    warning = _path_warning(shim, target)
    message = f"enabled git shadow: {target}"
    return message if warning is None else f"{message}\n{warning}"


def disable(shim: Path) -> str:
    """Record that the installed ``git`` trampoline should pass through to real Git."""

    shim = _real_shim(shim)
    target = shadow_git_path(shim)
    _marker_path(shim).write_text("disabled\n", encoding="utf-8")
    if target.is_file():
        return f"disabled git shadow: {target} (passthrough to real Git)"
    return "disabled git shadow (git trampoline not installed; git-shim still works)"


def status_text(shim: Path) -> str:
    """Describe the trampoline, marker, and PATH winner."""

    shim = _real_shim(shim)
    target = shadow_git_path(shim)
    enabled = is_shadow_enabled(str(shim))
    if not target.is_file():
        shadow_state = f"{target} (missing trampoline)"
    elif enabled:
        shadow_state = f"{target} (enabled)"
    else:
        shadow_state = f"{target} (disabled, passthrough)"

    found = shutil.which("git")
    if found is None:
        path_state = "not found on PATH"
    elif target.is_file() and _same_file(Path(found), target):
        path_state = f"{found} (this trampoline)"
    else:
        path_state = f"{found} (system)"

    return f"launcher: {shim}\nshadow:   {shadow_state}\npath git: {path_state}"


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _path_warning(shim: Path, target: Path) -> str | None:
    found = shutil.which("git")
    if found is None:
        return f"warning: {shim.parent} is not on PATH; `git` will not resolve to the shim"
    if _same_file(Path(found), target):
        return None
    return (
        f"warning: `git` on PATH is {found}, not {target}; "
        f"put {shim.parent} earlier on PATH to shadow system Git"
    )
