# Spec: AI Model Selection Policy

**Date:** 2026-05-25
**Status:** Draft
**Type:** Governance / AI Toolchain
**Consolidated into:** [unified-ai-strategy.md](../docs/unified-ai-strategy.md)
**Canonical:** false

**Companion doc:** [query-quality-checklists.md](../docs/query-quality-checklists.md) —
per-tier checklists for query preparation and pre-escalation gates.

**Terminology note (AT-1232, 2026-06-18):** this spec names its three tiers
Level-1/Level-2/Level-3 (§5 below). `ai-task-queue.md`'s Task Authoring
Policy header, and every AT row's `Model:` annotation written against it,
instead uses **Tier-R / Tier-C / Tier-M**. The two namings drifted apart
without either being updated to match the other. Mapping (1:1, same
boundaries, no semantic change):

| This spec | `ai-task-queue.md` |
|---|---|
| Level-1 (Routine) | Tier-R |
| Level-2 (Complex) | Tier-C |
| Level-3 (Research) | Tier-M |

Any AT row's `Model: Tier-R/Tier-C/Tier-M` annotation should be read as
referring to this spec's Level-1/2/3 respectively. New writing should prefer
`Tier-R/C/M` to match the much larger body of existing AT rows; this spec's
internal Level-1/2/3 naming is left as-is below rather than mass-renamed, to
avoid churn risk in a long, heavily-cross-referenced document for a pure
naming change.

**Enablement framework:** [model-enablement-toolset-strategy.md](model-enablement-toolset-strategy.md)
— the adjacent-toolset (MCP/RAG/decomposition/skills/validation/OQ) framework for raising a
cheap model's *effective* tier ("SQEP enablement"). §7 of this policy's Level 2 default
(Cloud-API) is the subject of AT-1157's planned experiment in that spec — this policy is not
changed by that spec until AT-1157 produces evidence.

---

## 1. Design-Goal Linkage

- Primary system requirement: SR-1.4 — AI toolchain governance
  ([architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md))

This spec defines which AI model (or model tier) should be used for each class of task in this
project, and the constraints that govern that selection.

---

## 2. Problem Statement

This project spans multiple task types with radically different complexity profiles. At one
extreme, generating a GUI button or a simple TypeScript refactor is well-covered by any coding
model's training data and executes quickly. At the other extreme, deriving novel G0 continuity
joint geometry, designing surface-integral sweep algorithms, or debugging a custom ray tracer
involves mathematics that has no direct precedent in any model's training corpus. Using the same
model for both classes wastes capability on easy work and produces inadequate results on hard work.

A second constraint is cost. If cloud model pricing increases to a commercially unviable level,
the project must have a credible local path for all task classes. Cost is the primary driver of
the local-first tier hierarchy.

A third constraint is IP protection. The G0 joint algorithm and sweep pipeline represent
significant proprietary development. Any cloud API transmits prompt content to third-party servers.
IP protection is a secondary preference — prefer local execution when local capability is adequate,
but do not block task execution waiting for a local-only path. Self-provisioned cloud inference
(§6 Inference: Cloud-Batch) may be more privacy-preserving than managed APIs, since open-weights models
running on rented hardware carry no data retention obligations.

---

## 3. Scope

In scope:

- Task classification: mapping work types to the model tier best suited to each
- Model tier definitions: capability, VRAM/RAM requirements, provider, data-sovereignty classification
- Selection decision rules: given a task, which tier to use and when to escalate
- Hardware constraints: what can run on the current development machine
- IP constraints: which providers are permitted for sensitive work
- VS Code Copilot Chat configuration: how tiers are activated in the development environment

Out of scope:

- Prompt engineering techniques (covered by CLAUDE.md and skills)
- Agent delegation and tool-boundary contracts (covered by agentic-coding-governance.md)
- CI/CD model usage (not currently in scope)

---

## 4. Constraints

### 4.1 IP / Data Sovereignty Constraint

IP protection is a secondary preference — prefer local execution when local model capability is
adequate for the task. Do not block task execution on IP grounds alone. Specifically:

- **Permitted cloud providers**: Anthropic (US, explicit API no-training policy), Google AI
  (US, explicit API no-training policy), OpenAI (US, explicit API no-training policy).
- **Prohibited cloud APIs**: Any provider operated by or subject to the laws of a government
  whose intelligence-sharing arrangements are not consistent with protecting proprietary IP.
  Chinese-government-affiliated APIs (deepseek.com, Alibaba/Qianwen cloud) are specifically
  excluded from cloud use regardless of IP classification.
