# Spec: Model Enablement Toolset Strategy (SQEP Framework)

**Date:** 2026-06-14
**Status:** Draft
**Type:** Governance / AI Toolchain
**Consolidated into:** [unified-ai-strategy.md](../docs/unified-ai-strategy.md)

**Companion docs:**
- [ai-model-selection-policy.md](ai-model-selection-policy.md) -- Level 1/2/3 task
  classification, inference tiers, the reducibility gate, PEV protocol, and the OQ mechanism.
  This spec does not redefine any of those; it asks how much of the gap between "what a cheap
  model can do unaided" and "what §5 requires" can be closed by tooling rather than by
  escalating the model.
- [agentic-tiered-inference-strategy.md](agentic-tiered-inference-strategy.md) -- Tier A/B/C
  budget allocation ($100 AUD/month ceiling). This spec is the mechanism by which Tier A
  absorbs more of the workload that the budget analysis assumes it must carry.
- [odysseus-convergence-phased-plan.md](odysseus-convergence-phased-plan.md) and
  [odysseus-convergence-experiment-protocol.md](../docs/odysseus-convergence-experiment-protocol.md)
  -- AT-O1/AT-O2 controlled experiments (Phase 1, Ready) and AT-1151-1153 (skein-toolkit
  <-> Odysseus MCP bridge, verified zero-code-change). This spec's proposed AT items are the
  next layer on top of that bridge.
- [query-quality-checklists.md](../docs/query-quality-checklists.md) -- per-tier pre-query and
  pre-escalation checklists. §8 of this spec extends those checklists with explicit
  escalation triggers per toolset element.
- [cf-proxy-cheap-model-context-budget-roadmap.md](../docs/cf-proxy-cheap-model-context-budget-roadmap.md)
  -- CB-1..CB-7 chronic context-budget problem. §6 of this spec proposes RAG-based context
  narrowing as a pre-hoc complement to the CB-1..CB-5 post-hoc mitigations already tried.

---

## 1. Design-Goal Linkage

- Primary system requirement: SR-1.4 -- AI toolchain governance
  ([architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md))

---

## 2. Problem Statement

[agentic-tiered-inference-strategy.md](agentic-tiered-inference-strategy.md) establishes that
financial feasibility requires Tier A (cheap CF Workers AI models, `cf/gpt-oss-120b` /
`cf/kimi-k2.6`) to be the daily driver for routine *and* complex agentic work -- Tier C
(Claude Sonnet) at frontier rates is not viable at 36 hours/week. But
[ai-model-selection-policy.md](ai-model-selection-policy.md) §5 records an empirical floor:
local/cheap reasoning models "produce frequent incorrect derivations" even on Level 2
(Complex) work, and the policy's own decision rules (§7) default Level 2 to Cloud-API.

These two documents are in tension. The tension is not resolved by re-measuring the model --
it is resolved by asking what changes when a Tier A model is given the **adjacent toolset**:
MCP tool access, RAG/context narrowing, task decomposition, skills/procedures, sub-agents,
prompt refinement, validation harnesses, ambiguity analysis, and OQ escalation. The thesis of
this spec, supplied by the System Architect, is:

> A key strategy is to provide support to weaker models in the form of the broader toolset
> that sits adjacent to the model. Weaker models can do the bulk of the grunt work, but for
> that to work, they need to be enabled -- like a SQEP employee.

**SQEP** (Suitably Qualified and Experienced Person) is a competency-assurance framework term
from safety-critical industries: a worker is not trusted to perform a task because they are
inherently brilliant, but because the *system* around them -- procedures, training records,
defined competency boundaries, supervision, and escalation paths -- makes their output
trustworthy and makes the boundary of their competency explicit and checkable. This spec
applies that framing to the Tier A / Local-Agent model: the model is the SQEP worker, and the
adjacent toolset is the procedures-and-supervision system.

---

## 3. Scope

In scope:

- Mapping the 8 toolset categories (MCP, RAG, task decomposition, skills, agents, prompt
  refinement, validation harnesses, ambiguity analysis/OQ escalation) to their current
  implementation status in this repo and in `skein-toolkit`.
- Identifying the highest-leverage gap and proposing a bounded investigation.
- Defining "enablement-adjusted tier" as a refinement to the high-low model mix, and proposing
  a controlled experiment to test it.
