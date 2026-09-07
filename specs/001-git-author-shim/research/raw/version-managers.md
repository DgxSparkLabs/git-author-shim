<!-- Temporary research artifact: raw verified scout report (version-managers). Session 2026-09-06. -->

## Summary

Version managers share one pattern: walk up from cwd for a pin file, then activate via (a) shell cd/prompt hooks that mutate PATH/env, (b) PATH shims that resolve at exec time, or (c) command-time lookup with no hook. Trust/allow exists only where repo-local config is executable (direnv always; mise when config can run code). Declarative pins (.tool-versions, .nvmrc, .python-version, .prototools) have no allow step. For a git identity/credential shim, copy the walk-up pin, prefer exec-time shims over cd-hooks, and never auto-apply repo-local secrets without a direnv-style content-hashed allow.

## Architecture

Two orthogonal layers: (1) DISCOVERY — walk parents from cwd until a named pin/config is found (nearest-wins for nvm/fnm/direnv/uv; merge-all for mise/proto/asdf-per-tool). (2) ACTIVATION — either a shell hook on cd/prompt that exports PATH/env (direnv, mise activate, fnm --use-on-cd, nvm recipes, proto activate) or a PATH shim / CLI that re-resolves on every invocation (asdf, mise --shims, proto shims, uv commands). TRUST is a third layer applied only when the discovered file is executed as code.

## Primary Sources

- https://github.com/direnv/direnv — direnv repo (15.4k stars). README + rc.go FindRC/findUp/fileHash allow model.
- https://direnv.net/man/direnv.1.html — Official direnv(1): prompt hook, .envrc walk, direnv allow rationale.
- https://github.com/direnv/direnv/blob/master/man/direnv.toml.1.md — direnv.toml whitelist prefix/exact (implicit allow; warned as arbitrary-code risk).
- https://mise.jdx.dev/configuration.html — mise hierarchical config filenames, walk-up merge, ceiling_paths.
- https://mise.jdx.dev/cli/trust.html — mise trust: content-bound trust, paranoid mode, safe vs executable configs.
- https://mise.jdx.dev/dev-tools/shims.html — mise activate (prompt/cd hook-env) vs shims vs mise exec.
- https://github.com/jdx/mise — mise repo (33.5k stars); README activate recipe; version 2026.9.1.
- https://asdf-vm.com/manage/configuration.html — asdf .tool-versions format, .asdfrc, ASDF_TOOL_VERSIONS_FILENAME.
- https://asdf-vm.com/manage/versions.html — asdf shims → asdf exec; env ASDF_${TOOL}_VERSION overrides.
- https://github.com/asdf-vm/asdf — asdf repo (25.6k stars); per-dir auto-switch via shims.
- https://github.com/Schniz/fnm — fnm repo (26.8k stars); .nvmrc/.node-version; --use-on-cd.
- https://github.com/Schniz/fnm/blob/master/docs/configuration.md — fnm --use-on-cd and --version-file-strategy=local|recursive.
- https://github.com/nvm-sh/nvm — nvm repo (94.9k stars); v0.40.7; .nvmrc walk-up; unofficial cd recipes.
- https://moonrepo.dev/docs/proto/config — proto .prototools locations, resolution modes (upwards / upwards-global).
- https://moonrepo.dev/docs/proto/detection — proto version detection order: CLI, PROTO_*_VERSION, FS walk, ecosystem files, global.
- https://moonrepo.dev/docs/proto/workflows — proto shims vs bins vs proto activate shell hooks.
- https://github.com/moonrepo/proto — proto repo (1.4k stars).
- https://docs.astral.sh/uv/concepts/python-versions/ — uv .python-version walk-up, pin commands, no cd hook.
- https://github.com/astral-sh/uv — uv repo (89.5k stars).

---

# Version-Manager Pattern

Common model for per-directory auto-switch, verified against primary repos/docs (not search summaries). Star counts are GitHub API snapshots from this research pass (2026-09-06).

