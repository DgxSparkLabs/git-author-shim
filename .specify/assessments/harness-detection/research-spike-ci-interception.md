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

All evidence below is *observed* on this machine unless tagged otherwise. The probe pointed a minimal `PATH` — `[.venv/Scripts, C:\Program Files\Git\cmd, C:\Windows\System32, C:\Windows]` — at the fixed `.venv/Scripts/git.exe` trampoline (deliberately excluding `C:\Users\devic\.local\bin`), spawned `git` with no shell (`subprocess.run([...], shell=False)`), and was deleted after the run. It engaged the shim by setting `GIT_SHIM_SHADOW=1` in the child env — the same activation shortcut the existing `_run_shim` subprocess test uses, **not** a `git-shim shadow enable` marker beside the launcher.

### Gap 1 — PATH-routed, no-shell interception: PASS (local, narrow)

- **Shim wins `PATH` resolution.** `shutil.which("git")` over the probe `PATH` resolved to `...\.venv\Scripts\git.EXE`, ahead of `C:\Program Files\Git\cmd`. (observed, high)
- **A bare `git` spawn is intercepted and detects agent mode.** `GIT_SHIM_EXPLAIN=1 git commit -m probe` with `AGENT_ID=spike-probe-agent` (no shell) returned rc 0 and printed `Mode: agent (detected via AGENT_ID)`, `Target Host: github.com`, `Write Permitted: NO` (fail-closed — no identity configured), then exited *without* running Git. The shim ran, not real Git. (observed, high)
- **Real-git discovery skips the sibling shim via `PATH`, with no override.** `git --version` (shadow via env, agent marker) returned `git version 2.54.0.windows.1` in well under a second — so `find_real_git` discovered `C:\Program Files\Git\cmd\git.exe` by walking `PATH` past its own sibling trampoline, without any `GIT_SHIM_REAL_PATH` set. This is the genuine advance over the existing subprocess test, which hardcodes both `GIT_SHIM_REAL_PATH` and the module path. (observed, high)
- **Process count bounded.** `git.exe` count after both spawns was 1 — no runaway. Contrast the two-install case earlier this session, which climbed 3→8→14→… unbounded until tree-killed. (observed, high)
- **No operator mutation.** `~/.gitconfig` was byte-identical before/after (197 bytes); `~/.git-shim/` did not exist before and was not created. (observed, high)

**Honest delta & limits.** What is *newly* proven is narrow: (1) `PATH` resolution selects the trampoline over real Git, and (2) real-Git discovery works with no `GIT_SHIM_REAL_PATH`. This is **not** a verification of the `git-shim shadow enable` install layout — the probe forced shadow via env and used `.venv/Scripts` as the `PATH` head, not a marker-bearing tool-bin. Identity matching was also *not* exercised: with no `~/.git-shim/config.toml`, the plan resolves agent mode but matches no identity (`Matched Profile: -`). That full marker→identity→stamped-object chain is already covered by `test_e2e_agent_detection.py`, so the spike leaves it there rather than reseeding a throwaway HOME.

**Not yet run:** the same probe on a CI runner (Ubuntu). `ci.yml` already runs the suite cross-OS, so the missing piece is a *permanent* PATH-routing regression test; once added in SDD it runs cross-OS automatically. Residual risk is low but non-zero (runner `PATH` precedence differs). Full spike "Pass" therefore waits on that one CI leg.

### Gap 2 — real-harness realism: assessed (ceiling reached)

