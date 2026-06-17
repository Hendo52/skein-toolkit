# Unified AI Strategy

**Date:** 2026-06-14
**Status:** Draft
**Type:** Governance / AI Toolchain
**Replaces:** `agentic-budget-tiered-strategy-2026-06-11.md` (superseded), `odysseus-comparison-and-convergence-plan.md` (superseded), `odysseus-convergence-next-steps.md` (superseded)
**Symlinks to:**
- `agentic-tiered-inference-strategy.md` -- tier definitions, per-tier budget
- `model-enablement-toolset-strategy.md` -- SQEP enablement framework (MCP/RAG/decomposition/skills/validation/OQ)
- `ai-model-selection-policy.md` -- task-classification rules (Tier R, Tier M, Tier C)
- `query-quality-checklists.md` -- per-tier pre-escalation checklists
- `cf-proxy-cheap-model-context-budget-roadmap.md` -- CF proxy orchestrator technical roadmap and chronic-problem ledger

---

## 1. Design-Goal Linkage

Primary system requirement: SR-1.4 -- AI toolchain governance.

This document is the single-strategy view. It tells an architect or operator:

1. Which model to use for a given task (today).
2. What the budget ceiling is and how it is split.
3. Which tools raise a cheap model's effective capability (SQEP enablement).
4. Which quality gates must pass before a task can be dispatched.
5. What chronic problems exist, which are fixed, and which still block.

The five linked specs above hold the full detail. **This doc does not duplicate them** -- it provides the decision flow and cross-references the authoritative section in each spec.

---

## 2. The Unified Tier Model

We run two tier vocabularies on this project. They are NOT in conflict -- they classify orthogonal dimensions. This section reconciles them.

### 2.1 Model-Selection Tiers (what kind of task?)

From `ai-model-selection-policy.md`:

| Tier | Task profile | Default model | Fallback |
|------|-------------|---------------|----------|
| **Tier R** (Routine) | GUI tweaks, simple refactors, docs, tests with precedent | Local 7B (e.g. `qwen2.5-coder:32b`) | Cloud Tier A if local is cold |
| **Tier M** (Novel Math) | Deriving geometry, debugging surface algorithms, novel mathematics | Local `phi4-reasoning` or `llama3.3:70b` | Cloud Tier C (architect-approve) |
| **Tier C** (Complex Agent) | Multi-file orchestration, spec authorship, architecture refactoring | Cloud Claude Sonnet (pay-as-you-go) | Cloud Tier C only |

IP constraint: Chinese-origin cloud APIs excluded per policy.

### 2.2 Infrastructure Tiers (which compute?)

From `agentic-tiered-inference-strategy.md`:

| Tier | Infrastructure | Cost (AUD/month) | Daily-driver suitability | Status |
|------|---------------|-------------------|------------------------|--------|
| **Tier A** | CF Workers AI (`cf/kimi-k2.6`, `cf/gpt-oss-120b`) | $13-66 | Yes -- primary daily driver | Operational (CB-7 Verified 2026-06-12) |
| **Tier B** | Vast.ai GPU rental for batch/escalation | Unknown (not provisioned) | No -- on-demand only | Not provisioned (stub repo) |
| **Tier C** | Anthropic Claude Sonnet API | ~$20 | No -- architect-invoked only | Operational |

### 2.3 The Cross-Matrix (Tier R/M/C x Tier A/B/C)

| Task class | Daily driver | Escalation path | Criteria |
|-----------|-------------|-----------------|----------|
| Tier R (routine) | **Tier A** (`cf/kimi-k2.6`) | Local 7B if warm; Tier B batch if amortized | Any single-file change with precedent |
| Tier M (novel math) | Local heavy (`phi4-reasoning`) if context fits | **Tier C** (Claude Sonnet) -- architect-approve | Breakthrough tasks with no training precedent |
| Tier C (complex agent) | **Tier C** (Claude Sonnet) | None within budget | Multi-file orchestration, spec authorship |

