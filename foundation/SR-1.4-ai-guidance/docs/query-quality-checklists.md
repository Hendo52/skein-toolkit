# Query Quality Checklists

**Owner:** SR-1.4 — AI Toolchain Governance
**Date:** 2026-05-25
**Status:** Active

> These checklists govern how tasks are prepared before submission to an AI model and what must
> be done before escalating to the next model tier. The goal is to make each query as easy as
> possible for the current tier before concluding that a more expensive tier is required.
>
> See [ai-model-selection-policy.md](../specs/ai-model-selection-policy.md) for tier definitions,
> model assignments, and the Cloud Approval Gate (§7.1).
>
> **Consolidated strategy companion:** See [unified-ai-strategy.md](unified-ai-strategy.md) for the
> consolidated cross-policy view covering budget, quality, enablement, and context management.

---

## Core Principle

**Wild speculation costs more than gathering evidence.** Every vague or underspecified query
causes the model to fill gaps with assumptions. A single well-specified query with strong evidence
is worth more than five iterative attempts on a poorly framed one.

The headless Electron harness (SR-1.16) is the project's highest-value evidence source. It
produces deterministic, machine-readable, session-independent output. Any bug or geometry question
that can be captured as a harness fixture should be, before any model query is written.

---

## 1. Universal Pre-Query Checklist

Apply before submitting any task to any tier.

### 1.1 Task decomposition

- [ ] The task has exactly one stated goal. If you can write two different "done" conditions, it
      is two tasks.
- [ ] The exit evidence fits in one sentence. If it references two subsystems or two files in
      separate concerns, split the task.
- [ ] Dependency ordering is correct: if Task B can only be verified after Task A changes a file,
      they are sequential — do not merge them into one query.
- [ ] Every sub-problem that can be independently verified has been separated out. Bundled tasks
      force the model to hold multiple concerns simultaneously and increase the chance it solves
      one while silently getting the other wrong.

### 1.2 Scope specification

- [ ] The exact files to read and modify are named explicitly. Do not rely on the model to
      discover them by searching the repo.
- [ ] The relevant spec section or contract is cited (e.g., "per HED-2 in
      `headless-electron-driver.md`" or "per the runtime contract in
      `SR-3.4-control-plane/docs/runtime-contract-snapshot.md`").
- [ ] If the task is a bug fix, the symptom is separated from the suspected cause. State what the
      system currently does and what it should do. Do not only state the suspected cause — you
      may be wrong.
- [ ] Out-of-scope files are identified if there is risk of accidental modification (e.g.,
      "do not touch `HeadlessEditorDriver.ts` — only `EditorTestApi.ts` is in scope").

### 1.3 Evidence attachment

Attach the strongest available evidence in this priority order. Stop when you have at least one
item from the list — do not skip levels without reason.

| Priority | Evidence type | How to produce |
|----------|--------------|----------------|
| 1 (best) | Headless harness counterexamples JSON | `npx playwright test app/e2e/harness/rca-sweep.spec.ts` → `test-results/rca-sweep/counterexamples.json` |
| 2 | One-shot harness diagnostic JSON | `yarn diag --out report.json [--profiles] [--node N]` |
| 3 | Harness reader value (single field) | `driver.getJointDiagnostics()`, `driver.getProfileRingSummary()`, etc. |
| 4 | STL mesh analysis output | `python engine/SR-3.8-mesh-qa/code/analyze_mesh.py <file.stl>` |
| 5 | OpenSCAD ECHO log with specific values | headless render with `--export-format echo` |
| 6 | Failing test output with exact assertion text | `yarn test` filtered to the failing suite |
| 7 (worst) | Screenshot or written description | Only when no programmatic capture is possible |

**Never submit only a screenshot or written description if a harness fixture can demonstrate
the same thing.** The harness is deterministic and session-independent; a description is not.

### 1.4 Test authoring (AT-1172 — contract vs implementation rubric)

Apply when writing new tests OR reviewing AI-generated tests before approving a commit.

- [ ] **State the contract first.** In 1-2 sentences, write the function's or module's public
      contract before writing any assertion: "Given [inputs], the module must produce [outputs /
      side-effects]." If you cannot state the contract, the test is premature.
