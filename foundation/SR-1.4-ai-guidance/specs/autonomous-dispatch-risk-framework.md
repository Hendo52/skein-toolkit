# Spec: Autonomous Dispatch Risk Framework (AT-1235)

**Date:** 2026-06-19
**Status:** Draft -- OQ-296 resolved 2026-06-20 (Option B: automated/scheduled push via AT-1247). OQ-295 remains open.

## 1. Framing

Architect's framing (2026-06-18): think like a paranoid sysadmin securing
against negligent vibe coders, **not** an approval bureaucracy. Explicitly
avoid a heavyweight per-action permission-gating system. Invest instead in
git discipline, CI/CD gates, and structural/physical protections (backups,
audit logs, branch-protection barriers to the default branch).

This framework folds in rather than re-invents what already exists:
- AT-1228/1230's branch-then-promote pattern -- a dispatched coding job
  never touches the default branch directly; it lands on an isolated
  worktree branch, reviewed (by a human or, per AT-1233's decision menu, a
  supervisor) before `promote_coding_task` merges it.
- CLAUDE.md's existing Git Safety Protocol and Dirty Working Tree Severity
  Model -- already cover destructive-command discipline for interactive
  sessions; this framework extends the same posture to autonomous dispatch.
- The commit-hygiene size guardrail (>30 files / >500 insertions stops and
  asks) -- already a structural circuit-breaker, not a per-action gate.

## 2. Risk-tier classification

### Tier 1 -- Safe to fail (freely autonomous, no special handling needed)

Docs/markdown edits (AT/OQ ledgers, specs, READMEs); test code; commits on
an isolated dispatch-branch worktree (never main); research/evaluation
artifacts; read-only operations (`Read`, `Grep`, running a test suite);
creating new files in a clearly-scoped location.

**Why these are Tier 1:** every one of them is fully recoverable via `git
revert`/`git worktree remove`/deleting a file, and none of them can affect
anything outside this repo's own history. The branch-then-promote pattern
already makes the *majority* of a coding-task dispatch's actual file-editing
work Tier 1 by construction -- the risk only enters at promotion.

### Tier 2 -- Bounded risk (autonomous OK, but needs the recoverability this
framework names explicitly, not implicit trust)

Code changes to application logic (the test suite is the safety net, not a
formality); config changes (`litellm_config.yaml` and similar -- reversible
via `git revert`); installing a new dependency (reversible, but see S3
below on supply-chain exposure); **merging a dispatch branch into the
default branch** (`promote_coding_task`) -- this is the one Tier 2 action
that does touch the default branch, which is why AT-1230's review-before-
promote gate exists specifically for it.

### Tier 3 -- Real damage potential (must never be autonomous, regardless of
which model or supervisor tier is involved)

Force-push to any shared branch; deleting a branch or tag on the remote;
modifying CI/CD pipeline configuration (`.github/workflows/*` or
equivalent) -- this can silently weaken the very gates this framework
relies on; modifying any file containing credentials/secrets, or any
`.env`-pattern file; modifying GitHub branch-protection settings themselves
(guard the guards); rewriting already-pushed git history (`rebase -i`,
amending a pushed commit); bypassing git hooks (`--no-verify`,
`--no-gpg-sign`); `git reset --hard`/`git clean -f` against a working
directory that isn't the dispatch tool's own isolated worktree.

This list is deliberately short and bright-line, per the architect's
explicit framing -- the goal is a small set of *structurally prevented*
actions (S3), not an approval workflow that has to evaluate every action
against a sprawling matrix.

## 3. Concrete recommendations

### 3.1 Backups

Git itself, pushed to a remote, *is* the backup -- provided pushes
actually happen regularly. A local-only repo is a single point of failure
(disk/laptop failure loses all history). Job-state JSON files and
orchestrator logs (`~/.coding_task_dispatch/`, `~/.cf_proxy_orchestrator/`)
are intentionally **not** git-tracked and therefore **not** backed up --
this is an accepted, named risk, not an oversight: they're ephemeral
operational detail, and the actual durable record of what a dispatch did
is the commit it produced plus that commit's message (this session's own
commit-message discipline -- citing real evidence, real test counts, real
file paths -- already functions as the audit trail; see S3.2).