- **A live, shadow-enabled install already routes a bare `git` in production.** Corrected machine state: `C:\Users\devic\.local\bin\` contains `git.exe` (≈1 day old), `git-shim.exe`, **and** a `.git-shim-shadow` marker — a full opt-in shim install — and it wins the ambient operator `PATH`. So a real harness spawning `git` does hit an installed, shadow-enabled shim; this is genuine Gap-2 evidence, not simulation. (An earlier discovery step reporting `~/.local/bin` "absent" was a bash-`$HOME` artifact and was wrong.) (observed, high)
- **That live shim is the pre-fix build, and every session `git` went through it.** It predates the recursion fix (`6340a28`). Every ambient `git` this session — commits included — was routed through it, succeeding in **human passthrough** (its live markers `CLAUDECODE`/`OMPCODE` are unmatched, so it delegates to real Git) and *not* recursing, because `.venv/Scripts` only joins `PATH` under `uv run`. The ambient `git` was therefore not exercised non-explain here; the earlier unbounded recursion reproduced only under the two-install (`uv run`) condition. (observed, high)
- **Under the real harness the shim resolves to human today.** Live env exports `CLAUDECODE=1` and `OMPCODE=1` but not `CLAUDE_CODE`/`AGENT_ID`/`AI_AGENT`, so `_VENDOR_MARKERS` does not match and detection returns human — reconfirming the problem baseline (detection-coverage gap), a separate, already-documented question. (observed, high)
- **Vendor-binary realism is only partly irreducible — the strong claim is REFUTED.** Driven live this session (see "Live real-harness verification" below), the real `omp` (v18.1.15) and `claude` (v2.1.263) binaries **did** spawn `git` offline with **no model round-trip** (from already-authenticated installs — not proven on an unauthenticated/clean image) via their local-shell REPL escape: omp's `!git …` (a read probe and a real `! git commit` write) and claude's `! …` shell mode. Two other credential-free candidates from the subagent design — `omp --mode rpc {type:bash}` and `claude --bg --exec` — were **not** driven successfully: a live `--mode rpc` attempt sent the `{type:bash}` frame and got no bash-result back (only command-catalog re-emission), so its frame shape is unverified. The spawned `git` (via the escape) hit the shim, which stamped identity on a real `! git commit` and failed closed with no matching identity. What remains genuinely auth-bound is only *autonomous LLM-decided* git. Caveat: those paths route `git` through the harness's **shell** executor, so they prove vendor process → shell → PATH git → shim, **not** the no-shell `CreateProcessW("git")` contract that Gap 1 owns. Simulated-marker parity is still the right CI oracle; real-binary drive is an optional local realism gate. (observed, high)

### Result & Flow

- **Gap 1 local: PASS (narrow).** PATH selection of the trampoline, `GIT_SHIM_REAL_PATH`-free real-git discovery, bounded process count, and zero operator mutation are proven for the fixed code under a controlled single-shim `PATH`. The shadow-marker install layout and identity matching — earlier deferred — were since proven live (the real `.git-shim-shadow` marker engaged, and commit `7198d27` stamped the bot as author+committer); the only Gap-1 leg still unproven is the CI-runner cross-OS run.
- **Gap 2: strong "irreducible offline" claim refuted; ceiling clarified.** Real `omp`+`claude` were driven to spawn `git` offline via local-shell APIs and hit the shim; only autonomous LLM-decided git needs auth+network. That drive is shell-routed, so the no-shell contract stays Gap 1's; the stub remains the CI oracle, with real-binary drive as an optional local gate.
- **Into `shape`:** appetite is small — the mechanism works; the residual is a permanent PATH-routing regression test plus the marker-coverage fix. This favors the "detection fix + PATH-routing regression coverage" option over any larger rebuild.
- **Into `decide`:** not a full go yet — the CI-runner leg of Gap 1 is unproven, so the honest posture is *go once the PATH-routing regression test lands and runs green cross-OS in CI*, not before.

### Operator hazard (out of pipeline)

The live `C:\Users\devic\.local\bin\git.exe` is the pre-`6340a28` build, so any session where `.venv/Scripts` also lands on `PATH` (e.g. `uv run`, an activated venv) re-triggers the unbounded `git.exe` recursion that had to be tree-killed. One-command fix, independent of this assessment: `uv tool install --force .` from the clone (or the `git+https://…` remote) to redeploy the fixed code.

## Live real-harness verification (executed 2026-09-09, Windows 11)

