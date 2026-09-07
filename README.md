# git-author-shim

Git author identity and credential shim for AI coding agents.

Published under [https://github.com/DgxSparkLabs/git-author-shim](https://github.com/DgxSparkLabs/git-author-shim).

## Why it exists

Coding agents run ordinary Git commands inside the operator's environment. Left alone, those commits and pushes inherit personal `user.name` / `user.email` and the operator's SSH keys or HTTPS tokens.

**git-author-shim** sits in front of real Git and, when an agent is active against a configured host, stamps a dedicated bot identity and injects host-scoped credentials. It never rewrites `~/.gitconfig` or `~/.ssh/config`. Human Git in unconfigured or non-agent sessions continues to pass through.

## Install

Requires [uv](https://docs.astral.sh/uv/), Python 3.12+, and system Git.

### Remote

```bash
uv tool install git+https://github.com/DgxSparkLabs/git-author-shim.git
```

### Local clone

```bash
git clone https://github.com/DgxSparkLabs/git-author-shim.git
cd git-author-shim
uv tool install .
```

`uv tool install` installs every `[project.scripts]` entry. This package declares both `git` (`git_author_shim.__main__:main`) and `git-shim` (`git_author_shim.cli:main`), so uv places a real `git` trampoline (`git.exe` on Windows) and `git-shim` on the tool bin path (`~/.local/bin` on POSIX, `%USERPROFILE%\.local\bin` on Windows). Keep that directory on `PATH` ahead of system Git for Option 1.

On Windows the trampoline is a PE `git.exe` that `CreateProcessW` can execute. Agent spawners (Claude Code, Cursor, Codex, and `subprocess.run(["git", ...], shell=False)` / `child_process.spawn("git", ...)`) cannot run a `.cmd` wrapper; this project never uses one.

## Two ways to use it

### Option 1: Transparent Git shadowing (default)

The installed `git` executable **is** the shim. Any coding agent that calls `git` (including `CreateProcessW` / `spawn` without a shell) goes through it automatically.

Operator commits in unconfigured repositories pass through with zero mutation of personal Git or SSH configuration. Agent writes against a matching identity receive bot attribution and bot credentials. Agent writes with no identity, missing credentials, or an ambiguous match are refused rather than falling back to the operator.

```bash
git-shim shadow enable    # default after install; re-assert full shim
git-shim shadow status
```

Launch the agent from a shell whose `PATH` lists the uv tool bin directory before system Git.

### Option 2: Passthrough / standalone `git-shim`

Leave the `git` trampoline on `PATH` but make it a no-op wrapper around real Git:

```bash
git-shim shadow disable
```

`git` then passes through to system Git with no identity or credential injection. Invoke the shim by name when you want bot attribution:

```bash
git-shim commit -m "feat: bot commit"
git-shim push origin feature-branch
```

Point AI coding agents or shell aliases at `git-shim` as the Git binary when you want bot attribution without intercepting every `git` on the machine. `GIT_SHIM_SHADOW=0` forces passthrough for a single process without changing the marker.

## Configuration

Global configuration lives at:

| Platform | Path |
| --- | --- |
| POSIX | `~/.git-shim/config.toml` |
| Windows | `%USERPROFILE%\.git-shim\config.toml` |

Override the file path with `GIT_SHIM_CONFIG`.

Create the parent directory, then adapt:

```toml
# ~/.git-shim/config.toml
# (Windows: %USERPROFILE%\.git-shim\config.toml)
# Override the path with GIT_SHIM_CONFIG.

[settings]
# auto  — treat the run as an agent only when a vendor or custom marker is present
# agent — always resolve a bot identity for protected writes
# human — always pass through; no bot identity or credential injection
default_mode = "auto"
vendor_detection = true
# Extra environment variables that, when set, count as an agent session.
custom_agent_markers = ["MY_AGENT_SESSION"]

# One profile per hosting account / bot. Most-specific match wins.
[[identities]]
id = "acme-github"
name = "Acme Automation Bot"
email = "bot@acme.example"
# Canonical form is host/owner/repo (no git@, https://, or .git suffix).
# SSH and HTTPS remotes both normalize to this shape.
match_patterns = ["github.com/org/*", "github.com/org-internal/*"]

# Isolated SSH key offered only to this identity's matched host.
[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
strict_host_checking = true

# Host-scoped HTTPS token. Configure exactly one of token_env_var,
# token_file, or token_command. The value never appears in argv or URLs.
[identities.https]
username = "x-access-token"
token_env_var = "ACME_BOT_TOKEN"
# token_file = "/absolute/path/to/private-token.txt"
# token_command = "op read op://vault/item/token"
```

SSH and HTTPS references may coexist on one identity; Git's remote URL selects the transport. Keep keys and tokens outside the repository. Token commands run under the operator's control — only configure commands you trust.

Matching uses canonical `host/owner/repository`. `github.com/org/app` beats `github.com/org/*` beats `github.com/*`. Equal-specificity ties across identities are refused. For local writes, the branch upstream wins, then `origin`, then a sole remote.

## Management and inspection

```bash
git-shim explain [--json]
git-shim list-identities
git-shim trust <repo-config>
git-shim untrust <repo-config>
git-shim shadow enable|disable|status
```

- **`git-shim explain [--json]`** prints the resolved plan for the current repository and arguments. Secret tokens are strictly redacted. The command has zero Git side-effects: it does not commit, push, or contact credential sources.
- **`git-shim list-identities`** prints a tabular audit of every configured profile.
- **`git-shim trust <repo-config>`** / **`git-shim untrust <repo-config>`** implement a cryptographic SHA-256 trust gate for repository-local `.git-shim.toml` files. Untrusted or modified files are ignored. Local files may select a global identity and override display name/email; they cannot introduce keys, tokens, or token commands.
- **`git-shim shadow enable|disable|status`** flips the installed `git` trampoline between full shim (Option 1) and passthrough to real Git (Option 2). It does not create or delete `git.exe`.

```toml
# .git-shim.toml at the repository root — ignored until trusted
identity = "acme-github"

[override]
name = "Acme Release Bot"
email = "release-bot@acme.example"
```

```bash
git-shim trust .git-shim.toml
git-shim explain --json commit
git-shim untrust .git-shim.toml
```

## Architecture and guarantees

- **Zero external runtime dependencies.** Python 3.12+ standard library only.
- **Sub-5ms in-process CPU resolution overhead** for config, mode, repository, identity, and credential planning (excluding Python startup and real Git I/O).
- **Sequencer author preservation.** Cherry-pick, rebase, and amend keep the original (human) author and set the bot as committer. Fresh commits, merges, reverts, stashes, and notes stamp the bot as author and committer.
- **Fail-closed.** Missing credentials, unmatched hosts, and ambiguous identity matches refuse the write instead of falling back to the operator.

This is an attribution and credential-scoping tool, not a sandbox. An agent that controls its environment can still invoke real Git or force human passthrough.

## Troubleshooting environment variables

| Variable | Purpose |
| --- | --- |
| `GIT_SHIM_MODE` | `auto` (default), `agent`, or `human`. `human` is a fast passthrough with no bot identity. |
| `GIT_SHIM_CONFIG` | Absolute path to the global `config.toml`. |
| `GIT_SHIM_EXPLAIN` | `1` / `true` prints the resolved plan (secrets redacted) and exits 0 without running Git. |
| `GIT_SHIM_REAL_PATH` | Absolute path to real Git when PATH discovery fails or would select the shim. |
| `GIT_SHIM_SHADOW` | `1` forces the `git` trampoline into the full shim; `0` forces passthrough, overriding the `.git-shim-shadow` marker. |
| `__GIT_SHIM_CONTINUATION` | Internal. Set on child Git processes to prevent recursive self-invocation. Not an authorization grant. |

## License

MIT. See [LICENSE](LICENSE).