The key insight: Tier A's effective capability is NOT the raw model capability. Tier A + "Enabled" support (SQEP) can absorb tasks that Tier C + "Bare" used to handle. The experiment **AT-1157** measures how far this absorption goes.

---

## 3. Financial Architecture

- **Ceiling:** $100 AUD/month.
- **Currency conversion:** 1 USD = 1.42 AUD (June 2026).
- **Daily hard cap:** ~$20 AUD/day (from `scripts/local-mcp.py`).
- **Daily review threshold:** ~$3.33 AUD/day.

### 3.1 Current allocation

| Tier | Estimated cost (AUD/month) | Per-call cost | Notes |
|------|---------------------------|---------------|-------|
| A -- CF Workers AI | $13-66 (today ~$14) | ~$0.025-0.037/call (kimi-k2.6) | Default cheap-tier model per OQ-264 Option C |
| B -- Vast.ai | Not yet provisioned | Unknown | Experiment deferred until A stabilizes |
| C -- Claude Sonnet | ~$20 | Variable, architect-bounded | Low-frequency, architect-invoked |

### 3.2 Decision record: Model choice

**OQ-264 (2026-06-12):** Architect adopted Option C -- `cf/kimi-k2.6` is the default cheap-tier model effective immediately. CB-1/2/3 (`gpt-oss` context-budget investigation) moved to low-priority backlog with two explicit revisit triggers: (1) monthly cost exceeds budget, or (2) incidental fix discovered. This decision is fully reversible (`-Model` flag in `run-cline.ps1`).

---

## 4. Enablement Toolset (SQEP)

From `model-enablement-toolset-strategy.md`.

"SQEP" = Structured Query Enhancement Pipeline. The premise: a cheap model with excellent context, tools, and validation infrastructure outperforms a frontier model with no support.

### 4.1 The 8 enablement items

| # | Item | What it does | Current status | Relevant CB |
|---|------|-------------|---------------|-------------|
| 1 | **MCP Tool Surface** | Exposes 20+ tools (file I/O, search, git, test) to the model | Operational | CB-16 (fixed: 0 ReadTimeout across 164+ requests) |
| 2 | **RAG Context Narrowing** | Retrieves only relevant project context vs dumping whole repo | Experimental -- AT-1156 research pending | -- |
| 3 | **PEV Decomposition** | Breaks architect requests into spec-tracked action items | Operational in orchestrator | -- |
| 4 | **Skills / Templates** | Reusable prompt patterns for common task types | Partial -- needs population | -- |
| 5 | **Validation Infrastructure** | `yarn test`, `yarn build`, git-diff checks per step | Operational in orchestrator | CB-11 (fixed), CB-12 (fixed), CB-14 (fixed) |
| 6 | **Live OQ Escalation** | Model can pause and ask architect when ambiguous | Operational in orchestrator | CB-9 (fixed) |
| 7 | **Agentic Governance** | Human-in-the-loop for C-tier tasks, spend caps | Operational (`cap=$2.00`/day) | -- |
| 8 | **SQEP Telemetry** | Tracks pass rates, costs, quality per tier for evidence | Design -- AT-O1 evidence gathering | -- |

### 4.2 Enablement impact: The AT-1157 question

The central open question of this strategy: **Can Tier A + "Enabled" consistently handle tasks currently dispatched as Tier C?**

- AT-1157 ("Enablement-adjusted tier experiment") proposes selecting 5 representative Level-2 (Complex) tasks, executing each via CF proxy with full SQEP support, and scoring against the Tier C baseline.
- The experiment design is in `model-enablement-toolset-strategy.md` §7 and the rubric in `odysseus-convergence-experiment-protocol.md`.
- **This strategy holds:** if AT-1157 shows Tier A+Enabled reaches Tier C+Bare quality within ±5% on the rubric, the default for Level-2 tasks shifts from Claude Sonnet (Tier C) to `cf/kimi-k2.6` (Tier A). If not, Tier C remains the default and the $35-85/month headroom goes to Tier B experiments.

---

