# Idea Intake: Full Harness End-to-End Test and CI

- **Slug**: harness-e2e-tests-detection
- **Created**: 2026-09-08
- **Source**: pasted text
- **Type**: improvement

## Idea (as captured)

> "Full Harness End-to-End Test and CI"
> "how can we e2e test for 'an agent under claude code or omp that executes git commands hits the shim' ... the e2e suggestion will be able to be executed in a ci/cd testing environment?"

## Restated

Implement a credential-free, hermetic end-to-end integration test suite and CI workflow that validates that an AI coding agent process (under harnesses like Claude Code or Oh My Pi) executing bare `git` commands resolves to the `git-author-shim` trampoline on `PATH`, correctly detects the harness environment, and stamps bot authorship without altering operator configuration.

## Origin & Context

- **Raised by**: Project operator during discussions on verifying agent detection in automated CI/CD pipelines.
- **Trigger**: Need to prove real `PATH`-resolved bare `git` execution across Ubuntu, macOS, and Windows in CI without requiring live agent login credentials, paid API keys, or interactive TTYs, while avoiding cross-platform process spawning traps (e.g. Windows `CreateProcessW` parent environment resolution).

## First-Glance Unknowns

- [NEEDS CLARIFICATION: Should the CI suite run against a checked-in `harnesses.toml` manifest to parametrize tests across all supported harnesses?]
- [NEEDS CLARIFICATION: How should the CI workflow handle optional real CLI executable smoke tests (e.g. `claude --version` or `omp --version`) without failing when those tools are uninstalled or unauthenticated on CI runners?]
- [NEEDS CLARIFICATION: What assertion depth is needed for secondary Git objects (tags, stashes, notes) in the CI pipeline?]
