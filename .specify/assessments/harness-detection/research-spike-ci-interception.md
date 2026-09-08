# Research Spike: Real-Harness Spawn and PATH-Routed Interception

- **Slug**: harness-detection
- **Created**: 2026-09-08
- **Stage**: research (feasibility spike, scoped)
- **Feeds**: `/speckit-assess-shape` (as the appetite-defining risk) then `/speckit-assess-decide` (as a gate)
- **Status**: executed 2026-09-08 — Gap 1 local leg PASS; CI-runner leg deferred to SDD; Gap 2 realism assessed

## What Already Ships (Baseline — Do Not Re-Prove)

Open Question #4 ("how can we e2e test for an agent under Claude Code or OMP that executes git commands hits the shim") is mostly answered already, so the spike must not re-propose it:

- `tests/integration/test_e2e_agent_detection.py` (commit `cabef8b`) proves the full offline chain `marker -> IdentityMode.AGENT -> matched identity -> stamped Git object`, with no credential, no network socket, and the operator profile relocated via `isolated_env`. It asserts `~/.gitconfig` and `~/.ssh` are left untouched, that a marker-driven push aborts before any network connection, and that explicit `human` mode and absent markers fall back cleanly.
- It exercises real harness variable *names* — `AGENT_ID`, `CLAUDE_CODE`, and the `PI_*` / `ORCA_*` / `CLAUDECODE` families under `custom_agent_markers` — not just `GIT_SHIM_MODE=agent`.
- `.github/workflows/ci.yml` runs `pytest tests/` on `ubuntu-latest`, `macos-latest`, and `windows-latest` across Python 3.12 and 3.13. A credential-free cross-OS CI job already exists.

The marker-detection unknown and the credential-free-CI unknown are therefore de-risked. This corrects an earlier draft of this spike that wrongly claimed no such evidence existed.

## The Genuine Residual (What the Spike Targets)

Two gaps survive, and both are about *realism of the interception path*, not the detection logic:

1. **PATH-routed interception of a bare `git` spawn is untested.** Every passing assertion resolves interception either in-process (`_explain` calls `git_author_shim.cli:main` directly) or through a subprocess that runs `python -m git_author_shim` with `GIT_SHIM_REAL_PATH` and `GIT_SHIM_SHADOW=1` set explicitly. Nothing proves that a no-shell `spawn("git", ...)` — the actual harness contract — resolves through `PATH` to the installed trampoline and is intercepted. That routing surface (tool-bin `PATH` precedence, trampoline discovery, and the two-install mutual-recursion class just fixed) has no automated coverage.
2. **No real harness process ever spawns `git`, and the live-harness probe is inert in CI.** `test_live_harness_environment_is_detected_when_configured` skips unless the suite runs inside a recognized harness; CI runners export no such markers, so it never runs there. Detection is proven from injected marker *values*, never from an actual Claude Code / OMP process spawning `git`.

## Feasibility Questions

1. In credential-free CI with exactly one shim install placed ahead of real Git on `PATH`, does a no-shell `spawn("git", ["status"])` (or `GIT_SHIM_EXPLAIN=1 git ...`) carrying an agent marker get intercepted, with the `git.exe` process count staying bounded?
2. How much real-harness realism can be bought without credentials — can any actual vendor CLI reach a `git` call offline and unauthenticated — and if not, is simulated-marker parity a sufficient basis for the go decision?

## Hypothesis

Placing one shim on `PATH` ahead of real Git and issuing a no-shell `git` spawn with an agent marker will be intercepted and will report agent mode through `explain`, on Ubuntu and Windows, with no credential present, no operator config mutated, and a bounded process count. The real-harness-process gap will prove partly irreducible offline, so the spike's second output is a recommendation on how much realism to require.

## Method (Throwaway Probe)

Build nothing permanent; reuse the shipping mechanism.

