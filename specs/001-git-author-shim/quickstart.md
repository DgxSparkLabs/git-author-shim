# Quickstart & Validation Guide: Git Author Identity Shim

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

These five scenarios run locally, without a hosting account or network access. They
exercise the installed `git` and `git-shim` console scripts, not mocked Git. The
push in scenario 2 is deliberately an **inspection-only dry run**; a real push
requires an authorized bot key and a reachable repository.

## Prerequisites and installation

Install Python 3.12+, [uv](https://docs.astral.sh/uv/), and system Git. Primary install:

```sh
# From GitHub
uv tool install git+https://github.com/DgxSparkLabs/git-author-shim.git

# Or from this git-author-shim checkout
uv tool install .
command -v git-shim
```

`uv tool install` places both `git` and `git-shim` on the uv tool bin path (`~/.local/bin` on POSIX, `%USERPROFILE%\.local\bin` on Windows).

- **Option 2 (default):** standalone `git-shim`. The installed `git` trampoline is passthrough to real Git. Use `git-shim` for bot identity injection.
- **Option 1:** `git-shim shadow enable` activates shadowing on the `git` trampoline so agents that spawn `git` are intercepted. `git-shim shadow disable` returns to passthrough; `git-shim shadow status` reports the current mode.

Global configuration lives at `~/.git-shim/config.toml` (`%USERPROFILE%\.git-shim\config.toml` on Windows). Override with `GIT_SHIM_CONFIG`.

On Windows, use the PowerShell installation commands in [README.md](../../README.md).
The scenarios below use POSIX shell syntax; on PowerShell, set variables with
`$env:NAME = 'value'`, unset them with `Remove-Item Env:NAME`, and use `Set-Content`
instead of `printf`/heredocs. The same Git arguments and assertions apply.

Create a dedicated temporary workspace and configuration; this does not replace
your normal shim configuration or modify your global Git identity:

```sh
WORKSPACE="$(mktemp -d)"
export GIT_SHIM_CONFIG="$WORKSPACE/config.toml"
export GIT_SHIM_SHADOW=1  # Option 1 for these scenarios without writing the shadow marker
cat > "$GIT_SHIM_CONFIG" <<'TOML'
[[identities]]
id = "acme-github"
name = "Acme Automation Bot"
email = "bot@acme.corp"
match_patterns = ["github.com/acme-corp/*"]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
TOML

git-shim list-identities
mkdir "$WORKSPACE/test-repo"
cd "$WORKSPACE/test-repo"
GIT_SHIM_MODE=human git init -b main
GIT_SHIM_MODE=human git config user.name "Operator"
GIT_SHIM_MODE=human git config user.email "operator@example.invalid"
GIT_SHIM_MODE=human git remote add origin git@github.com:acme-corp/test-repo.git
```

The configured SSH key is not needed for local commits. For a real network push,
generate/register a bot key at that path and provision verified host keys first.

## Scenario 1: Human passthrough

An explicit human override makes the scenario independent of inherited agent
markers. Human mode leaves the operator's author, committer, and credentials alone.

```sh
export GIT_SHIM_MODE=human
git-shim explain --json status
# mode: "human", is_write: false

git config user.name
# Operator (the repository-local value configured above)
```

No shim invocation writes `~/.gitconfig` or `~/.ssh/config`. To exercise automatic
human detection instead, unset `GIT_SHIM_MODE` and all configured/vendor agent
markers before running explain.

## Scenario 2: Agent commit and SSH push plan

```sh
unset GIT_SHIM_MODE
export AGENT_ID=test-agent-01
printf 'hello world\n' > hello.txt
git add hello.txt
git commit -m "initial agent commit"
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>'
# Author: Acme Automation Bot <bot@acme.corp>
# Committer: Acme Automation Bot <bot@acme.corp>

git-shim explain --json push origin main
# mode: "agent", transport: "ssh", matched_identity_id: "acme-github"
# No push occurs and the private key is not read.
```

Explain reports the proposed plan, not successful authentication. A real
`git push origin main` contacts GitHub and needs a repository you control and a
usable bot key; do not run it against the example remote.

## Scenario 3: Preserve a cherry-picked human author

Create a **nonempty** human change and branch from its **parent** before replaying
it. Cherry-picking onto the same commit would be empty and would not validate
attribution.

```sh
printf 'human contribution\n' > human.txt
GIT_SHIM_MODE=human git add human.txt
GIT_SHIM_MODE=human git commit -m "human work" --author='Jane Doe <jane@company.com>'
HUMAN_HASH="$(git rev-parse HEAD)"
git checkout -b feature-backport HEAD~1
git cherry-pick "$HUMAN_HASH"
git log -1 --format='Author: %an <%ae>%nCommitter: %cn <%ce>'
# Author: Jane Doe <jane@company.com>
# Committer: Acme Automation Bot <bot@acme.corp>
```

## Scenario 4: Refuse an unconfigured agent write

```sh
mkdir "$WORKSPACE/unconfigured-repo"
cd "$WORKSPACE/unconfigured-repo"
git init -b main
git remote add origin git@github.com:random-stranger/repo.git
git commit --allow-empty -m "must not commit"
# Nonzero exit; diagnostic identifies the unmatched repository and a remedy.
GIT_SHIM_MODE=human git rev-parse --verify HEAD
# Nonzero exit: no commit was created.
```

Read-only operations remain available. Fix the global match pattern rather than
using human mode for agent work; the human override is an intentional operator
escape hatch, not a recommended workaround for missing bot configuration.

## Scenario 5: Content-hash trust gate

Use an existing global identity and a visible local name override. An untrusted
or changed local file is ignored, falling back to the global identity.

```sh
cd "$WORKSPACE/test-repo"
cat > .git-shim.toml <<'TOML'
identity = "acme-github"
[override]
name = "Acme Release Bot"
TOML

git-shim explain --json commit
# author.name: "Acme Automation Bot" (untrusted override ignored)
git-shim trust .git-shim.toml
git-shim explain --json commit
# author.name: "Acme Release Bot"

cat > .git-shim.toml <<'TOML'
identity = "acme-github"
[override]
name = "Tampered Bot"
TOML
git-shim explain --json commit
# author.name: "Acme Automation Bot" (content hash no longer matches)
git-shim untrust .git-shim.toml
```

## Verification record

The five scenarios were exercised with the installed console scripts and real Git
on Windows/Python 3.14: human passthrough, bot commit plus SSH push dry-run,
nonempty cherry-pick author preservation, refusal with no commit created, and the
untrusted → trusted → content-changed override transition. The operator global
Git configuration was hash-checked unchanged. No live hosting-service push was
performed by this quickstart validation.
