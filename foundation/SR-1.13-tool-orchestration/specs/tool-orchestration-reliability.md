# Spec: Tool Orchestration Reliability

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.13 (Tool orchestration) |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | `agent-harness-reliability-standard.md` (SR-1.4, the cross-cutting tier review this spec splits out from), AT-1196/1197 dispatch incidents, external research (cited inline) |
| **Agent** | `docs` |
| **Model** | Tier-C |

---

## 1. Scope

Owns whether a tool call a dispatched agent issues actually gets executed,
its result correctly returned, and the executing process's lifecycle
correctly torn down -- regardless of which model issued the call. Does not
own which model runs (SR-1.4) or agent-role/delegation semantics (SR-1.5).

## 2. Confirmed-good existing practice

External research is explicit: "never let the LLM call tools directly...
the harness validates the schema, checks permissions, executes, and
injects the result back" (Faros, "Harness Engineering," 2026). This
project already does this correctly by construction -- `dispatch_coding_task`
never lets a model execute anything directly; Cline's own tool-execution
layer is the validated intermediary, and our harness's job is making sure
*that* layer gets a fair, correctly-configured run (the rest of this spec).

## 3. Requirements

### TOOL-1 (= master spec REQ-4): Dispatch prompts must be repo-agnostic

A prompt template usable against more than one repo must not assert
file paths, section names, or conventions specific to one consuming repo.
**Status: Implemented 2026-06-20.** See master spec REQ-4 for the AT-1196
incident this was found from.

### TOOL-2 (= master spec REQ-5): AT-row file-path references must be repo-target-relative, not Electron-Splines-relative

An AT row's exit-evidence output path must be written relative to the
*target* repo's own root, never as `../skein-toolkit/...` -- that
convention only resolves correctly when read from Electron-Splines itself,
and resolves to the wrong location entirely when read from inside an
isolated dispatch worktree (a sibling directory of the real checkout, not
a subdirectory). **Status: Found 2026-06-20 (AT-1196). Worked around
per-row since (AT-1197 uses the corrected form). Not yet enforced
structurally** -- see AT-1248 (lint/validator for this).

### TOOL-3 (= master spec REQ-6): A job's process tree must be verifiably terminated before its state is treated as terminal

No process whose command line references a job's worktree path may remain
alive once that job reaches a terminal status. **Status: Found 2026-06-20,
reproduced three times in one session (100% reproduction rate across every
dispatch attempted today). Not yet implemented** -- see AT-1249.
`kill_job_process_tree`'s PID-tree kill cannot catch this case: by the time
a job is terminal, the wrapper script (the intermediate parent) has often
already exited, re-parenting its child outside that PID's tree. The fix
needs a command-line-match search, not PID lineage.

### TOOL-4: Worktree/branch isolation must remain collision-free under concurrent dispatch

Per the parallel-dispatch relaxation (`odysseus-agentic-dispatch-architecture.md`
§3.1, 2026-06-20): two different AT-ids dispatched concurrently against the
same repo must never collide on worktree path or branch name. **Status:
Implemented and verified 2026-06-20** -- every worktree path and branch
name is derived from `at_id` (`dispatch_branch_name`), and concurrent `git
worktree add` against the same repo was directly tested safe (`git fsck
--full` clean after two simultaneous calls). The one real remaining
collision risk -- the *same* AT-id dispatched twice concurrently -- is
still blocked by `find_busy_job_for_repo`'s per-(repo, at_id) check.

## 4. AT tasks spawned

- AT-1248 (REQ-5/TOOL-2 enforcement: output-path lint)
- AT-1249 (REQ-6/TOOL-3 implementation: command-line-match process cleanup)

## 5. Relationship to other SRs

- SR-1.4 owns which model runs; this SR owns whether its tool calls survive
  to completion regardless of which model issued them.
- SR-1.16 (Guardrails) owns retry/timeout *policy*; this SR owns the
  *mechanics* of the process being retried (spawn, monitor, kill).