1. **Gap 1 — PATH routing.** Enable shadow (`git-shim shadow enable`), put the tool-bin ahead of real Git on `PATH`, and from a launcher that spawns without a shell (Python `subprocess.run(["git", ...], shell=False)`, Node `child_process.spawn("git", ...)`) run `git` with `GIT_SHIM_EXPLAIN=1` and an agent marker set. Assert: the printed plan shows agent mode and the resolving marker; the `PATH` winner is the shim, not system Git; `~/.gitconfig` / `~/.ssh` are byte-identical before and after; and the `git.exe` process count stays bounded (guards the double-install recursion regression). Local (this Windows box) first, then one Ubuntu CI job.
2. **Gap 2 — real-harness realism.** Attempt the smallest faithful reproduction of a harness spawn: a stub that sets the documented markers and execs `git` with no shell, and a check of whether any installed vendor CLI can be driven to invoke `git` offline without auth. Record exactly where the credential-free constraint caps realism.
3. **Record evidence** (redacted plan, runner OS, `PATH` ordering, process-count trace) in a Findings block appended below.

## Pass / Kill Criteria

- **Pass** — A no-shell `git` spawn is intercepted via `PATH` on one CI runner and locally, marker-driven, credential-free, config unchanged, process count bounded. The routing gap is closeable with a permanent regression test in SDD.
- **Needs-clarification** (routes back before `decide`) — Routing works locally but a CI-specific obstacle appears (runner `PATH` precedence, non-interactive trampoline, or install layout) with a plausible, scopeable fix.
- **Kill / rethink** — Interception of a bare `git` spawn cannot be proven without a shell wrapper (contradicting the native-spawn model) or without secrets.

## Time-Box & Effort

Half a day. Gap 1 is a focused coverage probe against a shipping mechanism; Gap 2 is a bounded realism assessment that ends in a recommendation, not a build.

## Risks & Confounders

- **Double-install recursion.** CI that both `uv tool install`s the shim and installs the project into a venv places two `git` shims on `PATH`. Install exactly one and assert bounded process count; this is the regression surface from commit `6340a28`.
- **Runner `PATH` precedence.** Hosted runners ship Git high on `PATH`; verify the tool-bin actually wins or a "miss" is really a `PATH` artifact.
- **Irreducible realism gap.** Real Claude Code / OMP need install and auth; running them breaks the credential-free constraint. The spike proves the *mechanism* an agent relies on, and must state plainly that simulated-marker parity is the ceiling for offline CI.
- **Windows non-interactive trampoline.** The PE `git.exe` trampoline must run under a non-PTY CI shell without blocking on stdin.

## What This Spike Deliberately Does Not Test

- The detection chain, no-mutation, fail-closed, and cross-OS credential-free execution already covered by `test_e2e_agent_detection.py` and `ci.yml`.
- Whether the marker set is complete (coverage redesign, conceptually de-risked).
- The extensible registry format, wildcard grammar, or any diagnostic command.

## Outputs & Flow

- A Findings block appended here (result, evidence, OS, blockers, realism ceiling); the throwaway launcher and any temporary CI job deleted after the result is recorded. A permanent PATH-routing regression test, if warranted, is left for SDD `implement`.
- Into `shape`: the result sets appetite and chooses between "detection/registry only" and "detection + PATH-routing regression coverage" option scopes.
- Into `decide`: a non-pass result makes the honest verdict needs-clarification, not go.

## Findings (executed 2026-09-08, Windows 11, this box)

All evidence below is *observed* on this machine unless tagged otherwise. The probe used exactly one shim (the fixed `.venv/Scripts/git.exe` trampoline) on a minimal `PATH` ahead of real Git, spawned `git` with no shell (`subprocess.run([...], shell=False)`), and was deleted after the run.

### Gap 1 — PATH-routed, no-shell interception: PASS (local)

