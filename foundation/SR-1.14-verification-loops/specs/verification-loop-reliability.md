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
