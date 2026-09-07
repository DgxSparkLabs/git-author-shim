<!-- Temporary research artifact: raw verified scout report (credential-managers). Session 2026-09-06. -->

## Summary

Verified prior-art on GCM, gh, git-credential-oauth, ssh-agent/1Password, and osxkeychain: HTTPS helpers key by host plus optional URL username or useHttpPath; none auto-switch like nvm/direnv. GCM supports multiple accounts on the same host via URL userinfo and credential.https://HOST.username. gh auth switch changes the active host account in hosts.yml/keyring and therefore HTTPS git iff gh is the credential helper; it does not switch SSH. Credential helpers are HTTPS-only.

## Architecture

Git credential helpers are HTTPS-only get/store/erase programs keyed by protocol plus host, optional username, and path if credential.useHttpPath. Same-host multi-account is disambiguated by embedding username in the remote URL, not by cwd. SSH identity is a separate stack (ssh_config IdentityFile/IdentityAgent). gh adds a process-wide active account for a host that the git-credential helper then returns.

## Primary Sources

- https://github.com/git-ecosystem/git-credential-manager — GCM repo (9247 stars, pushed 2026-09-01); HTTPS credential helper
- https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/multiple-users.md — GCM same-host multi-account: URL userinfo plus credential.https://HOST.username
- https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/configuration.md — GCM namespace, credentialStore, useHttpPath mechanics
- https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/credstores.md — GCM storage backends (wincredman/keychain/libsecret/gpg/cache/plaintext)
- https://cli.github.com/manual/gh_auth_switch — Official gh auth switch man page
- https://github.com/cli/cli/blob/trunk/pkg/cmd/auth/gitcredential/helper.go — gh git-credential helper uses ActiveToken/ActiveUser; HTTPS only
- https://github.com/hickford/git-credential-oauth — git-credential-oauth (871 stars, last push 2026-01-14); generating helper
- https://developer.1password.com/docs/ssh/agent/ — 1Password SSH agent: vault keys, IdentityAgent, host aliases
- https://github.com/git/git/blob/master/contrib/credential/osxkeychain/git-credential-osxkeychain.c — osxkeychain helper: Keychain internet-password lookup by host/user/path

---

# Credential & Auth Managers

Cross-cutting facts verified from primary sources:

- **Git credential helpers apply to HTTPS only**, not SSH. gitcredentials(7): Git requests credentials "in order to access a remote repository **over HTTP**." GCM FAQ: "GCM is only useful for HTTP(S)-based remotes. Git supports SSH out-of-the box." The `gh auth git-credential` helper returns silently unless `protocol=https`.
- **None of these systems auto-detect identity from cwd** the way nvm/fnm/asdf/mise/direnv/uv/proto do. Switching is by remote URL (host / userinfo / path), by a process-wide active account (`gh auth switch` / `GH_CONFIG_DIR`), or by SSH Host aliases. Per-directory switching only appears if the user layers direnv or includeIf themselves.
- **Committer user.name / user.email is orthogonal.** GCM: "GCM doesn't interact with this notion of a user at all."

---

## 1. Git Credential Manager (GCM)

**Verified:** https://github.com/git-ecosystem/git-credential-manager -- **9247** stars, last push **2026-09-01**, C#. Docs: multiple-users.md, configuration.md, credstores.md, faq.md.

### STORAGE
OS credential store selected by `credential.credentialStore` / `GCM_CREDENTIAL_STORE`:

- `wincredman` (default Windows): Windows Credential Manager
- `dpapi`: DPAPI files under `%USERPROFILE%\.gcm\dpapi_store`
- `keychain` (default macOS): macOS login Keychain
- `secretservice`: libsecret / Secret Service (Linux)
- `gpg`: GPG/pass files (`~/.password-store`)
- `cache`: git-credential-cache in-memory
- `plaintext`: `~/.gcm/store`
- `none`: passthrough (no GCM store)

Service name format via `credential.namespace` (default **git**):

> "Use a custom namespace prefix for credentials read and written in the OS credential store. Credentials will be stored in the format `{namespace}:{service}`. Defaults to the value `git`."

Namespace is a **store-key prefix** (isolate GCM from other helpers), **not** an account picker for the same host.

### SELECTION (same host?)
**Yes, GCM supports multiple accounts on the same host.** Disambiguation is Git's credential context, not cwd.

1. **URL userinfo** (canonical GCM recipe), from multiple-users.md:

> "HTTPS URLs include an optional 'name' part before an `@` sign in the domain name, and you can use this to force Git to distinguish multiple users. This should likely be your username on the Git hosting service."
>
> Example: `git clone https://alice@github.com/mona/test`
>
> Also: `git config --global credential.https://github.com.username alice`

