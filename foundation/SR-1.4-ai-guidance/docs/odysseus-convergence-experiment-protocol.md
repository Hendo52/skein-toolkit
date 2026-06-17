# Odysseus Convergence — Controlled Experiment Protocol

> Scope: AT-O1 and AT-O2 acceptance experiments
> Agent: `spec`
> Model: Tier-R
> Owner: SR-1.4 AI Guidance Synchronization

## Purpose
Define repeatable, blind comparison procedures so an agent (or human) can run AT-O1 and AT-O2 without re-deriving methodology from scratch. The protocol is intentionally model-agnostic: it describes *what to measure* and *how to score it*; the tool under test supplies the completion.

---

## Experiment AT-O1: Context Reordering Efficacy on >300 KB Spec Reads

### Setup
1. Pick a stable, unchanging spec file >= 300 KB in the repo.
   - Candidate canonical: `architecture-docs/research_into_prior_work/omega-primary-surface-architecture.md`.
   - Confirm byte count at runtime; abort if < 300 KB.
2. Prepare 5 prompt variants over the **same** reading task.
   - Task: "Summarize the design decisions, data structures, and algorithmic pipelines described in the attached spec, focusing on what an implementer needs to know."
3. For each of n = 5 repeats:
   - Load the spec into a fresh context/session.
   - Measure
     a. **Wall-clock latency** from invocation to first token.
     b. **Total latency** from invocation to completion.
     c. **Token cost** (input + output tokens if available; otherwise document "unavailable").
     d. **Accuracy score** — see rubric below.
   - Append results to a timestamped run log.

### Accuracy Scoring Rubric (blind, against Cline baseline)
Produce a structured summary JSON with fields:
- `designDecisions`: list of key architectural choices and trade-offs.
- `dataStructures`: list of key types and their roles.
- `algorithmicPipelines`: list of named algorithms / evaluation orders.
- `implementationNotes`: list of concrete constraints, budgets, or thresholds.

A Cline baseline run is produced first and stored unmodified. Subsequent runs are scored against it:

| Score | Criterion |
|-------|-----------|
| 5 / 5 | All four JSON fields present; each item is factually correct and matches or exceeds baseline granularity. |
| 4 / 5 | All four fields present; one item contains a minor omission or imprecision that does not mislead an implementer. |
| 3 / 5 | One field missing or collapsed; remaining fields substantively correct. |
| 2 / 5 | Two fields missing or materially wrong. |
| 1 / 5 | Only one field substantially correct; others hallucinated or omitted. |
| 0 / 5 | Hallucinated or no meaningful content. |

### Blind procedure
- Label each run output with a random UUID; do not expose tool name to the evaluator.
- The evaluator compares the UUID-labelled output against the Cline baseline using the rubric.
- Evaluation and scoring may be done by a different agent instance or by a human.

### Acceptance
AT-O1 is **converged** (adopt Odysseus capability) if the mean accuracy score across n=5 is within ±5% of the Cline baseline mean OR if total latency is measurably lower (>=10% speedup) with no accuracy regression.

AT-O1 yields an **OQ** if neither condition is met and the gap is >5% in either direction with p<0.05 visual evidence (no formal stats required; 5-repeat spread is the evidence).

---

## Experiment AT-O2: Concept-Graph Mapping for Architecture Reasoning

### Setup
1. Pick a bounded architecture-gap question that both tools can be asked.
   - Candidate: "Given our current Omega-primary surface architecture (evaluateSurface → OmegaSurface migration), list the exact files, functions, and test files that must change, in dependency order, to complete the migration."
2. Prepare the same prompt as a system/user message pair with no tool-specific framing.
3. For each of n = 5 repeats:
   - Invoke the tool with the prompt.
   - Record wall-clock latency, total latency, token cost.
   - Record the structured answer.

### Accuracy Scoring Rubric
Score the answer against the ground-truth dependency graph (as known from `ai-task-queue.md` and `INDEX.md`):

| Score | Criterion |
|-------|-----------|
| 5 / 5 | All files/functions/tests listed; dependency order strictly correct; no phantom entries. |
| 4 / 5 | One minor ordering error or one missing leaf test file; no phantom entries. |
| 3 / 5 | One missing non-leaf file or function; ordering mostly correct. |
| 2 / 5 | Multiple missing files or ordering inversions that would break the build. |
| 1 / 5 | One correct file and some correct functions; remainder hallucinated. |
| 0 / 5 | Entirely hallucinated or no meaningful content. |

### Blind procedure
Same UUID-labelling and separate-evaluation rule as AT-O1.

### Acceptance
Same ±5% mean-accuracy or >=10% speedup-without-regression rule as AT-O1.

---

## Common Controls

| Control | Value | Rationale |
|---------|-------|-----------|
| Temperature | 0.0 or tool-default | Minimizes run-to-run variance for deterministic comparison. |
| Max tokens | 4096 | Sufficient for detailed summaries; caps cost. |
| Context limit | Tool's native limit | Document if the tool truncates the 300 KB spec. |
| Repeat count | n = 5 per condition | Trades statistical power against API spend; documented as "informational, not hypothesis-tested." |
| Baseline tool | Cline (current harness) | The existing harness is the "as-is" reference; Odysseus is the challenger. |

---

## Evidence Capture

Each experiment run must deposit:
1. **Run log** — `foundation/SR-1.4-ai-guidance/docs/odysseus-convergence-experiment-logs/AT-O1-runs.json` or `AT-O2-runs.json`.
2. **Baseline JSON** — unmodified Cline output against which all runs are scored.
3. **Score sheet** — one row per run: UUID, tool (revealed only after scoring), latency, tokens, accuracy score, evaluator notes.
4. **Verdict note** — a one-line convergence/divergence/OQ statement with numerical evidence.

---

## Exit Evidence

1. This file exists at the path above.
2. AT-O1 and AT-O2 rows appear in `architecture-docs/global/ai-task-queue.md` Ready Pool.
3. `odysseus-convergence-phased-plan.md` Phase 0 lists this protocol file as created.
4. `git status --short` is GREEN.