- Defining the competency envelope -- what the toolset does *not* compensate for, so enablement
  does not become silent over-trust.

Out of scope:

- Re-deriving Level 1/2/3 classification or the §7 decision rules
  ([ai-model-selection-policy.md](ai-model-selection-policy.md)).
- Re-deriving Tier A/B/C budget figures ([agentic-tiered-inference-strategy.md](agentic-tiered-inference-strategy.md)).
- CB-1..CB-7 mechanics themselves ([cf-proxy-cheap-model-context-budget-roadmap.md](../docs/cf-proxy-cheap-model-context-budget-roadmap.md)) --
  this spec proposes one new strategy (RAG-based narrowing, §6) that is additive to that roadmap.
- Re-running AT-1151-1153 (skein-toolkit <-> Odysseus bridge) -- those are done/ready and are
  treated here as existing infrastructure.

---

## 4. The SQEP Enablement Model

| SQEP element (human workforce) | Purpose | Agentic equivalent |
|---|---|---|
| Procedures / SOPs | Defines exactly how to do routine work without judgment calls | Skills (`load_skill`/`list_skills`, `scripts/local-mcp.py`), CLAUDE.md, path-scoped instruction packs |
| Training records / competency matrix | Defines what tasks a person is authorized to do unsupervised | Level 1/2/3 classification + `Model:` annotation ([ai-model-selection-policy.md](ai-model-selection-policy.md) §5, §11) |
| Supervisor sign-off / escalation path | When a task exceeds competency, escalate rather than guess | OQ mechanism, `paused_for_oq` orchestrator state ([ai-model-selection-policy.md](ai-model-selection-policy.md) §7.2) |
| Toolbox / equipment provided | Task-specific tools so the worker doesn't need to improvise | MCP tool surface (`local-mcp.py`/`skein-toolkit`, 9 tools, verified reachable from Odysseus's MCP manager with zero code changes -- AT-1152) |
| Reference library, indexed | Quick access to the specific information needed, not everything | RAG -- **gap**, see §6 |
| Work breakdown / method statement | Large jobs broken into bounded, checkable steps | Task decomposition: `_detect_multi_step_ask` multi-step interceptor, Plan-Execute-Verify (`ai-model-selection-policy.md` §7.3) |
| Job briefing / pre-task talk | Clarify scope and expectations before starting | Prompt refinement: [query-quality-checklists.md](../docs/query-quality-checklists.md) |
| Quality inspection / sign-off before close-out | Independent check before work is accepted as done | Validation harnesses: `_run_validator_pass` (orchestrator per-step), SR-1.16 headless harness |

The point of this table is not the analogy itself -- it is that **every row on the right
already exists in some form**. The work this spec proposes is not "build the toolset"; it is
"identify which rows are weakest, and measure whether strengthening them shifts the high-low
mix."

---

## 5. Enablement Toolset Inventory (current status)

Each subsection below describes one toolset element: its current implementation status and the
concrete, observable conditions under which a session using that element should escalate to the
next model tier or to an architect via an OQ. The escalation triggers are derived directly from
the competency-envelope analysis in §8. See
[query-quality-checklists.md](../docs/query-quality-checklists.md) §2.1, §3.1, and §4.2 for
how these triggers map to the per-tier pre-escalation gates.

### 5.1 MCP

**Implementation:** `scripts/local-mcp.py` / `skein-toolkit/mcp-server/local-mcp.py` --
FastMCP SSE server, 9 tools (`fs_write_file`, `fs_read_file`, `run_shell`, `web_search`,
`fetch_page`, `list_directory`, `create_test`, `load_skill`, `list_skills`, `repo_map`,
`find_files`, `search_code`). Confirmed reachable from Odysseus's
`McpManager.connect_server(transport="sse")` with zero code changes (AT-1152).

**Status:** Implemented.

#### Escalation triggers

MCP provides tool access, not tool judgment (see §8 item 1). Escalate when:

- More than 3 consecutive tool-call failures occur on the same tool with no change in the
  call parameters (the model is stuck in a retry loop rather than adapting).
- The model hallucinates a tool name that is not in `_KNOWN_TOOLS` and then retries the
  hallucinated call after being shown the valid tool list.

### 5.2 RAG