## Common DISCOVERY + ACTIVATION + TRUST model

**DISCOVERY.** From `$PWD`, walk *up* parent directories looking for a well-known filename. Stop at filesystem root, `$HOME`, a project/workspace boundary, or an explicit ceiling. Two merge policies:

- **Nearest wins:** first matching file is the only one used (direnv `.envrc`, nvm `.nvmrc`, fnm default `local`, uv `.python-version`).
- **Walk-and-merge:** collect every matching file and overlay, closer-to-cwd wins per key (mise, proto `upwards`, asdf per-tool across ancestor `.tool-versions`).

**ACTIVATION.** Three triggers, often combined:

| Trigger | When it fires | Who |
|---|---|---|
| Shell hook (cd / prompt) | `chpwd` / wrapped `cd` / `PROMPT_COMMAND` / fish PWD | direnv (always), mise `activate`, fnm `--use-on-cd`, nvm *unofficial* recipes, proto `activate` |
| PATH shim | every invocation of a wrapped binary | asdf (primary), mise `--shims`, proto shims |
| Command-time lookup | user ran the tool (`uv venv`, `nvm use`, `fnm use`) | uv (no cd hook), nvm/fnm without hook |

**TRUST.** Only tools that *execute* repo-local files gate them:

- direnv: **always** blocked until `direnv allow` (content+path hash). Official rationale: otherwise `cd` into a cloned repo would run arbitrary bash.
- mise: **trust** required when config can run code/templates/env; “safe” `[tools]` version strings skip trust in normal mode; paranoid mode always requires content-bound trust.
- asdf / nvm / fnm / uv / proto pins: **no allow step** because files are data (version strings / TOML), not executed. Residual risk is `path:` versions, plugin install, or `[env]` injection — not an allowlist.

### Security lesson for injecting credentials from repo-local config

direnv’s man page states the threat model in one sentence: without an allow step, “any git repo that you pull, or tar archive that you unpack, would be able to wipe your hard drive once you `cd` into it.” Allow is **content-hashed** (`sha256(path + "\n" + file bytes)` in `internal/cmd/rc.go`); editing `.envrc` invalidates the grant. Whitelist prefixes in `direnv.toml` skip the grant and are documented as “use with great care” because collaborators can write executable files.

mise’s `mise trust` is the same idea for TOML that can template/run tasks: “Without trust, mise may prompt, skip the config… or fail with an untrusted-config error.” Paranoid mode binds trust to **content**, not just path, and disables worktree sharing.

**For a git identity/credential shim:** do **not** auto-load tokens, SSH keys, or `GIT_CONFIG_PARAMETERS` from a committed project file on `cd`. Prefer:

1. Declarative *identity pin* in-repo (name/email/profile id) — like `.nvmrc` / `.tool-versions` (data, no exec).
2. Secrets only from user-level store or an explicit allow (direnv-style hash of the file that *points at* credentials, never the secret itself in the repo).
3. Prefer **exec-time shims** (`git` wrapper like asdf) over **cd-hooks** so non-interactive agent runs still resolve identity without mutating the user’s shell, and so `cd && git` in one line still sees the right profile (mise documents this as a bash/prompt-hook pitfall).

---

## Per-tool specifics

### direnv — https://github.com/direnv/direnv (15,419★) · https://direnv.net/man/direnv.1.html

**DISCOVERY.** `FindRC` → `findEnvUp` → `findUp` walks `eachDir(cwd)` (cwd then every parent to `/`). Per directory, tries `.envrc` then (if `load_dotenv`) `.env`. **First hit wins**; parents are *not* auto-merged. Parent `.envrc` is loaded only if the child file calls `source_up` (stdlib; **“the other `.envrc` is not checked by the security framework”**).

**ACTIVATION.** Shell hook, **before each prompt**: `eval "$(direnv hook bash|zsh|…)"`. Loads `.envrc` in a **bash subprocess**, captures export diff, applies to the current shell; `cd` out unloads. Not a PATH shim.

