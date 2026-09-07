<!-- Temporary research artifact: raw verified scout report (git-identity-tools). Session 2026-09-06. -->

## Summary

Verified third-party git identity switchers from primary GitHub/npm/docs. Closest nvm-style auto-switch is git-ego (includeIf gitdir). Most others are manual CLI that write global or local git config. Candidate URLs mohan-c/git-profile-switcher, variant96/git-account-switcher, and djaustin/gitrole 404.

## Architecture

Pattern split: (1) mutate ~/.gitconfig or .git/config on a switch/use/bind/pin command; (2) generate includeIf gitdir snippets so Git itself auto-selects identity per directory with no hook; (3) rewrite remotes / SSH Host aliases / core.sshCommand; (4) optional gh auth switch or credential-helper PATs. Almost none auto-detect like nvm without a prior bind/auto-rule. No verified third-party tool uses git config --get-urlmatch as the switch trigger.

## Primary Sources

- (sources cited inline in report)

---

# Third-Party Git Identity Tools

Primary sources only (GitHub README/source, npm registry, gitswitch.dev). Star counts and `pushed_at` from GitHub API as of 2026-09-06. Native `includeIf`/`credential.<url>` and `gh auth switch`/GCM are out of scope (sibling scouts).

**Closest nvm/direnv analogue:** `git-ego` (and 0-star `forceuser/git-profile-switcher`) write Git `includeIf "gitdir:…"` so identity/SSH/signing apply automatically when Git runs in that tree. `gitswitch` is the opposite: explicit global switch + optional per-repo **pin** (local config) plus a **cd nudge**, not silent auto-apply.

---

## guser / Git-User-Switch

- **Repo:** https://github.com/geongeorge/Git-User-Switch
- **CLI:** `git-user` (`npm i -g git-user-switch`)
- **Lang:** JavaScript · **Stars:** 645 · **Last push:** 2023-03-20 (stale) · MIT

1. **SWITCHING:** Manual interactive list. Default **local** (`git config user.*`); `-g/--global` for global. No per-directory auto-detect.
2. **STORAGE/CONFIG:** Profile list via sindresorhus `conf` (`new Conf()`, no options) keyed from package name `git-user-switch` → typical `config.json` under OS config dir (`…/git-user-switch-nodejs/`). `[INFERENCE]` exact path from Conf v7 defaults, not hardcoded in repo. Applies `user.name`, `user.email`, optional `user.signingKey` (clears signingKey if absent).
3. **USER INTERACTION:** Run `git-user`; pick user or “Add new user”. `-d` delete, `-r` reset store. No env-var profile select.
4. **CREDENTIALS vs IDENTITY:** Identity + optional **GPG/SSH signingKey** only. **No SSH key / `core.sshCommand` / HTTPS tokens.**

Quote (`src/lib/selectUser.js`): `git config ${globalFlag} user.name` / `user.email` / `user.signingKey`.

---

## git-identity-switcher (`gitx`)

- **Repo:** https://github.com/csawai/git-identity-switcher
- **CLI:** `git-identity-switcher` (alias `gitx`; brew `csawai/tap/gitx`)
- **Lang:** Go · **Stars:** 10 · **Last push:** 2026-01-14 · MIT

1. **SWITCHING:** Manual **per-repo bind**. `bind <alias>` writes **local** config; no global mutation; no auto on `cd`. Optional `install-hook` pre-push blocks unbound repos.
2. **STORAGE/CONFIG:** `~/.config/gitx/identities.json` (`Identity`: alias, name, email, github_user, ssh_key_path, auth_method `ssh|pat`, ssh_host_alias). PATs in OS keychain service `"gitx"`. SSH keys `~/.ssh/gitx_<alias>`. Managed block in `~/.ssh/config` (`# BEGIN git-identity-switcher managed`). Local marker `gitx.bound=<alias>`.
3. **USER INTERACTION:** `add identity` (prompts), `list identities`, `bind work`, `unbind`, `tui`, `show-key`/`copy-key`. `--dry-run` on bind.
4. **CREDENTIALS vs IDENTITY:** Local `user.name`/`user.email`. **SSH:** Host alias `github.com-work` + rewrite `origin` to `git@github.com-work:…` (`IdentitiesOnly yes`). **PAT:** convert origin to HTTPS + `credential.helper` `osxkeychain` (fallback `store`). **No GPG/signing.** Does not touch `~/.gitconfig`.

Quote (`bind.go`): `exec.Command("git", "config", "--local", key, value)`.

---

## @variant96/git-account-switcher (`git-switch`)

