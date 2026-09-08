# Problem Definition: Extensible Harness Detection

- **Slug**: harness-detection
- **Created**: 2026-09-08
- **Inputs used**: intake.md | research.md

## Problem Statement

`git-author-shim` decides whether a `git` invocation belongs to an AI agent by matching a hardcoded, exact-string list of environment markers that does not reflect what real harnesses export today (Claude Code sets `CLAUDECODE` and `AI_AGENT`, Oh My Pi sets `OMPCODE`, none of which the list matches — it carries `CLAUDE_CODE` instead), so agent writes are silently misattributed to the human operator or refused, and there is no automated, credential-free proof that an agent under a real harness invoking `git` actually reaches the shim. This matters now because new agent runtimes ship every quarter and each one currently requires a source change and release to be recognized.

## Affected Users & Stakeholders

- **Users — individual engineers on multi-agent machines**: Run Claude Code, Oh My Pi, Cursor, Codex, and Aider beside personal work; when their harness is unlisted or its real marker differs from the hardcoded entry, the shim does not switch to bot attribution automatically. [research.md Users & Demand]
- **Users — operators in worktree environments (Orca / OMP)**: Depend on the inverse guarantee — ambient workspace and CI plumbing must never flip their own manual commits into bot mode. [research.md; spec.md User Story 2]
- **Stakeholders — engineering managers, security & compliance teams**: Require reliable machine-vs-human commit provenance for IP and audit compliance; undetected agents corrupt that record. [research.md Users & Demand]
- **Stakeholders — `git-author-shim` maintainers**: Bear the recurring cost of editing and releasing the vendor list every time a harness appears or changes a flag. [research.md Prior Art; src/git_author_shim/agent_detection.py]
- **Users — early adopters of emerging agents**: Want newly released tools recognized without waiting for an upstream release. [NEEDS CLARIFICATION: demand for this is an assumption, not yet evidenced — research.md marks it medium confidence]

## Goals

- Existing real-world harnesses (at minimum Claude Code and Oh My Pi, plus Cursor, Codex, Aider) are recognized out of the box using the markers they actually export.
- An operator can make the shim recognize a harness that does not exist today without a new tool release.
- Detection stays correct under the human-isolation invariant: human terminal sessions, CI runs, and Orca/OMP workspace plumbing are never treated as agents by default.
- Automated, zero-credential end-to-end evidence exists that an agent running under a supported harness and invoking `git` is intercepted by the shim, and it runs in CI across Ubuntu, macOS, and Windows.
- Detection continues to meet its standing constraints: under 5 ms per invocation, standard-library only, no network or subprocess.

## Non-Goals

- Selecting the registry format, marker-matching grammar, or any diagnostic command name or behavior — those are solution-space decisions for shaping and specification.
- Sandboxing or otherwise stopping a hostile or misconfigured agent from bypassing the shim; this remains an attribution and credential-scoping tool, not an enforcement boundary. [README Architecture and guarantees]
- Standardizing agent environment-variable conventions across vendors.
- Changing identity matching, credential injection, or commit-authorship classification.
- Detecting agents by signals other than the process environment (for example process-tree or parent-binary inspection). [NEEDS CLARIFICATION: whether env-only detection is sufficient, or whether marker drift forces a secondary signal]

## Success Metrics

- Share of listed real harnesses detected out of the box with no user configuration: target 100% of {Claude Code, Oh My Pi, Cursor, Codex, Aider} (baseline: Claude Code and Oh My Pi are undetected today — confirmed live in this session, where `CLAUDECODE=1` and `OMPCODE=1` are exported while `AGENT_ID` is absent, so `resolve_identity_mode` returns `human`. `_VENDOR_MARKERS` carries `CLAUDE_CODE`, which does not match the real `CLAUDECODE`, and omits `OMPCODE`, so there is no incidental generic-marker fallback).
- Effort to onboard an unknown future harness: target zero source edits and zero release — configuration only (baseline: requires a source change plus a release).
- False-positive rate on non-agent sessions (human terminal, CI without an agent, Orca/OMP worktree plumbing): target 0 (baseline: 0 for the currently enumerated workspace/CI variables; unmeasured under any future user-supplied wildcard).
- End-to-end interception coverage: target a passing CI job on all three operating systems that spawns a simulated agent, runs `git`, and asserts the shim ran — with no credentials present (baseline: no such test exists).
- Per-invocation detection overhead: target under 5 ms (baseline: currently met).

## Cost of Inaction

Agents running under unlisted or mismatched harnesses keep producing bot commits stamped with the human operator's identity — the exact compliance and IP-provenance failure the tool exists to prevent — or hit fail-closed refusals that force operators to export `GIT_SHIM_MODE=agent` by hand across varied shells. Maintainers keep patching a hardcoded list reactively, always one release behind the ecosystem. With no end-to-end interception test, a silent break in the `git`-to-shim path (of the kind just fixed for mutual shim recursion) can ship undetected, and the shim can appear installed while quietly passing every agent write through to the operator.

## Open Questions

- [NEEDS CLARIFICATION: Should the harness registry be a bundled package manifest, a user file under `~/.git-shim/`, or in-code constants?]
- [NEEDS CLARIFICATION: Should user-supplied marker patterns be restricted to prefix globs with a minimum non-wildcard prefix, and must broad tokens like `*`, `?`, `PATH`, or `GIT_*` be rejected outright?]
- [NEEDS CLARIFICATION: Is a diagnostic command warranted to help operators onboard unknown harnesses, and what should it inspect?]
- [NEEDS CLARIFICATION: How can CI simulate agent spawns on Ubuntu, macOS, and Windows while still proving the User Story 2 human-isolation guarantee holds?]
- [NEEDS CLARIFICATION: How should the design absorb upstream marker drift when vendors rename or stop exporting flags between versions?]
