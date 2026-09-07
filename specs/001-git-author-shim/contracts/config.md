# Configuration Schema Contract: Git Author Identity Shim

**Feature**: [spec.md](../spec.md) · **Plan**: [plan.md](../plan.md) · **Status**: Completed

## 1. Global Configuration File: `config.toml`

Default path: `~/.git-shim/config.toml` (or `%USERPROFILE%\.git-shim\config.toml` on Windows). Override with `GIT_SHIM_CONFIG`.

```toml
[settings]
default_mode = "auto" # "auto", "agent", "human"
vendor_detection = true
custom_agent_markers = ["CUSTOM_AGENT_ENV", "MY_CI_RUNNER"]

[[identities]]
id = "acme-github"
name = "Acme Automation Bot"
email = "bot@acme.corp"
match_patterns = [
    "github.com/acme-corp/*",
    "github.com/acme-internal/*"
]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
strict_host_checking = true

[identities.https]
token_env_var = "ACME_BOT_TOKEN"
# Alternatively: token_file = "/path/to/token.txt"
# Alternatively: token_command = "op read op://vault/item/token"
username = "x-access-token"

[[identities]]
id = "personal-gitlab"
name = "Personal Agent"
email = "agent@personal.dev"
match_patterns = [
    "gitlab.com/my-username/*"
]

[identities.ssh]
key_file = "~/.ssh/gitlab_agent_ed25519"
```

---

## 2. Repository-Local Configuration File: `.git-shim.toml`

Located in the root of a repository. **Ignored until trusted via `git-shim trust`**.

```toml
# Overrides or selects which identity to use for this specific repository
identity = "acme-github"

# Optional local overrides (e.g. override commit name/email without redefining keys)
[override]
name = "Acme Release Bot"
email = "release-bot@acme.corp"
```
