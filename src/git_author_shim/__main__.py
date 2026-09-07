"""Console-script entry point for the ``git`` trampoline.

This module is imported on every single ``git`` call, including the ones the
operator makes for themselves, so its top-level imports are restricted to ``os``
and ``sys``. Everything else -- including the execution engine in
:mod:`git_author_shim.cli` -- is imported inside :func:`main`.
"""

import os
import sys


def main(argv: list[str] | None = None) -> int:
    """Run the shim, or pass through to real Git when shadow is disabled."""
    from git_author_shim.shadow import is_shadow_enabled

    arguments = sys.argv[1:] if argv is None else argv
    if not is_shadow_enabled(sys.argv[0], os.environ):
        from git_author_shim.cli import passthrough_git

        return passthrough_git(arguments, env=os.environ)

    from git_author_shim.cli import run_git

    return run_git(arguments, env=os.environ)


if __name__ == "__main__":
    sys.exit(main())
