<!--
Sync Impact Report
==================
Version change: 2.0.0 → 2.1.0
Rationale: MINOR bump. The maintainer expanded the shim's scope beyond flags to the full
invocation context: environment variables (including secrets/passwords), working directory,
and execution target (local, container, or remote). This adds new principles and materially
expands existing guidance without removing or redefining a principle.

Modified principles:
  - I. Augment, Then Delegate → I. Augment the Full Invocation, Then Delegate (expanded to
    cover env vars, working directory, and execution target in addition to flags)
  - II. Explicit Flag Contracts → II. Explicit Invocation Contracts (expanded to cover env,
    cwd, and target, not only flags)
  - (new) III. Secret Handling (NON-NEGOTIABLE)
  - IV. Cross-Platform Parity → retained; extended to note container/remote targets
  - V. Test-First → retained; extended to cover env/cwd/target and secret handling
  - VI. Explicit, Transparent Behavior → retained; clarified the child-context vs user-shell
    distinction

Added sections: none (new material added as principles)
Removed sections: none

Deferred TODOs:
  - RATIFICATION_DATE remains the adoption date 2026-09-05. Amend if an earlier date is
    confirmed (PATCH bump).

Assumptions:
  - Domain per maintainer input: shims wrap existing CLI programs and may augment their flags,
    inject/manage environment variables (including secrets), change the working directory, and
    run the program locally, in a container, or on a remote host, then delegate.
-->

# uv-shims Constitution

## Core Principles

### I. Augment the Full Invocation, Then Delegate (NON-NEGOTIABLE)

A shim wraps an existing CLI program and may augment its **entire invocation** — flags,
environment variables, working directory, and execution target (a local process, a container,
or a remote host) — then delegates to that program. The wrapping MUST preserve the tool's
usefulness:

- Flags and arguments the shim does not explicitly handle MUST pass through unchanged. The
  shim MUST NOT drop, reorder, or silently rewrite them.
- Every input the shim adds, intercepts, or transforms — a flag, an environment variable, the
  working directory, or the execution target — MUST resolve to a well-defined, documented
  invocation of the underlying program.
- The underlying program's core functionality MUST remain reachable through the shim,
  regardless of whether it runs locally, in a container, or remotely.
- The underlying program's exit code, `stdin`/`stdout`/`stderr`, and terminating signals
  (SIGINT/SIGTERM on POSIX, Ctrl+C/Ctrl+Break on Windows) MUST be propagated unchanged across
  whatever execution target is used, including container and remote boundaries.

Rationale: The purpose of a shim here is deliberate enhancement of how and where a tool runs,
not transparency. It may change flags, environment, directory, and location, but it must never
break, weaken, or silently mangle the tool it fronts.

### II. Explicit Invocation Contracts (NON-NEGOTIABLE)

Everything a shim introduces or overrides across the invocation is its public contract and
MUST be explicit:

- Every added or overridden flag, injected or transformed environment variable, working
  directory change, and execution target MUST be declared and documented, including how it
  maps to the resulting invocation.
- Shim-introduced inputs MUST NOT collide with the underlying program's own flags or expected
  environment unless the override is intentional, documented, and justified.
- There MUST be a way to inspect the full resolved invocation for a given call — flags,
  environment (with secret values redacted, see Principle III), working directory, and target
  — without executing it (e.g. a dry-run or explain mode).

Rationale: Because shims change the flags, environment, directory, and location under which
known tools run, ambiguity about what the shim contributes versus the tool is the primary
source of confusion and bugs. Contracts must be explicit and inspectable.

### III. Secret Handling (NON-NEGOTIABLE)

Shims may pass secrets (passwords, tokens, keys) to the underlying program, typically via
environment variables. Secrets MUST be handled defensively:

- Secret values MUST NOT be written to logs, error messages, dry-run/explain output, or any
  persisted artifact in plaintext; such surfaces MUST redact them.
- Secrets MUST be passed via environment variables or a secure channel, NEVER via command-line
  arguments, which are visible in process listings.
- The shim MUST NOT persist secrets to disk in plaintext; when a secret must be sourced, it
  MUST come from an explicit location (environment, a referenced secret store, or an interactive
  prompt), never hardcoded.
- When delegating to a container or remote target, secrets MUST be transmitted over a secure
  channel and MUST NOT be baked into images, command lines, or shell history.

Rationale: Injecting credentials is a core capability of these shims, so credential leakage is
a first-class risk. Mishandled secrets are high-severity failures, not cosmetic ones.

### IV. Cross-Platform Parity