**TRUST.** Default blocked: “`.envrc` is not allowed”. `direnv allow [PATH]`. Allow records under `$XDG_DATA_HOME/direnv/allow` keyed by **fileHash(path+content)**; deny keyed by path hash. Optional `[whitelist] prefix|exact` in `$XDG_CONFIG_HOME/direnv/direnv.toml` implicitly allows — documented as arbitrary-code risk.

**CONFIG.** `.envrc` = bash (plus stdlib). Optional `.env` (dotenv). User: `direnv.toml`, `direnvrc`, `lib/*.sh`.

**IDENTITY vs CREDENTIALS.** Env vars only (can set `GIT_AUTHOR_*`, `GIT_SSH_COMMAND`, tokens). No git-specific identity. Highest risk analog for credential injection.

---

### mise — https://github.com/jdx/mise (33,509★) · https://mise.jdx.dev/configuration.html · trust: https://mise.jdx.dev/cli/trust.html · shims: https://mise.jdx.dev/dev-tools/shims.html

Maintained (README reports `2026.9.1`).

**DISCOVERY.** Walks cwd → root (or `MISE_CEILING_PATHS`). **Merges all** files; closer overrides. Per-directory filename precedence (higher overrides lower):

`mise.local.toml` > `mise.toml` > `mise/config.toml` > `mise/conf.d/*.toml` > `.mise/config.toml` > `.mise/conf.d/*.toml` > `.config/mise.toml` > `.config/mise/config.toml` > `.config/mise/conf.d/*.toml`  
Dot variants (`.mise.toml`) allowed. Plus `MISE_ENV` files (`mise.development.toml`). System `/etc/mise` lowest; `mise.local.toml` gitignored. `mise config` prints loaded order.

**ACTIVATION.** Dual:

- **PATH activation (recommended interactive):** `eval "$(mise activate zsh)"` runs `hook-env` on **prompt** (and `cd` on bash/zsh/fish/xonsh: zsh `chpwd`, bash wrap `cd`+`PROMPT_COMMAND`). Mutates `PATH` to real tool bins.
- **Shims:** `mise activate --shims` prepends `~/.local/share/mise/shims` (Windows `%LOCALAPPDATA%\mise\shims`); shims are links to `mise` that resolve on exec. Env vars from `[env]` then apply **only inside shimmed processes**, not the shell.
- **Neither:** `mise exec` / `mise run` load env for one command.

**TRUST.** `mise trust [CONFIG_FILE]`. Quote: “This means mise is allowed to parse the file when it needs to read config that may execute code or affect the environment.” Normal mode auto-trusts on `run`/`install`/`exec`/`watch`; **safe** files (`min_version`, plain `[tools]` versions, `[tasks]` without templates) skip trust. **Paranoid mode:** explicit content-bound trust for every non-global config; no worktree sharing.

**CONFIG.** TOML: `[tools]`, `[env]`, `[tasks.*]`, `[settings]`, `[plugins]`, `[wrappers]`. Hierarchical merge (tools/env additive; tasks replaced).

**IDENTITY vs CREDENTIALS.** `[env]` can export anything (including git identity env). Trust is the gate. Not git-specific.

---

### asdf — https://github.com/asdf-vm/asdf (25,564★) · https://asdf-vm.com/manage/configuration.html · versions: https://asdf-vm.com/manage/versions.html

**DISCOVERY.** Filename `.tool-versions` (override `ASDF_TOOL_VERSIONS_FILENAME`). Docs: “Whenever `.tool-versions` file is present in a directory, the tool versions it declares will be used in that directory and any subdirectories.” Resolution is **on shim exec**, climbing parents until a version for that tool is found (home file is global default). `asdf set -p` writes the closest parent file. Env `ASDF_${TOOL}_VERSION` overrides all files for that shell. Optional `legacy_version_file = yes` in `~/.asdfrc` lets plugins read `.nvmrc` / `.ruby-version` / etc.

