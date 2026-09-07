# Research: Git Author Identity Shim

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Status**: Completed

## Executive Summary

The `git` shim augments the execution context of `git` commands invoked by autonomous AI coding agents to attribute commits and authenticate pushes under a dedicated bot identity without modifying the operator's global or ambient configurations (`~/.gitconfig`, `~/.ssh/config`). This document consolidates the technical design decisions, rationale, and alternatives evaluated for Phase 0.

---

## 1. Technical Decisions

### Decision 1: Language, Toolchain & Latency Optimization
* **Decision**: Python 3.12+ packaged with `uv` and standard `pyproject.toml`, with strict lazy-import architecture.
* **Rationale**: Fast development, cross-platform signal and process fidelity.
  * **Latency Budget**: Measured bare CPython startup is ~33ms on Windows, while full stdlib imports cost ~107ms. To minimize overhead, `__main__.py` top-level imports are strictly restricted to `os` and `sys`. Heavier modules (`tomllib`, `hashlib`, `subprocess`, `argparse`) are imported lazily inside relevant branches.
  * **Resolution Target**: In-process CPU resolution overhead <5ms (measured via `time.perf_counter()`). Total wall-clock overhead target <25ms on Linux/macOS and <120ms on Windows CPython.
* **Alternatives Considered**:
  * *Rust*: Excellent standalone binary and startup speed (<5ms), but higher initial development overhead and cross-compilation matrix.
  * *Go*: Good single-binary distribution, but requires Go toolchain setup in Python-centric `git-author-shim` project.

### Decision 2: Real Git Binary Discovery & Recursion Prevention
* **Decision**: The shim discovers the underlying real Git binary by scanning `PATH` (using `PATHEXT` on Windows) while skipping its own executable path. On child process invocation, it sets an internal marker environment variable (`__GIT_SHIM_CONTINUATION=1`).
* **Rationale**: When the shim binary is placed in `/usr/local/bin` or a virtual environment `bin/` directory ahead of system Git, child processes (e.g., pre-commit hooks, git aliases, submodule updates) would otherwise invoke the shim in an infinite loop.
* **Security Guardrail**: The continuation sentinel serves strictly as a recursion loop break—it does NOT bypass security authorization, host-matching validation, or fail-closed rules on distinct child operations.
### Decision 3: Commit Classification & Sequencer State Detection
* **Decision**: Classify invocations into *Originating* vs. *Carrying* based on a 7-stage precedence engine:
  1. Explicit `--author="..."` on argv -> Respected verbatim.
  2. `--reset-author` -> Originating (Bot is Author & Committer).
  3. `-c` / `-C` / `--reuse-message` / `--reedit-message` -> Carrying (Preserve Author, Bot is Committer).
  4. `--amend` -> Carrying (Preserve Author, Bot is Committer).
  5. Sequencer state present (`CHERRY_PICK_HEAD`, `REBASE_HEAD`, `rebase-merge/`, `rebase-apply/`) -> Carrying.
  6. In-progress `MERGE_HEAD` or `revert` -> Originating.
  7. Default fresh commit -> Originating (Bot is Author & Committer).
* **Rationale & Probing Behavior**: Git's sequencer allows multi-step cherry-picks and rebases where intermediate conflicts are resolved with a bare `git commit`.
* **Cataloged Probing Quirks**:
  * `git rev-parse --git-path <NAME>` returns path strings whether the files exist or not. The classifier MUST perform `os.path.exists()` on the returned paths.
  * `--show-toplevel` fails in bare repositories (`fatal: this operation must be run in a work tree`). The probe must run `git rev-parse --git-dir` and check for bare repository state before requesting worktree paths.
  * Single batched probe:
    ```bash
    git rev-parse --git-dir --git-path CHERRY_PICK_HEAD --git-path REBASE_HEAD --git-path rebase-merge --git-path rebase-apply --git-path MERGE_HEAD
    ```
    This probe runs only for commit-classifying subcommands; read-only operations skip probing entirely.