Behavior MUST be equivalent across Windows, macOS, and Linux, and consistent across execution
targets:

- Every feature MUST work on all three platforms or explicitly document the unsupported
  platform and fail there with a clear, actionable error.
- Path handling, executable extensions (`.exe`/`.cmd` vs. none), argument quoting, environment
  semantics, and signal semantics MUST be handled per-platform rather than assuming POSIX
  behavior.
- Local, container, and remote targets MUST present consistent observable behavior for the same
  logical invocation, differences being documented where the target makes them unavoidable.
- Platform-specific and target-specific code paths MUST have corresponding tests.

Rationale: Shims are invoked on mixed operating systems and against mixed targets; behavior that
diverges silently across either dimension breaks the promise of a consistent wrapped tool.

### V. Test-First (NON-NEGOTIABLE)

Development follows a strict test-first discipline:

- Tests MUST be written and MUST fail before the implementation that satisfies them is written
  (Red-Green-Refactor).
- Every fix for a reported bug MUST include a test that reproduces the bug and fails prior to
  the fix.
- The invocation contract MUST be covered in both directions: augmented/overridden inputs
  (flags, env, cwd, target) map to the intended invocation, and unhandled flags pass through
  unchanged.
- Secret handling (Principle III) MUST have tests asserting that secrets are never emitted to
  logs, errors, explain output, or argv.

Rationale: Invocation augmentation, passthrough, and secret redaction are subtle and easily
regressed. Tests are the only durable guarantee that Principles I–III hold as the code evolves.

### VI. Explicit, Transparent Behavior

The tool MUST be predictable and free of hidden magic:

- Configuration and invocation resolution MUST be explicit and inspectable; a user MUST be able
  to see which program a shim targets, where and how it runs, and how a given call is
  transformed.
- Constructing the child process's environment, working directory, and execution target is a
  core, declared purpose and is expected. However, the tool MUST NOT silently modify the
  *user's own* shell profiles, `PATH`, or ambient environment without explicit, opt-in action
  and clear reporting of what changed.
- Errors MUST be actionable: state what failed, the resolved inputs involved (secrets redacted),
  and the next step to remediate.

Rationale: Tooling that changes invocation behavior and mutates the operator's own environment
invisibly is a frequent source of hard-to-debug failures. Explicitness — while distinguishing
the intended child context from the user's own shell — keeps the system trustworthy.

## Compatibility Constraints

- A shim MUST remain valid when its underlying program, container image, or remote target is
  upgraded, moved, or reinstalled; a shim that can no longer locate or correctly invoke its
  target MUST fail loudly rather than silently invoke a wrong or missing program.
- The tool MUST NOT depend on undocumented internals of a wrapped program; it MAY only rely on
  that program's public CLI contract.
- Shims sit on invocation paths and MUST be efficient: resolution work that can be cached MUST
  be cached, and a shim MUST NOT perform network calls, container/remote setup, or environment
  mutation at invocation time unless that is the explicit, declared purpose of the invocation.
- The tool MUST NOT require elevated privileges for normal operation; any operation that does
  MUST be opt-in and clearly disclosed.

## Development Workflow & Quality Gates

- Every change MUST pass the automated test suite on all supported platforms before merge.
- Changes touching invocation augmentation/passthrough (Principles I, II), secret handling
  (Principle III), or platform/target handling (Principle IV) MUST include or update the
  corresponding tests in the same change.
- Any new or changed flag, environment variable, working-directory, or target behavior MUST
  update its documented contract in the same change.
- Code review MUST verify constitution compliance, with explicit attention to secret leakage; a
  reviewer MUST reject changes that weaken passthrough, contract explicitness, secret handling,
  parity, or transparency without a documented, justified exception.

## Governance

This constitution supersedes ad-hoc practices for the uv-shims project. All pull requests and
reviews MUST verify compliance with the principles above.

- **Amendments**: Proposed via pull request that edits this document, states the rationale, and
  identifies the version bump. Amendments require maintainer approval and, where behavior
  changes, a migration note.
- **Versioning policy** (semantic):
  - MAJOR: Backward-incompatible governance changes — removing or redefining a principle.
  - MINOR: Adding a new principle or section, or materially expanding guidance.
  - PATCH: Clarifications, wording, and non-semantic refinements.
- **Compliance review**: Maintainers MUST periodically confirm that code and tests still
  satisfy each principle, and MUST open remediation issues for any drift discovered.

**Version**: 2.1.0 | **Ratified**: 2026-09-05 | **Last Amended**: 2026-09-05
