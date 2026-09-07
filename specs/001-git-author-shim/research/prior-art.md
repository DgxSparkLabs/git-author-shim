# Prior Art: Managing and Switching Multiple Git Identities and Credentials

**Feature**: [spec.md](../spec.md) · **Created**: 2026-09-06 · **Status**: Final research artifact

## Purpose and Method

This document surveys how existing systems manage multiple git identities, credentials, and
profiles, and how they switch between them, to ground the design of the uv-shims `git` shim.
A specific inspiration was the version-manager pattern (nvm, fnm, asdf, mise, direnv, uv,
proto), which auto-detects and switches the active runtime per directory; we wanted to know
whether that pattern is applied to git identity and credentials, and what to borrow.

Findings were verified against primary sources (official git documentation, tool GitHub
repositories and their source, and official product docs), not search-engine summaries.
Search summaries in this session produced at least three fabricated or wrong repository URLs
(`mohan-c/git-profile-switcher`, `variant96/git-account-switcher`, `djaustin/gitrole`, all
404), so every tool below was confirmed to exist and read at its real source. Raw verified
reports are retained under [`research/raw/`](./raw/).

## The Central Structural Finding: Four Independent Planes

Every system converges on the same separation. "Git identity" is not one thing; it is four
planes that are configured and switched independently:

1. **Committer identity**: `user.name`, `user.email`, and signing (`user.signingKey`,
   `commit.gpgSign`, `gpg.format`). Stored in git config. Applied at commit time with no
   remote involved.
2. **HTTPS credentials**: tokens supplied through a credential helper. Keyed by protocol and
   host, optionally by username or path. HTTPS only.
3. **SSH credentials**: keys selected by OpenSSH through `~/.ssh/config` (`IdentityFile`,
   `IdentityAgent`, host aliases) or by git through `core.sshCommand`/`GIT_SSH_COMMAND`. A
   separate plane that credential helpers never touch.
4. **Hosting-API account**: for example `gh`'s active account in `hosts.yml`, which affects
   `gh` and HTTPS git only if `gh` is installed as the credential helper.

The load-bearing consequence: a shim that only wraps the git credential-helper protocol will
never see SSH, and committer identity is orthogonal to both. Our spec already separates these,
and this survey confirms the separation is correct and universal.

## Native Git (the baseline everyone builds on)

