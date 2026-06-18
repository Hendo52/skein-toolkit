# Spec: Odysseus Agentic Dispatch Architecture

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.4 (AI toolchain governance) -- with a caveat, see §9 |
| **Status** | Draft |
| **Date** | 2026-06-18 |
| **Source** | AT-1216 (dashboard redesign research), AT-1217 (skein/Odysseus merge research, referenced not resolved), architect chat session 2026-06-18 |
| **Agent** | `docs` |
| **Model** | Tier-R (this document); see per-AT annotations in §8 for implementation tiers |

---

## 1. What we are trying to do, and why

**What:** Make Odysseus the single chat-driven surface for the whole coding loop --
idea -> decomposition -> prior-art research -> AT/OQ creation -> queued async
implementation -> review of what came back -> merge -- without the architect
writing code by hand. Git stays the ground truth throughout; the architect's
primary interface to all of it is conversation, the same way this document's
own request was made.

**Why now:** Three concrete pressures converged in one session (2026-06-18):

1. **The planning machinery already exists but stops short of execution.**
   `create_actionable_task`, `create_open_question`, `resolve_open_question`,
   and the Decomposition Gate (`task-and-oq-authoring-standard.md` Part 3)
   already let chat turn a vague idea into tracked AT/OQ rows. Nothing then
   picks those rows up and runs them -- that step happens today only because
   a human (or, this session, Claude Code acting as a supervisor) manually
   invokes `run-cline.ps1` from outside Odysseus entirely. The loop is open,
   not closed.
2. **Manual supervision doesn't scale and isn't the stated goal.** This
   session's AT-1212/1213 dispatch work involved one human-in-the-loop agent
   (Claude Code) babysitting `cline` CLI invocations one at a time, watching
   for 429s, restarting stale servers, and reading logs by hand. That is the
   opposite of "chat is the primary way code is created" -- it is a
   real-time-supervised manual process wearing an automation costume.