**ACTIVATION.** **Shims only** (v0.16+ getting-started: prepend `${ASDF_DATA_DIR:-$HOME/.asdf}/shims` to `PATH`; no cd hook). Shim → `asdf exec` → lookup version → `exec` real binary. `asdf reshim` after extra binaries (e.g. `npm -g`). README: “automatically switches runtime versions as you traverse your directories” — meaning next command, not PATH rewrite on `cd`. Optional [asdf-direnv](https://github.com/asdf-community/asdf-direnv) for cd-time env (third-party).

**TRUST.** None for `.tool-versions` (data). `path:~/src/elixir` runs user-supplied binaries. Plugins are git clones (install-time trust of plugin authors).

**CONFIG.** Space-separated lines: `nodejs 10.15.0`, comments `#`, fallbacks `python 3.7.2 2.7.15 system`, `ref:`, `path:`, `system`. User: `~/.asdfrc` (`legacy_version_file`, hooks `pre_<plugin>_<command>`).

**IDENTITY vs CREDENTIALS.** Tool versions only. No git identity.

---

### fnm — https://github.com/Schniz/fnm (26,791★) · https://github.com/Schniz/fnm/blob/master/docs/configuration.md

**DISCOVERY.** Files: `.node-version`, `.nvmrc`, and (CLI default on) `package.json#engines#node` if no dotfile. `--version-file-strategy` (`FNM_VERSION_FILE_STRATEGY`):

- **`local` (default):** cwd only — `fnm use` in a subdirectory errors “Can't find version in dotfiles”.
- **`recursive` (docs: highly recommended):** walk parents; nearest wins.

**ACTIVATION.** `eval "$(fnm env --use-on-cd --shell zsh)"` appends a **cd hook** that runs `fnm use`. Without the flag, only explicit `fnm use` / `fnm exec`. `fnm env` mutates PATH to the selected Node (not asdf-style persistent shims).

**TRUST.** None. Pin files are version strings / JSON engines. No allow.

**CONFIG.** Dotfile = version string. State in `FNM_DIR` (default XDG). Flags on `fnm env`.

**IDENTITY vs CREDENTIALS.** Node version only.

---

### nvm — https://github.com/nvm-sh/nvm (94,898★) · README `.nvmrc` + “Deeper Shell Integration”; v0.40.7

**DISCOVERY.** README: “You can create a `.nvmrc` file … in the project root directory (or any parent directory).” “`nvm use` et. al. will traverse directory structure upwards from the current directory looking for the `.nvmrc` file.” Nearest wins. `nvm use`/`install`/`which` with no arg use it; else exit 127. Format: one `<version>` plus newline; `#` comments; `key=value` reserved/ignored.

**ACTIVATION.** **Not automatic.** nvm is a sourced shell function that rewrites `PATH` (`NVM_BIN`) on `nvm use`. Auto-switch is **unsupported user recipes**: bash aliases `cd` to `cdnvm` calling `nvm_find_up .nvmrc`; zsh `add-zsh-hook chpwd load-nvmrc` + `nvm_find_nvmrc`; fish `--on-variable=PWD`. Third-party `nvshim` mentioned as unsupported. No built-in shim farm.

**TRUST.** None for `.nvmrc` (data). Sourcing `nvm.sh` is user-level.

**CONFIG.** `.nvmrc` text; aliases under `$NVM_DIR`; `nvm alias default`.

**IDENTITY vs CREDENTIALS.** Node version only. `NVM_RC_VERSION` set when using `.nvmrc`.

---

### proto — https://github.com/moonrepo/proto (1,406★) · https://moonrepo.dev/docs/proto/config · detection: https://moonrepo.dev/docs/proto/detection · workflows: https://moonrepo.dev/docs/proto/workflows · activate: https://moonrepo.dev/docs/proto/commands/activate

**DISCOVERY.** File `.prototools` (TOML). Locations: `local` `./.prototools`, `user` `~/.prototools`, `global` `~/.proto/.prototools`. Modes (`--config-mode` / `PROTO_CONFIG_MODE`):

- `upwards` (default for activate/install/outdated/status): walk cwd → `$HOME`, merge, cwd highest.
- `upwards-global`/`all` (default for other commands): same + append `~/.proto/.prototools`.
- `local` / `global`: single file.

`PROTO_ENV=production` loads `.prototools.production` **before** `.prototools` in the same directory. Version **detection** order (run/shim): (1) CLI arg, (2) `PROTO_<TOOL>_VERSION`, (3) FS walk `.prototools` then ecosystem files (`.nvmrc`, `package.json` engines), (4) global pin, (5) fail.

**ACTIVATION.** Three workflows:

- **Shims** `~/.proto/shims` — wrappers around `proto run` (runtime detection every call).
- **Bins** `~/.proto/bin` — versioned symlinks; **no** per-dir detection.
- **`proto activate <shell>`** — hook on directory **and** prompt change; loads `.prototools`, exports `[env]`, prepends tool PATH. Only tools with a version in `.prototools` (global pins excluded unless `--config-mode all`). POSIX `sh` shadows `cd`.

**TRUST.** No direnv-style allow for `.prototools`. Docs emphasize checksum verification of *downloaded tools* and WASM plugins — not an allowlist for project TOML. `[env].file = ".env"` loads dotenv relative to the config file (env injection, still not executed as bash).

**CONFIG.** TOML map `node = "16.16.0"`, `[env]`, `[settings]` (`auto-install`, etc.), `[tools.*]`.

**IDENTITY vs CREDENTIALS.** Env vars via `[env]` on activate/shim execution; not git-specific.

---

### uv (Python versions) — https://github.com/astral-sh/uv (89,496★) · https://docs.astral.sh/uv/concepts/python-versions/

**DISCOVERY.** “uv searches for a `.python-version` file in the working directory and each of its parents. If none is found, uv will check the user-level configuration directory.” **Stops at project/workspace boundaries** (except user config). `--no-config` disables. `.python-versions` (plural) lists many versions for `uv python install`. `requires-python` in `pyproject.toml` also constrains project commands; `.python-version` / `--python` override.

**ACTIVATION.** **No cd hook and no version-manager shims for switching.** Discovery is **command-time** (`uv venv`, `uv run`, `uv python find`, …). `uv python pin` / `uv python pin --global` write the file. `uv python install` may put `python3.12` in `~/.local/bin` — that is a static executable, not a per-dir switcher.

**TRUST.** None. File is a version request string, not executed.

**CONFIG.** One request per line (docs recommend a plain version number for interoperability). User-level global pin via `--global`.

**IDENTITY vs CREDENTIALS.** Interpreter selection only.

---

## Comparison (for uv-shims git identity)

| Tool | Pin files | Walk | Merge | Trigger | Trust/allow |
|---|---|---|---|---|---|
| direnv | `.envrc` (`.env` opt.) | up to `/` | nearest only (`source_up` opt-in) | prompt hook | **Yes — content hash** |
| mise | `mise.toml` family | up to ceiling | merge all, closer wins | prompt/`cd` hook **or** shims | **Yes if executable config** |
| asdf | `.tool-versions` | up (home = global) | per-tool nearest | **shim exec** | No (data) |
| fnm | `.nvmrc` / `.node-version` | `local` or `recursive` | nearest | optional `--use-on-cd` | No |
| nvm | `.nvmrc` | up | nearest | `nvm use` + unofficial cd | No |
| proto | `.prototools` | `upwards` to `$HOME` | deep merge | shims **and/or** activate hook | No allow; tool checksums |
| uv | `.python-version` | up to project boundary | nearest + user global | command-time only | No |

**Closest analog to a `git` shim:** asdf/mise/proto **shims** (resolve identity at `git` invocation from cwd’s pin file). **Closest analog to credential safety:** direnv/mise **trust**, applied to any file that can change env or run code. Do not copy direnv’s “execute the pin file”; copy its **allow-before-apply** if the pin can influence credentials.
