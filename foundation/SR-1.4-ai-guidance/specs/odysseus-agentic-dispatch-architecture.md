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
dispatch_coding_task(at_id: int, model: str = "cf/kimi-k2.6") -> str
```

- Reads AT-`<at_id>`'s row from `ai-task-queue.md` (reuse the same row-lookup
  logic `ledger_io.py` already has for OQ blocks; AT rows don't yet have an
  equivalent `get_at_block`-style accessor -- needed as part of implementation).
- Resolves which repo the task targets. AT rows don't currently declare this
  explicitly (see AT-1216 item 7 -- multi-repo awareness) -- until that lands,
  require an explicit `repo_root` parameter or infer it from the `Spec / Issue`
  column's file paths.
- Spawns the **Cline CLI** (not the VS Code extension -- see §3.3) using the
  same invocation shape as `run-cline.ps1`, as a detached background process,
  and returns immediately with a job id. Must not block the calling chat turn
  for the job's full duration (this session observed real AT dispatches taking
  200-1200+ seconds).
- Writes a job-state JSON file in `~/.cf_proxy_orchestrator/` (or a sibling
  directory if conflating "chat-turn orchestration" and "AT dispatch" job
  state under one directory turns out to confuse the existing staleness
  tooling -- implementation should check `toolchain-doctor.ps1`'s
  `Test-OrchestratorRunActive` staleness logic, fixed this session, doesn't
  mistake a long-running coding job for an abandoned chat-orchestration run).

### 3.2 Status tool

```
get_coding_task_status(job_id: str) -> str
```

Reads the job-state file, returns status, elapsed time, and (once complete)
the commit SHA and a short diff summary (`git show --stat`).

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

## 5. Concurrency and review-model questions (raised here, not resolved)

Two questions this spec deliberately leaves open rather than guesses at,
because the wrong guess is expensive to unwind once jobs are actually
running concurrently against shared repos:

- **OQ (draft, see §7):** should `dispatch_coding_task` serialize to one job
  at a time per repo initially, or allow N concurrent jobs from day one?
- **OQ (draft, see §7):** does the existing direct-to-main commit pattern
  (used throughout this session, and the project's general practice) remain
  correct once concurrent jobs are possible, or does that threshold require
  a staging-branch-plus-promote step?

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

## 7. Draft Open Questions spawned by this spec

These are staged here in draft form; promoting them to live rows in
`architect-open-questions.md` is part of this AT's exit evidence (see AT-1216).

1. **Job concurrency model.** Options: **(A)** serialize to one job at a time
   per repo (simplest, avoids the git-conflict and Checkpoint-collision risk
   classes entirely). **(B)** allow N concurrent jobs from day one (matches
   the "fleet management" framing more literally, but multiplies every
   shared-state risk found this session). Preemptive answer: **A** -- ship
   the simplest version that proves the loop closes end-to-end; revisit only
   once a real backlog of Ready ATs makes serialization the bottleneck, not
   before.
2. **Review/merge gate.** Options: **(A)** keep today's direct-to-main commit
   pattern. **(B)** introduce a staging-branch-plus-promote step once jobs
   run unattended. Preemptive answer: **A** for now, explicitly re-open this
   the moment OQ-1 above is answered **B** (concurrency and the merge gate
   are coupled -- a staging step matters far more once two jobs could commit
   to the same repo near-simultaneously).
3. **Job-state directory.** Options: **(A)** reuse `~/.cf_proxy_orchestrator/`
   for coding-task jobs too. **(B)** give coding-task jobs their own
   directory to avoid confusing the chat-turn-orchestration staleness logic
   (`toolchain-doctor.ps1`'s `Test-OrchestratorRunActive`, fixed this
   session) with long-running coding jobs that legitimately stay "running"
   for 20+ minutes. Preemptive answer: **B** -- the two concepts are
   different enough (chat-turn steps vs. multi-minute coding jobs) that
   sharing a directory risks exactly the kind of staleness-detection
   confusion this session spent real effort fixing.
4. **AT row repo targeting.** Options: **(A)** require an explicit
   `repo_root` argument to `dispatch_coding_task` until AT-1216 item 7 lands.
   **(B)** block `dispatch_coding_task` entirely until multi-repo AT
   awareness exists. Preemptive answer: **A** -- don't let a sequencing
   accident block the higher-value tool; an explicit argument is a one-line
   stopgap.

---

## 8. Draft AT tasks spawned by this spec

Staged here; adding these as live Intake rows in `ai-task-queue.md` is part
of this AT's exit evidence.

| # | Task | Effort | Depends on |
|---|------|--------|------------|
| 1 | Add `dispatch_coding_task(at_id, repo_root, model)` MCP tool to `local-mcp.py`, reusing `run-cline.ps1`'s invocation shape and a new job-state directory (OQ-3 above) | Medium | OQ-1..4 above |
| 2 | Add `get_coding_task_status(job_id)` MCP tool | Small | #1 |
| 3 | Extend `dashboard_routes.py`/`dashboard.html` to list coding-task jobs alongside existing orchestrator runs (AT-1216 item 3) | Small-Medium | #1 |
| 4 | Add a dedicated OQ UI to the dashboard with a one-click resolve calling `resolve_open_question` (AT-1216 item 1) | Medium | -- |
| 5 | Add a cost chart + monthly spend projection reading `~/.litellm/costs.jsonl` and `~/.cf_proxy_spend.json` (AT-1216 item 2; reconcile with already-queued AT-1186) | Small-Medium | AT-1186 |
| 6 | Make `task_queue_reader.py`'s `_GLOBAL_DIR` a configurable list instead of a single hardcoded path (AT-1216 item 7) | Small | -- |
| 7 | Document the workspace-registration preset template (§6) -- no new code, just a documented, copy-pasteable preset | Tiny | -- |
| 8 | Monaco diff-editor spike for job review (AT-1216 item 6, Adopt disposition) | Medium | #1, #2 |
| 9 | xterm.js live-terminal-streaming spike for in-flight job output (AT-1216 item 6, Adopt disposition) | Medium | #1 |
| 10 | Resolve the SR-1.4 taxonomy mismatch (§9): give skein-toolkit's AI-ops content its own SR identity instead of borrowing Electron-Splines's SR-1.4 (which actually means ES's own Copilot agent pipeline) | Small | -- |

**Rough count: 4 draft OQs + 10 draft ATs.** Expect this to grow on the next
Decomposition Gate pass once #1 specifically gets implemented -- a tool this
central usually surfaces its own sub-ambiguities once real AT rows are run
through it (the recursive-convergence pattern `task-and-oq-authoring-standard.md`
Part 3 describes is the expected shape here, not a sign the plan was wrong).

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