**Implementation:** Odysseus has ChromaDB + fastembed vector memory and RAG-based tool
surfacing ("only relevant tools shown in context per query" -- `reference_odysseus.md`).
`local-mcp.py`/`skein-toolkit` has neither: the orchestrator's per-step dispatch body
assembles context by inclusion (file reads, prior step summaries), not by retrieval.

**Status:** Gap -- see §6, AT-1156.

#### Escalation triggers

RAG narrows context to what is indexed; undocumented tribal knowledge remains an OQ trigger
(see §8 item 2). Escalate when:

- Retrieved context appears to be less than 30% of the information the human knows is
  relevant to the task (model is visibly missing key prior decisions or contracts).
- Two or more unrelated files appear in the retrieved top-5 results, indicating the retrieval
  index cannot distinguish the relevant domain from noise for this query.

### 5.3 Task decomposition

**Implementation:** `_detect_multi_step_ask` multi-step interceptor (`local-mcp.py`
~line 1359), wrapped in `ask_followup_question` per commit `924b623f`;
Plan-Execute-Verify protocol (`ai-model-selection-policy.md` §7.3) and the §0 reducibility
gate. Validated end-to-end at Tier A: AT-1140 ran a full 9-step orchestrator plan,
exit 0 in 42s.

**Status:** Implemented, validated for Tier A.

#### Escalation triggers

Decomposition is only as good as the manifest; an ambiguous Plan phase cannot be rescued by
execution (see §8 item 3). Escalate when:

- The generated plan exceeds 12 steps -- beyond this size the cumulative error probability
  across steps makes autonomous execution unreliable without intermediate architect review.
- Three or more steps in the plan have no verifiable exit criterion (the model cannot
  confirm completion without human inspection).
- Steps in the plan have circular dependencies that cannot be resolved by reordering.

### 5.4 Skills

**Implementation:** `load_skill`/`list_skills` (`local-mcp.py` lines 307/336),
`.github/skills/`.

**Status:** Implemented.

#### Escalation triggers

Skills encode known procedures; a skill cannot exist for a genuinely novel problem (see §8
item 4). Escalate when:

- No matching skill exists for a task type that has been performed three or more times
  before in the project (absence of a skill for a repeated task is a gap that the architect
  should close, not something the model should work around ad hoc).

### 5.5 Agents / sub-agents

**Implementation:** `.github/agents/*.agent.md`, Claude Code's `Agent` tool (specialist
subagents: Explore, Plan, general-purpose, etc.). AT-O2 (Odysseus convergence, Ready)
investigates whether Odysseus's concept-graph agent loop is a complementary reasoning aid
for architecture-gap analysis.

**Status:** Implemented; AT-O2 pending.

#### Escalation triggers

Spawning sub-agents does not raise the competency ceiling; it only increases throughput
within it (see §8 item 5). Escalate when:

- Sub-agent output is internally inconsistent across two independent attempts on the same
  bounded sub-task with identical input (the task is above the raw-tier ceiling, not just
  noisy).

### 5.6 Prompt refinement

**Implementation:** [query-quality-checklists.md](../docs/query-quality-checklists.md) --
per-tier pre-query and pre-escalation checklists, evidence-priority table,
observe-reason-fix-reobserve cycle. **Note:** this doc's tier names (Tier R/C/M) predate
the Tier A/B/C budget tiers in `agentic-tiered-inference-strategy.md` -- they describe
*task* tiers (Routine/Complex/Math), not *infrastructure* tiers, and are not currently
cross-referenced against each other. This naming overlap is a minor source of confusion;
not addressed by this spec but flagged for a future docs pass.

**Status:** Implemented, naming overlap flagged.

#### Escalation triggers

Prompt refinement improves the odds of a well-posed question; it cannot turn a genuinely
ambiguous task into an unambiguous one (see §8 item 6). Escalate when:

- Two distinct reframings of the same query still produce the same class of error (the
  error is structural -- the model cannot reason over this input domain -- not lexical).
- The same structural error recurs after a cold-context retry with a minimal prompt (rules
  out context-window saturation as the cause).

### 5.7 Validation harnesses

**Implementation:** `_run_validator_pass` (`local-mcp.py` ~line 1868) -- per-step
orchestrator validation; SR-1.16 headless Electron harness for geometry/UI work.
SR-1.16 is product-specific (Electron-Splines geometry) and not part of the
repo-agnostic `skein-toolkit` toolset.

