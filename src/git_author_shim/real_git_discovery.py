"""Locate Git without recursing through this shim's executable."""

import os
import shutil
import sys

_IS_WINDOWS = os.name == "nt"
_CONTINUATION = "__GIT_SHIM_CONTINUATION"


def _launcher_stem(path: str) -> str:
    name = os.path.basename(path)
    if _IS_WINDOWS:
        name = name.lower()
        root, ext = os.path.splitext(name)
        if ext:
            name = root
    return name


def _is_shim(candidate: str, shim_path: str) -> bool:
    if os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(
        os.path.realpath(shim_path)
    ):
        return True
    try:
        if os.path.samefile(candidate, shim_path):
            return True
    except OSError:
        pass
    candidate_dir = os.path.normcase(os.path.abspath(os.path.dirname(candidate)))
    shim_dir = os.path.normcase(os.path.abspath(os.path.dirname(shim_path)))
    if candidate_dir == shim_dir:
        stems = {_launcher_stem(candidate), _launcher_stem(shim_path)}
        if stems == {"git", "git-shim"}:
            return True
    return False


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _resolve_own_path(shim_path: str, env) -> str:
    """Turn ``sys.argv[0]`` (often a bare ``git``) into the launcher file.

    Windows ``CreateProcessW`` runs ``git.exe`` from PATH but leaves
    ``argv[0]`` as ``git``. Treating that as the shim path would make PATH
    discovery select our own trampoline and recurse.
    """

    raw = os.fspath(shim_path)
    absolute = os.path.abspath(raw)
    if _is_executable(absolute):
        return absolute
    located = shutil.which(os.path.basename(raw) or raw, path=env.get("PATH"))
    if located:
        return os.path.abspath(located)
    return absolute


def find_real_git(shim_path=None, env=None) -> str:
    """Return an absolute executable path, or raise ``FileNotFoundError``.

    An explicit override is authoritative: invalid or recursive overrides fail
    rather than selecting an unexpected binary from PATH. File identity checks
    exclude symlink and hard-link aliases of the shim as well as its own path.
    The ``git`` console-script trampoline beside ``git-shim`` is also skipped
    so discovery cannot recurse through a shadowed invocation.
    """
    if env is None:
        env = os.environ
    shim_path = _resolve_own_path(
        os.fspath(shim_path) if shim_path is not None else sys.argv[0], env
    )
    override = env.get("GIT_SHIM_REAL_PATH")
    if override is not None:
        candidate = os.path.abspath(override)
        if _is_executable(candidate) and not _is_shim(candidate, shim_path):
            return candidate
        raise FileNotFoundError(
            "GIT_SHIM_REAL_PATH must name an executable other than the Git shim"
        )

    names = ("git",)
    if _IS_WINDOWS:
        extensions = env.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
        names = tuple("git" + extension.lower() for extension in extensions.split(";") if extension)
    path = env.get("PATH", "")
    if path:
        for directory in path.split(";" if _IS_WINDOWS else ":"):
            if _IS_WINDOWS:
                directory = directory.strip('"')
            for name in names:
                candidate = os.path.abspath(os.path.join(directory, name))
                if _is_executable(candidate) and not _is_shim(candidate, shim_path):
                    return candidate
    raise FileNotFoundError(
        "Real Git was not found on PATH; set GIT_SHIM_REAL_PATH to the Git executable"
    )


def is_continuation(env=None) -> bool:
    """Recognize only the internal loop sentinel, not an authorization grant."""
    if env is None:
        env = os.environ
    return env.get(_CONTINUATION) == "1"


def inject_continuation(env) -> dict[str, str]:
    """Copy the child environment and mark re-entry without changing its parent."""
    child = dict(env)
    child[_CONTINUATION] = "1"
    return child