- [ ] **Test the contract, not the internals.** Does this test assert on observable outputs or
      side-effects (return values, emitted events, console signals, model state changes)? If it
      asserts on private helper call counts, internal variable names, or intermediate data shapes
      not part of the public contract, ask: can it be rewritten to test the same behaviour via
      the public surface instead?
- [ ] **Distinguish specification from regression.** A specification test documents what the
      module must do and will catch any future implementation change that breaks the contract.
      A regression test pins specific current behaviour. Prefer specification tests; label
      regression tests explicitly so a future reader knows they are allowed to change.
- [ ] **If a test can only be written against internals**, the likely root cause is that the
      unit has no clean public contract. The fix is to extract the behaviour behind a well-named
      function with clear inputs/outputs, then test that function — not to write a brittle
      internal-state test.

---

## 2. Tier R — Before Submitting to Local 7B

Tier R = routine tasks (GUI, single-file refactor, docs). Model: `qwen2.5-coder:7b`.

- [ ] The task touches at most 2-3 files. If more, it is Tier C.
- [ ] The expected output is boilerplate-adjacent: a React component, a CSS rule, a renamed
      symbol, a new test stub. If it requires understanding non-obvious architectural invariants,
      it is Tier C.
- [ ] The query includes the current file content (or relevant excerpt) so the model does not
      need to infer existing structure.
- [ ] The query states the exact change in "before / after" terms where possible.
- [ ] **Do not request step-by-step reasoning from a 7B model.** Chain-of-thought prompting is
      only reliably effective in models above approximately 30B parameters. Below that threshold,
      asking for reasoning steps frequently produces confident-sounding but incorrect chains.
      Ask directly for the output; do not ask the model to explain its reasoning.

### 2.1 Before escalating Tier R to Tier C

Do all of the following before concluding the task needs a cloud model:

- [ ] Simplify the query: remove everything except the single change needed. If you described
      context, cut half of it and retry.
- [ ] Verify the task is actually Tier R. If the model keeps misunderstanding the intent, the
      task may require architectural context it cannot hold in a 7B context window.
- [ ] Check if the task can be reduced further: is there a 10-line version of the change that
      proves the concept, leaving the full wiring as a separate Tier R follow-up?
- [ ] If the model is making structural mistakes (wrong file, wrong pattern), provide an explicit
      example of the pattern used elsewhere in the codebase in the same query.

> **Escalation-trigger cross-reference:** See [model-enablement-toolset-strategy.md](
> ../specs/model-enablement-toolset-strategy.md) §5 for per-toolset escalation triggers.
> The most relevant subsections for Tier R escalation are: §5.3 (Task decomposition),
> §5.6 (Prompt refinement), and §5.7 (Validation harnesses).

---

## 3. Tier C — Before Submitting to Cloud (Claude via Anthropic API)

Tier C = multi-file agent tasks, architectural patterns, integration. Model: Cloud Tier 3.

> **Reminder:** Tier C requires architect approval (§7.1 of the policy). Staging a
> `Model: Tier-C` task into a READY batch is the approval act.

- [ ] Task decomposition checklist (§1.1) is complete. Tier C tasks are more expensive to
      correct mid-stream than to split upfront.
- [ ] The relevant architectural context is attached: runtime contract snapshot, spec section,
      data-model definition, or serialization schema as applicable.
- [ ] The agent is named (`Agent: typescript`, `Agent: docs`, etc.) so the model starts with
      the correct tool restrictions and file-system scope.
