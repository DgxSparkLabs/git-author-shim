# uv-shims

A Git identity and credential shim for AI coding agents. It puts a `git`
executable in front of your real Git so agent work is attributed to a configured
bot, while human invocations retain the operator's identity and credentials.

Python **3.12+**, system Git, and no third-party runtime dependencies are required.
The shim does not rewrite `~/.gitconfig`, `~/.ssh/config`, or stored Git credentials.
It applies identity environment variables and credential options to each child
Git process instead.

## Install from this checkout

Install [uv](https://docs.astral.sh/uv/) and system Git first. Capture the genuine
Git path **before** activating the environment, avoiding accidental selection of
the shim itself.

### Linux / macOS / POSIX shell

```sh
REAL_GIT="$(command -v git)"
uv venv
uv pip install -e .
. .venv/bin/activate
export UV_SHIM_GIT_REAL_PATH="$REAL_GIT"
command -v git
command -v git-shim
```

### Windows PowerShell

```powershell
$RealGit = (Get-Command git -CommandType Application | Select-Object -First 1).Source
uv venv
uv pip install -e .
. .\.venv\Scripts\Activate.ps1
$env:UV_SHIM_GIT_REAL_PATH = $RealGit
Get-Command git, git-shim
```

If activation is restricted, prepend the environment explicitly:
`$env:PATH = "$PWD\.venv\Scripts;$env:PATH"`.

The selected `git` and `git-shim` commands should now be in `.venv/bin` or
`.venv\Scripts`. Launch your coding agent from this environment so it inherits the
same `PATH`. Real Git can be discovered automatically; the explicit path above
makes installation/debugging predictable. Deactivate the environment to stop
intercepting Git.

## Configure identities

The global configuration is TOML:

- Windows: `%APPDATA%\uv-shims\git.toml`
- Linux/macOS: `$XDG_CONFIG_HOME/uv-shims/git.toml`, or
  `~/.config/uv-shims/git.toml` when `XDG_CONFIG_HOME` is unset
- Any platform: `UV_SHIM_GIT_CONFIG` overrides the full file path

Create the parent directory, then adapt this example to repositories you own:

```toml
[settings]
default_mode = "auto"
vendor_detection = true
custom_agent_markers = ["MY_AGENT_SESSION"]

[[identities]]
id = "acme-github"
name = "Acme Automation Bot"
email = "bot@acme.example"
match_patterns = ["github.com/acme/*"]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
strict_host_checking = true

[identities.https]
username = "x-access-token"
token_env_var = "ACME_BOT_TOKEN"
# Instead of token_env_var, configure exactly one of:
# token_file = "/absolute/path/to/private-token.txt"
# token_command = "op read op://vault/item/token"
```

SSH and HTTPS credential references can coexist; the remote transport selects
which to use. Keep private keys/tokens outside the repository. Token commands are
operator-controlled shell commands, so only put commands you trust in global
configuration. Use minimal hosting-provider permissions for the bot.

### Repository matching

SSH (`git@github.com:acme/app.git`) and HTTPS
(`https://github.com/acme/app.git`) normalize to `github.com/acme/app`. Matching
patterns use that canonical `host/owner/repository` form, not a transport prefix
or `.git` suffix.

More-specific matches win: `github.com/acme/app` over `github.com/acme/*` over
`github.com/*`. Equal-specificity matches across identities are refused rather
than choosing the first profile. For local writes, the branch's tracked remote
takes precedence, then `origin`, then a sole remote. With no primary remote,
conflicting remote identities are refused. Set the intended upstream or use a
trusted local identity selection to resolve ambiguity.

## Activation and attribution

`UV_SHIM_GIT_MODE` overrides the configured mode:

| Mode | Behavior |
| --- | --- |
| `auto` | Agent markers select bot mode; otherwise human passthrough. |
| `agent` | Require bot identity resolution for protected write operations. |
| `human` | Explicit operator passthrough; no bot identity or credential injection. |

Automatic detection recognizes `AGENT_ID`, `CLAUDE_CODE`, `CLAUDE_AGENT`,
`CODEX_SANDBOX`, `CURSOR_AGENT`, `OPENAI_AGENT`, and configured custom markers.
Set a mode in POSIX shells with `export UV_SHIM_GIT_MODE=agent`; in PowerShell use
`$env:UV_SHIM_GIT_MODE = 'agent'`.

- New commits use the bot as author and committer.
- Cherry-pick, rebase, `git am`, amend, and commit-message reuse preserve the
  original author while setting the bot as committer. Sequencer state is
  consulted for continuation workflows. Git's explicit `--author` and
  `--reset-author` semantics are retained.
- Annotated tags use the bot as tagger. Stash commits (including index/untracked
  commits) and notes commits use bot attribution without rewriting their target
  commits.
- Protected write families include `commit`, `push`, `tag`, `stash`, `notes`,
  `merge`, `revert`, `cherry-pick`, `rebase`, and `am`. Missing identity or ambiguous
  matching refuses these operations; read operations are available for diagnosis.

Example inside a matching repository:

```sh
UV_SHIM_GIT_MODE=agent git commit --allow-empty -m "automation checkpoint"
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>'
```

This is an attribution tool, **not a sandbox**. An agent with control of its
process environment can deliberately choose human mode or invoke real Git.

## SSH and HTTPS credentials

SSH invocations use a per-process `GIT_SSH_COMMAND` selecting the bot key with
`IdentitiesOnly=yes`, the ambient agent disabled, and strict host checking enabled
by default. Provision verified host keys and register the bot public key with your
Git host before pushing. Do not disable host verification to fix setup errors.

HTTPS uses a host-scoped, ephemeral Git credential helper. It clears inherited
helpers for the target scope and reads the configured environment variable, file,
or command; it does not put token values in Git's command-line arguments or save
them to credential stores. Bot network writes fail closed when the selected
credential cannot be used, rather than falling back to personal credentials.
Local object creation does not require a live hosting-service credential.

For an environment token in a POSIX shell, obtain it from your secret manager and
export `ACME_BOT_TOKEN`; in PowerShell set `$env:ACME_BOT_TOKEN`. Avoid typing
literal secrets into commands saved in shell history. Explain prints the source
reference, never the resolved token.

## Inspect before running

```sh
git-shim list-identities
git-shim explain --json push origin main
git-shim explain commit --amend
UV_SHIM_GIT_EXPLAIN=1 git push origin main
```

`list-identities` emits one tab-separated row per identity: ID, `Name <email>`, and
comma-separated patterns. `explain` accepts the Git arguments after its own
options; put `--json` before the Git command. Without Git arguments it reports the
current mode/repository plan as a read.

Explain **does not execute the requested operation**, access token sources, or
attempt network authentication. It may inspect local Git/sequencer metadata. It
returns zero for an inspectable refusal; scripts must check `write_permitted` in
the JSON, not only the process exit code. Malformed configuration is still an
error. A permitted plan is not proof that a future push will authenticate.

JSON includes mode, marker, matched identity, canonical repository, target host,
operation class, author/committer, transport, credential source, permission, and
failure reason. See the [JSON contract](specs/001-git-author-shim/contracts/cli.md).
`UV_SHIM_GIT_EXPLAIN=1` also works with an explicit human override.

## Trust repository-local configuration

A repository may select a global identity and optionally override its displayed
name/email:

```toml
# .git-shim.toml in the repository root
identity = "acme-github"

[override]
name = "Acme Release Bot"
email = "release-bot@acme.example"
```

Review the file yourself, then run:

```sh
git-shim trust .git-shim.toml
git-shim explain --json commit
git-shim untrust .git-shim.toml
```

Trust records the file's SHA-256 digest in the operator's configuration directory.
Untrusted files are ignored. Any content change invalidates the grant until you
review and trust the new content. Local files cannot introduce private keys,
tokens, or token commands; those stay in operator-owned global configuration.

## Environment reference

| Variable | Purpose |
| --- | --- |
| `UV_SHIM_GIT_MODE` | `auto`, `agent`, or `human`; overrides configuration. |
| `UV_SHIM_GIT_CONFIG` | Explicit global TOML file path. |
| `UV_SHIM_GIT_REAL_PATH` | Absolute genuine Git executable path. |
| `UV_SHIM_GIT_EXPLAIN` | `1`, `true`, `yes`, or `on`: inspect instead of execute. |
| `__UV_SHIM_GIT_CONTINUATION` | Internal recursion sentinel; do not set manually. |

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Agent commits still show your personal name | Verify the agent inherited the shim-first `PATH`; inspect `git-shim explain --json commit` and enable a recognized marker or agent mode. |
| No identity matches / no remote | Inspect `git remote -v`; add a matching global profile or configure the intended remote. Do not use human mode for routine bot work. |
| Equal specificity / conflicting remotes | Narrow a pattern, select an upstream, or review and trust a local identity selection. |
| Missing/unreadable SSH key | Check the configured key path and permissions; register its public key with the host. Local commits can work while a push is refused. |
| Host-key verification fails | Verify the host fingerprint through a trusted channel and provision `known_hosts`. |
| Missing/empty HTTPS token or token command failure | Check the configured source under the agent's environment; ensure the bot has repository permission. Explain intentionally does not execute token commands. |
| Local override has no effect | Confirm the file is at the repository root, selects an existing global identity, and its current content has been trusted. |
| Real Git cannot be found / recursion refusal | Set `UV_SHIM_GIT_REAL_PATH` to system Git, not the shim launcher; check the order of `PATH`. |
| Invalid TOML or unknown field | Use the [configuration contract](specs/001-git-author-shim/contracts/config.md); token sources are mutually exclusive. |

An operator can deliberately run one command with `UV_SHIM_GIT_MODE=human`
(PowerShell: temporarily change `$env:UV_SHIM_GIT_MODE`). This is an explicit
identity/security override, not a way to repair bot credentials.

## Validation and development

Follow the [five-scenario local quickstart](specs/001-git-author-shim/quickstart.md)
for human passthrough, bot commits, cherry-pick author preservation, fail-safe
writes, and content-hash trust. It uses temporary repositories and a push dry-run,
not a live remote push.

```sh
uv sync
uv run pytest
uv run pytest tests/integration/test_performance.py -s
```

The benchmark measures warmed, in-process config/mode/repository/identity/credential
resolution using `time.process_time()` for CPU and `time.perf_counter()` for elapsed
time. It excludes Python startup, the external commit sequencer probe, and real
Git/network I/O; the median CPU budget is **under 5 ms**. A Windows/Python 3.14 run
measured **0.625 ms CPU / 0.544 ms elapsed** per resolution. A separate
`python -X importtime` smoke run measured the lazy `uv_shims.git.__main__` import at
**4.933 ms cumulative**, including its package imports. These are local
measurements, not an end-to-end Git latency guarantee.
