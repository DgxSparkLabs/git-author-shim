"""Console-script entry point for the ``git`` shim.

This module is imported on every single ``git`` call, including the ones the
operator makes for themselves, so its top-level imports are restricted to ``os``
and ``sys``. Everything else -- including the execution engine in
:mod:`git_author_shim.cli` -- is imported inside :func:`main`.
"""

import os
import sys


def main(argv: list[str] | None = None) -> int:
    """Delegate to real Git and return its exit code unchanged."""
    from git_author_shim.cli import run_git

    return run_git(sys.argv[1:] if argv is None else argv, env=os.environ)


if __name__ == "__main__":
    sys.exit(main())