- **Self-provisioned cloud inference** (Vast.ai, RunPod running open-weights models) carries no
  managed data retention obligation. Treat as permitted for IP-sensitive tasks when local
  throughput is insufficient. The weights themselves are static open data; no training feedback
  loop applies.
- **Local inference is always permitted**: Model weights downloaded and run via Ollama on the
  developer machine involve no data transmission. US-origin and European-origin weights are
  preferred; open-weight models from any origin may be run locally. This explicitly includes
  DeepSeek-R1 distilled variants (`deepseek-r1:32b`, `deepseek-r1:70b`) and Qwen3 open weights
  -- the deepseek.com and Alibaba cloud API prohibitions above do not apply to self-hosted weights.
  The restriction targets data transmission to vendor servers, not the static model files.

### 4.2 Hardware Constraint (Current Development Machine)

This machine serves as the sole local inference server. All Ollama inference runs on this hardware.

| Component | Specification |
|-----------|---------------|
| CPU | Intel Core i9-13900K (24 cores / 32 threads, 3.0 GHz base / 5.8 GHz boost) |
| Motherboard | ASUS ROG STRIX Z790-H GAMING WIFI (Rev 1.xx) |
| GPU | NVIDIA GeForce RTX 3070, 8 GB GDDR6 VRAM |
| Display GPU | Intel UHD Graphics 770 (integrated, 2 GB, drives display output) |
| System RAM | 64 GB |
| Storage (primary) | Samsung SSD 990 PRO 1 TB (NVMe/PCIe) |
| Storage (secondary) | Kingston SA2000M 1 TB (NVMe/PCIe), Samsung SSD 860 PRO 512 GB (SATA), Samsung SSD 750 EVO 250 GB (SATA) |
| Local inference backend | Ollama at `http://localhost:11434` |

The Intel UHD 770 handles display output, leaving the RTX 3070 free for dedicated inference use
when both GPUs are installed and the display is connected to the integrated output.

Models exceeding 8 GB VRAM will be partially offloaded to system RAM (64 GB available) by Ollama.
For overnight batch runs, if local Inference: Local-Agent throughput with RAM offload is insufficient to drain the
task queue within the available window (~5–10 hours), Inference: Cloud-Batch (self-provisioned, see §6) is
the preferred alternative — not an upgrade to managed API.

### 4.3 Speed Constraint

Speed is **not a primary selection criterion** for the geometry and mathematics task class. A
model that takes 10 minutes to produce a correct derivation is preferable to a model that produces
an incorrect derivation in 30 seconds.

Speed is a secondary consideration for routine task classes (completions, small refactors) where
long waits degrade workflow momentum.

---

## 5. Task Classification

Tasks are classified into three levels by mathematical novelty and codebase scope.

### Level 1 — Routine

**Characteristics:** Well-precedented in training data. Little or no novel mathematics.
Output can be verified quickly by visual inspection or a fast test run.

Examples:
- GUI components, buttons, panels, CSS/layout
- Single-file TypeScript refactors with clear before/after
- Documentation updates
- Simple OpenSCAD utility functions with known geometry
- Import reorganization, lint fixes, rename operations
- Writing unit test boilerplate for already-specified behavior

### Level 2 — Complex

**Characteristics:** Multi-file scope, or requires understanding the project's existing
architectural patterns, or involves moderate algorithmic reasoning that is partially covered by
training data. Requires multi-step planning but not original mathematical derivation.

Examples:
- Multi-file TypeScript features following existing patterns (serialization, undo, UI wiring)
- Agent-mode tasks that require reading and modifying several files consistently
- Debugging TypeScript runtime errors with known error categories
- OpenSCAD pipeline stage additions that follow existing stage contracts
- Integration of a third-party library

### Level 3 — Research

**Characteristics:** Requires derivation of original mathematics or algorithmic reasoning that has
no direct precedent in the model's training corpus. Correctness cannot be verified without domain
expertise or geometric rendering. This is the tier that describes the core of this project.

Examples:
- G0 continuity joint geometry — bisector plane derivation, frame transport at joints
- Swept surface definition using surface integrals — profile sampling, curvature continuity
- PH quintic Hermite interpolation — arc length parameterization, osculating frame computation
- Custom ray-triangle intersection for the built-in ray tracer
- Novel OpenSCAD geometry algorithms with no established pattern to follow
- Mathematical debugging: understanding why a rendered joint produces a mohawk artifact

**Empirical model floor (6-month observation):** Inference: Cloud-API (Claude Sonnet) is the
minimum *effective* starting point for this task class in this project's domain. Inference: Local-Agent
models (phi4-reasoning, deepseek-r1:32b) produce frequent incorrect derivations on PH quintic
interpolation, frame transport, and Omega surface mathematics. This contradicts the theoretical
escalation path below — in practice, start Level 3 at Cloud-API; use Local-Agent only when Cloud-API is
unavailable or the task is primarily an implementation exercise with a fully-specified algorithm.