- **npm:** https://www.npmjs.com/package/@variant96/git-account-switcher (v1.0.1, ~8 weekly downloads, maintainer `variant96`)
- **Actual GitHub:** https://github.com/eliotalders0n/git-account-switcher-npm (0★, last push 2025-12-06). Claimed `github.com/variant96/git-account-switcher` is **404**.
- **Lang:** JavaScript · MIT

1. **SWITCHING:** Manual `git-switch switch <name>` — **local** by default, `--global`/`-g` for global. No directory auto-switch.
2. **STORAGE/CONFIG:** `~/.git-accounts.json`: `{ accounts: [{ name, git_name, git_email, gh_username }], last_used }`.
3. **USER INTERACTION:** `git-switch setup|add|list|current|remove|switch`.
4. **CREDENTIALS vs IDENTITY:** Sets `user.name`/`user.email`. Best-effort `gh auth switch -u "<username>"`. **No SSH, no signing, no tokens of its own.**

---

## gitswitch

- **Site:** https://gitswitch.dev · **Repo:** https://github.com/aksisonline/gitswitch · **Docs:** repo `docs/public/`
- **Lang:** Go (v0.4.4 on site) · **Stars:** 46 · **Last push:** 2026-09-04 (active) · Apache-2.0

1. **SWITCHING:** Manual. TUI Enter or `gitswitch work` / `gitswitch switch work` writes **global** `~/.gitconfig`. `gitswitch pin work` writes the **same five keys locally** so the repo keeps that identity while global stays unchanged. Shell hook on `cd` **nudges** (y/N, default N) after ≥3 visits and ≥60% share — does **not** auto-apply. Not includeIf-based.
2. **STORAGE/CONFIG:** `~/.config/gitswitch/config.yaml` (`version: 2`, profiles: nickname, user_name, email, ssh_key, sign_key, gh_user, active). `history.json` keyed by `origin` URL (fallback abs path) with counts + `pinned`. Tokens **not** stored; `gitswitch login` delegates to `gh auth login`.
3. **USER INTERACTION:** TUI (`a` add, `e` edit, `p` pin); CLI `add|list|current|remove|pin|unpin|login|reauthor|shell|claude`. Env: none for profile select (path fixed).
4. **CREDENTIALS vs IDENTITY:** Full bundle on switch/pin:
   - `user.name` / `user.email` always
   - SSH: `core.sshCommand = ssh -i <path> -o IdentitiesOnly=yes` (unset if profile has no key)
   - Signing: hex → `user.signingkey` + clear `gpg.format`; path/`ssh-…` → `gpg.format=ssh`; none → clear both
   - `gh auth switch --user` best-effort; optional HTTPS credential.helper routing + session-isolated `gh` wrapper

Quote (docs): pinning writes local `[user]`, `[gpg] format`, `[core] sshCommand`.

---

## git-ego (also published as gitego)

- **Repo:** https://github.com/bgreenwell/git-ego (`github.com/bgreenwell/gitego` redirects here)
- **CLI:** `git-ego` / `git ego`
- **Lang:** Go · **Stars:** 110 · **Last push:** 2026-07-25 · MIT

1. **SWITCHING:** **Automatic per-directory via Git `includeIf gitdir:`** after `git ego auto <path> <profile>`. Longest-prefix path match. `git ego use <profile>` sets global default (reconciles managed include). `git ego use --local` writes **local** repo config. `.gitego` file at repo root is an **assertion only** (hook/credential helper fail-closed); it does not select identity.
2. **STORAGE/CONFIG:** Authoritative `~/.gitego/config.yaml` (`profiles`, `auto_rules`, `active_profile`). Generated `~/.gitego/profiles/<name>.gitconfig`, `includes.gitconfig`, `default.gitconfig`. Reconcile appends one managed `[include]` at end of `~/.gitconfig`. PATs in OS keychain (`git ego pat set`).
3. **USER INTERACTION:** `add`, `use`, `auto`/`auto list`/`auto rm`, `pat set`, `doctor --repair`, `status`, `install-hook`. Credential helper: `git config --global credential.https://github.com.helper "!git-ego credential"`.
4. **CREDENTIALS vs IDENTITY:** Profile fields: name, email, username, ssh_key, signing_key, hosts. Generated gitconfig sets `user.*`, `gitego.profile`, `user.signingkey`+`gpg.format` (openpgp vs ssh), `core.sshCommand` when SSH key set. HTTPS: credential-helper `get` emits username+PAT **only** if host is in profile `hosts` (default github.com). No SSH Host-alias rewrite.

Quote (`config/reconcile.go`): `[includeIf "gitdir:"+rule.Path]` → profile gitconfig.

---

## git-identity (madx)

- **Repo:** https://github.com/madx/git-identity
- **CLI:** `git identity` (PATH git plugin)
- **Lang:** Bash · **Stars:** 126 · **Last push:** 2026-01-26 · WTFPL