Driven with the **real** binaries under a PTY (`omp` v18.1.15; `claude` v2.1.263, Opus), both from **already-authenticated** installs (claude banner "Claude Max"; omp showing live 5h/7d quota), in an isolated scratch repo (`%TEMP%\shim-e2e-scratch`) whose origin was repointed to a **nonexistent same-host path** (`github.com/DgxSparkLabs/shim-e2e-scratch.git`) so host matching still fires but no stray push can reach the real repo. Child env `GIT_SHIM_MODE=agent AGENT_ID=probe-*` (plus `GIT_SHIM_EXPLAIN=1` on the read probes; plus `GIT_SHIM_CONFIG` with a bot identity for the commit). Ambient `PATH` = single shim = the operator's `~/.local/bin/git.exe`, whose install carries a real `.git-shim-shadow` marker — so shadow was active via the **production marker**, not (only) an env override.

- **omp, LLM Bash-tool path (read):** the model (Claude Opus) ran `git status` via its Bash tool; the tool received the shim's `=== Resolved Plan === Mode: agent, Repository: github.com/DgxSparkLabs/shim-e2e-scratch`, not real git output — the model itself noted "it resolved Mode: agent, Operation: read." Uses a model turn (network). (observed, high)
- **omp, `!`-escape (read):** a clean `!git status` ran as `$ git status` with the model idle and zero token usage → same shim plan, **no model round-trip**. This depends on the `!` sitting at column 0: a stray leading char routes the whole line to the model instead (a real API call, observed twice this session), so the no-round-trip property requires a clean escape (clear the input first). (observed, high)
- **omp, `!`-escape (write) — the commit you asked for:** a clean `!git commit --allow-empty -m "e2e write path"` ran as `$ git commit …` (model idle) → `[master (root-commit) 7198d27] e2e write path`. Inspected afterward with real git (no shim), both **author and committer are `E2E Shim Bot <e2e-bot@test-org.invalid>`** — the shim stamped the configured bot identity, exercising the write/stamp path the read probes never touched. (observed, high)
- **Fail-closed write gate:** agent mode with **no matching identity** (direct shim invocation on the same repo) → `git-shim: no bot identity matches github.com/DgxSparkLabs/shim-e2e-scratch …`, rc 1, **no commit created** (count unchanged at 1). (observed, high)
- **claude, startup + shell mode (read):** claude's own startup `git` poll returned the shim plan; an explicit `! git status` (shell mode) likewise returned the shim plan. (observed, high)
- **Live auto-detection (no forced flag):** a follow-up run with `GIT_SHIM_MODE` and `AGENT_ID` **unset** exercised the production `resolve()`/`render_plan()` against the real config (`custom_agent_markers = [CLAUDECODE, OMPCODE, AI_AGENT]`) and scratch repo: it resolved `Mode: agent (detected via CLAUDECODE)`, `Matched Profile: e2e-bot`. Negative control — strip `CLAUDECODE`/`OMPCODE` from the same env → `human` — proves the live marker (not the config's `default_mode = "auto"`) is the cause. Composed with the harness→child env-passing proven in the drive above, this is live auto-detection, not a forced override. (observed, high)
- **Safety:** single shim on `PATH` → no recursion; read probes used `EXPLAIN` (no real git); the one real commit landed only in the throwaway repo (origin unreachable); operator `~/.gitconfig` untouched; after `stop`, zero leftover `git.exe`/`omp.exe`/`claude.exe`. (observed, high)

Honest limits of the live drive:
- **"No model round-trip" ≠ "credential-free."** Both binaries ran from already-authenticated installs. What is proven is that the git *spawn* needs no model turn — not that an *unauthenticated* `claude`/`omp` on a clean CI image reaches a prompt/exec at all (that stays untested; it is why the CI oracle is the no-shell stub, not the real binaries).
- Agent mode is **no longer overdetermined.** The read/write drive above forced it via `GIT_SHIM_MODE=agent`+`AGENT_ID`, but the follow-up run (bullet above) resolved agent purely from the live `CLAUDECODE` marker with both overrides unset. This confirms auto-detection works **once the markers are in `custom_agent_markers`**; without that config entry the live `CLAUDECODE`/`OMPCODE` still resolve human — the separate, already-documented vendor-list coverage gap.
- The `!`-escape and Bash-tool both route `git` through the harness **shell**, so this proves vendor process → shell → PATH git → shim, **not** no-shell `spawn("git")` (Gap 1's contract, proven separately and locally).
- Used the operator's **pre-fix** `.local/bin` shim; single-install, so routing/stamping/fail-closed are unaffected by the recursion fix. (This drive *did*, however, exercise the real `.git-shim-shadow` marker layout that the isolated Gap-1 probe faked with an env var.)

Net: the earlier "vendor-binary realism is irreducible offline" was wrong in the strong form — the real binaries spawn `git` with no model turn and route through the shim, and the shim stamps identity / fails closed on a real `! git commit`. The honest ceiling is "no model round-trip," not "runs unauthenticated."

## Programmatic e2e design (subagent discussion)

Three read-only scouts (`agent://HarnessDriver`, `agent://StubContract`, `agent://CIDesign`) converged on a two-tier design.

**Tier 1 — CI oracle (always, credential-free): a no-shell fake-harness stub.**
- A `fake_harness` helper spawns bare `git` with `shell=False`, `PATH` = exactly one installed trampoline dir ahead of real git (excluding any other `git`+`git-shim` sibling dir), harness markers `CLAUDECODE`/`OMPCODE` (+`AI_AGENT` for autonomous) in the child env, `GIT_SHIM_MODE`/`GIT_SHIM_REAL_PATH` unset (auto detection + real PATH discovery), config listing those names under `custom_agent_markers` until the vendor list is fixed.
- Delta vs today's `_run_shim`: bare `git` (not `python -m git_author_shim`), no `GIT_SHIM_REAL_PATH`, genuine PATH discovery — closing precisely the gap the current suite skips.
- Assertions: PATH winner is the shim (Windows: PE `git.exe`, no sibling `.cmd`); `Mode: agent (detected via <MARKER>)` under explain; identity stamped OR fail-closed; `~/.gitconfig`/`~/.ssh`/`config.toml` byte-identical; bounded `git`/`git.exe` process count with a 30s timeout as the `6340a28` recursion tripwire. Plus a plumbing-only negative (`ORCA_*`/`PI_*` → human) and a no-marker human baseline.
- New CI **`interception` job** (sibling to `test`; ubuntu+windows+macos; py3.12): `uv tool install .` **only** (never `uv sync`/`uv run` there — that is the two-shim recursion surface), `git-shim shadow enable` (the real marker), prepend the tool-bin, assert exactly one shim on `PATH`, then run the stub. Keep `test`/`lint` unchanged; the pytest job must never `uv tool install` this package.

**Tier 2 — optional local realism gate (skip-if-missing): drive the real binaries.**
- Candidate credential-free recipes, ranked by *expected* reliability but **only the last is proven**: (1) `omp --mode rpc` + `{"type":"bash","command":"git …"}` — **untested; frame shape unverified** (a live attempt this session sent the frame and got no bash-result back, only command-catalog re-emission), so `shape` must confirm the RPC bash contract before building Tier 2 on it; (2) `claude --bg --exec "git …"` (PTY-backed job, no session/model; set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`) — untested; (3) the REPL `!` escape — **the one path actually driven live** (omp `!git …` read+write, claude `! …`), fragile only in that `!` must sit at column 0 (a stray leading char routes the line to the model). Windows PTY: `pexpect` does not work natively and zellij is Unix/WSL-only.
- The `!`-escape (recipe 3) is what this session exercised by hand — the honest realism ceiling. Never required for merge; never given secrets in Actions.

**Key distinction:** the stub proves the *no-shell* contract (Gap 1); the real-binary drive proves *vendor → shell → git* (Gap 2). Both are wanted, but only the stub belongs in hosted CI — runners carry no `claude`/`omp`, and `-p`/`--allowedTools` model-driven git needs auth and network.