**Task reducibility principle:** Before assigning a Level 3 label, assess whether the task
can be decomposed into bounded sub-tasks (see §7.0 reducibility gate and §7.3 Plan-Execute-Verify).
A well-decomposed Level 3 task often reduces to a sequence of Level 2 sub-tasks, each within the
competency envelope of a cheaper model. Decomposition is cheaper than model escalation and produces
more verifiable results. Use PEV (§7.3) when decomposition produces many parallel Level 1 tasks.

---

## 6. Inference Tiers

### Inference: Local-Fast — Quick Completions

**Model:** `qwen2.5-coder:7b` (primary), `codellama:latest` (secondary)
**Size:** ~4–5 GB (fits entirely in 8 GB VRAM)
**Speed:** 8–20 tokens/sec
**Origin:** Alibaba (Qwen) / Meta (CodeLlama) — weights run locally, no data transmission
**Suitable for:** Level 1 tasks. Quick completions, inline suggestions.
**Not suitable for:** Multi-file agent tasks, novel mathematics.

Pull command:
```
ollama pull qwen2.5-coder:7b
```

### Inference: Local-Reason — Reasoning Consultation (non-agentic)

**Models:** `phi4-reasoning`, `deepseek-r1:14b`, `deepseek-r1:32b`
**Size:** ~9–20 GB (partial RAM offload)
**Ollama capabilities:** `completion` + `thinking` only — **no tool calling**
**Speed:** 8–15 tokens/sec (phi4-reasoning at partial VRAM)
**Origin:** Microsoft / DeepSeek — weights run locally, no data transmission
**Usage mode:** Manual consultation via terminal (`ollama run phi4-reasoning`), NOT via Copilot Chat
agent. These models cannot call tools (read files, run commands, make git commits). They are
single-turn reasoning engines: assemble the relevant context into one prompt, run it, read the
output, then carry the result back into an agentic workflow manually.
**Suitable for:** Hard mathematical derivations, algorithm proofs, geometry debugging where you
need extended chain-of-thought before writing any code.
**Not suitable for:** Any task requiring tool calls, file reads, multi-turn agent loops, or
appearing in the VS Code Copilot Chat model picker (they will not appear — no tools capability).

Pull commands:
```
ollama pull phi4-reasoning
ollama pull deepseek-r1:14b
```

Reasoning models spend many internal tokens working through a problem before producing output.
This is the desired behavior — do not mistake it for slowness or failure.

### Inference: Local-Agent — Agentic Execution

**Primary model:** `deepseek-r1:32b` (R1-Distill-Qwen-32B)
**Size:** ~20 GB (partial GPU offload — significant VRAM utilisation on RTX 3070)
**Ollama capabilities:** `completion` + `thinking` — agent use via Continue.dev openai provider
**Speed:** 4–10 tokens/sec (partial GPU offload on RTX 3070)
**Origin:** DeepSeek open weights, Qwen2.5-32B base — self-hosted, no data transmission
**Usage mode:** Continue.dev agent mode with `provider: openai` pointing at `http://localhost:11434/v1`.
Supports tool calling via the OpenAI-compatible endpoint. Combines R1 chain-of-thought reasoning
with the Qwen2.5-32B coding base, which outperforms Llama 70B on code and mathematical benchmarks.
**Suitable for:** Primary local agent model. Geometric/algorithmic debugging (Omega trace, frame
transport, joint classification). Overnight batch runs. Privacy-sensitive Level 2/3 tasks.
**Preferred over `llama3.3:70b`**: 2-4x faster, stronger reasoning, better partial GPU utilisation.

**Escalation model:** `deepseek-r1:70b` (R1-Distill-Llama-70B)
**Size:** ~43 GB (heavy RAM offload — 90% CPU / 10% GPU)
**Speed:** 1–3 tokens/sec
**Usage mode:** Same as primary — Continue.dev openai provider. Use when 32B loses the reasoning
thread on very long multi-step debugging chains that require holding many interdependent facts.
**Also available:** `llama3.3:70b` — US-origin (Meta), confirmed working in both VS Code Copilot
Chat BYOK and Continue.dev. Use as the VS Code Copilot Chat agent when the model picker path is
required (R1 distills may not appear in the picker depending on Ollama capabilities tag).

Pull commands:
```
ollama pull deepseek-r1:32b
ollama pull deepseek-r1:70b
ollama pull llama3.3:70b
```

### Cloud Inference Tiers