**Status:** Implemented for orchestrator steps; SR-1.16 is product-scoped, not
toolkit-scoped.

#### Escalation triggers

Validation harnesses catch deviations from expected values; they cannot catch a wrong
expectation encoded in the spec itself (see §8 item 7). Escalate when:

- CI fails on a change the model believes is correct, and the same error signature
  recurs across two retries with no change in the error output (the model has exhausted
  its ability to diagnose the root cause from harness output alone).
- The harness reports a pass but a human reviewer identifies a geometric or behavioral
  error not covered by any existing fixture (harness coverage gap rather than model error).

### 5.8 Ambiguity analysis / OQ escalation

**Implementation:** `paused_for_oq` orchestrator state (`local-mcp.py`), OQ mechanism
(`ai-model-selection-policy.md` §7.2), `oq-authoring-and-precedent-search-policy.md`
(materiality filter, mandatory precedent search). AT-1153 (Ready) extends
`create_open_question`/`create_actionable_task` with an Odysseus-Notes alternative mode.

**Status:** Implemented; AT-1153 extends it.

#### Escalation triggers

The OQ mechanism is only as good as the precedent search that precedes it; low-quality OQs
degrade the shared ledger (see §8 item 8). Escalate when:

- The architect responds "need more information" to an OQ twice for the same underlying
  question (the OQ is underspecified and the model cannot refine it further without
  human input on scope).
- A precedent search returns zero hits on a task that clearly has prior art in the project
  (the model failed to find existing decisions that should constrain the work; this warrants
  architect triage before proceeding).
- The model raises an OQ on a task where the materiality filter in
  `oq-authoring-and-precedent-search-policy.md` would have blocked the OQ (the model is
  not applying the filter correctly).

---

## 6. The Central Gap: RAG / Context-Surfacing for Weak Models

`cf-proxy-cheap-model-context-budget-roadmap.md` documents a chronic problem: `cf/gpt-oss-20b`
/`120b` produce degenerate empty responses (all tokens spent in the Harmony `analysis` /
reasoning channel, never reaching `final`) once a turn's prompt context reaches roughly
12-20K tokens of dense tool-result text (CB-1). The CB-1..CB-5 strategies tried so far --
compress tool results, tighten truncation, context-size-aware routing, expand the multi-step
action-verb list, per-step tool-call budgets -- are all **post-hoc**: they reduce or reroute
context *after* it has been assembled.

Odysseus's RAG-based tool surfacing (`reference_odysseus.md` item 5: "RAG-based tool surfacing
-- only relevant tools shown in context per query") and its ChromaDB + fastembed vector memory
are a **pre-hoc** approach: the weak model never sees the irrelevant fraction of the context in
the first place, because retrieval narrows what is assembled before the prompt is built.

AT-O1 (Ready, Odysseus convergence Phase 1) already tests a related but weaker hypothesis --
whether Odysseus's *context reordering* helps on >300KB spec reads. RAG-based retrieval is a
stronger version of the same idea: not reordering the same context, but *subsetting* it.

This is the highest-leverage item in this spec because it attacks CB-1's root cause (context
volume) rather than its symptom (degenerate output), and because the AT-1152 bridge means
Odysseus's retrieval machinery is already one MCP hop away from `skein-toolkit`'s orchestrator.

---

## 7. Refined High-Low Mix: Enablement-Adjusted Tiers

Define a model's *effective* capability for the high-low mix as a function of two
independent axes:

- **Raw tier**: the model itself (Tier A `cf/gpt-oss-120b`/`cf/kimi-k2.6`, Tier B Vast.ai,
  Tier C Claude Sonnet -- per `agentic-tiered-inference-strategy.md`).
