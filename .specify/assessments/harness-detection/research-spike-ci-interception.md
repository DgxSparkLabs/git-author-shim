# Research Spike: Credential-Free CI Proof of Agent-to-Shim Interception

- **Slug**: harness-detection
- **Created**: 2026-09-08
- **Stage**: research (feasibility spike, scoped)
- **Feeds**: `/speckit-assess-shape` (as the appetite-defining risk) then `/speckit-assess-decide` (as a gate)
- **Status**: planned — not yet executed

## Feasibility Question

Can we prove, in a credential-free CI environment, that a process which spawns `git` the way a real AI harness does — no shell, `CreateProcessW` / `spawn` with only the tool-bin ahead of real Git on `PATH` — is intercepted by the shim and resolves to agent mode, without mutating any operator config and without any SSH key or HTTPS token present?

This is the one unknown from `problem.md` that a go/kill decision leans on. The intake asks it directly: "how can we e2e test for 'an agent under Claude Code or omp that executes git commands hits the shim'."

## Why This Is the Decisive Unknown

- The *marker-detection* unknown is already de-risked. Live evidence this session: `CLAUDECODE=1` and `OMPCODE=1` are exported by real harnesses, and detection is a synchronous stdlib env lookup. Whether the marker set is correct is a coverage question, not a feasibility one.
- The *interception-in-CI* unknown is not de-risked. The shim's whole value depends on an agent-spawned `git` actually routing through it. The README asserts a no-`.cmd`, native-trampoline spawn model and a `PATH`-shadow mechanism, but no automated evidence exists that this holds on a CI runner with no credentials, and the recently fixed mutual-shim recursion shows this path can break silently.

## Hypothesis

With exactly one shim install placed ahead of real Git on `PATH`, a no-shell child `git` invocation carrying an agent marker will be intercepted and will report agent mode and a resolved plan through `GIT_SHIM_EXPLAIN` / `git-shim explain --json`, on Ubuntu and Windows runners, with zero credentials configured and zero writes to `~/.gitconfig` or `~/.ssh/config`.

## Method (Throwaway Probe)

Scope the probe to exercise the *existing* mechanism. Build nothing permanent.

1. **Isolate the interception question from the marker-coverage question.** Trigger agent mode with a marker the current build already honors (`AGENT_ID`, or `GIT_SHIM_MODE=agent`). This keeps the spike about routing and CI, not about the marker list under redesign.
2. **Reproduce the harness spawn contract, not a shell.** Write a tiny launcher (Python `subprocess.run(["git", "explain"], shell=False)` and a Node `child_process.spawn("git", …)`) that inherits an environment carrying the agent marker. This mirrors how Claude Code / OMP spawn `git` and deliberately avoids a shell alias or `.cmd` wrapper.
3. **Prove interception with zero side effects.** Use `GIT_SHIM_EXPLAIN=1` (prints the resolved plan and exits 0 without running Git) and `git-shim explain --json`. Assert the plan shows agent mode, the resolving marker name, and a repository/identity decision — no commit, push, or credential-source contact.
4. **Assert the credential-free and no-mutation invariants.** Run with no SSH key and no token env/file/command configured; snapshot `~/.gitconfig` and `~/.ssh/config` (or their absence) before and after and assert they are byte-identical.
5. **Run it in CI, single OS first.** One throwaway job that installs exactly one shim, puts the tool-bin ahead of real Git on `PATH`, and runs steps 2–4. Confirm locally on this Windows box first, then one Ubuntu runner.
6. **Record what the plan actually contained** (redacted) as the evidence artifact, plus the runner OS and the `PATH` ordering used.

## Pass / Kill Criteria

- **Pass** — On both a local run and one CI runner, the no-shell child `git` is intercepted, `explain` reports agent mode with the resolving marker, no credentials are present, and operator config is unchanged. Interception is provable without any secret.
- **Needs-clarification** (routes back before `decide`) — Interception works locally but a CI-specific obstacle appears (runner `PATH` precedence, trampoline execution, or the double-install recursion class of bug) that has a plausible fix worth scoping.
- **Kill / rethink** — Interception cannot be proven without secrets, or requires a shell wrapper (contradicting the stated native-spawn model), or the trampoline cannot be exercised non-interactively in CI.

## Time-Box & Effort

One day. If interception is not demonstrated locally within the first few hours, stop and record the blocker rather than expanding scope — the point is to reduce uncertainty cheaply, not to build the feature.

## Risks & Confounders

- **Double-install recursion.** CI that both `uv tool install`s the shim and installs the project into a venv places two `git` shims on `PATH`; before the recent fix this recursed without bound. The probe must install exactly one shim and assert the `git.exe` process count stays bounded.
- **Runner `PATH` precedence.** GitHub-hosted runners ship their own Git high on `PATH`; the probe must verify the tool-bin actually wins, or the interception "failure" is really a `PATH` artifact.
- **Realism gap.** Simulating the spawn contract is not the same as running the vendor binaries. Spawning real Claude Code / OMP needs install and auth, which breaks the credential-free constraint, so this spike proves the *mechanism* an agent relies on, not the vendor product itself. Note this limit explicitly in the findings.
- **Windows non-interactive trampoline.** The PE `git.exe` trampoline must run under a non-PTY CI shell; confirm it does not block on stdin.

## What This Spike Deliberately Does Not Test

- Whether the *marker set* is complete (that is the coverage redesign, already de-risked as a concept).
- The full three-OS matrix, real credential injection, or SSH/HTTPS transport selection — all post-go build work for SDD `implement`.
- Any design of the extensible registry, wildcard grammar, or diagnostic command.

## Outputs & Flow

- A short findings block appended here (result, evidence, OS, blockers), and the throwaway launcher + CI job deleted after the result is recorded.
- Into `shape`: the pass/kill result sets the appetite and picks between "detection-only" and "detection + e2e harness" option scopes.
- Into `decide`: a non-pass result makes the honest verdict needs-clarification, not go.
