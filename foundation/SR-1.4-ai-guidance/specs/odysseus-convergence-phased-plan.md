# Odysseus Convergence — Phased Implementation Plan

> Agent: `spec` / `docs`  
> Model: Tier-R (specs, docs, governance) with Tier-C cross-overs at integration commits  
> SR Owner: SR-1.4 AI Guidance Synchronization  
> Source document: `docs/odysseus-comparison-and-convergence-plan.md`

## Goal

Advance the Odysseus Comparison & Convergence Plan from a standalone observation document to an **active, trackable workstream** with:
1. Discrete, schedulable AT tasks in `ai-task-queue.md`
2. Acceptance criteria for each convergence step
3. Explicit entry evidence that records whether a given Odysseus capability has been absorbed, superseded, or rejected

## Where Odysseus Has a Clear Lead (Accept)

| Capability | Evidence threshold to absorb | Priority | Exit test / check |
|------------|------------------------------|----------|-------------------|
| Automated environment setup (Docker, toolchain) | New working `./scripts/dev/bootstrap.sh` landing | Medium | Fresh Windows VM runs script and reaches `yarn build` green |
| Simultaneous multi-window spec+code view | Screenshots or E2E spec showing multiple editor panes | Low | E2E harness captures multi-pane layout |
| Built-in FIM/infilling fill-in-the-middle everywhere | No direct equivalent in Cline; document why we don't need it | Low | Doc note only |

## Where Cline Has a Clear Lead (Reject)

| Capability | Why Cline wins | Convergence action |
|------------|----------------|-------------------|
| Deep tool-use / MCP orchestration | Cline's tool-calling depth verified in AT-970 headless harness | None; document divergence preserved |
| Multi-file agent autonomy (AT-mode) | Cline's 30+ file refactor history in Lane 100 | None; document divergence preserved |
| In-repo governance (task queue, dashboard) | Entire `architecture-docs/global/` governance surface | None; document divergence preserved |

## Where Ambiguity Remains (Investigate)

| Question | Investigative AT | Owner | Acceptance |
|----------|------------------|-------|------------|
| Does Odysseus's context reordering help on >300KB spec reads? | AT-O1: controlled experiment with `omega-primary-surface-architecture.md` (300KB+) read + summary | SR-1.4 | 5-repeat blind: accuracy within ±5% of Cline baseline or measurable speedup without quality loss |
| Does Odysseus's concept-graph mapping improve architecture reasoning? | AT-O2: controlled experiment comparing architecture-gap analysis (same prompt, both tools) | SR-1.4 | Similar blind assessment as AT-O1 |

## Phases

### Phase 0 — Instrumentation Baseline (this commit) — Complete 2026-06-14

- [x] Register AT-O1 and AT-O2 in `ai-task-queue.md` Ready Pool
- [x] Create `foundation/SR-1.4-ai-guidance/docs/odysseus-convergence-experiment-protocol.md` with:
  - Fixed prompt templates for controlled comparison
  - Scoring rubric (accuracy, speed, token cost)
  - Repeat-count (n=5 per condition)
- [x] Document the Accept / Reject / Investigate table above in `odysseus-comparison-and-convergence-plan.md` §Convergence Decisions

### Phase 1 — Controlled Experiment (two ATs)

- [ ] AT-O1: execute experiment; record results
- [ ] AT-O2: execute experiment; record results
- [ ] File OQ if results are ambiguous (no clear winner within ±5%)
- [ ] Mark Accept / Reject decisions as `converged` or `divergence-preserved`

### Phase 2 — Adoption for Accepted Capabilities

- [ ] For each "Accept" capability, create a bounded adoption AT (e.g. AT-O3: `bootstrap.sh` implementation)
- [ ] Each adoption AT gets its own spec, exit evidence, and commit
- [ ] Rejected capabilities get a one-line divergence note in `odysseus-comparison-and-convergence-plan.md` §Divergence Register

### Phase 3 — Closeout

- [ ] Update `odysseus-comparison-and-convergence-plan.md` status from Draft to Frozen
- [ ] Archive experiment logs to `foundation/SR-1.4-ai-guidance/docs/odysseus-convergence-experiment-logs/`
- [ ] Verify no orphaned ATs remain open

## Tracking

| AT ID | Phase | Status | Depends On |
|-------|-------|--------|------------|
| AT-O1 | 1 | Ready | Phase 0 complete |
| AT-O2 | 1 | Ready | Phase 0 complete |
| AT-O3+ | 2 | Blocked | Phase 1 complete |

## Exit Evidence for This Spec (Phase 0)

1. This file exists at the path above.
2. AT-O1 and AT-O2 rows appear in `architecture-docs/global/ai-task-queue.md` Ready Pool.
3. `docs/odysseus-comparison-and-convergence-plan.md` contains a §Convergence Decisions table linking to this plan.
4. `git status --short` is GREEN (no tracked file changes outside this commit).
