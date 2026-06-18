# skein-toolkit — Design Goals

AT-1219. skein-toolkit had no canonical SR (System Requirement) definitions
of its own. The `foundation/SR-1.4-ai-guidance/`, `SR-1.5-agent-contracts/`,
`SR-1.6-instruction-skills/`, and `SR-1.12-autonomous-coordination/`
directory names were copied verbatim from Electron-Splines during the
OQ-279/AT-1201 migration (2026-06-17/18) — but Electron-Splines's own
`architecture-docs/global/design-goals.md` defines SR-1.4 as **that repo's**
Copilot agent pipeline (`priorwork → rnd → spec → unittest → impl → meshqa →
docs`, 12 agent definitions), which is not what any file actually migrated
into this folder is about. The numbers matched by accident of how AT-1201
copied directories, not because the two repos share a system requirement.

This document is skein-toolkit's own, independent SR-1.x definitions. Same
numbers, same folder names, **deliberately not the same meaning** as
Electron-Splines's SR-1.x — there is no cross-repo requirement linkage
implied by the shared numbering, and none should be assumed when reading a
cross-reference from a migrated spec back to Electron-Splines's
`design-goals.md`.

---

#### SR-1.4 — AI toolchain governance (skein-toolkit)

skein-toolkit shall maintain the model-selection and inference-tier policy
(`ai-model-selection-policy.md`), the tiered-inference strategy
(`agentic-tiered-inference-strategy.md`), the agentic coding governance
contract (`agentic-coding-governance.md`), and the operational research/
roadmap docs (CF proxy context-budget roadmap, Odysseus convergence plans,
query-quality checklists) that govern how AI agents are dispatched, which
model tier handles which task class, and how query quality is enforced
before escalating tiers — across every project that consumes skein-toolkit
(Electron-Splines, Odysseus, and any future consumer), not scoped to one
repo's own Copilot agent pipeline.

**Owning directory:** `foundation/SR-1.4-ai-guidance/`

#### SR-1.5 — Agent contracts (skein-toolkit)

skein-toolkit shall define the agent-role and delegation-contract patterns
(teamlead/specialist orchestration, agent definition file format) as a
reusable specification independent of any one consuming repo's actual
`.github/agents/*.agent.md` instantiations — those instantiations stay
owned by each consuming repo; this SR owns the *pattern* they all follow.

**Owning directory:** `foundation/SR-1.5-agent-contracts/`

#### SR-1.6 — Instruction and skill system (skein-toolkit)

skein-toolkit shall define how path-scoped instruction packs and skill
manifests work as a system (trigger conditions, activation rules, the
on-demand skill-loading model) independent of any one consuming repo's
actual instruction/skill content — same pattern-vs-instantiation split as
SR-1.5.

**Owning directory:** `foundation/SR-1.6-instruction-skills/`

#### SR-1.12 — Autonomous execution coordination (skein-toolkit)

skein-toolkit shall maintain the tik/tok dual-queue batch dispatch model,
authority-packet conformance rules, the coordination-doc "temperature"
model, the OQ-authoring-and-precedent-search policy, and the AT/OQ
Decomposition Gate (`task-and-oq-authoring-standard.md`, currently still
physically hosted in Electron-Splines's `architecture-docs/governance/`
pending its own follow-on migration AT) — the protocol governing how
autonomous and semi-autonomous agent work gets coordinated, queued, and
escalated when ambiguous, across any consuming project.

**Owning directory:** `foundation/SR-1.12-autonomous-coordination/`

---

## Relationship to Electron-Splines's design-goals.md

Migrated specs under `foundation/SR-1.x-*/` that still contain a relative
link back to `../../../architecture-docs/global/design-goals.md` (Electron-
Splines's copy) are referencing stale linkage from before this document
existed. Those links should be updated to point here instead as they're
next touched — not as a dedicated mass-edit pass (low value, mechanical,
better done opportunistically per CLAUDE.md's general staleness-fixing
guidance than as its own task).
