# Implementation Plan: Git Author Identity Shim

**Branch**: `001-git-author-shim` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-git-author-shim/spec.md`

## Summary

Build a transparent CLI shim named `git` that intercepts AI coding agent invocations, injects dedicated bot committer/author identities and scoped SSH/HTTPS credentials based on repository remote URL matching, and delegates to the underlying real Git executable with complete fidelity (preserving exit codes, stdio, and OS signals) while leaving the human operator's ambient configuration (`~/.gitconfig`, `~/.ssh/config`) completely untouched.

## Technical Context

**Language/Version**: Python 3.12+ (built and managed via `uv`)

**Primary Dependencies**: Standard library (`os`, `sys`, `subprocess`, `signal`, `tomllib`, `hashlib`, `pathlib`), zero heavy external dependencies. Strict lazy-import architecture: top-level imports in `__main__.py` restricted to `os` and `sys`.
**Storage**: Local file configuration (TOML) for global settings (`~/.git-shim/config.toml`) and JSON for content-hash trust registry (`~/.git-shim/trusted-hashes.json`).

**Testing**: `pytest` for unit, contract, and end-to-end integration tests across Windows, macOS, and Linux.

**Target Platform**: Cross-platform (Windows 10/11, macOS 12+, Linux x86_64/aarch64).

**Project Type**: CLI executable / System shim.

**Performance Goals**: <5ms in-process CPU resolution overhead (measured via `time.perf_counter()`); single batched `git rev-parse` probe; total end-to-end wall-clock overhead <25ms on POSIX and <120ms on Windows CPython.
**Constraints**:
* No modification of user's personal configuration files (`~/.gitconfig`, `~/.ssh/config`).
* Zero secret leakage in `argv`, process tables (`ps aux`), remote URLs, or logs.
* Complete loop and self-recursion prevention when shim sits ahead of Git on `PATH`.
* Fail-closed on missing credentials or unmatched hosts during write operations.

**Scale/Scope**: Handles multi-tenant configurations (multiple bot profiles, wildcard repo matchers, SSH/HTTPS remotes, linked worktrees, and sequencer operations).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement / Gate | Status | Notes |
| :--- | :--- | :--- | :--- |
| **I. Augment Full Invocation, Then Delegate** | Preserve all flags/args, stdio, exit codes, and terminating signals across local/remote executions. | **PASS** | `os.execv` / `subprocess.Popen` with standard signal forwarding and full argument passthrough. |
| **II. Explicit Invocation Contracts** | Declare all modified env vars, provide dry-run / explain inspection. | **PASS** | `git-shim explain` CLI and `GIT_SHIM_EXPLAIN=1` provide structured inspection with zero execution. |
| **III. Secret Handling (NON-NEGOTIABLE)** | Secrets never in `argv`, never in URLs, redacted in logs/output, sourced from secure locations. | **PASS** | Secrets injected via ephemeral credential helpers / stdio; strictly redacted in all diagnostics. |
| **IV. Cross-Platform Parity** | Equivalent behavior on Windows, macOS, and Linux. | **PASS** | Explicit handling of `PATHEXT`, `.exe` binaries, Windows `NUL` vs `/dev/null`, and platform signals. |
| **V. Test-First (NON-NEGOTIABLE)** | Red-Green-Refactor; tests for passthrough, secret redaction, and error fail-safe before implementation. | **PASS** | Test suite organized into unit, contract, and integration tests covering all 12 user stories. |
| **VI. Explicit, Transparent Behavior** | Zero silent mutation of user's shell or configs; actionable error messages. | **PASS** | Fail-safe write refusals provide exact remedy; operator files are never touched. |

## Project Structure

### Documentation (this feature)

```text
specs/001-git-author-shim/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── cli.md           # CLI & environment variables specification
│   └── config.md        # TOML configuration schema
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/git_author_shim/
├── __init__.py
├── __main__.py                      # Entrypoint for `git` and `git-shim`
├── data_models.py                   # Dataclasses and internal state models
├── cli.py                           # Argument parsing and explain/trust/shadow subcommands
├── config.py                        # TOML configuration loader and validator
├── agent_detection.py               # Agent mode and vendor marker detection
├── real_git_discovery.py            # Real Git binary resolution and recursion avoidance
├── repo_identity_matcher.py         # Remote URL canonicalization and wildcard pattern matcher
├── commit_authorship_classifier.py  # Commit classification (originating vs carrying) & sequencer detection
├── credential_injector.py           # SSH key & HTTPS credential helper injection
├── shadow.py                        # `git` trampoline shadow enable/disable/status
└── repo_config_trust.py             # SHA-256 content-hash trust registry

tests/
├── conftest.py                      # Pytest fixtures, isolated HOME/PATH environments, fake git wrappers
├── unit/
│   ├── test_data_models.py
│   ├── test_config.py
│   ├── test_real_git_discovery.py
│   ├── test_agent_detection.py
│   ├── test_repo_identity_matcher.py
│   ├── test_https_credentials.py
│   ├── test_command_classifier.py
│   ├── test_sequencer_detection.py
│   ├── test_repo_config_trust.py
│   └── test_ambiguity_matcher.py
├── contract/
│   ├── test_process_execution.py
│   ├── test_trust_cli.py
│   └── test_explain_schema.py
└── integration/
    ├── test_ssh_injection.py
    ├── test_passthrough.py
    ├── test_https_injection.py
    ├── test_fail_safe.py
    ├── test_recursion_protection.py
    ├── test_cherry_pick_rebase.py
    ├── test_fail_closed_credentials.py
    ├── test_tag_attribution.py
    ├── test_stash_notes.py
    └── test_performance.py
```

**Structure Decision**: Python package under `src/git_author_shim/` installed with console script entry points `git` and `git-shim`, accompanied by modular unit, contract, and integration test suites in `tests/`.

## Complexity Tracking

> **Constitution Check has no violations. No complexity exemptions required.**