Git has no first-class "profile" object. Multiple identities are assembled from conditional
includes plus a last-value-wins merge. Verified against the official
[git-config docs](https://git-scm.com/docs/git-config) (published through 2.55.0),
[gitcredentials](https://git-scm.com/docs/gitcredentials), and the implementation in
[config.c](https://github.com/git/git/blob/master/config.c).

- **`includeIf "gitdir:<glob>"`** (and `gitdir/i` for case-insensitive) selects a config file
  by the repository's `.git` location. Trailing slash means recursive (`foo/` becomes
  `foo/**`). Matches `$GIT_DIR`, not the worktree path; linked worktrees match the real `.git`
  location.
- **`includeIf "onbranch:<glob>"`** selects by the checked-out branch. It fails closed on a
  detached HEAD (no match).
- **`includeIf "hasconfig:remote.*.url:<glob>"`** (Git 2.36+) matches when *at least one*
  configured remote URL matches the glob: *"If there exists at least one remote URL that
  matches this pattern, the include condition is met."* Files it includes may not themselves
  declare remotes (cycle break).
- **No URL normalization.** Matching is `wildmatch` on the literal `remote.<name>.url` string.
  `git@github.com:org/repo` and `https://github.com/org/repo` are different strings, so an
  operator must write two (or three) globs to cover SSH and HTTPS. `url.<base>.insteadOf`
  rewrites are not seen by `hasconfig`.
- **Last-include-wins.** When several includes match, later scalar values override earlier:
  *"last value found taking precedence over values read earlier."* This is the opposite of
  OpenSSH `ssh_config`, which is first-value-wins.
- **A commit needs no remote on the command line.** `gitdir`/`onbranch` fire from the repo you
  are in; `hasconfig` reads the repo's *stored* remotes. This is exactly why the earlier
  "which remote does `git commit` use" question dissolves: identity is a repo-level fact, not
  an operation argument.
- **HTTPS credentials** use `credential.<url>.helper`/`.username` (urlmatch by protocol+host,
  and path if `credential.useHttpPath` is true). **SSH auth never consults credential helpers.**

**Exact `gitdir`/`hasconfig` matching rules (verified verbatim against the 2.55.0 docs).**
These are the load-bearing details a matcher must reproduce:

- Pattern with a leading `~/` expands `~` to `$HOME`; a leading `./` expands to the directory
  of the *including* config file.
- A pattern that starts with none of `~/`, `./`, or `/` gets `**/` auto-prepended, so `foo/bar`
  matches `/any/path/to/foo/bar`.
- A pattern ending in `/` gets `**` appended (`foo/` becomes `foo/**`): match the dir and
  everything under it, recursively. The same trailing-slash rule applies to `onbranch`.
- `gitdir` matching does not resolve symlinks in `$GIT_DIR`, but both the symlink and realpath
  spellings match outside `$GIT_DIR`. `../` is not special and matches literally.
- `hasconfig` scans ahead: a remote URL defined *later in the same file, or in a file read
  after* the `includeIf`, still satisfies the condition. Included files may not declare remotes
  (the cycle break).

## The Version-Manager Auto-Switch Pattern

Verified across [direnv](https://github.com/direnv/direnv),
[mise](https://github.com/jdx/mise), [asdf](https://asdf-vm.com),
[fnm](https://github.com/Schniz/fnm), [nvm](https://github.com/nvm-sh/nvm),
[proto](https://moonrepo.dev/docs/proto/config), and [uv](https://docs.astral.sh/uv/). The
pattern decomposes into three orthogonal layers:

1. **Discovery**: walk up from the current directory to find a pin file. Some tools take the
   nearest match (direnv `.envrc`, nvm/fnm `.nvmrc`, uv `.python-version`); others merge all
   ancestors with closer-wins (mise, proto, asdf per tool).
2. **Activation**: either a **shell hook** on `cd`/prompt that mutates `PATH`/env (direnv,
   `mise activate`, `fnm --use-on-cd`), or a **PATH shim** that re-resolves on every
   invocation (asdf, `mise --shims`, proto shims), or **command-time** lookup with no hook
   (uv, plain nvm).
3. **Trust**: applied only where the discovered file is executed or can change the
   environment. direnv blocks every `.envrc` until `direnv allow`, keyed to a content hash so
   editing the file revokes the grant. mise requires `mise trust` for configs that can run
   code, content-bound in paranoid mode. Declarative pins (version strings, TOML data) have no
   allow step.

**The closest analog to our `git` shim is the exec-time PATH shim** (asdf/mise/proto): resolve
the active choice at each invocation from the current directory, rather than mutating the
user's shell on `cd`. This validates the shim architecture for non-interactive agent runs.

**The security lesson is direnv's trust model.** direnv's own rationale: without an allow
step, `cd` into a cloned repo would run arbitrary code. For a shim that injects *credentials*,
this is sharper: auto-applying a committed per-repo config that selects identity or points at
credentials lets a hostile repository redirect the agent's identity or exfiltrate through a
chosen credential. Any repo-local configuration that influences credentials must be
content-hash trusted before it is honored.

## Third-Party Git Identity Tools

Verified tools (stars and last-push as of 2026-09-06). None auto-switches on remote URL the
way nvm switches on `.nvmrc`; the only genuinely silent per-directory switch is native
`includeIf`, which two of these tools simply generate.

| Tool | Lang · Stars | Switching | Storage | Credentials beyond name/email |
|------|--------------|-----------|---------|-------------------------------|
| [git-ego](https://github.com/bgreenwell/git-ego) | Go · 110 | **Auto per-dir**: generates `includeIf gitdir:` (longest-prefix); `.gitego` is a fail-closed assertion only | `~/.gitego/config.yaml` + generated gitconfigs; PATs in OS keychain | SSH via `core.sshCommand`; signing; HTTPS PAT via own credential helper scoped to profile `hosts` |
| [gitswitch](https://github.com/aksisonline/gitswitch) | Go · 46 | Manual global switch; `pin` writes local; `cd` **nudge** (y/N), never silent | `~/.config/gitswitch/config.yaml`; `history.json` keyed by origin URL | `core.sshCommand`, signing, best-effort `gh auth switch`; tokens not stored |
| [git-identity (madx)](https://github.com/madx/git-identity) | Bash · 126 | Manual `git identity <name>` into local config | Identities in global git config `identity.<name>.*` | `core.sshCommand`, signing; no HTTPS tokens |
| [git-switcher (TheYkk)](https://github.com/TheYkk/git-switcher) | Rust · 250 | Manual; symlinks whole `~/.gitconfig` to a profile | `~/.config/gitconfigs/<name>` full configs | Only whatever is in that config |
| [git-profile (dotzero)](https://github.com/dotzero/git-profile) | Go · 76 | Manual `use`/`unuse`, local only | `$XDG_CONFIG_HOME/git-profile/config.json` | Arbitrary git keys; no key/token mgmt |
| [gitx (csawai)](https://github.com/csawai/git-identity-switcher) | Go · 10 | Manual per-repo `bind`; pre-push hook blocks unbound | `~/.config/gitx/identities.json`; PATs in keychain; managed `~/.ssh/config` block | SSH host alias + origin rewrite; PAT via osxkeychain; no signing |
| [guser](https://github.com/geongeorge/Git-User-Switch) | JS · 645 | Manual interactive; local (or `-g`) | sindresorhus `conf` JSON | signing key only; no SSH/HTTPS |
| [gitrole](https://github.com/synthesiseng/gitrole) | TS · 1 | Manual `use`; `.gitrole` is policy only; agent-oriented | `$XDG_CONFIG_HOME/gitrole/roles.json` | best-effort `ssh-add`, remote host-alias rewrite; no gh/token/GPG |
| [gip (forceuser)](https://github.com/forceuser/git-profile-switcher) | TS · 0 | `bind` generates `includeIf`; `use` = session env exports | `~/.config/git-profile-switcher/profiles.json` | identity via includes; session env |

Two patterns dominate: (a) mutate global or local git config on a manual `use`/`switch`/`bind`
command, or (b) generate native `includeIf gitdir:` snippets so git itself auto-selects. Tokens
are always pushed to the OS keychain, never committed. No verified tool uses
`git config --get-urlmatch` as its switch trigger.

## Credential and API-Account Managers

- **[Git Credential Manager](https://github.com/git-ecosystem/git-credential-manager)** (9.2k
  stars): HTTPS only. Supports multiple accounts on the *same* host by putting the username in
  the remote URL (`https://alice@github.com/...`) or `credential.https://HOST.username`, with
  optional `credential.useHttpPath` to key by path (forced for Azure DevOps). `credential.namespace`
  prefixes the OS-store bucket. Stores in OS keychain backends. Not cwd-based; explicitly not
  committer identity.
- **[gh auth switch](https://cli.github.com/manual/gh_auth_switch)**: flips the *process-wide*
  active account for a host in `hosts.yml` and the keyring. Affects `gh` API always, and HTTPS
  git only if `gh` is the credential helper; it does not touch SSH or committer identity.
  `GH_CONFIG_DIR` isolates a whole second config tree (direnv-able).
- **[git-credential-oauth](https://github.com/hickford/git-credential-oauth)** (871 stars): a
  read-only generating helper placed last in the chain; stores nothing itself; keyed by host;
  same-host multi-account is weak (its own docs recommend one account per host).
- **OpenSSH `ssh_config` / ssh-agent / [1Password SSH agent](https://developer.1password.com/docs/ssh/agent/)**:
  the SSH plane. Selection by first-matching `Host`/`Match`, `IdentityFile`, `IdentityAgent`,
  `IdentitiesOnly yes`. Host aliases plus origin-URL rewrite are the standard multi-account
  recipe. 1Password also does SSH commit signing.
- **osxkeychain helper**: internet-password items keyed by host/username/path; HTTPS only.

None of these auto-detect from the working directory. Same-host multi-account is always
URL-userinfo, path, a process-wide active account, or an SSH host alias.

## Conclusions and Design Implications for uv-shims

1. **The shim is the right shape.** The exec-time PATH-shim model (asdf/mise) is the closest
   and cleanest analog for wrapping `git`, and it works for non-interactive agents where
   `cd`-hooks do not. It also lets us do per-invocation SSH-key and HTTPS-credential selection
   that even native `includeIf` cannot fully do for SSH.

2. **Match at the repository level, not per operation.** Every system resolves identity from
   repo-level facts: the repo path (`gitdir`) and/or the set of configured remotes (`hasconfig`,
   any-remote match). Our shim should do the same. This is the verified resolution to the
   "`git commit` has no remote on argv" gap: match on the repository, not the operation's
   target.

3. **Our normalization and precedence are deliberate divergences from git, and worth it.**
   Native git matches remote URLs literally (two globs for SSH plus HTTPS) and resolves
   last-include-wins. Our proposed SSH/HTTPS normalization to a canonical `host/org/repo`, and
   most-specific-match precedence, are improvements that directly prevent the misattribution
   this feature guards against, but they are *ours*, not git behavior, and must be documented
   as such (corrects the earlier FR-026/FR-028 wording).

4. **Keep the four planes explicit.** Committer identity, HTTPS token, SSH key, and any
   hosting-API account are configured and scoped separately. Our spec already reflects this;
   keep credential scoping host-bound (`credential.https://HOST.helper`, `core.sshCommand`
   through a shim-managed `ssh -F` config).

5. **New requirement: trust repo-local config before honoring it.** This is the strongest
   finding. direnv and mise both gate directory-local configuration behind a content-hash
   allow, precisely because auto-executing repo config is a code/credential-injection risk.
   Since our per-repo configuration (FR-027) can select identity and point at credentials, a
   committed per-repo config MUST be trusted (content-hash allow-listed) before the shim
   honors it; otherwise cloning a hostile repository could redirect the agent's identity or
   its credential selection. The secret value itself must never live in the repo (all tools
   push tokens to the OS keychain).

6. **Do not disturb the human's account.** `gh auth switch` mutates a process-wide active slot
   and is the wrong lever. Prefer scoped mechanisms: a distinct `credential.namespace`, a
   distinct URL username, `GH_CONFIG_DIR`, or an SSH `IdentityAgent`/host alias, so the bot
   never displaces the operator's login.

7. **Reuse native git rather than reinvent where possible.** Because the shim wraps the real
   git binary, it inherits git's `includeIf`/`hasconfig`/`credential.<url>` support (and avoids
   the libgit2 gap that breaks tools like gitui). Generating `includeIf`/ssh_config, as
   `git-ego` and `gip` do, is a viable implementation lever to evaluate during planning.

## Recommended Spec Changes (to apply when clarify resumes)

- Restate FR-025/FR-026: match identity at the repository level against the union of the
  repo's configured remote URLs (any-remote match, like `hasconfig`) plus an optional repo-path
  matcher; mark SSH/HTTPS normalization as a shim feature, not git behavior.
- Restate FR-028: most-specific-match precedence is the shim's rule, explicitly divergent from
  git's last-include-wins.
- Add a requirement: repo-local configuration that influences identity or credential selection
  MUST be trusted via a content-hash allow step before it is honored; secrets are never read
  from repo-local files.