Three infrastructure options exist. All require architect approval (§7.1).
The choice is made at batch dispatch time, not per-task.

#### Inference: Cloud-Batch — Self-Provisioned (Overnight)

**Infrastructure:** Vast.ai or RunPod spot instances
**Models:** Open-weights models running on rented GPU hardware. Recommended targets for scale:
- `deepseek-r1:32b` / `deepseek-r1:70b` — single A100 80GB, strong reasoning, ~$0.80–1.50/hr
- `Qwen3-235B-A22B` Q4 (MoE, 22B active params) — 2x A100 80GB, ~$2–4/hr, high throughput
- `DeepSeek-R1 671B` Q4 (MoE, 37B active params) — 8x A100 80GB, ~$12–18/hr, maximum quality
**Cost:** ~$0.80–18/hr depending on model and GPU configuration; suitable for 5–10 hr overnight runs
**Inference server:** Prefer vLLM over Ollama for multi-GPU instances (3-5x better throughput)
  via `python -m vllm.entrypoints.openai.api_server`. Continue.dev `provider: openai` connects
  directly to vLLM's `/v1` endpoint.
**Data policy:** No managed data retention obligation. Open-weights models carry no training
feedback loop. More privacy-preserving than managed APIs for IP-sensitive work.
**Suitable for:** Level 3 overnight batch tasks where Inference: Local-Agent RAM-offload throughput is
insufficient to drain the queue. Preferred over Cloud-API when task volume justifies a dedicated instance.
**Not suitable for:** Interactive daytime sessions (setup overhead; not always-on).

Setup: spin up on demand, run the batch queue, shut down.

#### Inference: Cloud-API — Managed API (Interactive)

**Model:** Claude (Anthropic API direct)
**Provider:** Anthropic (US)
**Data policy:** Anthropic API does not use API inputs for training. Explicit in Anthropic's usage policy.
**Cost:** Higher unit cost than Cloud-Batch for equivalent compute. Suitable for interactive Level 2 tasks
where always-on availability matters.
**Suitable for:** Level 2 tasks requiring whole-project context, multi-file agent execution, and
high-quality instruction following. Also suitable for Level 3 escalation during interactive sessions.
**Not suitable for:** Long overnight batch runs where Cloud-Batch would be significantly cheaper.

Configuration: accessed via Anthropic API key, not via GitHub Copilot.

#### Inference: Cloud-Surge — SOTA Models (Exceptional Cases)

**Models:** o3, o3-pro (OpenAI), Gemini 2.5 Pro (Google), Claude Opus 4 (Anthropic)
**Cost (indicative, May 2026):**

| Model | Input ($/MTok) | Output ($/MTok) | Notes |
|-------|---------------|-----------------|-------|
| o3-mini | $1.10 | $4.40 | Fastest reasoning tier |
| o3 | $10 | $40 | Full reasoning depth |
| o3-pro | $20 | $80 | Maximum reasoning; async only |
| Gemini 2.5 Pro | $1.25 | $10 | 1M context window |
| Claude Opus 4 | $15 | $75 | Highest Anthropic tier |

*MTok = million tokens. One complex agent task with full codebase context: ~50–200K tokens total.*

**Data policy:** OpenAI and Google both offer explicit API no-training commitments. Same IP
protection tier as Cloud-API.
**Approval:** Requires explicit budget-level architect approval beyond standard cloud approval
(see §7.1). Surge use must be logged with justification: what Cloud-API attempted, why it failed.
**When to use:** A Level 3 task where Inference: Cloud-API (Claude Sonnet) has failed after 2–3
well-decomposed, well-contextualized attempts. Not a routine escalation — surge is exceptional.
The bar is: Cloud-API produced incorrect mathematics or contradicted established contracts, not merely
that Cloud-API was slow or produced imperfect style.
**What surge buys:** Deeper mathematical first-principles reasoning, larger effective working
memory for multi-step derivations, stronger ability to hold long dependency chains.
**What surge does not buy:** Immunity to wrong answers. A surge model can also fail on genuinely
novel mathematics. If Cloud-Surge also fails, the problem requires human original research (see §7.2).
**Suitable for:** Omega architecture derivations, PH quintic correctness proofs, novel geometric
algorithm design where Cloud-API has demonstrably failed.
**Not suitable for:** Routine escalation, cost-saving (it costs more, not less), tasks where
the root cause of Cloud-API failure was underspecified context rather than model capability.

---

## 7. Selection Decision Rules

