# Spec: Agentic Tiered Inference Strategy

**Date:** 2026-06-11
**Status:** Draft
**Type:** Governance / AI Toolchain
**Consolidated into:** [unified-ai-strategy.md](../docs/unified-ai-strategy.md)

**Source of record:**
[agentic-budget-tiered-strategy-2026-06-11.md](../docs/agentic-budget-tiered-strategy-2026-06-11.md) --
working notes that established the figures and tier definitions in this spec.
All budget figures in section 2 and tier definitions in section 3 are quoted
verbatim from the source document; do not recompute or re-derive them.

**Enablement framework:** [model-enablement-toolset-strategy.md](model-enablement-toolset-strategy.md)
-- defines how the adjacent toolset (MCP/RAG/decomposition/skills/validation/OQ) raises Tier A's
*effective* capability ("SQEP enablement"), and proposes AT-1157 to measure whether Tier A at
"Enabled" support can absorb work this spec currently assumes goes to Tier C.

---

## 1. Design-Goal Linkage

- Primary system requirement: SR-1.4 -- AI toolchain governance
  ([architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md))

This spec defines the three-tier inference strategy that governs which model
infrastructure is used for agentic programming in Electron-Splines, the
per-tier budget allocation, and the decision criteria for moving work between
tiers.

---

## 2. Problem Statement

Agentic development on Electron-Splines requires sustained inference over
long sessions (~36 hours/week). Frontier-only usage costs thousands of AUD per
month, which is incompatible with a personal-project budget. A cheap-model
toolchain exists but had a reliability blocker (CB-7 content fidelity). This
spec records the tiered fallback strategy that makes sustained agentic work
financially viable.

---

## 3. Scope

In scope:

- Three-tier inference hierarchy (Tier A / Tier B / Tier C)
- Per-tier budget allocation within the monthly ceiling
- Decision rules for moving work between tiers
- Currency, conversion rate, and budget ceiling
- Status of each tier and known blockers

Out of scope:

- Model-selection decision rules for individual tasks (covered by
  ai-model-selection-policy.md)
- Prompt engineering techniques (covered by CLAUDE.md)
- Agent delegation and tool-boundary contracts (covered by
  agentic-coding-governance.md)
- Infrastructure provisioning procedures

---

## 4. Constraints

### 4.1 Budget ceiling

- **Ceiling:** $100 AUD/month.
- **Time commitment:** approximately 36 hours/week of agentic programming.
- **Currency:** All dollar amounts are AUD. Where source pricing is in USD,
  the conversion rate used is 1 USD = 1.42 AUD (June 2026).

### 4.2 Hardware and availability constraints

- Tier A and Tier C are always-on (managed API).
- Tier B requires on-demand provisioning; not suitable for interactive daytime
  sessions due to setup overhead.

---

## 5. The Three Tiers

Quoted verbatim from section 3 of the source document.

### Tier A -- Cloudflare Workers AI daily driver

- **Models:** `cf/gpt-oss-120b` for most daily tasks; `cf/kimi-k2.6` for harder
  tasks.
- **Role:** Primary daily driver for routine and complex agentic programming
  tasks.
- **Cost:** $13-66 AUD/month (see 2.1).
- **Status (2026-06-11):** Mechanically working end-to-end for the first time
  (the orchestrator ran a full 9-step plan, exit 0 in 42s) after the
  `run-cline.ps1` stdin-truncation fix (commit `8d2fb468`). The remaining
  blocker is content fidelity (CB-7): "exit 0" did not mean "correct" -- a
  test run inverted the actual System Architect decisions it was asked to
  transcribe. A scoped fix for CB-7 (verbatim-quote instruction in the
  per-step executor system prompt) was applied 2026-06-11, commit `cfa3a2d4`,
  and is being validated.

### Tier B -- vast.ai dev server for escalation / batch complex tasks

- **Role:** Escalation target for tasks Tier A cannot handle reliably, and for
  batches of complex tasks where amortizing provisioning overhead makes sense.
- **Models:** The best available open model on rented GPU hardware (see
  `architecture-docs/research_into_prior_work/gpu-batch-cost-optimization.md`
  for prior Vast.ai + Ollama cost research).
- **Status (2026-06-11):** Does not exist yet. `electron-splines-dev-server/`
  is an empty stub repository (a fresh `master` branch with no commits, no
  remote, and a one-line `README.md`). `DEV_TOOLKIT_PLAN.md` describes the
  intended standalone, Docker-based toolkit repo but no provisioning has been
  done.
- **Open question:** there is likely a minimum viable batch size below which
  Vast.ai provisioning overhead is not worth it relative to running the same
  tasks on Tier A or Tier C.

### Tier C -- pay-as-you-go Claude Sonnet, architect-invoked

- **Role:** Specific tasks invoked directly by the System Architect -- not a
  daily-driver tier.
- **Cost:** ~$20 AUD/month (see 2.3).
- **Status (2026-06-11):** Already in use (this session is an example). Usage
  is naturally low-frequency and bounded.

---

## 6. Per-Tier Budget Allocation

Quoted verbatim from section 4 of the source document (within the
$100 AUD/month ceiling):

| Tier | Role | Estimated cost (AUD/month) |
|------|------|------------------------------|
| A -- CF Workers AI | Daily driver | $13-66 |
| B -- Vast.ai dev server | Escalation / batch | Not yet provisioned -- no cost data |
| C -- Claude Sonnet (pay-as-you-go) | Architect-invoked | ~$20 |

A, B, and C compete for the same $100 AUD/month budget. Tier B's cost is
currently unknown because the dev server has not been provisioned. Once Tier A
is reliable (CB-7 resolved), the ~$35-85 AUD/month headroom is available for
Tier B provisioning experiments and/or further Tier C usage, subject to
explicit per-tier caps to be set once Tier B has real cost data.

---

## 7. Conclusion

Quoted verbatim from section 2.4 of the source document:

> CF Workers AI (`gpt-oss-120b` / `kimi-k2.6`) is financially viable as a daily
> driver at 36 hours/week, within the $100 AUD/month ceiling. Frontier-only
> usage is not. **The constraint currently blocking Tier A from being usable is
> reliability (the CB-7 content-fidelity problem in
> `foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-roadmap.md`),
> not cost.**

---

## 8. Acceptance Criteria

- AC-1: This spec is listed in `architecture-docs/specs/INDEX.md` with SR-1.4
  ownership and status Draft.
- AC-2: CB-7 (content-fidelity fix, commit `cfa3a2d4`) is validated against a
  task that reaches the orchestrator's per-step executor without CB-1
  (degenerate-empty-response) interfering.
- AC-3: Tier B (`electron-splines-dev-server/`) has a provisioning plan and a
  measured cost-per-batch before any budget is allocated to it.
- AC-4: Per-tier budget caps are set once Tier B has real cost data, and
  enforced via the existing `cap=$2.00`/day spend-cap mechanism in
  `scripts/local-mcp.py` (or its successor in the agentic-server spinoff).

