# Odysseus Comparison & Convergence Plan — Superseded

> **Status: Superseded (2026-06-14).** This document previously held a standalone
> Odysseus-vs-Cline comparison (R1-R14 capability cross-reference, verdict column, and
> a 10-week fork-and-port proposal). That proposal has been superseded by an
> incremental, AT-O1/AT-O2 controlled-experiment approach. The canonical, actively
> tracked plan is now [odysseus-convergence-phased-plan.md](../specs/odysseus-convergence-phased-plan.md).
>
> This file is retained as a pointer because
> [agent-harness-phase0-readiness-review.md](agent-harness-phase0-readiness-review.md)
> and the phased plan's own Phase 0 exit evidence reference it by path.

## Convergence Decisions

The Accept / Reject / Investigate decisions below are carried forward from
[odysseus-convergence-phased-plan.md](../specs/odysseus-convergence-phased-plan.md)
and recorded here per that plan's Phase 0 exit evidence item 3.

### Where Odysseus Has a Clear Lead (Accept)

| Capability | Evidence threshold to absorb | Priority | Exit test / check |
|------------|------------------------------|----------|-------------------|
| Automated environment setup (Docker, toolchain) | New working `./scripts/dev/bootstrap.sh` landing | Medium | Fresh Windows VM runs script and reaches `yarn build` green |
| Simultaneous multi-window spec+code view | Screenshots or E2E spec showing multiple editor panes | Low | E2E harness captures multi-pane layout |
| Built-in FIM/infilling fill-in-the-middle everywhere | No direct equivalent in Cline; document why we don't need it | Low | Doc note only |

### Where Cline Has a Clear Lead (Reject)

| Capability | Why Cline wins | Convergence action |
|------------|----------------|-------------------|
| Deep tool-use / MCP orchestration | Cline's tool-calling depth verified in AT-970 headless harness | None; document divergence preserved |
| Multi-file agent autonomy (AT-mode) | Cline's 30+ file refactor history in Lane 100 | None; document divergence preserved |
| In-repo governance (task queue, dashboard) | Entire `architecture-docs/global/` governance surface | None; document divergence preserved |

### Where Ambiguity Remains (Investigate)

| Question | Investigative AT | Owner | Acceptance |
|----------|------------------|-------|------------|
| Does Odysseus's context reordering help on >300KB spec reads? | AT-O1: controlled experiment with `omega-primary-surface-architecture.md` (300KB+) read + summary | SR-1.4 | 5-repeat blind: accuracy within +/-5% of Cline baseline or measurable speedup without quality loss |
| Does Odysseus's concept-graph mapping improve architecture reasoning? | AT-O2: controlled experiment comparing architecture-gap analysis (same prompt, both tools) | SR-1.4 | Similar blind assessment as AT-O1 |

AT-O1 and AT-O2 are registered in [ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md) Ready Pool. Execution follows
[odysseus-convergence-experiment-protocol.md](odysseus-convergence-experiment-protocol.md).
