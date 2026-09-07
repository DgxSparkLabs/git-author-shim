# Idea Research: Extensible Harness Detection

- **Slug**: harness-detection
- **Created**: 2026-09-08
- **Evidence confidence (overall)**: high

## Users & Demand

- **Individual Engineers using Multi-Agent Tooling**: Developers frequently run agents like Claude Code, Oh My Pi, Cursor, Codex, and Aider on the same machine where they conduct personal work; they demand automated bot attribution during agent runs without manual mode toggling — [source: specs/001-git-author-shim/spec.md User Story 1] (confidence: high, cited)
- **Engineering Managers & Security/Compliance Teams**: Regulated organizations require strict Git commit provenance to distinguish machine-generated code from human author contributions for copyright and IP audit compliance — [source: specs/001-git-author-shim/spec.md Success Criteria SC-001] (confidence: high, cited)
- **Operators in Worktree Environments (Orca / OMP)**: Users working across multiple tabs and worktrees in composite environments need assurance that ambient workspace plumbing does not hijack their personal manual commits — [source: specs/001-git-author-shim/spec.md User Story 2] (confidence: high, cited)
- **Adoption of Emerging Agents**: Demand exists for supporting newly released agents without waiting for an upstream `git-author-shim` release cycle — [source: ASSUMPTION based on fast-moving AI CLI landscape in 2025-2026] (confidence: medium, assumption)

## Prior Art

- **Current In-Tree Implementation (`_VENDOR_MARKERS`)**: `src/git_author_shim/agent_detection.py` uses a hardcoded tuple of uppercase strings (`CLAUDE_CODE`, `AGENT_ID`, `CURSOR_AGENT`, `CODEX_SANDBOX`, etc.). It lacks wildcard support, requires source changes for new vendors, and suffers from a discrepancy where real Claude Code exports `CLAUDECODE` and OMP exports `OMPCODE` — [source: src/git_author_shim/agent_detection.py]
- **Static Binary Scanning of Claude Code (`claude.exe` v2.1.263)**: Decompilation of the bundled JavaScript runtime confirmed Claude Code injects `CLAUDECODE: "1"` into child process spawn environments, and sets `AI_AGENT: "agent"` when running as an autonomous agent — [source: strings analysis of claude.exe offset 186379874, 187462128]
- **Shell Wrapper Tools (direnv, asdf, mise)**: Common environment managers rely on declarative config files to switch tool behavior per directory or context without modifying global system state — [source: ASSUMPTION based on developer tooling patterns] (confidence: medium, assumption)
- **Git Native Hooks (`prepare-commit-msg`)**: Traditional approach uses local Git hooks, but hooks must be installed in every repository clone, are bypassed by `git -c` overrides or `--no-verify`, and cannot manage isolated SSH signing credentials — [source: specs/001-git-author-shim/spec.md]

## Market & Context

- **Fragmented Environment Standards**: AI agent vendors have not standardized on a single environment variable convention. Some inject tool-specific flags (`CLAUDECODE`, `OMPCODE`), others use generic flags (`AGENT_ID`), and some offer none by default — [source: empirical testing across Claude Code and OMP runtimes]
- **Rapid Evolution of Agent Runtimes**: New AI coding tools appear every quarter. A hardcoded vendor list creates an ongoing maintenance bottleneck; an extensible architecture (manifest + user wildcards) future-proofs the shim — [source: ASSUMPTION based on developer ecosystem trends]
- **Cost of Doing Nothing**: Without extensible detection, users running unlisted agents will produce bot commits attributed to their human identity (violating compliance), or will be forced to manually wrap commands or export `GIT_SHIM_MODE=agent` across diverse shells — [source: specs/001-git-author-shim/spec.md User Story 3]

## Data & Constraints

- **Execution Budget**: Detection executes synchronously on every intercepted `git` invocation. Matching must complete in under 5 milliseconds with zero external network or subprocess overhead — [source: specs/001-git-author-shim/spec.md SC-004 performance target]
- **Zero Third-Party Dependencies**: The implementation must rely exclusively on Python standard library modules (`tomllib`, `fnmatch`, `os`, `pathlib`) — [source: pyproject.toml / architectural constraints]
- **User Story 2 Human-Isolation Invariant**: Workspace-level variables (`ORCA_WORKTREE_ID`, `ORCA_TAB_ID`, `PI_SESSION_FILE`) and CI flags (`CI`, `GITHUB_ACTIONS`, `GITLAB_CI`) must NEVER be treated as agent markers by default; doing so would falsely attribute human operator commits — [source: specs/001-git-author-shim/spec.md User Story 2]
- **Safety Against Wildcard Catastrophe**: User-configurable wildcard patterns in `custom_agent_markers` must enforce a minimum non-glob prefix (e.g. at least 3-4 alphanumeric characters) and reject overly broad wildcards like `*`, `?`, `PATH`, or `GIT_*` to prevent accidental global trapping in bot mode — [source: ASSUMPTION based on defensive design principles] (confidence: medium, assumption)

## Evidence Against the Idea

- **Configuration Fatigue**: Asking users to manually configure `custom_agent_markers` when adopting a new tool adds cognitive load compared to a system that "just works" — [source: ASSUMPTION based on CLI usability studies]
- **Accidental False-Positive Risk with Wildcards**: If wildcard matching rules are too permissive, a human user might accidentally export a variable (e.g., `AIDER_THEME=dark` or `CURSOR_FONT=12`) that triggers agent mode unintentionally — [source: ASSUMPTION based on environment variable naming collision risks] (confidence: medium, assumption)
- **Upstream Churn**: AI vendors could change internal process flags across minor versions without notice (e.g. migrating from `CLAUDECODE` to an unexported internal channel) — [source: ASSUMPTION based on unversioned CLI agent internals]

## Gaps & Open Questions

- [NEEDS CLARIFICATION: Should the manifest `harnesses.toml` be bundled inside the package (`importlib.resources`) or loaded from `~/.git-shim/harnesses.toml`?]
- [NEEDS CLARIFICATION: Should wildcard matching be restricted strictly to prefix globs (`PREFIX_*`) rather than arbitrary glob expressions (`*SUFFIX` or `*SUBSTR*`) to prevent accidental matches?]
- [NEEDS CLARIFICATION: Should the discovery CLI command be named `git-shim doctor` (diagnostics + suggestions) or `git-shim detect` (detection-specific auditing)?]

## Sources

- `specs/001-git-author-shim/spec.md` (host: local repo, policy: allowlisted)
- `src/git_author_shim/agent_detection.py` (host: local repo, policy: allowlisted)
- `src/git_author_shim/config.py` (host: local repo, policy: allowlisted)
- Empirical strings and AST inspection of `@anthropic-ai/claude-code` binary runtime (host: local filesystem `C:\Users\devic\.proto\tools\node\globals\bin\claude.cmd`, policy: allowlisted)
- Empirical process environment inspection of live Oh My Pi worker sessions (host: local runtime environment, policy: allowlisted)
