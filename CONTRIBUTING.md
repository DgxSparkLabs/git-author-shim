# Contributing to git-author-shim

Thank you for your interest in contributing. **git-author-shim** is a dedicated Git author identity and credential shim for AI coding agents. It attributes agent work to host-scoped bot identities and injects matching credentials, without rewriting the operator's `~/.gitconfig` or `~/.ssh/config`.

This repository publishes the Python package `git_author_shim` at [https://github.com/DgxSparkLabs/git-author-shim](https://github.com/DgxSparkLabs/git-author-shim).

## Core engineering principles

Contributions must preserve these invariants:

1. **Zero runtime dependencies.** Production code uses the Python 3.12+ standard library only. Development tools (`pytest`, `ruff`) belong in the `dev` dependency group, never in runtime `dependencies`.
2. **100% Test-Driven Design.** Tests defend observable contracts, not implementation plumbing. Follow red-green-refactor: write a failing test for the contract, implement the minimum that makes it pass, then refactor. Behavioral changes without tests will not be merged.
3. **Cross-platform parity.** Windows and POSIX must agree on exit codes, signal forwarding, path handling, and user-visible outcomes. Platform-specific code requires corresponding tests.
4. **Lazy imports in `__main__.py`.** `src/git_author_shim/__main__.py` may import only `os` and `sys` at module top level. All other imports stay inside functions so process startup stays cheap when the shim is on `PATH`.

## Development workflow

### Clone

```bash
git clone https://github.com/DgxSparkLabs/git-author-shim.git
cd git-author-shim
```

### Environment setup

Requires [uv](https://docs.astral.sh/uv/) and system Git.

```bash
uv venv
uv sync
```

### Test suite

```bash
uv run pytest tests/
```

### Code quality and formatting

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Apply formatting with `uv run ruff format src tests` before opening a pull request.

## Contribution process

1. **Discuss first.** Open or comment on a GitHub issue before substantial work (new matching rules, credential sources, CLI surface, or behavior changes). Small, obvious fixes can go straight to a pull request.
2. **Tests are required for behavioral changes.** Add or update tests that fail on the old contract and pass on the new one. Prefer observable outcomes: attribution, refusal, redaction, passthrough, and trust-gate decisions. Do not assert internal field copies, mock echoes, or source text.
3. **Keep secrets out of the suite.** Tests must never print tokens, private keys, or credential-command output. Explain and diagnostic paths must stay redacted.
4. **Pull request conventions.**
   - Use a focused branch and a title that names the observable change (`fix: refuse equal-specificity identity ties`).
   - Describe the contract you are changing, the tests that defend it, and any operator-facing documentation updates (`README.md`, `CONTRIBUTING.md`).
   - Do not modify `~/.gitconfig`, `~/.ssh/config`, or operator credential stores — not even in examples that run as tests.
   - Keep runtime dependency-free. Do not add third-party imports to `src/`.
   - Confirm `uv run pytest tests/`, `uv run ruff check src tests`, and `uv run ruff format --check src tests` locally.

By contributing, you agree that your work is licensed under the MIT License (see `LICENSE`).