```
Given a task:

0. REDUCIBILITY GATE (apply before any model selection decision)
   Ask: can this task be decomposed into bounded sub-tasks with explicit contracts,
   each of which is independently verifiable and within the Level 2 (Complex) competency envelope?
   -> If yes: decompose. Use the task-decomposition skill. Assign sub-tasks as Level 2.
      This is always cheaper and produces more verifiable results than model escalation.
      If decomposition produces many parallel Level 1 tasks: use PEV (§7.3) to have a
      high-tier model plan them and cheap executors run them.
   -> If no (task requires unified mathematical derivation that cannot be split):
      proceed to step 1.
   -> If unsure: raise an OQ (see §7.2). Do not guess at scope.

1. Classify the task as Level 1 (Routine), Level 2 (Complex), or Level 3 (Research).

2. If Level 1 (Routine):
   -> Use Inference: Local-Fast. Do not involve cloud models for routine work.
   -> If blocked by ambiguity: raise an OQ (§7.2). Do not escalate model for clarity issues.

3. If Level 2 (Complex):
   -> STOP. Obtain architect approval before invoking any cloud model (see §7.1).
   -> Once approved: use Inference: Cloud-API (Claude Sonnet via Anthropic API).
   -> If cloud unavailable or cost-prohibited: use Inference: Local-Agent (deepseek-r1:32b)
      via Continue.dev openai provider. Expect reduced quality; log the degradation.
   -> If blocked by ambiguity: raise an OQ (§7.2).

4. If Level 3 (Research):
   -> FIRST: apply the reducibility gate (step 0). Most apparent Level 3 tasks can be
      partially decomposed. A Level 3 model should plan the decomposition; cheaper models
      execute (see §7.3 Plan-Execute-Verify).
   -> Start at Inference: Cloud-API (Claude Sonnet). Empirical floor — see §5 Level 3 note.
      Requires architect approval per §7.1.
   -> If Cloud-API cannot produce a correct result after 2-3 well-decomposed, well-
      contextualized attempts: STOP. Raise a failure report and request Surge approval.
   -> Once Surge approved: use Inference: Cloud-Surge (o3-mini first; o3 if o3-mini fails).
      Log: what Cloud-API attempted, specific failure mode, why it indicates model ceiling
      rather than context/decomposition issue.
   -> If Inference: Cloud-Surge also cannot solve the problem: raise an OQ (§7.2). The problem
      may require human original mathematical insight or a spec revision.
   -> Inference: Local-Agent (deepseek-r1:32b) is appropriate for Level 3 only when:
      (a) Cloud-API is unavailable, (b) the algorithm is fully specified and the task is
      implementation-only, or (c) the architect explicitly assigns local-only.

5. IP preference: Prefer local execution (Local-Fast or Local-Agent) for tasks involving novel
   algorithmic IP when local throughput is adequate for the workload. This is a preference,
   not a gate — do not block task execution on IP grounds alone. For overnight batch runs
   where Inference: Local-Agent throughput is insufficient, Inference: Cloud-Batch
   (self-provisioned, open-weights) is the preferred cloud path for IP-sensitive tasks.
```

### §7.2 Human System Architect Role

The human System Architect is not a model tier. The human is a cross-cutting collaborator
who operates alongside all tiers simultaneously. The division of responsibility is fixed:

**Human responsibilities (apply at all tiers):**
- Strategic direction: project objectives, priorities, what to build and why
- Architectural choices: design decisions that have long-term structural consequences
- Ambiguity resolution: when a task scope is genuinely unclear, the human defines it
- Validation: the human is the final arbiter of whether a result is correct and acceptable
- Coordination: directing work across agents, managing the task queue, sequencing batches

**Model responsibilities (apply at all tiers):**
- Writing code, tests, documentation, and specifications
- Executing multi-step agent tasks: reading files, running builds, making commits
- Raising OQs when blocked (see below)
- Not: making architectural decisions unilaterally, not: validating their own correctness

**The OQ (Architect Open Question) mechanism — available to all tiers:**
Any model at any tier may raise an OQ when:
- The task scope is genuinely ambiguous and proceeding in the wrong direction risks
  significant wasted work (not: minor uncertainties that can be resolved conservatively)
- A decision requires architectural judgment that is outside the model's authority
- The task cannot be completed without information the model does not have access to

OQs are filed in `architecture-docs/global/architect-open-questions.md`. A model raising an
OQ should: (1) document what is known, (2) document the specific blocking question,
(3) propose a conservative default action if the architect does not respond.
Do not block all work waiting for an OQ — move to other tasks and return when resolved.
A Level 1 model raising an OQ is not a failure; it is the correct response to genuine ambiguity.