1. **SWITCHING:** Manual `git identity <name>` copies identity into **local** repo config (`git config` without `--global`). No auto per-dir. `--update` refreshes local from global identity store.
2. **STORAGE/CONFIG:** Identities **in global git config**: `identity.<name>.name|email|signingkey|sshkey|sshkeyverbosity`. Local marker `user.identity`.
3. **USER INTERACTION:** `--define <id> <name> <email> [<ssh> [<gpg>]]`, `--define-ssh`, `--define-gpg`, `--list`, `--remove`, `-c` prints/runs with `GIT_SSH_COMMAND`.
4. **CREDENTIALS vs IDENTITY:** Local `user.name`/`email`; GPG → `user.signingkey` + `commit.gpgsign`/`tag.gpgsign true`; SSH → `core.sshCommand="ssh -i ~/.ssh/<file>"`. No HTTPS tokens, no ssh_config Host aliases.

---

## git-switcher (TheYkk)

- **Repo:** https://github.com/TheYkk/git-switcher
- **Lang:** Rust · **Stars:** 250 · **Last push:** 2025-11-18 · Apache-2.0

1. **SWITCHING:** Manual `git-switcher switch <profile>` (or interactive menu). **Replaces entire `~/.gitconfig` with a symlink** to the profile file. Global-only; no per-repo; no auto.
2. **STORAGE/CONFIG:** Profiles as files `~/.config/gitconfigs/<profile-name>` (full gitconfig copies, not just user.*).
3. **USER INTERACTION:** `create|list|switch|rename|delete|edit`.
4. **CREDENTIALS vs IDENTITY:** Whatever is in that full gitconfig (could include sshCommand/signing if user put it there). Tool itself only swaps the symlink — **does not manage keys/tokens**.

Quote (`switch.rs`): remove `~/.gitconfig`, `create_symlink(target_profile_path, git_config_path)`.

---

## git-profile (dotzero)

- **Repo:** https://github.com/dotzero/git-profile
- **Lang:** Go · **Stars:** 76 · **Last push:** 2026-08-14 · MIT

1. **SWITCHING:** Manual `git-profile use [name]` — **local only** (`git config --local`). `unuse` unsets those keys. Must be inside a repo (`-C` supported). No auto.
2. **STORAGE/CONFIG:** `$XDG_CONFIG_HOME/git-profile/config.json` else `~/.gitprofile` (legacy). Profiles are maps of arbitrary git keys (`user.name`, `user.email`, `user.signingkey`, …).
3. **USER INTERACTION:** `add`/`list`/`del`/`use`/`unuse`/`current`; interactive TUI; optional agent skill `npx skills add dotzero/git-profile`.
4. **CREDENTIALS vs IDENTITY:** Any git config keys you store (typically name/email/signingkey). **No SSH/HTTPS credential management.**

---

## git-profile-switcher (mchandr4) — closest to candidate `mohan-c/`

- **Repo:** https://github.com/mchandr4/git-profile-switcher (https://github.com/mohanchandrasekar/git-profile-switcher resolves to the same). **`github.com/mohan-c/git-profile-switcher` = 404.**
- **Lang:** Python · **Stars:** 2 · **Last push:** 2025-12-09 · MIT

1. **SWITCHING:** Manual `git-profile use <name>` → **`git config --global` user.name/email only**. Roadmap lists “automatic detection per repository” as unimplemented.
2. **STORAGE/CONFIG:** `~/.config/git-profiles/<name>.gitconfig` INI `[user]`; snapshot `~/.gitconfig-active`.
3. **USER INTERACTION:** `init|create|use|list|show|current`; Linux Zenity GUI `git-profile-gui`.
4. **CREDENTIALS vs IDENTITY:** Name/email only. SSH documented as **manual** `~/.ssh/config` Host aliases — tool does not swap keys.

---

## gitrole

- **Repo:** https://github.com/synthesiseng/gitrole (https://github.com/synsoftworks/gitrole redirects here). Docs https://docs.gitrole.dev
- **Lang:** TypeScript (npm `gitrole`) · **Stars:** 1 · **Last push:** 2026-04-15 · MIT
- Explicitly aimed at agents (“who will this commit say it is from?” / “who will GitHub think I am when I push?”).