- [ ] If the task involves a serializable field, the `@Serialize` requirement and the default
      value are stated explicitly. (Missing `@Serialize` is a recurring error; do not make the
      model discover it.)
- [ ] The exit evidence is stated as a verifiable condition: "`yarn build` green", "failing test
      now passes", "field visible in Developer Settings panel".

### 3.1 Before escalating Tier C to Tier M

Do all of the following before concluding the task requires a reasoning model:

- [ ] Confirm the task is actually mathematical, not just large. Large multi-file tasks stay
      Tier C. Only tasks requiring original derivation move to Tier M.
- [ ] If the cloud model is producing incorrect code, check whether the architectural contract
      was provided. Missing contracts are the most common cause of Tier C failures that look
      like Tier M problems.
- [ ] Verify the task is not two tasks: an implementation task and a mathematical design task.
      The design question (Tier M) should be resolved first and its answer provided as input
      to the implementation task (Tier C).

> **Escalation-trigger cross-reference:** See [model-enablement-toolset-strategy.md](
> ../specs/model-enablement-toolset-strategy.md) §5 for per-toolset escalation triggers.
> The most relevant subsections for Tier C escalation are: §5.7 (Validation harnesses --
> same error signature across retries), §5.6 (Prompt refinement -- structural error after
> two reframings), and §5.8 (OQ escalation -- architect responds "need more information").

---

## 4. Tier M — Before Submitting to Local Reasoning Model

Tier M = novel mathematics, geometry derivation. Model: `phi4-reasoning` (primary),
`llama3.3:70b` (secondary).

The most important preparation rule for Tier M: **strip away the implementation, ask only the
mathematical question.** Reasoning models produce better results when the prompt is a clean
mathematical problem statement, not a bug report embedded in a 300-line file context.

- [ ] The mathematical question is isolated from the codebase. State it as: "Given these inputs
      [X], what is the correct formula / algorithm / value for [Y]? The constraint is [Z]."
- [ ] **Translate the problem to symbolic notation before asking the model to solve it.**
      State the geometry problem once in natural language, then immediately provide the symbolic
      formulation: explicit equations, matrix definitions, coordinate notation, parameter domain.
      Ask the model to operate on the symbolic form, not to derive it from the description.
      Example: state "the tangent vectors are T0 = [1, 0, 0] and T1 = [0, 1, 0]" as explicit
      vectors before asking for the bisector normal, rather than saying "the curve bends 90 degrees
      in the XY plane." Symbolic grounding constrains the solution space and produces a verifiable
      reasoning artifact.
- [ ] The existing incorrect behavior is quantified: not "the joint looks wrong" but "the bisector
      plane normal is [0, 0, 1] but should be approximately [0.6, 0.8, 0] given tangent vectors
      T0=[1,0,0] and T1=[0,1,0]". Values from the harness diagnostic JSON are ideal for this.
- [ ] Relevant mathematical invariants are stated: frame orthonormality, curve parameter domain,
      angle conventions (degrees vs radians), coordinate system handedness.
- [ ] The known-good case is included if one exists: "for a straight segment this formula gives
      the correct result; it breaks at the following input."
- [ ] Prior approaches that have already been tried are listed, with the reason they failed.
      See `architecture-docs/global/investigation-history.md` for the project-level list.
- [ ] **Explicitly request step-by-step derivation.** Reasoning models (phi4-reasoning,
      llama3.3:70b) produce substantially better results when asked to show each derivation step.
      End the prompt with: "Work step by step. Show all intermediate expressions before giving
      the final result." Do not ask for a direct answer on Tier M problems.

### 4.1 Harness fixture as Tier M evidence

For any geometry bug that reaches Tier M, a harness fixture is required before the query is
submitted. Without a fixture, the model cannot verify its answer and neither can you.

- [ ] Drop a saved scene JSON into `app/e2e/harness/fixtures/` (any `.json` file).
- [ ] Run `npx playwright test app/e2e/harness/rca-sweep.spec.ts` and capture
      `test-results/rca-sweep/counterexamples.json`.
