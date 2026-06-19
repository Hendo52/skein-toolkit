# Spec: Odysseus Dashboard CRUD and Feedback Design (AT-1234)

**Date:** 2026-06-19
**Status:** Draft -- one genuine open design choice surfaced as OQ-297
rather than decided here.

## 1. Framing

Architect's framing (2026-06-18): "ponder what feedback we need to give,
how that's going to look, and what the CRUD lifecycle is." The dashboard
(AT-1220..1226) is for **monitoring, review, and control** -- chat remains
the primary **authoring** interface, per the dispatch architecture spec's
own framing. This document defines, per entity, which CRUD operations the
UI actually needs and what feedback/status it must surface at each
lifecycle stage.

## 2. AT (actionable task) rows

- **Create:** **Not in the UI.** `create_actionable_task` requires
  composing a real description/spec/exit-evidence/effort, which is exactly
  the kind of authoring a chat-driven agent does well and a quick UI form
  does badly. No "add new AT" control.
- **Read:** Yes -- list AT rows (status, tier, dependencies). Already
  partially exists; AT-1223 (configurable `_GLOBAL_DIR`) is a prerequisite
  for this to work across all 3 repos, not just Electron-Splines.
- **Update:** **Action-shaped, not free-text.** No raw description editing
  in the UI (that's a chat/direct-file-edit operation, where nuance can be
  articulated). The one UI-exposed state transition: **Dispatch** -- a
  button on a Ready, untiered-by-dependency AT row that calls
  `dispatch_coding_task(at_id, repo_root)`. This needs no free-text
  authoring (the AT row already has everything `dispatch_coding_task`
  needs), so it's a legitimate UI action, not authoring.
- **Delete:** **Not in the UI.** Removing an AT row is rare and
  consequential; a UI delete button risks an accidental click on something
  that should require the same deliberateness as creating it did.

## 3. OQ (open question) rows

- **Create:** **Not in the UI**, for the same reason as AT rows -- composing
  a well-formed OQ (>=2 lettered options, a preemptive answer, a
  reversibility tag, a precedent-search note, per ADR-011) is exactly the
  kind of reasoning a structured form does badly.
- **Read:** Yes -- list open OQs with their full question/options/context.
  This is the dashboard feature the architect most directly asked for
  (AT-1225).
- **Update / Resolve:** **Genuinely open -- see OQ-297 below.**
  `resolve_open_question(oq_id)`'s current mechanical behavior is "delete
  the row" -- it does not, on its own, capture *which* option was chosen or
  *why*. Every OQ resolution this session has had that reasoning captured
  because a chat-driven agent composed the changelog summary by hand. A
  literal "one-click resolve button" (AT-1225's own phrasing) would lose
  that, unless the UI also collects the choice and a reasoning note as part
  of resolving -- turning "one click" into a small form. This is the one
  real open design choice in this document.
- **Delete:** Only via resolve; no separate raw-delete action.

## 4. Coding-task job entities

- **Create:** The **Dispatch** action from S2 is this entity's create path
  -- triggering a job for an existing, already-fully-specified AT is not
  "authoring," so it's fine as a UI button (matches AT-1226's framing).
- **Read:** Yes -- list jobs with `job_id`, `at_id`, `status`, `model`,
  `branch_name`, matching `get_coding_task_status`'s existing return shape
  and `supervision-watcher.ps1`'s `codingTaskJobs[]` schema (AT-1232) so
  the dashboard and the supervisor are reading the same fields, not two
  independently-defined views of the same data.
- **Update:** Two real UI actions, both state transitions, neither free-text:
  - **Promote** -- calls `promote_coding_task(job_id)` for a `complete` job.
  - **Cancel** -- kills a `running` job's process tree
    (`dispatch_io.kill_job_process_tree`) for a job that looks stuck or
    was dispatched in error.
- **Delete:** Not needed as a separate action -- a promoted or cancelled
  job's worktree/branch cleanup already happens inside `promote_coding_task`
  /the cancel path itself.

## 5. Feedback/status surface, per lifecycle stage

Matches the job-state model already established (AT-1228/1233), not a new
vocabulary:

| Stage | UI should show |
|---|---|
| `Ready` (AT row, not yet dispatched) | A **Dispatch** button; nothing else needed. |
| `running` (job) | Model in use, elapsed time, a **Cancel** button. No live log streaming in v1 -- that's AT-1220's xterm.js spike, a separate, larger feature, not a CRUD requirement. |
| `complete` (job) | Recent commits (from `get_coding_task_status`'s existing output), a **Promote** button. |
| `failed` (job) | The log tail (already returned by `get_coding_task_status`) and, once AT-1233's degraded-mode question (OQ-294) resolves, the supervisor's `recommend_action` output (retry/restart_dependency/raise_oq) as a suggested next step -- not an auto-applied one. |
| `promoted` (job) | Merged SHA, target branch, timestamp -- a closed/historical record, no action buttons. |
| Open OQ | The full question text, options, and (per OQ-297's resolution) whatever the resolve interaction ends up requiring. |

## 6. What stays chat-only (explicit non-goal for the dashboard)

Authoring of any kind (new AT, new OQ, AT description edits, OQ option
text); anything in the risk framework's Tier 3 list
(`autonomous-dispatch-risk-framework.md`, AT-1235) -- force-push, branch/
tag deletion, CI/CD config changes, credential changes, branch-protection
changes, history rewrites, hook bypasses, `reset --hard`/`clean -f` outside
a dispatch worktree. The dashboard is read/monitor/control over an
already-defined task; it is not, and should not become, a second authoring
surface competing with chat.

## 7. Confirmation requirement for cost-bearing or destructive UI actions

Not a separate open question -- this just applies a standard this session
already established repeatedly in practice (the auto-mode classifier
correctly blocked unconfirmed dispatch calls, merges, and process kills
multiple times today). **Dispatch** (real model spend), **Promote** (merges
into the default branch), and **Cancel** (kills a real process) each need
an explicit confirmation step in the UI -- a second click or a confirm
dialog, not a bare single click that fires the action immediately. This
mirrors, rather than relaxes, the discipline already in effect for the
chat-driven path.

## 8. Open question surfaced

- **OQ-297:** Should resolving an OQ via the dashboard require capturing
  which option was chosen and a reasoning note (a small form), or is a bare
  "mark resolved" sufficient, with the actual decision/reasoning expected
  to live elsewhere (e.g. a follow-up chat message, or accepted as lost for
  UI-resolved OQs specifically)?