2. **`credential.useHttpPath`** (Git setting; GCM documents it). Default **false**: Git matches **user+hostname only**. `true`: full URL path is the lookup key.

GCM example with useHttpPath=false:

> Credential `git:https://github.com` (user=alice) is reused for `https://github.com/foo/bar`, `https://github.com/contoso/widgets`, **and** `https://alice@github.com/contoso/widgets`.
>
> Credential `git:https://bob@github.com` (user=bob) is used for all `https://bob@github.com/...` remotes.

With useHttpPath=true, credentials become per-path (`git:https://github.com/foo/bar`). GCM **forces** useHttpPath=true for `https://dev.azure.com` because the org is in the path:

> "we need this setting to make Git use the full remote URL (including the path component). The Azure DevOps account name is required in order to resolve the correct authority."

3. **GitHub account list / picker:** `git credential-manager github [list | login | logout]` (usage.md). `credential.gitHubAccountFiltering` filters GitHub.com EMU accounts by server hints.

4. **Azure DevOps bindings** (azrepos-users-and-tokens.md): `git-credential-manager azure-repos [list|bind|unbind]` stores org-to-account in `~/.gitconfig` (global) or `.git/config` (local `--local`). Per-remote: put username in the remote URL (`alice-alt%40contoso.com@...`).

GCM does **not** auto-switch on cd.

### SWITCH
- Change remote URL userinfo / `credential.https://HOST.username`.
- GitHub: `git credential-manager github login|logout`.
- Azure: `azure-repos bind|unbind`.
- Interactive account picker when GCM cannot decide ("Prompted to select an account?" in multiple-users.md).
- `credential.namespace` to isolate whole store buckets, not per-repo.

### CREDENTIALS vs IDENTITY
**Auth credentials only (HTTPS tokens/OAuth/PAT/basic).** Explicitly not committer identity. Not SSH keys. Not commit signing. FAQ: "I want to use SSH" means use native Git SSH.

---

## 2. GitHub CLI (`gh auth switch`, `GH_CONFIG_DIR`, `hosts.yml`)

**Verified:** https://github.com/cli/cli -- **46161** stars, last push **2026-09-05**. Docs: cli.github.com/manual/gh_auth_switch, gh_help_environment, gh_auth_login, gh_auth_setup-git. Source: pkg/cmd/auth/switch/switch.go, pkg/cmd/auth/gitcredential/helper.go, internal/config/config.go, cli/go-gh pkg/config ConfigDir.

### STORAGE
Config dir (go-gh ConfigDir):

> "Config path precedence: GH_CONFIG_DIR, XDG_CONFIG_HOME, AppData (windows only), HOME."

Official env man:

> "GH_CONFIG_DIR: the directory where gh will store configuration files. If not specified, the default value will be one of: `$XDG_CONFIG_HOME/gh` ... `$AppData/GitHub CLI` ... `$HOME/.config/gh`."

Files:
- `config.yml` -- general (git_protocol, editor, ...)
- `hosts.yml` -- per-host accounts (hosts.HOSTNAME.user, users.NAME, optional plaintext oauth_token)

Tokens: OS keyring service `gh:HOSTNAME`, keyed by username; **active** token also copied to the unkeyed slot `gh:HOSTNAME` / empty username. Fallback: plaintext oauth_token in hosts.yml (`--insecure-storage`). Env GH_TOKEN / GITHUB_TOKEN **overrides** stored credentials.

gh auth login: "an authentication token will be stored securely in the system credential store. If a credential store is not found ... fallback to writing the token to a plain text file."

### SELECTION
Process-wide **active user per host**, not per-repo and not per-directory.

SwitchUser (config.go):
1. Rejects if current token source is neither `keyring` nor `oauth_token` (env-token cannot be switched).
2. activateUser: delete host-level keyring/plaintext token; copy the chosen user's token into the **active** slot; set hosts.HOSTNAME.user; write hosts.yml.

Hidden helper `gh auth git-credential` (used after `gh auth setup-git`):

- If protocol is not https, SilentError.
- gotToken, source := ActiveToken(lookupHost); gotUser := ActiveUser(lookupHost).
- If Git asked for a username and it does not match the active user (and user is not x-access-token), SilentError.

So for HTTPS git, gh returns **whatever account is currently active for that host**, unless the remote URL's username disagrees (then it yields nothing and the next helper/prompt runs). gist.github.com falls back to github.com. **No path matching; useHttpPath is irrelevant to gh.**

### SWITCH
`gh auth switch [--hostname] [--user]`:

> "This command changes the authentication configuration that will be used when running commands targeting the specified GitHub host."
>
> Two accounts on the host: auto-toggles to the inactive one. More than two: --user or prompt.

**Does gh auth switch affect git?**