1. **SWITCHING:** Manual `gitrole use <name> [--global|--local]`. **No auto-switch, no hooks.** `gitrole pin` writes repo-local `.gitrole` **policy** (resolve/status/doctor); does not by itself change git config.
2. **STORAGE/CONFIG:** `$XDG_CONFIG_HOME/gitrole/roles.json` (or `~/.config/gitrole/roles.json`): `{ roles: [{ name, fullName, email, sshKeyPath?, githubUser?, githubHost? }] }`.
3. **USER INTERACTION:** `add|import current|use|pin|resolve|status|doctor|remote set|list|remove`. No prompts (by design).
4. **CREDENTIALS vs IDENTITY:** Sets `user.name`/`user.email` (global or local). Optional **`ssh-add` of sshKeyPath** (best-effort, does not fail the switch). `remote set` rewrites origin to role’s GitHub SSH host alias. **No `gh auth`, no HTTPS tokens, no GPG.** README: “No GitHub browser or session switching.”

---

## forceuser/git-profile-switcher (`gip`) — includeIf auto-bind (tiny)

- **Repo:** https://github.com/forceuser/git-profile-switcher · npm `@forceuser/git-profile-switcher`
- **Lang:** TypeScript · **Stars:** 0 · include because it is the other verified **includeIf directory switcher**

1. **SWITCHING:** `gip bind work` (cwd or path) writes Git `includeIf` directory rules. `gip bind personal --global` fallback. Session-only: `gip use work` via shell exports. Auto after bind — Git, not a cd hook.
2. **STORAGE/CONFIG:** `~/.config/git-profile-switcher/profiles.json` + generated `…/gitconfigs/`. One marked block in global gitconfig. Override `GIP_APP_DATA_DIR` / `XDG_CONFIG_HOME` / `GIP_GLOBAL_GITCONFIG`.
3. **USER INTERACTION:** `profile:add|list|remove`, `bind`, `clear`, `rule:*`, `tui`, `install:shell|prompt|all`.
4. **CREDENTIALS vs IDENTITY:** Git identity via generated includes. Session `use` is env exports. Not a credential/SSH key manager in the README surface.

---

## `git config --get-urlmatch` / `gh-account-switcher`

- **No verified third-party identity switcher** uses `--get-urlmatch` as the profile selector. URL-scoped `credential.*` / `includeIf.hasconfig:remote.*.url` are native Git (NativeGit scout).
- **No repo named `gh-account-switcher` verified.** Closest tiny CLIs: `SohamGanmote/ghswitch` (2★) wraps `gh auth switch` + hardcoded `git config --global user.*`. Official multi-account API auth is `gh auth switch` (CredentialManagers).

---

## Unverified / Not-found

| Candidate | Result |
|---|---|
| https://github.com/mohan-c/git-profile-switcher | **404.** Closest real: `mchandr4/git-profile-switcher` (also `mohanchandrasekar/…`). |
| https://github.com/variant96/git-account-switcher | **404.** npm `@variant96/git-account-switcher` exists; source is `eliotalders0n/git-account-switcher-npm`. |
| https://github.com/djaustin/gitrole | **404.** Real: `synthesiseng/gitrole`. |
| https://github.com/bgreenwell/git-ego vs `git-ego` as separate from `gitego` | **Same repo.** `gitego` URL redirects to `git-ego`. Path still `~/.gitego/`. |
| `gh-account-switcher` as a product | **Not found** as a dedicated maintained tool. |
| Web-search name `git-profile-switcher/git-profile-switcher` org | **Not fetched as a real org repo** in this pass; do not treat as verified. |

---

## Implications for a git shim (uv-shims)

| Approach | Who | Trigger | Writes |
|---|---|---|---|
| Mutate global gitconfig on `use` | guser `-g`, gitswitch switch, TheYkk symlink, mchandr4, gitrole default, variant96 `-g` | Manual command | Global user.*/sshCommand |
| Mutate local `.git/config` | guser default, madx, gitx bind, gitswitch pin, git-ego `--local`, dotzero use, gitrole `--local` | Manual / pin | Local beats global |
| **Git includeIf gitdir (nvm-like)** | **git-ego**, **gip** | Git reads config; no hook | Generated snippets + one global include |
| cd hook nudge | gitswitch shell | Prompt, default no | Optional later switch |
| Remote rewrite + SSH Host alias | gitx, gitrole `remote set` | Bind/remote set | origin URL + `~/.ssh/config` |
| `core.sshCommand` IdentitiesOnly | gitswitch, git-ego, madx | Switch/pin/include | gitconfig, not ssh_config |
| HTTPS PAT helper | git-ego credential | `git credential get` | OS keychain |
| `gh auth switch` | gitswitch, variant96, ghswitch | Coupled to identity switch | gh’s token store |

**None of the verified tools auto-switch on remote URL** the way nvm switches on `.nvmrc` without a prior directory rule. Directory auto-switch that is actually silent is **includeIf**, not a shim on `git` itself — except a future uv-shims git wrapper could do per-invocation identity like `GIT_SSH_COMMAND` / env, which only madx (`-c`) and gip (`use --exports`) approximate today.

