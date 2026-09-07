# CLI & Environment Contract: Git Author Identity Shim

**Feature**: [spec.md](../spec.md) · **Plan**: [plan.md](../plan.md) · **Status**: Completed

## 1. Primary Executable: `git`

The shim is distributed as an executable named `git` (or `git.exe` on Windows).

### 1.1 Passthrough Contract (FR-001, FR-003)
* All standard arguments, subcommands, and flags passed to `git <args>` are forwarded directly to the real Git binary.
* `stdin`, `stdout`, and `stderr` streams are piped transparently to preserve interactive editor workflows (`git commit` without `-m`) and colored output.
* Exit code of the real Git process is returned as the shim's exit code.
* OS signals (`SIGINT`, `SIGTERM` on POSIX; `Ctrl+C` on Windows) are forwarded to the child Git process (FR-002).

---

## 2. Environment Variables Contract

| Variable | Values | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `UV_SHIM_GIT_MODE` | `auto`, `agent`, `human` | `auto` | Explicitly sets the identity mode (FR-007, FR-010). Overrides auto-detection. |
| `UV_SHIM_GIT_CONFIG` | `<filepath>` | `~/.config/uv-shims/git.toml` | Path to the global shim configuration file. |
| `UV_SHIM_GIT_EXPLAIN` | `1`, `true` | Unset | When set, prints the resolved invocation plan (secrets redacted) and exits 0 without calling real Git (FR-021). |
| `UV_SHIM_GIT_REAL_PATH` | `<filepath>` | Auto-detected | Explicit path to the real Git binary to bypass auto-discovery. |
| `__UV_SHIM_GIT_CONTINUATION` | `1` | Unset | Internal sentinel injected into child processes to prevent infinite recursive self-invocation (FR-001, US6). |

### 2.1 Recognized Vendor Agent Markers (Auto-Detection)
Under `UV_SHIM_GIT_MODE=auto`, the presence of any of the following environment variables triggers `agent` mode:
* `AGENT_ID`
* `CLAUDE_CODE` / `CLAUDE_AGENT`
* `CODEX_SANDBOX`
* `CURSOR_AGENT`
* `OPENAI_AGENT`
* Operator-defined custom markers in `git.toml`.

---

## 3. Dedicated Inspection CLI: `git-shim`

In addition to acting as `git`, the package exposes `git-shim` for operator management.

### 3.1 Commands

#### `git-shim explain [--json]`
Prints the resolved plan for the current repository and environment without performing any Git actions.

**Sample Output (Human-readable)**:
```text
=== Git Author Identity Shim: Resolved Plan ===
Mode:            agent (detected via AGENT_ID=agent-worker-9)
Repository:      github.com/acme-corp/payment-service
Target Host:     github.com
Matched Profile: acme-prod (pattern: "github.com/acme-corp/*")
Operation:       originating commit
Author:          Release Bot <bot@acme.corp>
Committer:       Release Bot <bot@acme.corp>
Transport:       SSH
SSH Key:         ~/.ssh/bot_ed25519 (IdentitiesOnly=yes)
HTTPS Token:     [REDACTED] (source: env:BOT_GITHUB_TOKEN)
Write Permitted: YES
================================================
```

**JSON Schema (`--json`)**:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "mode",
    "is_write",
    "write_permitted",
    "author",
    "committer",
    "transport"
  ],
  "properties": {
    "mode": { "type": "string", "enum": ["auto", "agent", "human"] },
    "detected_marker": { "type": ["string", "null"] },
    "matched_identity_id": { "type": ["string", "null"] },
    "repository_canonical_url": { "type": ["string", "null"] },
    "target_host": { "type": ["string", "null"] },
    "operation_class": { "type": "string", "enum": ["originating", "carrying", "read", "unknown"] },
    "author": {
      "type": "object",
      "properties": {
        "name": { "type": "string" },
        "email": { "type": "string" }
      }
    },
    "committer": {
      "type": "object",
      "properties": {
        "name": { "type": "string" },
        "email": { "type": "string" }
      }
    },
    "transport": { "type": "string", "enum": ["ssh", "https", "local", "unknown"] },
    "ssh_key_path": { "type": ["string", "null"] },
    "https_token_source": { "type": ["string", "null"] },
    "write_permitted": { "type": "boolean" },
    "failure_reason": { "type": ["string", "null"] }
  }
}
```

#### `git-shim trust [path/to/.git-shim.toml]`
Computes the SHA-256 hash of the specified repository-local configuration file and adds it to the operator's trusted registry (`~/.config/uv-shims/trusted-hashes.json`).

#### `git-shim untrust [path/to/.git-shim.toml]`
Removes the specified file from the trusted registry.

#### `git-shim list-identities`
Lists all globally configured bot identities and their matching patterns.