- **Support level**:
  - **Bare** -- the model receives the task prompt and raw file contents directly. No
    decomposition, no RAG, no validator pass, no OQ path wired into the loop. This is the
    condition under which `ai-model-selection-policy.md` §5's empirical-floor observations
    were made.
  - **Enabled (SQEP)** -- the model receives a single bounded sub-task from a Task Manifest
    (§7.3 PEV), with RAG-narrowed context (once §6 is built), a skill-loaded procedure where
    one exists, a validator pass on its output, and a live OQ escalation path if it gets stuck.
  - **Advised** (AT-1173, 2026-06-18) -- a Tier-C executor (Sonnet 4.6 or Haiku 4.5) with
    Anthropic's `advisor_20260301` server-side tool wired in (beta header
    `anthropic-beta: advisor-tool-2026-03-01`), escalating to Opus 4.6 mid-call for hard
    sub-decisions via `max_uses`-capped consultation, all within a single Messages API call.
    Benchmarked: Haiku+advisor 19.7% -> 41.2% SWE-bench at 85% less cost than solo Sonnet;
    Sonnet+advisor 74.8% vs 72.1% solo Sonnet at lower cost than solo Opus. Billing: advisor
    tokens at Opus rates, executor tokens at Sonnet/Haiku rates -- the cost benefit holds only
    when most of a task's tokens flow through the cheap executor and the advisor is consulted
    sparingly. See `tier-c-cost-lever-evaluation-2026-06-18.md` for the full evaluation
    (GO recommendation) and the LiteLLM-passthrough question still open before this level can
    actually be wired into `litellm_config.yaml` routing.

**Hypothesis** (testable, directly serves the financial-feasibility goal in
`project_ai_toolchain.md`): a Tier A model at **Enabled** support level can correctly execute
tasks that §5 currently classifies as requiring Tier C at **Bare** support level -- specifically
Level 2 (Complex) tasks expressed as a single Task Manifest entry.

**What this hypothesis does NOT claim:** it does not move the Level 3 (Research) empirical
floor. Original mathematical derivation (G0 joint geometry, PH quintic correctness, novel
surface-integral algorithms) is not addressed by enablement -- a SQEP framework makes a
competent worker more productive and reliable *on defined work*; it does not make them a
research mathematician. The Level 3 boundary in §5/§7 of `ai-model-selection-policy.md` is
unchanged. The §7.2 "requires human insight" boundary is exactly where enablement stops
helping -- see §8.

---

## 8. The Competency Envelope -- What Enablement Does NOT Cover

A SQEP framework's defining feature is not just that it enables work -- it is that it makes the
*boundary* of enabled work explicit and checkable, so a worker (or model) operating inside the
envelope does not silently drift outside it. Per toolset element from §5:

1. **MCP**: provides tool access, not tool *judgment*. A model can call the wrong tool
   correctly. Does not reduce hallucinated tool names (`_KNOWN_TOOLS` / `_parse_any_tool_call`
   mitigate this at the parser level, not the model level).
2. **RAG** (once built, §6): narrows context to what is *indexed*. Cannot surface information
   that was never written down -- undocumented tribal knowledge remains an OQ trigger, not a
   retrieval failure.
3. **Task decomposition / PEV**: only as good as the manifest. "If an executor needs to
   interpret an entry, the manifest is underspecified -- the planner revises it" (§7.3).
   Decomposition does not compensate for an ambiguous Plan phase; garbage in, garbage out.
4. **Skills**: encode known procedures. A skill cannot exist for a problem that has never been
   solved before -- novel problems are by definition outside skill coverage.
5. **Agents/sub-agents**: parallelize and isolate context, but a sub-agent inherits the same
   raw-tier ceiling as its parent. Spawning more agents does not raise the competency ceiling,
   only the throughput within it.
6. **Prompt refinement**: improves the odds the model receives a well-posed question. Cannot
   turn a genuinely ambiguous task into an unambiguous one -- that's what OQ is for.
7. **Validation harnesses**: catch deviations from *expected* values. Cannot catch "the spec
   itself encodes the wrong expectation" -- that is a Level 3 / human-insight question, not a
   validator defect.
8. **OQ escalation**: only as good as the precedent search that precedes it
   (`oq-authoring-and-precedent-search-policy.md`). A model that skips precedent search and
   raises a low-materiality OQ degrades the mechanism for everyone reading the OQ ledger.

**The rule that keeps this from becoming silent over-trust:** enablement raises the ceiling of
work a Tier A model can be *assigned*; it does not remove the requirement that the model
recognize when a task has left its envelope and raise an OQ rather than improvise. This is the
same rule `ai-model-selection-policy.md` §7.2 already states for human-vs-model responsibility
-- this spec does not add a new rule, it makes the existing rule explicit per toolset element so
an "Enabled" Tier A agent has a checkable list rather than a vague instinct.

---

## 9. Relationship to Odysseus Convergence