**RESOLVED (2026-06-20, Option B via AT-1247):** Pushing to the remote is now automated via `docs/scheduled-git-push.ps1`, a Windows Scheduled Task that runs `git push` across Electron-Splines, skein-toolkit, and odysseus every 4 hours. The script skips repos in transient states (rebase, merge, bisect, cherry-pick, revert) and relies on git's own non-fast-forward refusal as the safety boundary -- it never passes `--force` or any history-rewrite flag.

### 3.2 Audit logging

Already substantially satisfied by existing practice, named explicitly here
rather than left implicit: every `dispatch_coding_task` run writes a
job-state JSON (model, timestamps, PID, branch) and a full log file; every
landed change has a commit message that (per this session's own demonstrated
pattern) cites the real evidence behind it. **Recommendation:** keep doing
this -- no new logging mechanism is needed. The one gap worth naming: job-
state JSON/log files get no long-term retention policy (they're just files
on disk, not rotated or archived). Given they're explicitly ephemeral
(S3.1), this is acceptable as-is; revisit only if disk usage or a real need
for historical job analysis becomes a problem.

### 3.3 GitHub branch-protection settings for the default branch

Concrete, low-cost, high-value settings to enable on the default branch of
any repo a coding-task dispatch can target (Electron-Splines, skein-toolkit,
the `odysseus` fork):
- **Disallow force-push.** Structurally prevents the single most
  catastrophic accidental-or-buggy-automation outcome (history rewrite on
  the branch everything else is built on).
- **Disallow branch deletion.** Same reasoning, for the deletion case.
- **Require status checks to pass before merging** -- if/when promotion
  moves to a PR-based flow (see OQ-295 below); not yet applicable to
  today's local-merge `promote_coding_task` implementation.

**Not recommending right now, pending OQ-295's resolution:** "require a pull
request before merging." Enabling this today would break
`promote_coding_task`'s current local-merge implementation outright (a
direct push to a PR-required branch is rejected by GitHub) -- this is
exactly the architectural fork OQ-295 exists to resolve before any branch-
protection change that touches it.

**Action needed, not taken here:** actually enabling branch-protection
settings is a real, external, security-relevant change to a shared system
(visible to anyone with repo access, consequential if misconfigured) --
this framework recommends it but does not enable it unilaterally. The
architect should enable "disallow force-push" and "disallow branch
deletion" directly (GitHub repo Settings -> Branches -> Branch protection
rules), or explicitly ask an agent to do it via `gh api` with that scope
named.

### 3.4 The short list of actions requiring explicit human action

Identical to the Tier 3 list in S2 -- deliberately the same list, not a
separate, longer one. Re-stated here as the framework's actual operational
answer to "what needs a human, not an approval matrix":

1. Force-push to any shared branch.
2. Delete a branch or tag on the remote.
3. Modify CI/CD pipeline configuration.
4. Modify any credentials/secrets file.
5. Modify branch-protection settings themselves.
6. Rewrite already-pushed git history.
7. Bypass git hooks.
8. `git reset --hard`/`git clean -f` outside the dispatch tool's own
   isolated worktree.

Everything else in this framework's Tier 1/Tier 2 classification is fair
game for autonomous dispatch, with the existing branch-then-promote pattern
and commit-hygiene guardrail as the structural safety net -- not a per-
action permission check.

## 4. Open questions surfaced (not decided in this document)

- **OQ-295:** Should `promote_coding_task` move to a GitHub-PR-based review
  flow now (in anticipation of enabling "require pull request" branch
  protection), or keep today's local-merge implementation until branch
  protection actually requires otherwise?
- **OQ-296:** ~~Should pushing to the remote (the actual backup mechanism per S3.1) be automated/scheduled, given the architect's own stated forgetfulness, or remain a manual habit?~~ **RESOLVED 2026-06-20 (Option B):** See `docs/scheduled-git-push.ps1` and AT-1247.

## 5. Explicit non-goal

This framework does not propose a per-action approval system, a permission
matrix, or any mechanism that requires a human to approve each individual
dispatch action. The architect's own framing is the test for any future
addition to this document: does it look like a paranoid sysadmin's
structural defenses (backups, branch protection, audit trails), or does it
look like an approval bureaucracy? Only the former belongs here.
