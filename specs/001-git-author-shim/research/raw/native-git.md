<!-- Temporary research artifact: raw verified scout report (native-git). Session 2026-09-06. -->

## Summary

Native Git has no identity-profile object. Switching is automatic via includeIf (gitdir, gitdir/i, onbranch, hasconfig:remote.*.url) plus last-value-wins config merge; HTTP uses credential.<url>.*; SSH uses ssh_config/core.sshCommand. hasconfig matches at least one stored remote.*.url with wildmatch and does not normalize git@ vs https://. git commit needs no remote on argv.

## Architecture

Config cascade: system, XDG/global, $GIT_DIR/config, worktree, command (-c/env). include/includeIf splice files in-place. Identity (user.*/signing) is scalar last-wins. HTTP auth is credential.<url>.* urlmatch at fetch/push. SSH auth is outside git (ssh_config or core.sshCommand). hasconfig inspects stored remote.*.url strings only.

## Primary Sources

- https://git-scm.com/docs/git-config — Official git-config: includeIf, last-value-wins FILES, core.sshCommand, credential.<url>.*
- https://git-scm.com/docs/gitcredentials — Official credential contexts: URL matching, helper/username, HTTP-oriented
- https://git-scm.com/docs/gitfaq — Official FAQ: user.name vs credential.username; HTTP vs SSH multi-account
- https://github.com/git/git/blob/master/config.c — includeIf implementation: wildmatch on literal remote URLs, no protocol rewrite
- https://man.openbsd.org/ssh_config — OpenSSH ssh_config: Host/IdentityFile first-value-wins (opposite of git)

---

# Native Git