3. **The capabilities already exist scattered across three places** (Skein
   MCP's tools, the CF-proxy orchestrator's step-dispatch/validator/OQ-escalation
   pattern, and Odysseus's dashboard/chat/model-browser), with no single
   product surface tying them together. Closing the loop is mostly wiring,
   not invention -- see §4.

**Out of scope (explicitly, per architect direction this session):**
- Forking VS Code, or building a rich in-editor agent UX. The goal is fleet
  management of async coding jobs, not an editor. See the prior-art survey
  policy (`task-and-oq-authoring-standard.md` Part 3 step 2a) -- Monaco and
  xterm.js (standalone packages) cover the review/observability needs this
  spec actually has; VS Code's unextracted workbench internals are not
  needed.
- Deciding whether skein-toolkit and Odysseus eventually merge into one repo.
  That is AT-1217's question. This spec assumes today's arrangement (two
  repos, Odysseus connects to Skein MCP as an external SSE tool source) and
  notes everywhere that assumption would change if AT-1217 lands differently.

---

## 2. Current state inventory (verified against code, 2026-06-18 -- not assumed)

| Capability | Exists? | Where |
|---|---|---|
| Chat creates AT rows | Yes | `create_actionable_task` (`local-mcp.py`), callable from Odysseus today via the existing Skein MCP connection |
| Chat creates/resolves OQ rows | Yes | `create_open_question` / `resolve_open_question` / `list_open_questions` / `get_open_question` (`local-mcp.py`) |
| Decomposition discipline | Yes | `task-and-oq-authoring-standard.md` Part 3, now with the prior-art survey step (added this session) |
| Spawning an actual coding agent against a repo | Yes, but **only from outside Odysseus** | `run-cline.ps1` (preflight via `toolchain-doctor.ps1`, `npx cline -P openai-compatible`), invoked manually |
| A job/run state model with status transitions | Yes, but scoped to **chat-turn orchestration**, not arbitrary AT dispatch | `~/.cf_proxy_orchestrator/*.json` (`status: running/halted/complete`, written by `local-mcp.py`'s multi-step detector -> planner pass -> step dispatch -> validator -> OQ-on-ambiguity pipeline) |
| A dashboard that reads job/task/OQ state | Yes, read-only, single-repo | `odysseus/routes/dashboard_routes.py` + `static/dashboard.html`; probes 2 hardcoded services + DB-registered MCP servers; `src/task_queue_reader.py` parses AT/OQ markdown tables but `_GLOBAL_DIR` is hardcoded to Electron-Splines only |
| Cost/spend data flowing into anything chat- or dashboard-visible | No | `~/.litellm/costs.jsonl` and `~/.cf_proxy_spend.json` exist on disk; nothing reads them into the dashboard yet (AT-1186 queued, not done) |
| A tool to trigger or poll a coding job from Odysseus chat | **No -- this is the actual gap** | n/a |
| Registered-repos concept (so the model knows the 3 repos exist without being told) | No native concept; system_prompt workaround verified working this session | `odysseus/routes/preset_routes.py`'s `system_prompt` field |

The honest summary: **the planning half of the loop is done, the execution
half is wired by hand, and the review half barely exists.** This spec is
about the middle and last thirds.

---

## 3. Target architecture

Three stages, with what's new marked:

```
INTAKE (exists)                  DISPATCH (new)                    REVIEW (new + existing)
chat -> create_actionable_task   dispatch_coding_task(at_id)        get_coding_task_status(job_id)
     -> create_open_question     -> resolves AT-<id> row            -> dashboard surfaces job list
     -> Decomposition Gate       -> spawns run-cline.ps1 logic         (extends existing orchestrator-
                                     as a non-blocking background       run reading, AT-1216 item 3)
                                     job                              -> chat can ask "what did AT-1218's
                                  -> persists state using the           job do" -> run_shell `git show
                                     SAME state-file shape already      <sha>` -> pasted back in chat
                                     proven for orchestrator runs       (no new tool needed for this part)
                                     (status running/halted/complete,
                                     reuses ~/.cf_proxy_orchestrator/
                                     directory and JSON shape)
```

### 3.1 Dispatch tool

New MCP tool in `local-mcp.py` (Skein MCP -- see §9 for why there, not
Odysseus-native, and why that's provisional):

```
dispatch_coding_task(at_id: int, repo_root: str) -> str
```

(No `model` parameter -- see the model-selection note below. Resolved
internally from the AT row's own `Model:` annotation.)

- Reads AT-`<at_id>`'s row from `ai-task-queue.md` (reuse the same row-lookup
  logic `ledger_io.py` already has for OQ blocks; AT rows don't yet have an
  equivalent `get_at_block`-style accessor -- needed as part of implementation).
- **Model selection (resolved 2026-06-18, second planning pass):** does not
  invent a new selection mechanism. Reads the target AT row's existing
  `Model:` annotation -- already a required field per
  `ai-model-selection-policy.md` §11 -- and resolves it through that policy's
  §7 decision rules, with a toolchain-doctor-health-aware fallback layered on
  top (this session found every tier flaky at a different point: Anthropic
  credit exhaustion, CF Workers AI capacity 429s, a local model hallucinating
  a tool call). **Naming caveat:** that policy names tiers Level-1/2/3; every
  AT row written to date (including this spec's own) uses Tier-R/C/M from
  `ai-task-queue.md`'s header instead -- a real drift, tracked as AT-1231,
  this tool's model-resolution code should use whichever naming AT-1231
  settles on, not invent a third mapping.
- **Working-tree precondition (resolved 2026-06-18):** refuses to start if
  the target repo has uncommitted changes (validator-at-the-boundary -- don't
  start an automated job from an ambiguous base state). Reports via the
  *existing* `create_open_question` escalation path, the same one every
  other model-blocked-by-ambiguity case uses today -- **not** a new
  "supervisor agent" triage layer. Whether such a layer should exist (and
  resolve some blockers automatically before they reach a human) is OQ-289,
  explicitly left open and explicitly not a blocker for this AT.
- **Repo-busy check (resolved 2026-06-18):** PID-liveness first (store the
  spawned process's PID in the job-state file; busy = PID still alive); a
  CB-24-style timestamp-staleness check as the fallback for the case the PID
  check can't resolve (e.g. PID reused after a restart). Mirrors, rather than
  duplicates, the staleness pattern already proven in
  `toolchain-doctor.ps1`'s `Test-OrchestratorRunActive`.
  **CB-25 (found 2026-06-18, live, not hypothetical):** when this tool needs
  to kill a job (timeout, cancellation, a future force-stop), use `taskkill
  /F /T /PID` (kills the whole process tree), never a single-process
  `Stop-Process`/`$proc.Kill()`. `run-cline.ps1`'s own timeout-kill used
  `$proc.Kill()` on the wrapping `cmd.exe`, which doesn't reach the actual
  `cline.exe` running downstream in a `type file | npx cline` pipeline --
  confirmed empirically: a "killed" job's `cline.exe` kept running
  unsupervised for the rest of that session, editing files no one reviewed,
  until caught by accident via a stray `git status`. Fixed in `run-cline.ps1`
  same day; `dispatch_coding_task`'s own kill path must use the same
  pattern, not reintroduce the bug.
- **Branch isolation mechanism (implementation detail, not a fresh OQ --
  OQ-286 already decided commits land on a branch; this is just how):**
  `git checkout -b` in the target repo's existing working directory would
  switch what that shared directory has checked out, colliding with anyone
  -- a human, or this very session -- working in that same directory at the
  same time. Use `git worktree add <path> -b at-<id>-dispatch` instead: a
  second, isolated working directory checked out to the new branch, leaving
  the primary working tree's checkout completely undisturbed. Cline runs
  against the worktree path (passed as `run-cline.ps1`'s `-RepoRoot`), not
  the original repo path. `promote_coding_task` (AT-1230) removes the
  worktree (`git worktree remove`) after merging.
- Resolves which repo the task targets. AT rows don't currently declare this
  explicitly (see AT-1216 item 7 -- multi-repo awareness) -- until that lands,
  require an explicit `repo_root` parameter (**OQ-288 resolved, Option A** --
  required argument as a stopgap until AT-1223's multi-repo AT awareness
  lands).
- **Serializes to one job at a time per repo (OQ-285 resolved, Option A).** A
  second `dispatch_coding_task` call against a repo with an already-running
  job is rejected (or queued -- implementation's choice, but must not run
  concurrently) rather than spawning a second Cline process against the same
  working tree.
- Spawns the **Cline CLI** (not the VS Code extension -- see §3.3) using the
  same invocation shape as `run-cline.ps1`, as a detached background process,
  and returns immediately with a job id. Must not block the calling chat turn
  for the job's full duration (this session observed real AT dispatches taking
  200-1200+ seconds).
- **Commits land on a dedicated branch (e.g. `at-<id>-dispatch`), never
  directly on the target repo's default branch (OQ-286 resolved, Option B --
  deviates from this spec's original preemptive answer).** Architect
  reasoning: unattended jobs aren't watched live regardless of concurrency, so
  a review/promote gate before the default branch matters even at the
  one-job-at-a-time concurrency OQ-285 settled on. Promotion is §3.2a's job,
  not this tool's.
- Writes a job-state JSON file in its **own directory, separate from
  `~/.cf_proxy_orchestrator/`** (OQ-287 resolved, Option B) -- chat-turn
  orchestration steps and 20+ minute coding jobs are different enough that
  sharing a directory risked confusing `toolchain-doctor.ps1`'s
  `Test-OrchestratorRunActive` staleness logic (fixed this session, CB-24).

### 3.2 Status tool

```
get_coding_task_status(job_id: str) -> str
```

Reads the job-state file, returns status, elapsed time, and (once complete)
the commit SHA (on the job's dedicated branch, not yet on the default branch
-- see §3.2a), and a short diff summary (`git show --stat`).

### 3.2a Promote tool (added per OQ-286's resolution)

```
promote_coding_task(job_id: str) -> str
```

The explicit human-approval step OQ-286 requires: confirms the job completed
successfully (rejects -- does not silently no-op -- if the job is still
running or failed), then merges/fast-forwards the job's dedicated branch into
the target repo's default branch, updating job state to reflect promotion.
The architect reviews via `get_coding_task_status`'s diff summary (or the
richer Monaco diff view, §3.4/AT-1221) before calling this -- review is a
chat action ("promote AT-1218's job"), not a separate UI flow, matching the
spec's "chat is the primary interface" goal throughout. Tracked as AT-1229.

### 3.2b Crash/hang detection (resolved 2026-06-18, second planning pass)

Chosen: a watcher process, not status-tool polling -- but extend the
*existing* `supervision-watcher.ps1` (AT-1168) rather than build a second
one. That script already polls AT row status, orchestrator state files, and
Cline process liveness on a fixed interval independent of any session, and
already produces exactly the `stuckTaskCount`/`stuck`-per-item shape this
need maps onto. It just doesn't know about `dispatch_coding_task`'s job-state
directory yet, because that directory didn't exist before this spec. Tracked
as AT-1232: add job entries to `supervision-status.json` alongside the
existing `tasks[]`/`orchestratorStates[]` arrays, using the same
PID-liveness-plus-staleness logic as §3.1's repo-busy check.

### 3.3 Why Cline CLI, not the VS Code extension

Found this session (`project_ai_toolchain` memory, 2026-06-12 entry): the
VS Code Cline extension's Checkpoints feature snapshots the workspace via a
shadow git repo at each step and can silently revert tracked files in the
shared working tree on a Checkpoint restore -- without touching the real
repo's `HEAD` -- producing a symptom indistinguishable from a toolchain bug
(committed work intact in git history, working tree reverted underneath a
concurrently running agent). Any design with multiple async jobs touching
the same repo makes this collision more likely, not less. The CLI path
(`npx cline -P openai-compatible`, no VS Code panel involved) doesn't carry
this risk and is the existing, proven invocation (`run-cline.ps1`).

### 3.4 Review

No new tool needed for the common case: once a job's state file has a commit
SHA, `git show <sha>` via the existing `run_shell` tool surfaces the diff
directly in chat. The dashboard (AT-1216 item 3) lists job status for
at-a-glance monitoring. A richer diff *view* (syntax-highlighted, side-by-side)
is where Monaco's diff-editor mode (Adopt disposition, AT-1216 item 6) earns
its place -- but plain `git show` in chat is sufficient for v1 and should not
be blocked on a UI spike landing first.

---

## 4. Substrate roles (Cloudflare / vast.ai / Odysseus) -- do not conflate these

| Substrate | Role today | Possible future role | Not a candidate for |
|---|---|---|---|
| **Cloudflare Workers AI** | Serverless model inference backend (`cf/*` models via LiteLLM) | Same -- serverless has no persistent process or filesystem | Hosting the dispatch loop or any agent process itself, in any version of this design |
| **vast.ai (rented GPU)** | Rented inference capacity for local-style models (existing devserver scripts) | Could host the *agent process* itself (multiple Cline jobs in parallel without saturating the architect's own machine) -- this is new infrastructure (the rented box needs a repo checkout/sync), not a config change, and is its own research question | Assuming this "just works" by analogy with its current inference role -- it doesn't; the integration is structurally different (process hosting vs. model serving) |
| **Local machine** | Runs LiteLLM, Skein MCP, and (today) every Cline CLI invocation | Same, likely permanently for at least the first job slot | n/a |

---

## 5. Concurrency and review-model questions -- resolved 2026-06-18 (OQ-285, OQ-286)

Both answered by the architect; see §3.1/§3.2a for the resulting design and
§7 for the full resolution record:

- **OQ-285:** `dispatch_coding_task` serializes to one job at a time per repo
  (Option A).
- **OQ-286:** commits land on a dedicated branch, promoted to the default
  branch only via the new `promote_coding_task` tool (Option B -- this
  deviates from the preemptive answer below; kept for the record). Decided
  independently of OQ-285's answer, not contingent on concurrency existing --
  the architect's reasoning was that unattended jobs aren't watched live
  regardless of how many run at once.

---

## 6. Workspace registration (AT-1216 item 9, included here for completeness)

No native "registered repos" concept exists in Odysseus (`core/` has no
Workspace/Project model). Verified working today with zero new code: list
the repo paths in a preset's `system_prompt` (`routes/preset_routes.py`).
Whether this becomes a small dedicated config (e.g. a `workspaces.json` read
at startup and injected into context) instead of a documented preset
template depends on how much friction the manual version causes in practice
-- recommend shipping the documented-preset version first (effectively zero
implementation cost) and only build dedicated config if that proves
insufficient.

---

## 7. Open Questions spawned by this spec -- all resolved 2026-06-18

Promoted to live rows (OQ-285..288) and resolved the same day; the rows
themselves are deleted from `architect-open-questions.md` per this project's
resolved-row policy (delete + changelog entry, not annotate-in-place). Record
kept here for spec-local traceability:

1. **Job concurrency model (OQ-285).** Options: **(A)** serialize to one job
   at a time per repo. **(B)** allow N concurrent jobs from day one.
   **Resolved: Option A.**
2. **Review/merge gate (OQ-286).** Options: **(A)** keep today's
   direct-to-main commit pattern. **(B)** introduce a staging-branch-plus-promote
   step now. **Resolved: Option B** (deviates from this spec's original
   preemptive answer of A) -- see §5 for the architect's reasoning. Spawned
   AT-1229 (`promote_coding_task`).
3. **Job-state directory (OQ-287).** Options: **(A)** reuse
   `~/.cf_proxy_orchestrator/`. **(B)** give coding-task jobs their own
   directory. **Resolved: Option B.**
4. **AT row repo targeting (OQ-288).** Options: **(A)** require an explicit
   `repo_root` argument to `dispatch_coding_task` until AT-1223 lands.
   **(B)** block `dispatch_coding_task` entirely until multi-repo AT
   awareness exists. **Resolved: Option A.**

### 7.1 Supervisor-agent escalation -- resolved 2026-06-18 (OQ-289)

5. **Supervisor-agent escalation (OQ-289).** Should blocking conditions (e.g.
   §3.1's working-tree precondition) route through a new automated
   "supervisor agent" triage layer instead of straight to a human-facing OQ?
   **Resolved: Option B, refined and specified** (the architect supplied the
   missing specification this OQ originally lacked) -- see §3.5 for the
   resulting two-tier design. AT-1228 still does not block on this; the
   working-tree precondition continues to use the plain OQ path until AT-1233
   lands.

### 3.5 The two-tier supervisor design (OQ-289's resolution)

The apparent tension in the architect's own framing -- "use the most capable
model for judgment calls" vs. "cannot afford to waste tokens" -- resolves to:
**invoke the expensive model rarely, not the cheap model constantly.**

- **Tier 1 (cheap, continuous):** `supervision-watcher.ps1` (AT-1168,
  extended by AT-1232) polls mechanically on a fixed interval. A PowerShell
  script costs nothing per check, independent of any LLM session. It already
  produces exactly the needed signal: `stuckTaskCount`, and per-job `status`/
  `stuck` flags.
- **Tier 2 (expensive, event-driven):** the supervisor LLM (the most capable
  model available -- the architect's reasoning: the decision of *which*
  corrective action fits a given failure is genuinely hard to template, so
  this is not where to economize on capability) sleeps between checks. It
  wakes on a schedule -- `ScheduleWakeup` for a live conversation session,
  a standing `CronCreate` routine for the fully-unattended case -- reads
  **only** the Tier 1 log (`supervision-status.json`), and if
  `stuckTaskCount == 0`, goes back to sleep immediately. This is the actual
  cost-control mechanism: a wake cycle with nothing to act on costs one
  cheap file read, not a full context re-derivation.
- **Decision menu, exercised only on a flagged event** (mirrors
  troubleshooting moves already used manually this session): **(1) retry**
  -- re-dispatch the same AT, optionally with backoff (CB-23's pattern).
  **(2) restart a dependency** -- the toolchain itself is stale/unhealthy,
  run `toolchain-doctor.ps1` first (CB-15/CB-24's pattern). **(3) revert**
  -- the job's branch made a mess, discard it and re-dispatch clean.
  **(4) stop and raise an OQ** -- the failure doesn't match any of the
  above, needs an actual architect decision. Tracked as AT-1233: build the
  wake mechanism and document the triage logic for choosing between these
  four, not just the mechanism itself.

---

## 8. AT tasks spawned by this spec -- live as AT-1219..1233

All 14 tasks below are live Intake rows in `ai-task-queue.md`. AT-1219..1228
landed with the first planning pass; AT-1229 (promote tool) was spawned by
OQ-286's resolution; AT-1231/1232 (tier-naming reconciliation, watcher
extension) were spawned by the second planning pass on AT-1228 itself;
AT-1233 (supervisor wake-loop) was spawned by OQ-289's resolution (§3.5).

| # | Task | AT ID | Effort | Depends on |
|---|------|-------|--------|------------|
| 1 | `dispatch_coding_task(at_id, repo_root)` MCP tool -- serializes per repo (PID-liveness + staleness fallback), commits to a dedicated branch (not main), own job-state directory, requires `repo_root`, resolves model from the AT row's existing `Model:` annotation | AT-1228 | Medium | AT-1231 (naming) |
| 2 | `get_coding_task_status(job_id)` MCP tool | AT-1227 | Small | #1 |
| 11 | `promote_coding_task(job_id)` MCP tool (spawned by OQ-286 Option B) | AT-1229 | Small-Medium | #1 |
| 12 | Extend `supervision-watcher.ps1` to poll coding-task job state (S3.2b) | AT-1232 | Small | #1 |
| 13 | Reconcile Tier-R/C/M vs. Level-1/2/3 naming between `ai-task-queue.md` and `ai-model-selection-policy.md` | AT-1231 | Tiny | -- (Done) |
| 14 | Supervisor wake-loop + four-item decision menu (S3.5) | AT-1233 | Medium | AT-1232 |
| 3 | Extend `dashboard_routes.py`/`dashboard.html` to list coding-task jobs | AT-1226 | Small-Medium | #1 |
| 4 | Dedicated OQ UI with one-click resolve | AT-1225 | Medium | -- |
| 5 | Cost chart + monthly spend projection | AT-1224 | Small-Medium | AT-1186 |
| 6 | `task_queue_reader.py`'s `_GLOBAL_DIR` -> configurable list | AT-1223 | Small | -- |
| 7 | Workspace-registration preset template doc | AT-1222 | Tiny | -- |
| 8 | Monaco diff-editor spike | AT-1221 | Medium | #1, #2 |
| 9 | xterm.js live-terminal-streaming spike | AT-1220 | Medium | #1 |
| 10 | Resolve the SR-1.4 taxonomy mismatch (§9) | AT-1219 | Small | -- |

**Running count: 5 OQs total (all resolved) + 14 ATs (3 Done: AT-1219,
AT-1222, AT-1231)** -- up from the first pass's 4+11 estimate. This is the
recursive-convergence pattern `task-and-oq-authoring-standard.md` Part 3
describes working as intended: each planning pass on the central tool
(AT-1228) surfaced real prior art (the model-selection policy, the
supervision watcher) and one genuinely new open question (OQ-289, resolved
the same day once the architect supplied the missing specification), not a
sign the plan was wrong. Expect at least one more pass once AT-1228 is
actually implemented and run against a real AT.

---

## 9. SR taxonomy caveat

This document is filed under skein-toolkit's `foundation/SR-1.4-ai-guidance/`
directory because that's where every other operational AI-ops spec already
lives (`agentic-coding-governance.md`, `odysseus-convergence-phased-plan.md`,
etc.) -- but `design-goals.md`'s actual SR-1.4 definition (still only in
Electron-Splines, never migrated) describes ES's own Copilot agent pipeline
(`priorwork -> rnd -> spec -> unittest -> impl -> meshqa -> docs`, 12 agent
definitions) -- a different thing entirely. The folder name was carried over
mechanically by the OQ-279 migration (AT-1201) without reconciling what SR-1.4
actually means in each repo. This spec uses the existing location for
consistency with everything else already filed there, and Task #10 above
tracks the actual fix (skein-toolkit needs its own design-goals.md / SR
numbering, independent of Electron-Splines's).

---

## 10. Relationship to AT-1217

AT-1217 (skein-toolkit <-> Odysseus merge depth) is referenced, not answered,
throughout this spec. Every design choice above assumes today's arrangement
(two repos, MCP-over-SSE connection) holds. If AT-1217 concludes that Skein's
MCP tools should become native Odysseus capabilities, §3.1's "why Skein MCP"
placement would need revisiting -- but the tool's *behavior* (job state,
CLI-not-extension, resolve AT rows) would not change, only where it's
implemented. This is the concrete reason §3 was written behavior-first
rather than location-first.