## 5. Quality Gates

From `query-quality-checklists.md`.

Before any task is dispatched, it must pass tier-appropriate quality checks. These are NOT bureaucratic -- they catch the most common failure modes before money is spent.

### 5.1 Pre-dispatch checklist (all tasks)

1. **Context assembly gate:** Does the prompt include the minimal necessary context? (Relevant files + specs, not the whole repo.)
2. **Precedent gate:** Has a similar task been done before? If yes, link the prior spec/task ID.
3. **Exit-criteria gate:** Is there a verifiable acceptance criterion? ("Update the file" is not verifiable; "Add `DOF: N` badge that updates on every constraint change and turns red when DOF < 0" is verifiable.)
4. **Budget gate:** Is the estimated call count within the per-tier cap? (See `agentic-tiered-inference-strategy.md` §6.)

### 5.2 Escalation triggers (per toolset item)

From `model-enablement-toolset-strategy.md` §8 and AT-1158:

Each enablement item has defined "escalation triggers" -- conditions under which the model should escalate to the next tier rather than continue struggling:

| Item | Escalation trigger |
|------|-------------------|
| MCP Tool Surface | >3 consecutive tool-call failures on the same tool; model hallucinates tool name |
| RAG Context Narrowing | Retrieved context is <30% of what the human knows is relevant; 2+ unrelated files in top-5 |
| PEV Decomposition | Plan exceeds 12 steps; 3+ steps have no verifiable exit criterion; steps have circular dependencies |
| Skills / Templates | No matching skill for a task type that has been done 3+ times before |
| Validation Infrastructure | CI fails on a change the model believes is correct; same error across 2 retries |
| Live OQ Escalation | Architect response to OQ is "need more information" twice for the same question |
| Agentic Governance | Estimated cost exceeds per-task cap; task touches files outside the agent's declared specialty |
| SQEP Telemetry | Same task type fails 2+ times within 48 hours; cost per task deviates >50% from moving average |

### 5.3 Post-execution review (for AT-1157 experiments)

Per `odysseus-convergence-experiment-protocol.md`: each experiment task is scored on a rubric (accuracy, completeness, tool-use efficiency, architect-review requirement). Scores feed into the SQEP telemetry pool.

---

## 6. Operational Runbook

### 6.1 Daily workflow

1. **Session start:** `toolchain-doctor.ps1` check 2/5 (local-mcp.py health). Expected: OK.
   - If STALE: restart server (CB-15 workaround -- AT-1142 pending for systemic fix).
2. **Task dispatch:** Classify task as Tier R/M/C per `ai-model-selection-policy.md` §5.
   - Tier R -> Tier A (`cf/kimi-k2.6`) if local model is cold; local if warm.
   - Tier M -> Local heavy model; architect approval for Tier C if local fails.
   - Tier C -> Claude Sonnet (architect-invoked, not automatic).
3. **Context prep:** Run pre-dispatch checklist (§5.1). Use `query-quality-checklists.md` for tier-specific items.
4. **Execution:** Prefer orchestrated dispatch for multi-step tasks (carries forward findings, bounded ambiguity).
5. **Review:** Post-execution validator pass (`yarn test`, `yarn build`, git diff). If AMBIGUOUS, escalate via OQ path.

### 6.2 Weekly review

- Check CF spend against $3.33/day threshold (~$100/month / 30 days).
- Review any OQs raised, classify as systemic (require spec fix) or one-off.
- Update `cf-proxy-cheap-model-context-budget-roadmap.md` section 8 with any new validation runs.

---

## 7. Chronic Problem Ledger (Snapshot)

This is a READ-ONLY summary. The authoritative ledger is `cf-proxy-cheap-model-context-budget-roadmap.md` section 5.