- [ ] Include the counterexample values (not the full JSON — extract the relevant reader fields)
      directly in the prompt.
- [ ] State which reader field deviates and by how much: "
      `JointDiagnostic.bisectorNormal` returns `[0,0,1]`, expected approximately `[0.71, 0.71, 0]`
      for a 90-degree in-plane joint."

### 4.2 Before escalating Tier M to Cloud (Tier M cloud escalation)

> **Reminder:** Tier M cloud escalation requires explicit architect approval (§7 escalation
> approval). Stop and report the local failure before invoking cloud.

Local failure is confirmed when:
- phi4-reasoning has been tried at least twice with a clean, isolated mathematical question and
  the output is either internally inconsistent or geometrically wrong (verified via harness).
- llama3.3:70b has been tried at least once with the same isolated prompt.

Before reporting local failure to the architect:

- [ ] Confirm the prompt is the minimal mathematical question, not the full task description.
      A reasoning model failing on a long implementation prompt may succeed on a 5-line math
      question extracted from the same task.
- [ ] Confirm the harness fixture shows the deviation clearly. Attach the before/after diagnostic
      JSON to the escalation report.
- [ ] Confirm the counterexample is reproducible (run the sweep twice; values must be identical).
- [ ] State what was tried: model, prompt summary, output summary, why it was wrong.
- [ ] If the problem involves a known architectural ceiling (see `investigation-history.md`),
      note that explicitly — the architect may redirect rather than approve cloud escalation.

> **Escalation-trigger cross-reference:** See [model-enablement-toolset-strategy.md](
> ../specs/model-enablement-toolset-strategy.md) §5 for per-toolset escalation triggers.
> The most relevant subsections for Tier M cloud escalation are: §5.8 (OQ escalation --
> architect responds "need more information" or precedent search returns zero hits on a
> problem with prior art) and §5.7 (Validation harnesses -- same error signature across
> retries). These conditions indicate the task exceeds the enabled model's competency
> envelope and requires human insight rather than a larger model.

---

## 5. Evidence Quality Reference

### 5.1 What makes evidence strong

Strong evidence is:
- **Deterministic**: running the same capture twice gives identical values.
- **Quantified**: numbers, not adjectives ("the normal is [0, 0, 1]" not "the normal looks flat").
- **Localized**: points to a specific reader field, a specific test assertion, a specific ECHO
  line — not a general area of the codebase.
- **Contrastive**: shows both the actual value and the expected value, making the gap explicit.

Weak evidence is:
- A screenshot with a verbal description of what looks wrong.
- "The test fails" without the assertion text and actual/expected values.
- "The geometry looks distorted" without a harness read showing which field is wrong.
- A written hypothesis about the cause before the symptom is quantified.

### 5.2 The evidence-before-hypothesis rule

Do not form a hypothesis about the cause before capturing evidence of the symptom. Hypotheses
in queries invite the model to confirm them rather than reason independently. State the symptom
and ask for the cause.

Weak: "I think the bisector plane calculation is wrong. Can you fix `computeBisectorPlane()`?"

Strong: "The harness reports `jointAngleDeg = 0` for a scene where the visual angle is 90 degrees.
`JointDiagnostic.bisectorNormal = [0, 0, 1]`. Here is the input: T0=[1,0,0], T1=[0,1,0].
What is the correct bisector normal, and which function is most likely producing the wrong value?"

### 5.3 The observe-reason-fix-reobserve cycle

Every non-trivial query should follow a four-step cycle. Do not collapse steps.

```
1. OBSERVE   Run the harness or test. Capture exact values.
2. REASON    Submit the observed values as evidence. Ask for cause and fix.
3. FIX       Apply the proposed fix.
4. REOBSERVE Run the same harness or test again. Compare values to step 1.
```