- **Shim wins `PATH` resolution.** `shutil.which("git")` over `[.venv/Scripts, C:\Program Files\Git\cmd, ...]` resolved to `...\.venv\Scripts\git.EXE`, not system Git. (observed, high)
- **A bare `git` spawn is intercepted and detects agent mode.** `GIT_SHIM_EXPLAIN=1 git commit -m probe` with `AGENT_ID=spike-probe-agent` (no shell) returned rc 0 and printed `Mode: agent (detected via AGENT_ID)`, `Target Host: github.com`, `Write Permitted: NO` (fail-closed — no identity configured), then exited *without* running Git. The shim ran, not real Git. (observed, high)
- **Real-git discovery skips the sibling shim via `PATH`.** `git --version` under shadow+agent returned `git version 2.54.0.windows.1` in well under a second — so `find_real_git` discovered `C:\Program Files\Git\cmd\git.exe` by walking `PATH` past its own sibling trampoline, with no `GIT_SHIM_REAL_PATH` override. (observed, high)
- **Process count bounded.** `git.exe` count after both spawns was 1 — no runaway. Contrast the two-install case earlier this session, which climbed 3→8→14→… unbounded until tree-killed. (observed, high)
- **No operator mutation.** `~/.gitconfig` was byte-identical before/after (197 bytes) and `~/.git-shim/` was never created. (observed, high)

**Not yet run:** the same probe on a CI runner (Ubuntu). `ci.yml` already runs the suite cross-OS, so the only missing piece is a *permanent* PATH-routing regression test; once added in SDD it runs cross-OS automatically. Residual risk is low but non-zero (runner `PATH` precedence differs). Full spike "Pass" therefore waits on that one CI leg.

### Gap 2 — real-harness realism: assessed (ceiling reached)

- **A real harness process really does route a bare `git` through the installed shim.** On this session's *live* operator `PATH`, `git` resolves to `C:\Users\devic\.local\bin\git.EXE` — an installed shim, first on `PATH` — confirming the spawn→PATH→shim routing is a production reality, not only a simulated construct. (observed, high)
- **The live shim is the pre-fix copy.** That `~/.local/bin` shim is a separate `uv tool install` copy predating the recursion fix (`6340a28`); the fix is not live for the operator until reinstall. The ambient `git` was therefore *not* exercised here (running it would reignite the proven old-code recursion if `.venv/Scripts` is also live). (observed, high)
- **Under the real harness the shim resolves to human today.** Live env exports `CLAUDECODE=1` and `OMPCODE=1` but not `CLAUDE_CODE`/`AGENT_ID`/`AI_AGENT`, so `_VENDOR_MARKERS` does not match and detection returns human — reconfirming the problem baseline (detection-coverage gap), which is a separate, already-documented question. (observed, high)
- **Vendor-binary realism is irreducible offline.** Driving an actual Claude Code / OMP process to emit a deterministic `git` call needs auth and network, which breaks the credential-free constraint. The faithful, reproducible substitute is exactly Gap 1's contract — a no-shell `git` spawn on `PATH` carrying the harness's documented markers — and the live resolution above confirms that substitute matches production routing. Simulated-marker parity is the ceiling and is sufficient for the go decision. (observed + reasoning, medium)

### Result & Flow

- **Gap 1 local: PASS.** PATH-routed no-shell interception, real-git discovery, bounded process count, and zero operator mutation are proven for the fixed code with a single install.
- **Gap 2: ceiling reached.** Real-harness routing is confirmed real; vendor-binary drive-through is out of scope for credential-free CI; simulated-marker parity stands in faithfully.
- **Into `shape`:** appetite is small — the mechanism works; the residual is a permanent PATH-routing regression test plus the marker-coverage fix. This favors the "detection fix + PATH-routing regression coverage" option over any larger rebuild.
- **Into `decide`:** not a full go yet — the CI-runner leg of Gap 1 is unproven, so the honest posture is *go once the PATH-routing regression test lands and runs green cross-OS in CI*, not before.