This spec is the financial-feasibility "why" behind the Odysseus convergence track:

- **AT-1151/1152 (done)**: `skein-toolkit` <-> Odysseus MCP bridge verified, zero code changes.
  This is the infrastructure precondition for §6.
- **AT-1153 (Ready)**: Odysseus-Notes alternative mode for the OQ/AT ledger -- strengthens
  toolset item 8 (§5).
- **AT-O1/AT-O2 (Ready, Phase 1)**: controlled experiments on context reordering and
  concept-graph reasoning. §6's RAG proposal (AT-1156) is a focused, stronger follow-on to AT-O1
  aimed specifically at CB-1, using the AT-1152 bridge.
- **AT-1156/1157/1158 (this spec, §10)**: the next layer -- use the bridge to enable Tier A,
  then measure whether that changes the §7 high-low mix.

---

## 10. New AT Items

| ID | Task | Spec / Issue | Exit Evidence | Effort |
|----|------|-------------|---------------|--------|
| AT-1156 | **RAG-based context/tool surfacing for Tier A sessions.** Agent: `docs`/`research`. Model: Level-2. Research Odysseus's RAG implementation (ChromaDB + fastembed vector memory, `src/agent_loop.py` RAG-based tool surfacing) and design how `skein-toolkit`'s orchestrator context assembly could adopt retrieval-based context narrowing for CF Tier A models, directly targeting CB-1 (degenerate-empty-response above ~12-20K tokens). Use the AT-1152 SSE bridge as the integration point. Produce a design note with a go/no-go recommendation and, if GO, a scoped prototype task. Depends on: AT-1152 (done). | This spec §6, AT-O1, `reference_odysseus.md`, `cf-proxy-cheap-model-context-budget-roadmap.md` | Design note written (in `skein-toolkit/docs/` or `foundation/SR-1.4-ai-guidance/docs/`) with go/no-go recommendation; if GO, a follow-up AT is registered. | Medium |
| AT-1157 | **Enablement-adjusted tier experiment.** Agent: `orchestrator`. Model: Level-2. Select 5 representative Level-2 (Complex) tasks. Execute each via the CF proxy orchestrator at Tier A (`cf/gpt-oss-120b` or `cf/kimi-k2.6`) with full "Enabled" support (PEV manifest decomposition, validator pass, live OQ escalation path). Score against `odysseus-convergence-experiment-protocol.md`'s rubric (accuracy, speed, token cost) and compare to the existing Tier C baseline for equivalent past tasks where available. Depends on: AT-1140 (done, proves Tier A can complete a 9-step plan mechanically). | This spec §7, `agentic-tiered-inference-strategy.md`, `odysseus-convergence-experiment-protocol.md` | Run log with a pass-rate/quality comparison table (Tier A+Enabled vs Tier C+Bare) for 5 tasks; verdict recorded: shift the §7 Level-2 default, keep as-is, or raise an OQ if results are ambiguous (no clear winner within the AT-O1/AT-O2 ±5% convention). | Medium |
| AT-1158 | **Escalation-trigger subsections for the enablement toolset inventory.** Agent: `docs`. Model: Level-1. Add a short "Escalation triggers" subsection to each of the 8 items in this spec's §5, drawing on the competency-envelope notes already in §8, and cross-reference them from `query-quality-checklists.md`'s pre-escalation gates (§2.1, §3.1, §4.2). | This spec §8, `query-quality-checklists.md` | §5 of this spec has 8 "Escalation triggers" subsections; `query-quality-checklists.md` cross-references this spec from its pre-escalation sections. | Small |

---

## 11. Acceptance Criteria

- AC-1: This spec is listed in `architecture-docs/specs/INDEX.md` with SR-1.4 ownership and
  status Draft.
- AC-2: AT-1156, AT-1157, AT-1158 are registered in `architecture-docs/global/ai-task-queue.md`.
- AC-3: `ai-model-selection-policy.md` and `agentic-tiered-inference-strategy.md` each carry a
  cross-reference to this spec as the enablement-toolset companion.
- AC-4: AT-1157's experiment produces a pass-rate/quality comparison for at least 5 Level-2
  tasks before any change is made to the §7 Level-2 default in `ai-model-selection-policy.md`.
  This spec does not itself change §7 -- it only proposes the experiment that would justify
  changing it.
