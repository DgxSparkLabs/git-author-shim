# Quickstart & Validation Guide: Git Author Identity Shim

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Status**: Completed

This guide walks through end-to-end setup and validation scenarios to verify all user stories in a local environment.

---

## Prerequisites

1. Python 3.12+ and `uv` installed.
2. System Git installed and reachable on system `PATH`.
3. An SSH key pair generated for testing (e.g. `ssh-keygen -t ed25519 -f ./test_bot_key -N ""`).

---

## 1. Setup & Installation

```bash
# 1. Install the package in editable mode
uv pip install -e .

# 2. Place the shim ahead of Git in PATH (or activate environment)
export PATH="$(pwd)/.venv/bin:$PATH"  # or Windows Scripts path

# 3. Verify the shim intercepts `git`
which git
# Output should point to the virtual environment's git executable
```

---

## 2. Validation Scenarios

### Scenario 1: Verify Operator Passthrough (User Story 2)
Verify that normal human operations remain completely untouched and leave global configs unmodified.

```bash
# Unset any agent variables
unset AGENT_ID
unset UV_SHIM_GIT_MODE

# Run explain
git-shim explain
# Expected Output: Mode: human (no marker detected). Passthrough active.

# Inspect git configs
git config --global user.name
# Should match operator's real name unchanged.
```

### Scenario 2: Agent Commit & Push under Bot Identity (User Stories 1 & 3)
Verify automated commit authoring and committer attribution.

```bash
# 1. Set agent marker
export AGENT_ID="test-agent-01"

# 2. Initialize a temporary repository matching configured pattern
mkdir /tmp/test-repo && cd /tmp/test-repo
git init
git remote add origin git@github.com:acme-corp/test-repo.git

# 3. Create a commit
echo "hello world" > README.md
git add README.md
git commit -m "feat: initial agent commit"

# 4. Inspect commit log
git log -1 --format="Author: %an <%ae>%nCommitter: %cn <%ce>"
# Expected Output:
# Author: Acme Automation Bot <bot@acme.corp>
# Committer: Acme Automation Bot <bot@acme.corp>
```

### Scenario 3: Author Preservation during Cherry-Pick (User Story 7)
Verify that replaying a human commit preserves original author while setting bot as committer.

```bash
# Create a human commit
UV_SHIM_GIT_MODE=human git commit --allow-empty -m "human work" --author="Jane Doe <jane@company.com>"
HUMAN_HASH=$(git rev-parse HEAD)

# Switch to a new branch and cherry-pick as agent
git checkout -b feature-backport
git cherry-pick $HUMAN_HASH

# Inspect attribution
git log -1 --format="Author: %an <%ae>%nCommitter: %cn <%ce>"
# Expected Output:
# Author: Jane Doe <jane@company.com>
# Committer: Acme Automation Bot <bot@acme.corp>
```

### Scenario 4: Fail-Safe on Unconfigured Repo (User Story 4)
Verify that write operations halt with an actionable error in unconfigured repos.

```bash
mkdir /tmp/unconfigured-repo && cd /tmp/unconfigured-repo
git init
git remote add origin git@github.com:random-stranger/repo.git

# Attempt a commit as agent
echo "code" > main.py
git add main.py
git commit -m "test"
# Expected Outcome:
# Command halts with non-zero exit code.
# Output: "Error: No bot identity configured matching repository 'github.com/random-stranger/repo'. Write operation refused."
```

### Scenario 5: Content-Hash Trust Gate (User Story 8)
Verify that untrusted repository-level `.git-shim.toml` is ignored until trusted.

```bash
cd /tmp/test-repo
echo 'identity = "malicious-bot"' > .git-shim.toml

# Explain output should warn that local config is untrusted and ignore it
git-shim explain

# Trust the file
git-shim trust .git-shim.toml

# Edit the file (tamper with content)
echo 'identity = "tampered-bot"' > .git-shim.toml

# Explain output should detect invalid hash and refuse to load untrusted override
git-shim explain
```