**What "requires human insight" actually means:**
When a Level 3 problem exceeds even Surge (Cloud-Surge) model capability, the correct interpretation
is: this problem requires original mathematical research that no current model can substitute
for. The human must either (a) derive the mathematics and provide it as a spec for the model
to implement, or (b) revise the task to a form that is within the model frontier. The outcome
is always a new spec or contract — not the human writing code directly.

### §7.3 Plan-Execute-Verify (PEV) Protocol

When a Level 3 task decomposes into many atomic sub-tasks, the most cost-effective execution
pattern uses the expensive model for planning and verification only — not execution.

**The three phases:**

**Plan** (Inference: Cloud-Surge or Cloud-API) — The high-tier model consumes the architect
directive and produces a **Task Manifest**: a structured list of atomic task entries. Each entry
specifies the exact file(s), change, verification command, and done-criterion with no ambiguity.
Human checkpoint: the architect reviews and approves the manifest before any executor is dispatched.

**Execute** (Level 1 or Level 2, as assigned per-task in the manifest) — Each executor reads one
entry directly from the manifest and produces an output artifact. No interpretation, no improvisation.
If an entry is unclear, execution stops and the manifest is returned to the planner for revision.

**Verify** (same tier as Planner — Cloud-Surge or Cloud-API) — The planner-tier model receives all
output artifacts and checks each against the manifest's done-criteria. It produces a verification
report: pass/fail per task, issues, and a recommended next action.
Human checkpoint: the architect reviews the report before the overall task is considered done.

**The Chinese Whispers principle — models produce artifacts, not messages:**

Information degrades when models relay instructions through each other. This protocol prevents
that by design:

- **Models are Planners or Executors — never relays.** No model rephrases instructions for another
  model. Executors read the manifest directly — they do not receive instructions via an intermediate
  tier.
- **Maximum two hops: Planner -> Executor.** If Level 3 decomposes into a mix of Level 2 and Level 1
  sub-tasks, Level 3 writes both sections of the manifest. Level 2 and Level 1 read their own
  sections independently — they do not relay to each other.
- **Manifest entries must be unambiguous.** If an executor needs to interpret an entry, the manifest
  is underspecified — the planner revises it. Ambiguous entries are returned, not improvised around.
- **The verifier is always the planner tier.** A Level 1 executor does not verify a Level 3 plan.
  The same model tier that wrote the contracts checks whether they were met.

**Task Manifest — minimum fields per entry:**

```
Task-ID:    <TM-NNN>
Tier:       <Level-1 | Level-2>
File:       <exact file path(s)>
Change:     <exact, unambiguous specification — no interpretation required>
Verify-cmd: <exact shell command>
Done:       <what passing looks like, e.g. "exit code 0, no new test failures">
Depends-on: <TM-NNN, ... | none>
```

**When NOT to use PEV:**
- Sub-tasks are interdependent such that each executor requires output from a prior executor
  to proceed — in that case a single context-holding Level 2/3 agent handles the sequence.
- Fewer than ~5 sub-tasks: the manifest overhead is not worth the savings.
- Verification requires the planner to re-read all execution artifacts at higher cost than
  completing the task directly at the planner tier.

---

### 7.1 Cloud Approval Gate

Any use of cloud inference incurs direct, real-money costs per token. No agent
may invoke a cloud model without explicit architect approval for that task or session.

**Approval can be granted in three ways:**

1. **Task-level approval**: The `Model: Level-2` annotation in the AT task row serves as standing
   approval for that specific task. The architect sets this annotation when creating or curating
   the task, meaning approval is implicit in staging the task into a READY batch.
2. **Session approval**: The architect sends an explicit message such as `cloud approved` or
   `/approve-cloud` during the active session. Valid for the current session only.
3. **Escalation approval**: For a Level 3 task escalating to cloud after local failure, the agent
   stops and reports the local failure to the architect. The architect approves or redirects.

**Overnight batch infrastructure choice**: For batches dispatched via `/tok` that include Level 2
or escalated Level 3 tasks, the executing agent defaults to Inference: Cloud-API unless
the architect specifies otherwise in the dispatch message. To use Inference: Cloud-Batch (self-provisioned)
for a batch, the architect adds a note to the `/tok` dispatch (e.g., `C1 batch — spin up Vast.ai`).
The infrastructure choice is a batch-level decision; individual task rows do not specify Cloud-Batch vs Cloud-API.

**Approval is NOT carried over between sessions.** Each new tik/tok batch that contains Level 2
tasks was explicitly staged by the architect, satisfying the task-level approval requirement.

**When approval is absent**, the agent must:
1. Log the missing approval in the task row: `(Cloud blocked — no approval. Attempted
   Inference: Local-Agent with reduced quality.)`
2. Attempt the task using Inference: Local-Agent (llama3.3:70b) and record the quality difference.
3. Do not silently invoke cloud to compensate for a local model's limitations.

