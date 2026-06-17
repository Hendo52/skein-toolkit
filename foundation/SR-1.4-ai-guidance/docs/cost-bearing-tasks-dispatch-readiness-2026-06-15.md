# Cost-Bearing Task Dispatch Readiness (2026-06-15)

## Purpose

AT-1156, AT-1157, AT-1159, AT-O1, and AT-O2 all involve real CF-proxy spend
at a scale where the architect benefits from being aware of (or actively
monitoring) the run, unlike routine Small/docs dispatches. This note
summarizes what each entails, its rough cost profile, blocking dependencies,
and a recommended order, so they can be picked up quickly.

## Summary table

| ID | What it does | Cost profile | Depends on | Status |
|----|------|------|------|------|
| AT-1156 | RAG-based context/tool surfacing research + design note (Odysseus ChromaDB+fastembed, `src/agent_loop.py`). Medium, Level-2. | One normal Cline/CF research-and-write session -- comparable to other Medium docs dispatches. | AT-1152 (done) | Ready -- no special monitoring needed; queued for the next Cline dispatch in this session. |
| AT-1157 | Enablement-adjusted tier experiment: pick 5 representative Level-2 tasks, run each via the CF proxy orchestrator at Tier A (`cf/gpt-oss-120b` or `cf/kimi-k2.6`) with full "Enabled" support (PEV decomposition, validator pass, live OQ escalation), score against the convergence-experiment rubric vs. the Tier-C baseline. Medium, agent: `orchestrator`. | Highest after AT-O1/AT-O2: effectively 5 full dev-task executions at Tier A plus scoring/comparison. Recommend picking the 5 tasks from already-queued Small/Medium Ready Pool items, so the work product (the tasks themselves getting done) is useful regardless of the experiment's verdict. | AT-1140 (done) | Ready, but recommend running with the architect able to glance at CF spend during the run. |
| AT-1159 | Tier-C vs Tier-A cost-allocation framework for supervision / failure-driven AT authoring / OQ raising, using `supervisor-cost-notes-2026-06-14.md` and AT-1157's pass-rate data. Small, Level-2. | Single docs session, normal cost. | AT-1157 (not done) | Blocked until AT-1157 lands. |
| AT-O1 | Controlled 5-repeat blind comparison: does Odysseus's context reordering help on >300KB spec reads (`omega-primary-surface-architecture.md`)? Protocol: `odysseus-convergence-experiment-protocol.md` SS AT-O1. Medium. | Highest single-item cost in the queue: 5 repeats x 2 conditions, each loading a >300KB doc into context. | None | Ready, but the protocol's blinding/repeat structure must be followed exactly for the result to be valid -- not a good fit for an unsupervised Cline run. Recommend running when the architect can watch CF dashboard spend live. |
| AT-O2 | Controlled 5-repeat blind comparison: does Odysseus's concept-graph mapping improve architecture-gap reasoning (Omega-primary-surface migration dependency graph)? Protocol: `odysseus-convergence-experiment-protocol.md` SS AT-O2. Medium. | Same profile as AT-O1 (5-repeat blind comparison, large-context reads). | None | Same as AT-O1. |

## Recommended order

1. **AT-1156** -- low-cost, independent, in the spirit of routine Cline
   dispatch. Queued next in this session.
2. **AT-1157** -- medium-cost, unblocks AT-1159; its task selection should
   draw from the existing Ready Pool so the underlying work has value
   independent of the experiment's verdict.
3. **AT-1159** -- cheap, follows directly from AT-1157's results.
4. **AT-O1 / AT-O2** -- highest cost, run when the architect is available to
   monitor CF spend; follow the blind-comparison protocol exactly.

## This session's disposition

- AT-1156: dispatched to Cline (see `ai-task-queue.md` for status once it
  lands).
- AT-1157, AT-1159, AT-O1, AT-O2: left for architect-supervised dispatch
  given their cost profile, per the table above. Not blocked by anything in
  this session's work.