**System:** Git itself (no profile CLI). Canonical sources: [git-config](https://git-scm.com/docs/git-config) (published through **2.55.0**, 2026-06-29), [gitcredentials](https://git-scm.com/docs/gitcredentials), [gitfaq](https://git-scm.com/docs/gitfaq), implementation [git/git config.c](https://github.com/git/git/blob/master/config.c), [ssh_config(5)](https://man.openbsd.org/ssh_config). Repo: https://github.com/git/git — actively maintained. Star-count not fetched (do not invent).

There is **no** first-class identity/profile object. Multiple identities are assembled from (a) conditional includeIf, (b) last-value-wins merge of scalar keys, (c) URL-scoped credential.<url>.* for HTTP, (d) OpenSSH Host/IdentityFile and/or core.sshCommand for SSH.

## 1. SWITCHING

Automatic, evaluated whenever Git **reads config** (including `git commit`). No extra subcommand. Triggers are cwd / `$GIT_DIR` / current branch / already-stored remotes, not a remote on the command line.

### includeIf gitdir / gitdir/i

Docs ([Conditional includes](https://git-scm.com/docs/git-config#_conditional_includes)):

> The data that follows the keyword `gitdir` and a colon is used as a glob pattern. If the location of the .git directory matches the pattern, the include condition is met.

> The .git location may be auto-discovered, or come from `$GIT_DIR` environment variable. If the repository is auto-discovered via a .git file (e.g. from submodules, or a linked worktree), the .git location would be the final location where the .git directory is, not where the .git file is.

Convenience rules (same page):

- `~/` becomes `$HOME`; `./` becomes the directory of the **including** config file.
- Pattern not starting with `~/`, `./`, or `/`: `**/` is prepended (`foo/bar` becomes `**/foo/bar`).
- **Trailing-slash rule:** If the pattern ends with `/`, `**` will be automatically added. For example, the pattern `foo/` becomes `foo/**`. In other words, it matches foo and everything inside, recursively.
- `../` is not special (will match literally).

**gitdir/i:** This is the same as gitdir except that matching is done case-insensitively (e.g. on case-insensitive file systems).

**Symlinks** (same section):

> Symlinks in `$GIT_DIR` are not resolved before matching.
>
> Both the symlink & realpath versions of paths will be matched outside of `$GIT_DIR`. E.g. if ~/git is a symlink to /mnt/storage/git, both `gitdir:~/git` and `gitdir:/mnt/storage/git` will match.

(v2.13.0 initially matched only realpath; both spellings needed for that vintage.)

Implementation (`include_by_path` in config.c): `strbuf_realpath` then `wildmatch(..., WM_PATHNAME)` with optional `WM_CASEFOLD`; if that fails, retry with `strbuf_add_absolute_path` (the symlink spelling).

### includeIf onbranch

> If we are in a worktree where the name of the branch that is currently checked out matches the pattern, the include condition is met.
>
> If the pattern ends with `/`, `**` will be automatically added. … it matches all branches that begin with `foo/`.

Source (`include_by_branch`): resolves HEAD; **fails closed** unless HEAD is a symref under `refs/heads/` (detached HEAD: no match). Then wildmatch on the short branch name.

### includeIf hasconfig:remote.*.url (Git 2.36)

Introduced in Git 2.36 ([RelNotes/2.36.0](https://raw.githubusercontent.com/git/git/v2.36.0/Documentation/RelNotes/2.36.0.txt)):

> The conditional inclusion mechanism of configuration files using [includeIf <condition>] learns to base its decision on the URL of the remote repository the repository interacts with.

**At-least-one (docs, quote):**

> If there exists **at least one remote URL that matches this pattern**, the include condition is met.

> The first time this keyword is seen, the rest of the config files will be scanned for remote URLs (**without applying any values**).

> Files included by this option (directly or indirectly) are **not allowed to contain remote URLs**.

Typical use: condition in global/system config, URL in local `$GIT_DIR/config` (scan-ahead). Included files cannot declare remotes (cycle break).

**No URL normalization (load-bearing):** matching is `wildmatch(pattern, stored_remote_url, WM_PATHNAME)` on the **literal** `remote.<name>.url` string (`at_least_one_url_matches_glob` / `add_remote_url` in config.c). There is **no** rewrite of `git@host:org/repo` versus `https://host/org/repo` versus `ssh://git@host/org/repo`. Docs never claim otherwise; the example glob is protocol-specific:

    [includeIf "hasconfig:remote.*.url:https://example.com/**"]
        path = foo.inc
    [remote "origin"]
        url = https://example.com/git

**Operator must write two (or three) globs** if both SSH and HTTPS remotes should select the same identity, e.g. `https://github.com/**` AND `git@github.com:**` (and optionally `ssh://git@github.com/**`). A single HTTPS glob will **not** match `git@github.com:org/repo.git`.

`url.<base>.insteadOf` is a separate rewrite applied later to network operations; hasconfig does **not** match the rewritten form, only the configured `remote.*.url` value.

### Multiple matching includes: LAST-INCLUDE-WINS

[FILES](https://git-scm.com/docs/git-config#FILES):

> The files are read in the order given above, with **last value found taking precedence** over values read earlier. When multiple values are taken then all values of a key from all files will be used.

Includes splice in place:

> The contents of the included file are inserted immediately, as if they had been found at the location of the include directive.

`git config get`:

> If key is present multiple times in the configuration, **emits the last value**.

So if two includeIfs both match, later (in file order / later scope) scalar keys (`user.email`, `core.sshCommand`, …) override earlier. Multi-valued keys (`credential.helper`) accumulate unless reset with an empty helper.

Command-line `-c` / `GIT_CONFIG_KEY_<n>` override files ([ENVIRONMENT](https://git-scm.com/docs/git-config#ENVIRONMENT)).

### git commit does not need a remote on argv

[git-commit](https://git-scm.com/docs/git-commit) records the index vs HEAD. Identity is `user.name` / `user.email` (and optional signing) from the already-loaded config. gitdir/onbranch fire from the repo you are in. hasconfig uses **stored** `remote.*.url` in config files, not a URL argument. A repo with no remotes yet will not satisfy hasconfig.

`core.sshCommand` is not used at commit time:

> If this variable is set, `git fetch` and `git push` will use the specified command instead of `ssh` … overridden when [GIT_SSH_COMMAND] is set.

## 2. STORAGE/CONFIG

INI-like Git config ([CONFIGURATION FILE](https://git-scm.com/docs/git-config#_configuration_file)). Scopes, low to high:

- system: `$(prefix)/etc/gitconfig`
- global: `$XDG_CONFIG_HOME/git/config` then `~/.gitconfig`
- local: `$GIT_DIR/config`
- worktree: `$GIT_DIR/config.worktree` if `extensions.worktreeConfig`
- command: `-c`, `GIT_CONFIG_{COUNT,KEY,VALUE}`

Identity snippets are ordinary files pointed to by `include.path` / `includeIf.<condition>.path` (tilde-expanded; relative to the including file). Common pattern: `~/.gitconfig` holds `[includeIf "gitdir:~/work/"] path = ~/.config/git/work.inc` and that file sets `[user] name/email`, optional `signingKey`, `core.sshCommand`.

SSH identities live in `~/.ssh/config` (and `/etc/ssh/ssh_config`), not gitconfig, except when Git wraps ssh via `core.sshCommand` / `GIT_SSH_COMMAND`.

HTTP secrets: credential helpers (osxkeychain/libsecret/wincred/store/cache), not `user.*`.

## 3. USER INTERACTION

No `git identity` command. Users:

1. Edit config files or `git config [--global|--system|--local|--worktree] set ...`.
2. Add `[includeIf ...] path = ...` blocks in `~/.gitconfig`.
3. Set env: `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` / `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` / `EMAIL` override `user.*`. `GIT_SSH_COMMAND` overrides `core.sshCommand`.
4. `git -c user.email=bot@example commit` for one-shot.
5. `user.useConfigOnly=true` (global) refuses guessed identity and forces a per-repo `user.email`.
6. HTTP: `git config credential.https://example.com.username me` and `credential.helper`.
7. SSH multi-account (FAQ): extra keys plus Host aliases in `~/.ssh/config`, then `git remote set-url` to `git@alias:org/repo.git`.

## 4. CREDENTIALS vs IDENTITY

Git **separates** committer identity from network credentials. gitfaq:

> This configuration [user.name] doesn’t have any effect on authenticating to remote services; for that, see `credential.username`.

### Committer identity (name/email/signing) — in git config

- `user.name` / `user.email` (and `author.*` / `committer.*`) go into commit object fields.
- `user.signingKey` + `commit.gpgSign` + `gpg.format` (openpgp or ssh) for commit/tag signing. For `gpg.format=ssh`, `user.signingKey` may be a private-key path, `key::ssh-...`, or agent key.
- These are what includeIf gitdir/onbranch/hasconfig is used for. They apply on `git commit` with no remote.

### HTTP(S) credentials — credential.<url>.*

[gitcredentials](https://git-scm.com/docs/gitcredentials):

> Git will sometimes need credentials … for example, it may need to ask for a username and password in order to access a remote repository **over HTTP**.

Context is a URL. `credential.*` applies to all; `credential.<url>.*` is urlmatch:

> Git considers each credential to have a context defined by a URL.
>
> … match if the context is a more-specific subset of the pattern … both protocols are the same and both hosts are the same.
>
> Git compares hostnames exactly … a config entry for `http://example.com` would not match: **Git compares the protocols exactly**.

`credential.useHttpPath` (default false): helpers ignore path, so one token is reused across repos on the same host unless set true.

`credential.helper` is multi-valued; empty string **resets** the list. Helpers run until username and non-expired password exist.

**Helpers are for HTTP(S) (and other curl-based transports), not SSH.** SSH never consults `credential.helper`; gitfaq splits HTTP credential questions vs SSH multi-account.

### SSH credentials — outside Git, plus core.sshCommand

OpenSSH [ssh_config(5)](https://man.openbsd.org/ssh_config): `~/.ssh/config` then `/etc/ssh/ssh_config`. **First specified value wins** (opposite of Git last-wins). Host patterns match the hostname argument (Git passes github.com or an alias from the remote URL).

IdentityFile: multiple entries accumulate (all these identities will be tried in sequence). Pair with `IdentitiesOnly yes` so the agent does not offer every key.

gitfaq recommended pattern: one key per hosting account, Host aliases with HostName, User git, IdentityFile, IdentitiesOnly yes, then remote URL `git@example_author:org/repo.git`.

Git-side: `core.sshCommand = ssh -i ~/.ssh/id_bot -o IdentitiesOnly=yes` (or GIT_SSH_COMMAND) on fetch/push only; can be set inside an includeIf snippet so a workdir gets a bot key without ssh_config aliases.

### Related URL rewrite (not identity)

`url.<base>.insteadOf` / `pushInsteadOf`: longest-prefix rewrite of remote URLs (e.g. force SSH). Does not set `user.email`. hasconfig still sees the un-rewritten stored URL.

## Implications for a git shim (uv-shims)

- Per-directory bot name/email on commit: `includeIf gitdir:~/proj/` (trailing slash means recursive). Matches `$GIT_DIR`, not worktree path. Linked worktrees match the main .git location.
- Case-insensitive Windows paths: `gitdir/i:`.
- Per-branch identity: `onbranch:` (detached HEAD: no match).
- Per-remote-host identity without laying out dirs: `hasconfig:remote.*.url:` (2.36+). Literal glob; two globs for SSH+HTTPS; no remotes means no match; included files cannot set remotes.
- Override order: later include / later scope / `-c` (last-wins scalars).
- HTTPS token: `credential.<url>.helper` / `.username` (not used for SSH).
- SSH key: `core.sshCommand` or ssh_config Host+IdentityFile (fetch/push only; ssh_config is first-wins).
- Signing: `user.signingKey` + `commit.gpgSign` in same include.

**includeIf worktree / worktree/i:** present in git/git master Documentation/config.adoc (realpath of `git rev-parse --show-toplevel`). **Not** in the published git-scm.com 2.55.0 git-config page (that page lists gitdir, gitdir/i, onbranch, hasconfig only). Treat as unreleased-in-that-manual unless targeting a newer Git than 2.55 docs.

