"""Locate Git without recursing through this shim's executable."""

import os
import sys

_IS_WINDOWS = os.name == "nt"
_CONTINUATION = "__UV_SHIM_GIT_CONTINUATION"


def _is_shim(candidate: str, shim_path: str) -> bool:
    if os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(
        os.path.realpath(shim_path)
    ):
        return True
    try:
        return os.path.samefile(candidate, shim_path)
    except OSError:
        return False


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_real_git(shim_path=None, env=None) -> str:
    """Return an absolute executable path, or raise ``FileNotFoundError``.

    An explicit override is authoritative: invalid or recursive overrides fail
    rather than selecting an unexpected binary from PATH. File identity checks
    exclude symlink and hard-link aliases of the shim as well as its own path.
    """
    if env is None:
        env = os.environ
    shim_path = os.path.abspath(os.fspath(shim_path) if shim_path is not None else sys.argv[0])
    override = env.get("UV_SHIM_GIT_REAL_PATH")
    if override is not None:
        candidate = os.path.abspath(override)
        if _is_executable(candidate) and not _is_shim(candidate, shim_path):
            return candidate
        raise FileNotFoundError(
            "UV_SHIM_GIT_REAL_PATH must name an executable other than the Git shim"
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
        "Real Git was not found on PATH; set UV_SHIM_GIT_REAL_PATH to the Git executable"
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
