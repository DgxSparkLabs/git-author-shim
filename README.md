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

`uv tool install` places `git` and `git-shim` on the tool bin path (`~/.local/bin` on POSIX, `%USERPROFILE%\.local\bin` on Windows). Keep that directory on `PATH`.

## Two ways to use it

### Option 1: Transparent Git shadowing (agent mode)

The installed `git` executable is the shim. Any coding agent that calls `git` goes through it automatically.

Operator commits in unconfigured repositories pass through with zero overhead and zero mutation of personal Git or SSH configuration. Agent writes against a matching identity receive bot attribution and bot credentials. Agent writes with no identity, missing credentials, or an ambiguous match are refused rather than falling back to the operator.

Launch the agent from a shell whose `PATH` lists the uv tool bin directory before system Git.

### Option 2: Coexistence / standalone mode (`git-shim`)

Leave system `git` first on `PATH` and invoke the shim by name:

```bash
git-shim commit -m "feat: bot commit"
git-shim push origin feature-branch
```

Point AI coding agents or shell aliases at `git-shim` as the Git binary when you want bot attribution without shadowing every `git` on the machine.

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
```

- **`git-shim explain [--json]`** prints the resolved plan for the current repository and arguments. Secret tokens are strictly redacted. The command has zero Git side-effects: it does not commit, push, or contact credential sources.
- **`git-shim list-identities`** prints a tabular audit of every configured profile.
- **`git-shim trust <repo-config>`** / **`git-shim untrust <repo-config>`** implement a cryptographic SHA-256 trust gate for repository-local `.git-shim.toml` files. Untrusted or modified files are ignored. Local files may select a global identity and override display name/email; they cannot introduce keys, tokens, or token commands.

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

## License

MIT. See [LICENSE](LICENSE).