- gh API commands (gh pr, gh api, ...): **Yes** -- they use ActiveToken
- git HTTPS, if `gh auth setup-git` installed gh as credential helper: **Yes** -- helper returns ActiveToken
- git SSH remotes (git@github.com:): **No** -- helper ignores non-https; SSH keys are not swapped
- Committer name/email / signing: **No**

`gh auth login --git-protocol`: "Although login is for a single account on a host, setting the git protocol will take effect for **all users on the host**." SSH key upload is a login-time side effect, not switched later.

GH_CONFIG_DIR is a **whole-config isolation** switch (can be direnv'd). That is not gh auth switch; it is a second hosts.yml tree.

### CREDENTIALS vs IDENTITY
Handles GitHub **OAuth/PAT tokens** for gh plus optional HTTPS git. Can upload an SSH public key at login. Does **not** manage committer identity or commit signing.

---

## 3. git-credential-oauth

**Verified:** https://github.com/hickford/git-credential-oauth -- **871** stars, last push **2026-01-14**, Go, Apache-2.0. README + main.go.

### STORAGE
**Does not store.** It is a read-only **generating** helper meant **last** in the helper chain:

> "git-credential-oauth is a read-only credential-generating helper, designed to be configured in combination with a storage helper."
>
> helper = cache --timeout 21600 then helper = oauth (or osxkeychain / wincred / libsecret first).

`configure` on Darwin sets storage=osxkeychain; Windows=wincred; else cache 6h.

Refresh tokens live in the **storage** helper (oauth_refresh_token capability). Requires Git >= 2.45 for refresh-token storage (README troubleshooting).

### SELECTION
Keyed by **host** from Git's credential protocol. Built-in OAuth client IDs for github.com, gitlab.com, bitbucket.org, etc. Custom hosts via credential.https://HOST.oauthClientId / oauthAuthURL / oauthTokenURL.

Same-host multi-account is **weak**:

- If Git passes username and it is not oauth2, GitHub auth URL gets a login=USERNAME query (GitHub identity hint). Same for googlesource login_hint.
- Output username defaults to oauth2 (GitLab-style) or x-token-auth (Bitbucket) if Git did not supply one -- **not** the GitHub login.
- README troubleshooting: "Check Git remote URL `git remote -v` **does not contain a username**." So the project's own docs prefer **one account per host** in the storage helper.
- No auth switch, no namespace, no active-account file.

Practical same-host split: put username in the HTTPS URL (so the storage helper keys on user) **or** credential.useHttpPath true so the storage helper keys on path; oauth then only runs when storage misses.

### SWITCH
Re-auth in browser (or -device flow). Erase the storage-helper entry, or change remote username. No first-class switch command. No cwd detection.

### CREDENTIALS vs IDENTITY
HTTPS OAuth access tokens only. README slogan "No more SSH keys" means it **replaces** SSH for clone/push; it does not manage SSH or signing. Not committer identity.

---

## 4. ssh-agent / OpenSSH IdentityAgent + 1Password SSH agent

**Verified OpenSSH:** Debian ssh_config(5) (OpenSSH 10.5) https://manpages.debian.org/unstable/openssh-client/ssh_config.5.en.html

**Verified 1Password:** developer.1password.com docs for ssh/agent, agent/config, agent/advanced, get-started, git-commit-signing.

This stack is **SSH**, not Git credential helpers.

### STORAGE
- **ssh-agent:** private keys in memory after ssh-add; files under ~/.ssh/ (IdentityFile defaults: id_rsa, id_ecdsa, id_ed25519, ...).
- **1Password:** SSH Key items in vaults. Private key never leaves the app. Agent socket:
  - macOS: ~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock (symlink ~/.1password/agent.sock)
  - Linux: same IdentityAgent pattern (~/.1password/agent.sock in advanced examples)
  - Windows: takes over \\.\pipe\openssh-ssh-agent (no per-host IdentityAgent; "it will authenticate for all hosts")
- Optional 1Password ~/.config/1Password/ssh/agent.toml (Windows: %LOCALAPPDATA%/1Password/config/ssh/agent.toml) listing [[ssh-keys]] by item / vault / account. Order = offer order (six-key MaxAuthTries limit).

### SELECTION
OpenSSH, first matching Host/Match in ~/.ssh/config:

> **IdentityAgent:** "Specifies the UNIX-domain socket used to communicate with the authentication agent. This option overrides the SSH_AUTH_SOCK environment variable ... Setting the socket name to none disables the use of an authentication agent."
>
> **IdentityFile:** "It is possible to have multiple identity files ... all these identities will be tried in sequence." Public key path can select the corresponding key **already loaded in the agent**.
>
> **IdentitiesOnly yes:** only configured identity files, even if the agent offers more.

1Password multi-GitHub-account recipe (advanced.md) -- **host aliases**, not cwd:

```
Host personalgit
  HostName github.com
  User git
  IdentityFile ~/.ssh/personal_git.pub
  IdentitiesOnly yes
Host workgit
  HostName github.com
  User git
  IdentityFile ~/.ssh/work_git.pub
  IdentitiesOnly yes
```

Then `git remote set-url origin personalgit:org/repo.git`. Same pattern with IdentityAgent ~/.1password/agent.sock vs IdentityAgent none.

Default 1Password agent offers **all** eligible keys in Personal/Private/Employee vaults; agent.toml restricts/orders them.

### SWITCH
- Edit ~/.ssh/config / remote URL host alias (persistent, per-remote).
- SSH_AUTH_SOCK / IdentityAgent (per-process or per-Host).
- ssh-add -d / add different keys (session).
- 1Password: authorize a specific key when prompted; no gh auth switch equivalent.
- Windows 1Password: cannot per-host IdentityAgent.

### CREDENTIALS vs IDENTITY
**SSH auth keys.** 1Password also does **commit signing** (not HTTPS tokens):

> Sets gpg.format=ssh, user.signingkey=pubkey, optional commit.gpgsign=true, gpg.ssh.program=op-ssh-sign.

Multiple signing setups via Git includeIf (1Password documents this). Still not HTTPS credentials. Not user.name unless the snippet also sets it.

---

## 5. macOS Keychain / osxkeychain helper

**Verified:** Git contrib source git-credential-osxkeychain.c. Listed in gitcredentials(7) as the macOS secure persistent helper. **No separate man page** (git-scm.com/docs/git-credential-osxkeychain returned 404). GCM's default macOS store is the same Keychain APIs under credential.credentialStore=keychain.

### STORAGE
macOS Keychain **internet password** items (kSecClassInternetPassword) with attributes:

kSecAttrServer (host), kSecAttrAccount (username), kSecAttrPath (path), kSecAttrPort, kSecAttrProtocol, plus password data (and optional oauth_refresh_token / expiry metadata in the password blob).

Lookup: SecItemCopyMatching with kSecMatchLimitOne on those attributes. If username is empty, it still returns the first matching host item and fills username from kSecAttrAccount.

### SELECTION
Whatever Git puts on the credential protocol stdin. Default Git **omits path**, so one password per (protocol, host, username). Enable credential.useHttpPath true so Git sends path= and the helper stores/looks up distinct items per repo path.

No account switcher, no active-user file, no cwd hook. Multiple GitHub accounts: different username (URL userinfo) and/or path.

### SWITCH
Keychain Access / security CLI to delete items; change remote URL username; or git credential reject. GCM/oauth/gh sitting in front of Keychain own the UX.

### CREDENTIALS vs IDENTITY
HTTPS (and other internet-password protocols Git asks for). **Not SSH** (SSH keys are a different Keychain class / files). Not committer identity. Not signing.

---

## Answers to the explicit design questions

**Does GCM support multiple accounts for the SAME host, and how is the account disambiguated?**
Yes. Primary mechanism: put the account in the remote URL (`https://alice@github.com/...`) and/or `credential.https://github.com.username`. Optional credential.useHttpPath makes the **path** part of the store key (GCM already does this for dev.azure.com). credential.namespace only prefixes the OS-store service name. GitHub/Azure extra CLIs manage remembered accounts. GCM may prompt if still ambiguous. **Not cwd-based.**

**How does gh auth switch change the active account, and does it affect git or only the gh API?**
It rewrites hosts.yml user: for that host and moves that user's token into the active keyring/plaintext slot. All gh commands for that host follow. **HTTPS git follows only if gh is the credential helper** (gh auth setup-git / gh auth git-credential); the helper returns ActiveToken. If Git's requested username != active user, the helper refuses. **SSH git is unaffected.** Env GH_TOKEN blocks switching.

**Do credential helpers apply to HTTPS only (not SSH auth)?**
**Yes.** Confirmed by gitcredentials(7), GCM FAQ, and gh helper's protocol != https early-out. SSH uses ssh-agent / IdentityFile / IdentityAgent / 1Password, a separate plane.

## Implications for a git shim (uv-shims)

- Treat **HTTPS credentials** and **SSH identities** as two planes; a shim that only wraps git credential helper protocol will never see SSH.
- Same-host multi-account prior art is **URL userinfo plus optional useHttpPath**, plus gh's **process-wide active account**. Nobody ships nvm-style directory auto-switch for credentials.
- A bot-identity shim that must not disturb the human's GitHub login should prefer: dedicated credential.namespace, a distinct URL username, GH_CONFIG_DIR, or SSH IdentityAgent/IdentityFile Host alias -- not gh auth switch (that mutates the user's active slot).