### Decision 4: Remote URL Normalization & Primary Remote Matcher
* **Decision**: Normalize configured remote URLs into canonical tuples `(host, owner_or_org, repo)`:
  * Normalizes SSH forms (`git@github.com:org/repo.git`, `ssh://git@github.com:22/org/repo.git`) and HTTPS forms (`https://github.com/org/repo.git`, `https://token@github.com/org/repo`).
  * Matches against glob patterns (`host/org/repo`, `host/org/*`, `host/*`).
  * **Primary Remote Policy**: For local writes (e.g. `git commit`), matches against the primary remote (the current branch's tracked upstream remote, or `origin`, or the single configured remote). If multiple configured remotes resolve to conflicting bot identities without a primary remote, the shim fails closed and refuses the write.
  * **Precedence**: Per-repository configuration takes precedence over global, and among matching patterns for the resolved remote, the most specific match wins. Specificity ties fail closed (US10).
* **Rationale**: Eliminates duplicate configuration blocks for SSH/HTTPS and prevents multi-remote configuration hijacking from misattributing local commits.

### Decision 5: SSH Credential Injection & Destination Host Validation
* **Decision**: Inject `GIT_SSH_COMMAND` targeting an isolated SSH invocation:
  ```bash
  ssh -i <BOT_KEY_PATH_FORWARD_SLASHES> -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -F /dev/null
  ```
  (On Windows, `-F NUL` is used instead of `/dev/null`).
* **Cataloged Windows Path Handling**: Git-for-Windows evaluates `GIT_SSH_COMMAND` inside an MSYS `sh` shell. Backslashes in paths (`C:\Users\...`) are stripped by `sh`. All file paths inside `GIT_SSH_COMMAND` MUST be converted to forward slashes (`C:/Users/...`).
* **Destination Host Guard (`insteadOf` Defense)**: The shim pre-evaluates `url.*.insteadOf` and `url.*.pushInsteadOf` rewrites to determine the *effective runtime destination host*. If the rewritten destination host does not match the bot identity pattern, the write is aborted immediately with exit code 1 to prevent key exfiltration to malicious hosts.
### Decision 6: HTTPS Credential Injection & Secret Redaction
* **Decision**: Supply credentials using host-scoped overrides:
  ```bash
  -c credential.https://<matched-host>.helper= \
  -c credential.https://<matched-host>.helper="<shim_helper>"
  ```
* **Cataloged Credential Precedence**: In Git, URL-scoped helpers (e.g. `[credential "https://github.com"]`) take precedence over generic `credential.helper`. To guarantee the bot token is supplied, the override MUST be scoped to the exact destination host (`credential.https://<matched-host>.helper=`). Generic global reset must NOT be used as it breaks fallback authentication on foreign/unconfigured hosts.
* **Secret Redaction**: Secrets are strictly sourced from environment variables, files, or secret commands, never placed on command-line arguments or written to stored `.git/config`.
### Decision 7: Content-Hash Trust Gate for Repo-Local Config
* **Decision**: Store trusted SHA-256 hashes of repository-local configuration files in the operator's global state (`~/.git-shim/trusted-hashes.json`).
* **Rationale**: Following the pattern of `direnv` and `mise`, untrusted cloned repositories cannot execute arbitrary credential commands or redirect identities without explicit operator approval (`git-shim trust` or prompt).

---

## 2. Cataloged Failure Modes & Adversarial Defenses

| Observed Failure Mode / Attack | Cataloged Behavior | Engineered Defense |
| :--- | :--- | :--- |
| **Windows `os.execv` exit code loss** | `os.execv` on Windows spawns a child process and returns `0` immediately, ignoring child exit codes. | Use `subprocess.run()` with direct file descriptor inheritance and propagate `sys.exit(proc.returncode)` on Windows. |
| **Windows backslash stripping in SSH** | Git's MSYS shell strips backslashes in `GIT_SSH_COMMAND` (`C:\key` -> `C:key`). | Normalize all key and config paths inside `GIT_SSH_COMMAND` to forward slashes (`C:/key`). |
| **`insteadOf` destination hijacking** | Hostile `.git/config` rewrites remote to attacker host; static remote check passes and key is offered to attacker. | Pre-compute effective destination host using `insteadOf`/`pushInsteadOf` rules; refuse if rewritten host is untrusted. |
| **URL-scoped credential helper bypass** | Repo `.git/config` with `[credential "https://github.com"]` overrides generic `-c credential.helper=`, stealing bot token or leaking human token. | Apply host-scoped resets `-c credential.https://<host>.helper=` before setting the shim helper. |
| **Multi-remote identity collision** | Repo with `origin` (GitHub) and `upstream` (GitLab) resolves to wrong bot due to pattern specificity tie/win. | Prioritize tracked upstream/origin remote; fail closed if remotes resolve to conflicting bot identities. |
| **`--git-path` non-existent paths** | `git rev-parse --git-path` emits path strings even when no sequencer file exists. | Explicitly verify `os.path.exists()` on every returned path in the classifier. |
| **Bare repository crash on probe** | Probing `--show-toplevel` inside a bare repository crashes with exit 128. | Check bare repo state first; omit worktree probes in bare repositories. |
| **Infinite loop on recursion** | Hook/alias re-invoking `git` triggers infinite shim loop. | Inject `__GIT_SHIM_CONTINUATION=1` into child environment to break recursion while preserving security boundaries. |
