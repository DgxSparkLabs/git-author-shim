# Idea Intake: Extensible Harness Detection

- **Slug**: harness-detection
- **Created**: 2026-09-08
- **Source**: pasted text
- **Type**: new-capability

## Idea (as captured)

> "Extensible Harness Detection (Future & Existing Harnesses)"
> "we a mechanism that help us support the tool being extensible to future harnesses that don't even exist today but support existing ones out the box in a simple, possibly user configurable way. the e2e suggestion will be able to be executed in a ci/cd testing environment? how can we e2e test for 'an agent under claude code or omp that executes git commands hits the shim'"

## Restated

Provide an extensible mechanism for `git-author-shim` that detects both existing AI coding harnesses (such as Claude Code and Oh My Pi) out of the box and unknown future harnesses in a simple, user-configurable way without requiring new tool releases, accompanied by automated end-to-end tests that prove an agent executing Git commands hits the shim in a zero-credential CI/CD environment.

## Origin & Context

- **Raised by**: Project operator during discussion on Claude Code and Oh My Pi detection boundaries.
- **Trigger**: Discovery that real-world harnesses export distinct process markers (`CLAUDECODE`, `OMPCODE`, `AI_AGENT`) that differ from the initial static vendor list, coupled with the need to ensure future harnesses are easily on-boardable while preventing false positives on human terminal sessions.

## First-Glance Unknowns

- [NEEDS CLARIFICATION: What exact data format should the harness registry take (e.g. checked-in `harnesses.toml` manifest vs code constants)?]
- [NEEDS CLARIFICATION: What wildcard or glob syntax should be allowed in `custom_agent_markers` without risking broad environment capture (e.g. restricting to prefix globs like `PREFIX_*`)?]
- [NEEDS CLARIFICATION: Should an interactive CLI diagnostic command such as `git-shim doctor` or `git-shim detect` be added to help operators onboard unknown harnesses?]
- [NEEDS CLARIFICATION: How should the CI/CD test harness simulate agent spawns across Ubuntu, macOS, and Windows while preserving the User Story 2 human-isolation guarantee?]