| ID | Problem | Status | Remaining impact |
|----|---------|--------|------------------|
| CB-1 | `gpt-oss` degenerate empty response on large context | Backlog (low priority) | `gpt-oss` not used; revisit per OQ-264 triggers |
| CB-7 | CF proxy content fidelity (verbatim quoting) | **Verified** (2026-06-12, test #17) | None -- fix `cfa3a2d4` confirmed working |
| CB-11 | Validator false-positive AMBIGUOUS on read-only steps | **Verified** (2026-06-12) | Fixed in `_VALIDATOR_RECORD_ONLY_STEP_RE` |
| CB-12 | Orchestrator findings-carry-forward missing | **Verified** (2026-06-12) | Fixed in `findings` array propagation |
| CB-13 | File creation lands outside repo root | **Verified** (2026-06-12, test #17) | CB-7 test #17 confirmed in-repo write |
| CB-14 | Cline-terminal tool call strands orchestrator | **Verified** (2026-06-12) | Fixed in `_cline_terminal_tool_summary` branch |
| CB-15 | Long-running local-mcp.py server serves stale code | In-progress (AT-1142) | Manual restart workaround; systemic fix pending |
| CB-16 | CF Workers AI `ReadTimeout` | **Verified fixed** | 0 occurrences across 164+ requests |
| CB-17 | State-overwrite on naive orchestrator resume | Documented | Avoid naive resume; use `resume-orchestrator-run.ps1` |
| CB-18 | `_next_oq_id` ID-reuse-after-retirement | Documented | Aware; no fix scheduled |
| CB-19 | Step-session overshoot (executor performs extra steps) | Documented | Aware; verify after every step |

---

## 8. Experiment Portfolio

| Experiment | Status | Decision gate |
|-----------|--------|---------------|
| AT-1140 -- CB-7/11/13/14 live validation | **Done** (2026-06-12, test #17) | CB-7 Verified; CB-11/13/14 Verified |
| AT-1141 -- CB-14 fix implementation | **Done** (2026-06-12) | Unblocked AT-1140 |
| AT-1142 -- CB-15 systemic fix | Ready / Small | Will add server SHA to health check + doctor STALE state |
| AT-1156 -- RAG context narrowing research | Ready / Medium | Design note with go/no-go |
| AT-1157 -- Enablement-adjusted tier experiment | Ready / Medium | 5 tasks, Tier A+Enabled vs Tier C+Bare |
| AT-1158 -- Escalation trigger subsections | Ready / Small | Add 8 subsections to `model-enablement-toolset-strategy.md` §5 |

---

## 9. Convergence with Odysseus

The project's AI toolchain evolved independently of Odysseus but has converged on similar architectural choices:

| Dimension | Electron-Splines (this project) | Odysseus |
|-----------|--------------------------------|----------|
| Orchestration model | Decoupled (server dispatches independent `cline` invocations) | Coupled (single process with message bus and model swappable mid-session) |
| Context narrowing | MCP search tools + planned RAG (AT-1156) | ChromaDB + fastembed vector memory (`src/agent_loop.py`) |
| Tool surface | MCP (20+ tools via local-mcp.py) | Custom tool registry with RAG-based surfacing |
| Spend control | Per-day hard cap (`cap=$2.00`/day) | Model-level budget tracking |
| Quality gating | Pre-dispatch checklist + live validator pass | Reflective critique on result before submission |

Convergence finding: both projects treat "context quality" as the primary optimization target, not "model capability". The enabling infrastructure (RAG, tool-surfacing, validation) matters more than the base model. Our AT-1156/1157 experiments test this hypothesis directly.

---

## 10. Acceptance Criteria for This Strategy

- AC-1: This file exists at `foundation/SR-1.4-ai-guidance/docs/unified-ai-strategy.md` and is listed in `architecture-docs/specs/INDEX.md`.
- AC-2: All five linked specs have back-references to this file in their §1 or preamble.
- AC-3: The cross-matrix in §2.3 is the single reference point that resolves all tier-naming confusion in the project.
- AC-4: AT-1158 has escalation-trigger subsections in `model-enablement-toolset-strategy.md` §5, cross-referenced from `query-quality-checklists.md`.
- AC-5: AT-1142 has a commit with the CB-15 systemic fix unit-tested.
