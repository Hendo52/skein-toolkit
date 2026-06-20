# Spec: Verification Loop Reliability

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.14 (Verification loops) |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | `agent-harness-reliability-standard.md` (SR-1.4), CB-8/CB-11 (validator false-positives), external research (cited inline) |
| **Agent** | `docs` |
| **Model** | Tier-C |

---

## 1. Scope

Owns how a dispatched task's success or failure is actually *determined*
-- not the action menu chosen in response (SR-1.12's coordination
protocol), the verdict itself. A wrong verdict here feeds a wrong decision
everywhere downstream.

## 2. Confirmed-good existing practice, now externally corroborated

External research (DEV Community, "AI coding agents lie about their work")
states plainly: agents "generate completion language as part of their
output pattern regardless of the actual state of the codebase" -- a model
will claim success in its own text while the actual artifact is empty or
broken. This is not a hypothetical for this project: today's qwen2.5-coder:7b
dispatch (AT-1196, attempt 1) produced a response that read like a
completed tool call but corresponded to zero real files or commits.

`get_coding_task_status`'s existing design already does the right thing by
construction -- it checks **real git state** (commits on the job's branch,
diff against the base branch), never the model's own claimed-success text.
This is exactly the "outcome-based verification" the research names as the
correct countermeasure, arrived at independently (via CB-8/CB-11's
validator work) before this research was done.

## 3. Requirements

### VERIFY-1: Verification must always check independently-observable evidence, never the model's own self-reported completion claim

**Status: Implemented, predates this spec** (`get_coding_task_status`'s
commit-diff-based check; CB-11's read-only-step false-positive fix).
Formalized here as a standing requirement so it survives as a checked
property rather than an accidental design choice: any *new* verification
logic added to this harness must be checked against this requirement
before being accepted.

**Corroborating evidence this generalizes beyond dispatched jobs
(2026-06-20, odysseus, interactive Cline session, not `dispatch_coding_task`):**
a task to fix Odysseus's launcher ended with `attempt_completion` declaring
"Done. I fixed the two root causes..." and committing that claim --
*before the launcher had ever been run.* It crashed immediately on the
very next command (wrong Python interpreter). No harness consumed this
claim automatically (a human read it directly), so this incident is the
mirror image of VERIFY-1's own rationale: the requirement here protects a
*consumer* from trusting a self-reported claim; the analogous fix for an
interactive session is producer-side discipline (added to `.clinerules`
in both Electron-Splines and a newly-created one for odysseus, which had
none at all) -- run the actual change at least once before claiming it
works, regardless of which side of the claim you're on.

### VERIFY-2 (= master spec REQ-7): Every real incident produces a regression test in the same commit as its fix

**Status: Already the de facto practice all session** -- formalized here
because it is itself a verification-loop property (the test IS the
independently-observable evidence that the fix actually addresses the
reported failure, not just a plausible-sounding patch).

### VERIFY-3: A validator's false-positive rate must be checked against a real captured failure, not assumed correct from reading the code

**Status: Already the practice** -- CB-11's own fix was verified against
a real captured job log (`at1230-184de386`), not a synthetic one; that dry
run found and fixed a second bug (a line-wrapped log phrase missed by a
naive substring match) that code review alone had missed. Formalized as
the standing bar for any future validator change: a synthetic test proves
the logic; a real captured incident proves it doesn't have a blind spot
code review wouldn't catch.

### VERIFY-4: Interactive Cline sessions get the same outcome-based verification dispatched jobs already have

VERIFY-1 is implemented for `dispatch_coding_task` (`get_coding_task_status`
checks real git state) but interactive Cline sessions (the VS Code
extension) had no equivalent -- a human reads `attempt_completion`'s text
directly, nothing automatically checks it. **Trigger:** real incident,
2026-06-20 (odysseus) -- a session declared "Done... I fixed the two root
causes" and committed, before ever running the launcher it had just
written; it crashed immediately on the next command (wrong Python
interpreter, no venv check). **Status: Implemented 2026-06-20**
(`cline_completion_watcher.py`) -- polls Cline's task storage for new
completion claims, determines touched repos via real git log timestamps
(not the task's self-reported summary), runs each repo's test suite, and
for any touched file shaped like a launcher/entrypoint, actually spawns it
briefly and confirms it doesn't crash. This is the CRITIC pattern (verify
via execution, not re-reading) applied externally, since Cline's own
mechanisms can't provide it on Windows -- researched and ruled out before
building: hooks have no completion-blocking event and are macOS/Linux only;
"Double-Check Completion" is text-only self-critique (confirmed by reading
its actual checklist text -- it never asks the model to re-run anything).
**Not yet decided:** how this actually gets invoked on a schedule and
surfaced (manual on-demand vs. a recurring check vs. a real Windows
Scheduled Task) -- deliberately left open rather than built speculatively
ahead of that decision.

## 4. AT tasks spawned

None new -- this layer's existing practice already conforms to the
research-confirmed standard. Tracked here so future verification-logic
changes have an explicit bar to check against, not so existing code gets
rewritten.

## 5. Relationship to other SRs

- SR-1.12 (autonomous coordination) consumes this SR's verdicts to decide
  what action to take; this SR is upstream of that decision, not a
  replacement for it.
- SR-1.16 (Guardrails)'s retry decisions are also downstream consumers of
  this SR's verdicts (a transient-failure verdict triggers a retry; a
  genuine-failure verdict should not).