---

## 8. VS Code Copilot Chat Configuration

The Ollama endpoint is configured in VS Code user `settings.json`:

```json
"github.copilot.chat.byok.ollamaEndpoint": "http://localhost:11434"
```

To select a local model as the implement (edit) agent, set:

```json
"github.copilot.chat.implementAgent.model": "<model-id-from-VS-Code-model-picker>"
```

The exact model ID string must be read from the VS Code Copilot Chat model picker UI (the ID
assigned by VS Code's Language Model API is not always identical to the Ollama model name).

For routine completions, Inference: Local-Fast (`qwen2.5-coder:7b`) should be selected in the
completions model picker. For mathematical work sessions, switch the chat model to Inference: Local-Agent.

**Remote inference (dev server as inference backend):** When the local machine lacks sufficient
GPU to run the required models, `localhost:11434` can be transparently served from the Vast.ai
dev server via SSH port forwarding. The BYOK endpoint and Continue.dev `apiBase` settings do not
change — both already point to `http://localhost:11434`. The tunnel is established automatically
when VS Code Remote-SSH connects via `launch-devserver.ps1`, which writes
`LocalForward 11434 localhost:11434` into the SSH config for the `vast-devserver` host. The dev
server's Ollama service must be running as a systemd daemon bound to all interfaces
(`OLLAMA_HOST=0.0.0.0:11434`) — see `provision-devserver.sh` step 4. When using the dev server
for interactive sessions, prefer a persistent (non-spot) instance or ensure the Ollama service
recovers on restart; a session drop silently breaks inference with no client-side error.

### 8.1 Known Limitation: VS Code Copilot BYOK + Ollama Tool Call Roundtrip

The BYOK Ollama integration works via the VS Code Language Model API. A model appearing in the
Copilot Chat model picker (i.e., having Ollama `tools` capability) is a necessary but not
sufficient condition for working agentic tool calls. The framework must also correctly execute
the request -> model outputs `tool_calls` -> VS Code intercepts -> executes tool -> returns
result cycle. In practice, several models output tool call syntax as plain text in the completion
rather than as structured `tool_calls` in the API response, breaking the loop.

**Verified working in Copilot Chat BYOK as of 2026-05-26:**
- `llama3.3:70b` — confirmed working

**Known broken in Copilot Chat BYOK (outputs XML as text):**
- `qwen3.6:latest` — emits raw XML tool call syntax, never receives results back

**Known broken in Continue.dev with `provider: ollama` (outputs raw JSON tool calls as text):**
- `qwen2.5-coder:7b` — intercepted by Continue but model stops generating after tool call JSON;
  agent loop does not complete. Works as a chat model but not as an agent.

**Note:** The `provider: ollama` Continue.dev configuration uses text-based tool parsing. Switch
to `provider: openai` with `apiBase: http://localhost:11434/v1` to use structured API function
calling, which completes the agent loop correctly. See §8.2.

### 8.2 Alternative Local Agent Clients (Lines of Inquiry)

The community uses dedicated local AI coding clients that implement their own Ollama tool call
protocol, bypassing the VS Code LM API BYOK layer entirely. These are promising alternatives
to investigate when Copilot BYOK + Ollama is insufficient.

**Continue.dev** (VS Code extension `Continue.continue`, 3M+ installs)
- Has its own agent mode with tool calling independent of Copilot Chat BYOK
- Config: `~/.continue/config.yaml` — requires schema v1 top-level fields: `name`, `version`, `schema`
- **Critical:** Use `provider: openai` with `apiBase: http://localhost:11434/v1` (not `provider: ollama`).
  The `ollama` provider uses text-based tool parsing; the `openai` provider uses structured API
  function calling which correctly completes the agent loop.
- Status: **Partially working** — `llama3.3:70b` confirmed working via openai provider (2026-05-26).
  `deepseek-r1:32b` is the recommended primary; test and verify tool call roundtrip.

Working config entry:
```yaml
name: Local Ollama
version: 1.0.0
schema: v1
models:
  - name: deepseek-r1:32b
    provider: openai
    model: deepseek-r1:32b
    apiBase: http://localhost:11434/v1
    apiKey: ollama
  - name: llama3.3:70b
    provider: openai
    model: llama3.3:70b
    apiBase: http://localhost:11434/v1
    apiKey: ollama
```

**Cline** (VS Code extension, popular for agentic local LLM coding)
- Agentic-first design, manages tool call loop itself
- Supports Ollama OpenAI-compatible endpoint (`http://localhost:11434/v1`)
- Status: **to evaluate** — alternative if Continue.dev agent mode proves unreliable

**Aider** (terminal-based, no VS Code dependency)
- Direct Ollama integration via OpenAI-compatible endpoint
- Tool call roundtrip managed entirely by Aider, model output format issues are less common
- Best-in-class benchmark scores for local code editing (see aider.chat/docs/leaderboards)
- Status: **to evaluate** — best option when VS Code UI is not required

---

## 9. Escalation and Failure Definition

A model "cannot solve" a Level 3 task when:
- Two or three focused, well-contextualized, well-decomposed attempts produce geometrically
  incorrect output that cannot be repaired by follow-up prompting within the same session.
- The model produces confident but internally inconsistent mathematical statements that
  contradict the established geometry contracts in the pipeline documentation.
- The model repeatedly loses the reasoning thread on multi-step derivations in ways that
  more context or rephrasing cannot resolve.

**Before escalating model tier, check decomposition first:** If the failure pattern is
"model loses track of too many interdependent facts," the correct intervention is task
decomposition (§7.0 reducibility gate), not model upgrade. A cheaper model on a smaller
well-scoped sub-task often outperforms an expensive model on an oversized task.

When the threshold is genuinely reached (decomposition attempted, model ceiling confirmed):
- Escalate to the next tier. Log the failure mode specifically.
- Escalating to a higher tier is not a failure — it is the correct application of this policy.
- At C3 ceiling: raise an OQ (§7.2). Do not attempt infinite escalation.

---

## 10. Acceptance Criteria

This spec is considered Verified when:

- AC-1: `foundation/SR-1.4-ai-guidance/specs/ai-model-selection-policy.md` is listed in
  `architecture-docs/specs/INDEX.md` with SR-1.4 ownership and correct lifecycle state.
- AC-2: `phi4-reasoning` and `llama3.3:70b` are available in the local Ollama instance
  (`ollama list` shows both models).
- AC-3: `qwen2.5-coder:7b` is available in the local Ollama instance.
- AC-4: VS Code `settings.json` contains `github.copilot.chat.byok.ollamaEndpoint` pointing
  at `http://localhost:11434`.
- AC-5: The architect has confirmed the task classification examples in §5 are representative
  of actual project work.
- AC-6: `architecture-docs/global/ai-task-queue.md` policy header references the `Model:` field
  requirement and points to this spec.

---

## 11. Task Queue Model Assignment Contract

This section is the governance enforcement clause for §5 task classification. It defines the
requirement to assign a model tier to every AI task at creation time.

### 11.1 Requirement

Every new AI task (AT-NNN) added to the ready pool in `ai-task-queue.md` MUST include a
`Model:` annotation inline in the Task column, immediately after the `Agent:` annotation.

Format:

```
Agent: `<agent-name>`. Model: Level-1
Agent: `<agent-name>`. Model: Level-2
Agent: `<agent-name>`. Model: Level-3
```

The level value must be one of `Level-1`, `Level-2`, or `Level-3` as defined in §5. The architect
applies the decision rules in §7 to determine the correct level when creating the task. If the
classification is uncertain, default to `Level-2` and note the ambiguity.

### 11.2 Pre-existing Tasks

Tasks created before this policy was adopted (prior to the commit that introduces this §11) are
grandfathered. They do not require retroactive annotation. When an agent picks up a grandfathered
task that has no `Model:` annotation, the agent infers the tier from the task body using §5 rules
and records the inferred tier in its session notes. No retroactive edit to the task row is required
unless the architect explicitly requests a retroactive tagging pass.

### 11.3 Enforcement

A task that reaches ACTIVE state without a `Model:` annotation is a non-conformance under this
policy. The executing agent must:

1. Infer the tier from §5 and apply the model selection rules from §7 for execution.
2. Log a non-conformance note in the task row: `(Model not set — inferred Tier-X per §5)`.
3. Do not block execution; annotation gaps must not become blockers.

### 11.4 Architect Responsibility

The System Architect is responsible for setting the `Model:` annotation when adding tasks to the
Ready Pool. Agent-authored tasks (e.g., tasks generated by a research or spec agent as part of
their output) must include the `Model:` annotation as part of their deliverable. Omitting the
annotation is a task authoring defect, not an agent execution error.

### 11.5 Model Selection Override

If during execution the agent determines that the assigned level is wrong (e.g., a Level-1 task
turns out to contain novel mathematics), the agent must:

1. Pause if a level upgrade is needed (e.g., Level-1 to Level-3 would require switching to a local
   reasoning model or cloud model).
2. Log the reclassification in the task row: `(Model: Level-3 — reclassified during execution,
   original annotation was Level-1)`.
3. Apply the §7 decision rules for the new level.