The fix is not verified until step 4 produces the expected change in the diagnostic values.
Declaring a fix complete after step 3 (code written, not re-tested) is the primary source of
regressions in multi-model sessions. The reobservation must use the same evidence source as the
initial observation so the comparison is apples-to-apples.

For Tier M tasks, the cycle extends: if the reobservation shows partial improvement but residual
error, the step-2 output (the model's derivation) plus the step-4 values become the new evidence
for the next iteration. Each iteration narrows the deviation quantitatively.

---

## 6. Relationship to the Tik/Tok Queue

When an architect stages tasks into a READY batch, these checklists govern what "ready" means:

- A **Tier R task** is ready when the task description names the file, the change, and the
  expected exit state.
- A **Tier C task** is ready when the task description includes the agent name, relevant spec
  references, and a verifiable exit condition. Staging a Tier C task also satisfies the cloud
  approval requirement (§7.1 of the policy).
- A **Tier M task** is ready when the task description includes or references a harness fixture
  (or equivalent quantified evidence), the mathematical question is isolated, and known prior
  approaches are noted.

Tasks that fail these readiness criteria should be returned to STAGING, not executed.

---

## 7. Research Basis

The following papers and sources informed or independently validate specific sections of this
document. Listed for traceability.

| Section | Principle | Research basis |
|---------|-----------|----------------|
| §1.1 One-goal decomposition | Decomposition quality is the primary agent quality lever | HuggingGPT (arXiv:2303.17580); MetaGPT (arXiv:2308.00352) |
| §1.3 Evidence priority table | Deterministic tool-call outputs outperform descriptions | ReAct (arXiv:2210.03629); SWE-agent ACI design (arXiv:2405.15793) |
| §1.3 Evidence priority table | Context quality dominates context quantity | Advanced RAG Survey (arXiv:2312.10997) |
| §2 CoT warning for 7B | Chain-of-thought unreliable below ~30B parameters | Chain-of-Thought Prompting (arXiv:2201.11903) |
| §3 Pre-escalation gate | Start simple; add complexity only when demonstrated necessary | Anthropic Engineering, "Building effective agents" (2024) |
| §4 Symbolic reformulation | NL-to-symbolic translation before solving reduces logic hallucination | Faithful CoT (arXiv:2301.13379) |
| §4 Step-by-step request | CoT reliably improves output quality in >30B reasoning models | Chain-of-Thought Prompting (arXiv:2201.11903); Tree of Thoughts (arXiv:2305.10601) |
| §5.2 Evidence-before-hypothesis | Observe before reason; grounded observations suppress hallucination | ReAct (arXiv:2210.03629) |
| §5.3 Observe-reason-fix-reobserve | Execution feedback is the dominant quality signal | SWE-bench analysis (arXiv:2310.06770); AutoCodeRover (arXiv:2404.05427) |
| §4.1 Trim evidence to relevant fields | Context compression: less, targeted context outperforms full dumps | Advanced RAG Survey (arXiv:2312.10997) |

### 7.1 Confirmed design decisions

The following aspects of this document were independently validated as best practice by the
research survey and require no change:

- Three-tier model routing is structurally equivalent to the FrugalGPT cascade and the
  RouteLLM learned-router concept. The manual classification approach is correct; an automated
  signal (e.g., harness pass rate) would be an enhancement, not a correction.
- The headless harness as the primary evidence source is exactly the Agent-Computer Interface
  investment that SWE-agent and SWE-bench analysis identify as the highest-leverage quality gate.
- The validator-at-the-boundary policy is the project-level implementation of MetaGPT's
  inter-agent verification step, which is the documented primary mitigation for cascading
  hallucination in multi-agent systems.
- Naming hallucinations (fabricated symbol names) are a well-documented failure mode (CodeHalu,
  arXiv:2405.00253). The NAMING_VIOLATIONS.md tracker and naming enforcement policy address the
  same failure class the research identifies.
