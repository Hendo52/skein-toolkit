# Cheap-Model Context-Budget Improvement Roadmap

**Status:** Active -- chronic / long-term
**Date opened:** 2026-06-11
**Owning SR:** SR-1.4 (AI toolchain governance)
**Companion to:** [`ai-model-selection-policy.md`](../specs/ai-model-selection-policy.md)
**Related bug:** [`BUG-SR-1.4-cf-proxy-planner-pass-latency-not-reproduced.md`](../../../architecture-docs/bugs/BUG-SR-1.4-cf-proxy-planner-pass-latency-not-reproduced.md)
**Consolidated into:** [unified-ai-strategy.md](unified-ai-strategy.md)

---

## 1. Why this exists

Agentic development on Electron-Splines currently depends on frontier cloud models
(Claude Sonnet/Opus) for almost all non-trivial work. That is not financially sustainable
on an ongoing basis -- as of 2026-06-11, development on the core Electron-Splines product
has paused except for the narrow effort of getting Cline to produce usable results with
**cheap models** (CF Workers AI `gpt-oss-20b`/`120b`, local Ollama models).

This matters beyond this repo: if the agentic toolchain, configuration, and orchestration
work here (`scripts/local-mcp.py`, `run-cline.ps1`, `toolchain-doctor.ps1`, the CF proxy
orchestrator) can be made to produce reliable results on cheap models, it becomes the seed
of a standalone toolchain repo for a community "vibe coding" effort with external
contributors. That depends entirely on cheap models being *operationally viable*, not just
occasionally working.

**This document exists because that is a hard, multi-faceted problem that will not be
solved in one pass.** It is the running record of what we've tried, what we know, and what
to try next -- analogous in spirit to
[`investigation-history.md`](../../../architecture-docs/global/investigation-history.md) for
the geometry pipeline. Read §6 (experiment log) before re-attempting anything in §5.

---

## 2. The chronic problem: "context budget"

Two findings from the 2026-06-11 decomposition-test session turned out to be two faces of
one problem:

- **Degenerate empty responses.** `cf/gpt-oss-20b` (and `-120b`) reliably returns an empty
  completion -- all token budget spent in the Harmony `analysis` (reasoning) channel, never
  reaching the `final` channel -- once a turn's prompt context reaches roughly **12-20K
  tokens**, particularly when that context is dense raw tool-result text (grep/search
  output, file dumps). `reasoning_effort: "low"` (added 2026-06-08, applied from attempt 1)
  reduces but does not eliminate this at this context size.
- **Multi-step detection misses investigation tasks.** `_detect_multi_step_ask`'s
  action-verb list (`create, copy, configure, build, write, refactor, implement, deploy,
  ...`) is code-modification-oriented and contains none of `review, examine, investigate,
  analyze, verify, summarize, locate, identify` -- so read-heavy "investigate X, then Y,
  then report Z" tasks never get decomposed.

These connect because **investigation tasks are exactly the ones that accumulate large raw
tool-result contexts**, and `_build_step_dispatch_body` already gives each orchestrator
step a narrow, fresh frame (system prompt + step instruction + only that step's own
`tail_messages` -- prior steps and the original ask are excluded by design). Finer-grained
steps -> smaller per-step `tail_messages` -> less chance of crossing the degeneracy
threshold. But decomposition alone is not sufficient: the same degeneracy reproduced in a
**non-orchestrated** turn, and a single step's own tool exploration can itself accumulate
past the threshold regardless of step granularity.

**Working name for this chronic problem: "context budget"** -- keeping the token count and
*density* of what gets sent to a cheap model, on any single turn, inside the envelope where
that model reliably produces a final answer.

---

## 3. What we know so far (do not re-derive)

- `CF_GPT_OSS_REASONING_EFFORT = "low"` is already applied from attempt 1 for all
  `@cf/openai/gpt-oss-*` calls (`scripts/local-mcp.py` ~line 918). Confirmed insufficient
  alone at ~15-20K prompt tokens (reproduced 2026-06-11, completion_tokens 34-46, all
  reasoning).
- `_build_step_dispatch_body` (~line 1816) already narrows context per orchestrator step --
  this is NOT something that needs building, it needs *exploiting* (steps need to be small
  enough that a step's own tool exploration doesn't blow the budget).
- Oversized tool results are already truncated 59043 -> 20000 chars before forwarding to
  CF (~5K tokens per result). Two or three such results in one turn already lands in the
  12-20K degeneracy zone.
- gpt-oss-20b's documented CF context window is 128K tokens -- the degeneracy at 15-20K
  (12-16% full) is **not** a hard context-window limit. It correlates with content
  *density/shape* (raw tool dumps), consistent with Chroma's "Context Rot" research
  (degradation is content-shape-sensitive, not purely token-count-driven).
- Anthropic's published multi-agent pattern keeps raw subagent tool output **out of** the
  orchestrator's context entirely -- subagents return 1000-2000 token condensed summaries.
  This is the direction "context engineering" as a field is converging on; see §7.
- The "5-10 min planner pass latency" finding (Problem 1) was investigated and **not
  reproduced** -- see the linked bug report. It is a separate, currently-dormant track; do
  not conflate it with the context-budget problem.

---

## 4. Operating model

This is a **chronic problem worked incrementally**, not a one-shot fix:

1. **Research first.** Before implementing a strategy from §5, do a short prior-art check
   (the field is "context engineering" -- see §7 for starting points already gathered).
   Record what was found, even briefly, in the experiment log (§6).
2. **One strategy, one small experiment.** Pick the highest-confidence untried strategy from
   §5. Implement the smallest version that can be measured.
3. **Validate locally** using the methodology in §6 before/after comparison -- a strategy is
   not "done" until it has before/after evidence in the experiment log.
4. **Record the outcome** in §6 regardless of whether it worked -- negative results are as
   valuable as positive ones (see Problem 1's bug report for why).
5. **Update §5's status column** (Untried / Testing / Adopted / Rejected / Superseded).
   Adopted strategies move their detail into the relevant code comments / spec; this doc
   keeps a one-line pointer.
6. Per CLAUDE.md commit hygiene: each experiment that touches code is its own commit. This
   doc's updates can ride along with the experiment's commit (same issue).

---

## 5. Strategy backlog

| ID | Strategy | Hypothesis | Status | Notes |
|----|----------|------------|--------|-------|
| CB-1 | **Compress/summarize large tool results before re-injection** (Anthropic subagent pattern) | If raw `search_codebase`/`read_files` output is condensed to ~1-2K tokens before it re-enters the conversation sent to gpt-oss, the analysis-channel lock-up won't trigger even across multiple tool calls in one turn | Untried -- low-priority backlog (OQ-264, 2026-06-12) | Most "correct" per current context-engineering consensus; most engineering effort. Needs a cheap summarizer step (could itself be a local model call). **2026-06-11 (test #4/#5):** the degeneracy is not purely size-gated -- a 4174-token *first-turn* prompt (no tool results yet) degenerated 6/6 attempts (3 retries x 2 separate runs), surviving the proxy's existing temperature-perturbation retry (0.7, 1.0). A 3996-token first-turn prompt with different content succeeded 6/6 in test #3. The failure is prompt-content-correlated, not just size-correlated. **2026-06-11 (test #7): the floor moved again, to 1879 tokens** -- a read-only first-turn prompt below half of test #4/#5's failure size also degenerated. The floor is shrinking, not stabilizing; size-based mitigation (CB-3) looks increasingly unviable on CF's current serving stack. **OQ-264 (2026-06-12):** `cf/kimi-k2.6` adopted as the default cheap-tier model for the local-mcp orchestrator (CB-7 9/9 proven, ~$0.025-0.037/call); CB-1/2/3 (gpt-oss context-budget investigation) move to this low-priority backlog with two explicit revisit triggers: (i) a future task batch's estimated `cf/kimi-k2.6` cost exceeds a to-be-set monthly budget, or (ii) an unrelated task surfaces a CB-1/2/3 root cause incidentally. Broader investigation of other heavyweight alternative models (`gpt-oss-120b`/`20b`, `qwen2.5-coder:32b`, `llama3.3:70b`, `gemma-4-26b` -- the `$cfModelReverseMap` set in `resume-orchestrator-run.ps1`) is deferred similarly, non-gating. See section 8 |
| CB-2 | **Tighten oversized-tool-result truncation** (currently 59043->20000 chars) | Lowering the per-result cap (e.g. to 8000-10000 chars) keeps 2-3 accumulated results under the ~12K degeneracy floor | Untried -- low-priority backlog (OQ-264, 2026-06-12; see CB-1 note for revisit triggers) | Cheap, one-line change. Lossy -- may hide information Cline needs. Good first experiment because it's nearly free to try and revert |
| CB-3 | **Context-size-aware model routing** | Once a turn's prompt crosses ~10K tokens, transparently route *that turn* to a model without the Harmony analysis/final split (e.g. `local/qwen3.6`, 262K context, free) | Untried -- low-priority backlog (OQ-264, 2026-06-12; see CB-1 note for revisit triggers) | Sidesteps the gpt-oss-specific quirk entirely. Must be a named, logged, observable alternative path per CLAUDE.md First-Class Scenarios policy -- not silent. Need to confirm `qwen3.6` doesn't have its own large-context quirks first |
| CB-4 | **Expand `_detect_multi_step_ask` action-verb list for investigation tasks** | Adding `review, examine, investigate, analyze, verify, summarize, locate, identify, audit, compare` lets investigation asks get decomposed, capping per-step `tail_messages` growth | Tested 2026-06-11 -- Rejected as primary lever | Implemented (commit 9632472c) but never exercised: the heuristic inspects only the trailing user message, which is short and verb-free. The prompt bulk comes from Cline's own system prompt/tool schema, not the task text. See section 8 |
| CB-5 | **Per-step tool-call budget / early step termination** | If a step's `tail_messages` length crosses a threshold mid-step (before the executor's final turn), proactively prompt for a final answer instead of letting Cline keep exploring | Untried | More invasive -- changes orchestrator step-loop control flow. Consider only after CB-2/CB-4 measured |
| CB-6 | **Disable native tool calls for cf/gpt-oss models** (`nativeToolCallEnabled=false` in Cline's global state) | Forces Cline's `next-gen` (XML-tag tools) prompt variant instead of `native-gpt-5` (full OpenAI `tools` array) for gpt-oss-120b -- a smaller system prompt and a tool-call format closer to what gpt-oss already produces unprompted (see commit 924b623f) -- which may avoid the degenerate-empty-response failure seen even on a trivial 4K-token prompt | Tested 2026-06-11 -- Rejected, wrong codebase | The `ModelFamily`/`nativeToolCallEnabled`/`native-gpt-5` prompt-variant registry this hypothesis was based on lives in `apps/vscode` (the VSCode extension). `run-cline.ps1` invokes `apps/cli` ("cline-core"), a separate codebase with its own fixed ~2922-char system prompt that does not consult this setting at all. Setting `nativeToolCallEnabled=false` produced a byte-identical request (`tools=yes`, `prompt=3996`, `7492 chars`) to the baseline. Reverted. See section 8 |
| CB-7 | **Planner/step content-fidelity: pass through literal source-document text verbatim** | `_run_planner_pass`/`_build_step_dispatch_body` likely let the cheap model re-derive "decisions"/"facts" from its own reasoning about referenced source docs instead of quoting the literal text, producing plausible-but-inverted output (observed 2026-06-11 test #3: OQ-259/260/261 resolutions were inverted in `planning_document.md`) | Fix applied 2026-06-11 (commit `cfa3a2d4`); **Verified 2026-06-12** (run `a731f317e9507669`, test #15, commit `f8b3bd30`) | `_ORCHESTRATOR_STEP_SYSTEM_PROMPT` now explicitly requires opening the source document and quoting it verbatim before transcribing any fact/decision/value, with literal text overriding the model's own inference. **Could not be exercised in test #4/#5** (gpt-oss CB-1 on first turn), **test #11** (kimi-k2.6 planner `max_tokens=1024` degenerates every turn, then 4th-turn CB-1), **test #12** (planner fixed, step 1 executor produced correct verbatim-quoted output, but the validator itself false-positived on the quoted text -- see CB-8), or **test #13** (run `97ee060abc9315f1`, blocked at step 5/8 by CB-9). **Test #14** (2026-06-12) was the first formal completion (8/8), but 1 of 4 facts was fabricated (cost range, ~100x off) and 1 of 4 dropped entirely (through-proxy result for test #10, traced to CB-12). **Test #15 (2026-06-12, same run key `a731f317e9507669`, re-run after CB-11/CB-12 fixes)** completed 9/9 and the committed `cb7-ac2-validation-summary.md` (commit `f8b3bd30`) has **all 4 facts verbatim-correct**, including the previously-fabricated cost range (now correctly `$0.025-0.037 per call`) and the previously-dropped through-proxy result (`completion_tokens: 6324` in `121s`). This confirms the test #14 cost-range fabrication was a **downstream confusion effect of CB-12's missing fact (3)**, not a standalone CB-7 gap -- with CB-12 fixed, CB-7's verbatim-quoting instruction produced correct output for all 4 facts unaided. See section 8 |
| CB-8 | **Validator false-positive on quoted/reproduced source text** | `_run_validator_pass`'s `_VALIDATOR_FAILURE_RE`/`_VALIDATOR_NEGATED_FAILURE_RE` pair (local-mcp.py:1600-1658) flags a step as "NO" whenever the executor's summary contains bare "fail/error/..." nouns, even when those words are part of a verbatim quote from source material the step was asked to transcribe (not a self-report of the step's own outcome). Negation-awareness covers "no/not/without X failures" but not "X failures observed/are a known problem" framings used when *describing* failures rather than denying them | New 2026-06-11 (test #12) -- **blocks CB-7/AC-2 validation directly** | Confirmed 2026-06-11: step 1/8 of a kimi-k2.6 orchestrator run correctly read and verbatim-quoted a section of *this roadmap doc* (which discusses CB-1 "failures" by name); the validator returned `NO -- summary contains explicit failure language` on a 0-files-changed, fully-correct read step, halting the run per the (correct) no-auto-retry policy. Smallest viable fix: scope the failure-language regex to skip fenced/quoted-block spans, or only scan the executor's own framing sentences outside any reproduced source text. This is the most direct remaining path to a CB-7/AC-2 "yes" -- the model output was already correct. See section 8 |
| CB-10 | **`_cf_complete_once`'s 120s timeout is too short for large step-dispatch prompts; per-step dispatch doesn't carry forward prior steps' findings** | (a) Raising/making configurable the 120s `httpx.AsyncClient` timeout in `_cf_complete_once` for orchestrated dispatch calls would let large-prompt steps complete instead of `ReadTimeout`-ing; (b) passing accumulated step-output summaries explicitly in each step's dispatch body (the deferred half of OQ-262 Option C) would avoid the executor needing to re-read large source documents to recover prior steps' findings at all | (a) **Implemented 2026-06-11** -- new `ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS = 590.0`, used only by `_cf_complete_once`'s step-dispatch call; `litellm_config.yaml`'s `request_timeout` raised 300 -> 600 to stay above it. Cheap, reversible config change, no OQ needed -- **untested live** (no run has yet produced a step large enough to need >290s). (b) **Resolved 2026-06-11** -- implemented as OQ-263 Option A (commit `62105b48`) and live-validated (run `2b3ea4aba969d3d3`, 7/7 steps, findings carried forward correctly). | Confirmed 2026-06-11: after the CB-9 fix correctly resumed `97ee060abc9315f1` and auto-advanced through step 5/8 (YES), step 6/8 ("create a summary file from the four sentences identified in steps 2-5") had no record of those sentences -- `_build_step_dispatch_body` always reset to a narrow `[system, step-prompt]` frame per step, with no carry-forward, even for in-session auto-advance. The executor exhausted `git log`/`git reflog`/file-search dead ends, then read the entire ~1700-line roadmap doc (the source of the four sentences) into context, jumping the prompt from 32 msgs/108,946 chars to 34 msgs/178,311 chars in one step. `_cf_complete_once`'s non-streaming `httpx.AsyncClient` timeout (290s at the time, despite the original CB-10 framing citing the now-superseded 120s value) could not complete that call and raised `ReadTimeout`, halting the run cleanly (`status: halted`, `current: 6`, no working-tree changes). **(b) fix validated 2026-06-11**: a fresh 7-step run with a structurally identical final step (synthesize a summary file from facts identified in earlier steps) completed end-to-end -- step 7 wrote the summary file using only the carried-forward "Prior step findings" block, with no re-read of source documents. See section 8, CB-9 and CB-10(a)/(b) live validation entries |
| CB-9 | **Orchestrator resume cannot run non-interactively (`cline --id` requires a TTY)** | `_orchestrator_key()` re-derives a paused run's identity from the first user message, which only happens if Cline replays the paused session's history via `--id <session-id>` resume; if `--id` resume requires an interactive TTY in this scripted environment, every OQ pause is permanently stuck | Confirmed 2026-06-11 (run `97ee060abc9315f1`, resuming the OQ-259 pause at step 5/8); **architect decision recorded 2026-06-11: Option C** -- **implemented 2026-06-11, live resume of `97ee060abc9315f1` pending** | Confirmed 2026-06-11: four distinct invocation styles (`--id ... "continue"`; the same with `"continue"` piped via stdin per the `run-cline.ps1` trick; `--id ... --json -t 20 "continue"`; `-i --tui --id ... -t 60 "continue"`) all failed identically with TTY-related errors (`error: interactive mode requires a TTY (stdin/stdout must both be terminals)` / `JSON output mode requires a prompt argument or piped stdin (interactive mode is unsupported)`). Fresh, non-`--id` "act mode" invocations (what `run-cline.ps1` uses for new tasks) are unaffected. Raised to architect as OQ-262 (Options A/B/C); **architect confirmed Option C 2026-06-11**: eliminate session-spanning pauses entirely -- every step is dispatched as a fresh, independent (non-`--id`) cline invocation, with the current step plus accumulated step-output summaries passed explicitly in the prompt; `_orchestrator_key` is re-derived from a fixed key embedded in every step's prompt rather than session replay; "pause for OQ" means "don't dispatch the next step's invocation yet." **Implemented 2026-06-11** as the targeted fix for the resume-from-pause case (the part of Option C that actually blocks CB-9): `_orchestrator_key` now also matches an embedded `[orchestrator-key: <hex>] ` marker; `_format_resume_prompt(key, state)` builds a short marker-bearing "continue" message for the resolved step + the next step's task; a new resume branch in `_handle_orchestrated_request` recognizes a fresh (non-`--id`) single-message session carrying that marker against a `paused_for_oq` run as the architect's "continue" verdict and dispatches the next step; `_new_orchestrator_state` now records `model` (the `@cf/...` model the run started with) so a resume script can relaunch with the same model; `--print-resume-prompt <key>` (CLI mode) and `scripts/resume-orchestrator-run.ps1` wire this into a one-command resume. In-session step-to-step auto-advance (the YES-verdict path) is unchanged -- it doesn't hit CB-9. Unit tests: `scripts/tests/test_local_mcp_orchestrator_resume.py`. Live resume of `97ee060abc9315f1` from step 5/8 (its state file predates this change and has no `model` field, so `-Model cf/kimi-k2.6` must be passed explicitly to `resume-orchestrator-run.ps1`) is the next validation step. See section 8 |
| CB-11 | **Validator false-positives on read-only "Record/Identify the exact quote" steps and on post-commit clean-diff steps** | `_run_validator_pass`'s snapshot-diff approach conflates "no working-tree diff" with "the step did nothing," but both "record a fact" steps (read-only by design) and "commit" steps (clean diff vs. HEAD after a successful commit) legitimately produce empty/no diffs | **Implemented and Verified 2026-06-12** | Confirmed twice now for "Record/Identify the exact quote/sentence stating X" steps (run `97ee060abc9315f1` step 4/8, test #13; run `a731f317e9507669` step 4/8, test #14) -- both auto-raised an `OQ-259` and both resolved Option A with identical reasoning ("read-only step, empty diff is correct by design"). A third, structurally distinct instance hit run `a731f317e9507669` step 8/8 (the final `git commit` step): after a successful commit, `git status`/`git diff` vs. HEAD is clean, which the validator can't distinguish from "did nothing" -- auto-raised `OQ-260`, also resolved Option A (commit `1abe98d4` had in fact succeeded). All three OQs consumed an architect round-trip for a predictable, by-design outcome. **Fix (2026-06-12)**: new `_VALIDATOR_RECORD_ONLY_STEP_RE` treats a step task matching "Record/Identify/Note/Quote/Locate the exact quote/sentence/wording/text/value ..." as read-only-by-design, so an empty diff yields YES instead of AMBIGUOUS even if the task wording also contains an incidental change-verb (e.g. "...after the fix..."); separately, `_run_validator_pass` now accepts a `head_changed` flag (derived in `_finish_step` from `_git_snapshot`'s pre-/post-step `git rev-parse HEAD`) so a successful commit with a clean working tree also yields YES ("HEAD advanced"). 5 new unit tests in `test_local_mcp_validator.py` (`TestCB11RecordOnlyStepFalsePositive`, `TestCB11PostCommitCleanDiff`), all passing. **Verified 2026-06-12 (test #15)**: the post-commit `head_changed` fix worked on the first try -- step 9/9's `git commit` validated YES immediately ("the working tree is clean but HEAD advanced"), no OQ raised, the first time this scenario hasn't needed an architect round-trip. **Residual gap found (test #15, step 5/9)**: the step task was "**Copy** the exact sentence stating the through-proxy result... after the fix" -- `_VALIDATOR_RECORD_ONLY_STEP_RE` only matches `record\|identify\|note\|quote\|locate`, not `copy`, so this still produced AMBIGUOUS/OQ-259 and needed Option A. **Follow-up fix (2026-06-12)**: added `copy\|transcribe\|extract` to the verb alternation (all still gated by the existing "exact quote/sentence/wording/text/value" requirement, so a refactor-style "extract this into a function" step is unaffected -- covered by `test_extract_function_refactor_step_still_ambiguous`). 4 new unit tests in `TestCB11CopyVerbStepFalsePositive`. Full suite: 44/44 pass. **New variant found 2026-06-12 (essay task 2, run `90c2dbb2a162a15b`, step 2/12)**: "Create a new empty file at `<path>`" -- the file WAS created (confirmed empty via read-back), but `git diff`/`git status`-based change detection doesn't see a brand-new **untracked** file as "changed" (`0 file(s) changed, head_changed=False`), so the validator raised AMBIGUOUS even though the step succeeded. This is the same root cause (snapshot-diff can't distinguish "nothing happened" from "something happened that the diff mechanism doesn't surface") applied to a third step shape: not read-only-by-design (CB-11 original) or post-commit-clean (CB-11 `head_changed`), but post-creation-of-an-untracked-file. Resolved Option A (OQ-266, second occurrence -- see CB-18). Not yet fixed; candidate fix is to extend `_git_snapshot`/`_run_validator_pass` to also diff `git status --porcelain` (which DOES list untracked files) rather than only `git diff`. See section 8 |
| CB-12 | **Resume-as-"continue" (CB-9/Option C) path doesn't record a finding for the step it resolves as complete** | `_handle_orchestrated_request`'s resume-marker branch advances `current` and dispatches the next step but never calls `_extract_step_finding`/appends to `state["findings"]` for the resolved step, unlike the normal `_finish_step` YES auto-advance path -- so any step resolved via an OQ Option A pause silently drops out of the CB-10(b) findings-carry-forward block for all subsequent steps | **Implemented and Verified 2026-06-12** | Confirmed 2026-06-12: run `a731f317e9507669` step 4/8 ("Record the exact quote stating the through-proxy result for test #10 after the fix") was resolved via OQ-259/Option A and resumed; its finding was never appended to `state["findings"]`. Step 6/8 ("create `cb7-ac2-validation-summary.md` with the four quotes") therefore received a "Prior step findings" block containing only steps 1, 2, 3, 5 -- missing fact (3) (the through-proxy result, `completion_tokens: 6324` in `121s`) entirely. The committed `cb7-ac2-validation-summary.md` (commit `1abe98d4`) has no bullet for fact (3) as a direct, traced result. **Fix (2026-06-12)**: `_finish_step`'s ambiguous branch now records `state["ambiguity_last_summary"]` and `state["ambiguity_oq_id"]`; a new `_record_resolved_step_finding(state, step_idx)` helper extracts a finding from that summary (or synthesizes a placeholder referencing the OQ and "Option A" if the summary yields nothing) and appends it to `state["findings"]`, the same as `_finish_step`'s YES auto-advance path. Called from both resume-resolution branches in `_handle_orchestrated_request` (the fresh-session "(a-resume)" marker path and the in-session "(a)" continue path). 5 new unit tests in `test_local_mcp_orchestrator_findings.py` (`TestRecordResolvedStepFinding`), all passing. **Verified 2026-06-12 (test #15)**: step 5/9 ("Copy the exact sentence stating the through-proxy result... after the fix") was resolved via OQ-259/Option A and resumed; its finding (`completion_tokens: 6324` in `121s`) was correctly appended to `state["findings"]` and reached step 6/9's "Prior step findings" block, which then produced the **correct** cost-range fact (`$0.025-0.037 per call`) where test #14 had fabricated `$0.0003-$0.003`. See section 8 |
| CB-13 | **Orchestrator step executor wrote its output file to the wrong absolute path** | A "create file X" step's Cline session may resolve relative paths against the wrong working directory, writing to (e.g.) `C:\Users\jakeh\foundation\...` instead of `C:\Users\jakeh\source\repos\Electron-Splines\foundation\...` -- the repo's working tree is then unchanged, which `_run_validator_pass` correctly flags as AMBIGUOUS (this is the validator working as intended, not a CB-11 case) | **Fixed and Verified 2026-06-12 (AT-1140 test #17)** | Confirmed 2026-06-12: run `a731f317e9507669` step 7/9 ("Create `cb7-ac2-validation-summary.md` containing exactly four bullet points...") reported success ("file created/overwritten successfully", listed as a changed file in its own summary) and even ran `cmd.exe /c type C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md` to "verify" it -- but that path is missing `source\repos\Electron-Splines\`. The real target file in the repo was untouched (`git status` clean), so the validator correctly raised `OQ-260` as AMBIGUOUS. The file *content* the executor produced was verbatim-correct (all 4 facts) -- only the path was wrong. Resolved manually for test #15 (content copied into the correct repo path by hand, then OQ-260 resolved Option A so steps 8/9-9/9 could stage/commit it). **Root cause (2026-06-12)**: `run-cline.ps1`'s `Start-Process -FilePath cmd.exe ...` call had no `-WorkingDirectory`, so the spawned `cmd.exe`/`npx cline` process inherits the *calling* PowerShell session's current location, not the repo root. `Push-Location $env:USERPROFILE; Start-Process -FilePath cmd.exe -ArgumentList '/c','cd > out.txt' -NoNewWindow -PassThru` empirically writes `C:\Users\jakeh` to `out.txt` -- confirming that when `run-cline.ps1` (or a wrapper like `resume-orchestrator-run.ps1`/`run_cb7_ac2_test15.ps1`) is launched from a shell whose cwd is `$env:USERPROFILE`, `cline`'s `process.cwd()` is `$env:USERPROFILE` too, and it resolves the task's relative path `foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md` against that -- producing exactly the observed wrong path. **Fix**: added `-WorkingDirectory $repoRoot` (`Split-Path -Parent $PSScriptRoot`) to the `Start-Process` call in `run-cline.ps1`, pinning the spawned process's cwd to the repo root regardless of the caller's location. Verified empirically with the same `Push-Location $env:USERPROFILE` + `Start-Process -WorkingDirectory $repoRoot` repro -- `out.txt` now correctly contains the repo root. The stray file at `C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md` (outside the repo) was a known artifact of the pre-fix behavior; deleted 2026-06-12 with user authorization. **AT-1140 (2026-06-12, test #16)** attempted the live, non-repo-root-cwd re-validation of this fix but stalled at step 7/11 (CB-14) before reaching the file-creation step. **Verified live 2026-06-12 (AT-1140 test #17, run `be93f4ca79f39b49`, step 7/9)**: launched from `$env:USERPROFILE` via `resume-orchestrator-run.ps1`, the file-creation step wrote `foundation/SR-1.4-ai-guidance/docs/at1140-validation-summary-test17.md` to the correct repo path on the first try -- `-WorkingDirectory $repoRoot` confirmed working end-to-end. See section 8 |
| CB-14 | **A step whose response includes Cline-terminal `tool_calls` (e.g. `attempt_completion`) permanently strands the orchestrator at `status: "running"`** | `_dispatch_step` relays ANY non-empty `tool_calls` list to Cline and waits for a tool-result round trip to resume via the "(b) Mid-step continuation" branch -- but Cline-terminal tools (`attempt_completion`, possibly `ask_followup_question`/`plan_mode_respond`) end the CLI session instead of producing a tool result, so `_finish_step` (validator pass, finding recording, auto-advance) never runs for that step | **Implemented and Verified 2026-06-12 (AT-1140 test #17)** | By elimination of `_dispatch_step`'s branches (local-mcp.py:2283-2306): a transport-error halt or an empty-`tool_calls` `_finish_step` call would both have produced a log entry, and run `eb45b9846fdc72f1` has none after "dispatching step 7/11" even though `run-cline.ps1` exited cleanly (exit 0, 672.8s) with step 7's answer text as Cline's apparent final response. The leading hypothesis is `cf/kimi-k2.6` returned a non-empty `tool_calls` (most likely `attempt_completion`, in `_KNOWN_TOOLS`) for a "Copy the exact sentence ..." step that, from the model's perspective with full prior-step context, looked like the final answer to the whole task. State stuck at `status: "running", current: 7` -- no halt, no OQ, no error (a silent-fallback / First-Class-Scenarios violation). **Fix (AT-1141, 2026-06-12)**: added `_cline_terminal_tool_summary` (local-mcp.py, just above `_dispatch_step`) -- if a step response's `tool_calls` are made up ENTIRELY of `attempt_completion` / `ask_followup_question` / `plan_mode_respond` (the Cline-terminal tools, per `_CLINE_TERMINAL_TOOL_ARG_KEYS`), `_dispatch_step` now routes the call's `result`/`question`/`response` text (plus any `content`) through `_finish_step` directly instead of relaying to Cline, logging an `_orchestrator_log` entry tagged "CB-14" so a stranded-`status: "running"` state can no longer occur silently. **Precedence for mixed tool_calls**: if ANY tool call in the list is a real action tool (not in `_CLINE_TERMINAL_TOOL_ARG_KEYS`), the whole list is relayed to Cline unchanged -- the existing, regression-tested path -- documented and covered by `test_mixed_terminal_and_real_tool_returns_none` / `test_mixed_terminal_and_real_tool_is_relayed_unchanged`. New tests in `scripts/tests/test_local_mcp_orchestrator_cb14.py` (13 tests) pass alongside the existing 44/44 suite (57/57 total). State file `eb45b9846fdc72f1.json` left as-is (evidence); do not reuse this key -- AT-1140 re-run (test #17) uses a fresh key. **Verified live 2026-06-12 (AT-1140 test #17, run `be93f4ca79f39b49`, steps 5/9 and 6/9)**: both "Extract the exact sentence ..." steps -- the same shape that stranded test #16's step 7 -- completed cleanly with no `status: "running"` strand, auto-advancing YES. See section 8 |
| CB-15 | **The local-mcp.py orchestrator server (port 3100) is a long-running process that is never automatically restarted after edits to `local-mcp.py`, and has no version/staleness observability signal** | `_run_validator_pass`/`_dispatch_step` and other orchestrator logic only take effect once the running uvicorn process (no `reload=`) is restarted; there is no startup log line or health-check field reporting the running commit SHA, so a stale server can silently serve pre-fix behavior that is indistinguishable from a real regression, consuming an architect OQ round-trip on a false positive | **Found and worked around 2026-06-12 (AT-1140 test #17, step 4/9)**; **systemic fix implemented and verified 2026-06-14 (AT-1142)** | Confirmed 2026-06-12: test #17 step 4/9 ("Extract the exact sentence ... that begins with the bolded label \"Fix (AT-1141, 2026-06-12)\".") returned AMBIGUOUS ("the step's own wording implies a working-tree change, but the diff is empty and the summary doesn't explain why") even though `_VALIDATOR_RECORD_ONLY_STEP_RE` (current source, commit `25071d8c`) matches this step's text (`re.search` confirmed offline: `span=(0, 26), match='Extract the exact sentence'`), which should have produced YES. Root cause: the running server (PID 2932, parent 23732, port 3100) had `CreationDate` 09:18:46, predating BOTH `25071d8c` (CB-11 fix, 10:01:11) and `72eb75cc` (CB-14 fix, 11:01:40) -- it was serving pre-CB-11 validator logic where this step's `is_record_only_step` would be `False`, producing exactly the observed false-positive AMBIGUOUS. `toolchain-doctor.ps1`'s health check (`/sse` responds) reported "OK" immediately before this run because it checks liveness only, not code freshness. OQ-265 (raised for this step) resolved Option A (the extraction was verbatim-correct; treat as complete); the server was then restarted (`Stop-Process -Id 2932,23732 -Force`, relaunched via toolchain-doctor's plain-background-process path -- `.venv\Scripts\python.exe scripts\local-mcp.py` from repo root, logs to `cf_proxy_live.log`/`cf_proxy_live.err.log`), new PID confirmed via `Get-CimInstance Win32_Process` to have `CreationDate` after `72eb75cc`. **AT-1142 fix implemented and verified 2026-06-14**: `local-mcp.py` now computes `_get_server_commit_sha()` (`git rev-parse --short HEAD` run against the skein-toolkit repo root, NOT the consuming project's `WORKSPACE`) at startup -- printed to stdout alongside the existing startup banner -- and serves it on a new `Route("/health", _health)` returning `{"status": "ok", "commit": "<sha>"}`; if `git` is unavailable or fails, it logs to stderr and reports `"unknown"` (a named, observable degenerate-input handler per the First-Class Scenarios policy, not a silent fallback). `toolchain-doctor.ps1` check 2/5 now, when `/sse` is up, calls `/health` and compares its `commit` field against `git -C $RepoRoot rev-parse --short HEAD`: a match reports **OK** (commit shown); a mismatch, or an unreachable/missing `/health` (meaning the running process predates AT-1142 and is therefore definitionally stale), reports a new **STALE** state -- distinct color (yellow) and its own `LocalMcpStale` field on the returned `[PSCustomObject]`, separate from `LocalMcpOk`/`PROBLEM`. **`-Fix` decision (AT-1142d)**: on STALE, `-Fix` (the default) auto-restarts using the same kill-port-3100-and-plain-relaunch sequence as the "nothing listening" case (`Stop-Process -Id <ownerPid> -Force`, then relaunch via the new shared `Start-LocalMcpAndWait` helper), since this is exactly CB-15's manual fix; `-DiagnoseOnly` reports STALE without restarting. **Verified live 2026-06-14**: the actual long-running server left over from before this fix (PID 32264, no `/health` route, predating AT-1142) was correctly reported `STALE: ... /health is missing or unreachable (PID 32264)` by `toolchain-doctor.ps1 -DiagnoseOnly`; after restarting it with the new code, the same script reported `OK - local-mcp.py is up, /sse responds, and is running the current commit (7cc971f)` and `LocalMcpStale = False`. **Correctness fix (same day, commit `1264982`)**: the initial `_health` implementation called `_get_server_commit_sha()` per-request, so it always re-ran `git rev-parse HEAD` and reported the CURRENT working tree -- a process running stale in-memory code would self-report as fresh, defeating the entire check. Fixed by computing the SHA once at import time into a frozen `_SERVER_STARTUP_COMMIT_SHA`. **Re-verified live after this fix**: making the fix's own commit advanced HEAD from `d75a12e` (the SHA the then-running process had frozen at startup) to `1264982`; `toolchain-doctor.ps1 -DiagnoseOnly` correctly reported `STALE: local-mcp.py (PID 38868) is running commit d75a12e, but the working tree is at 1264982`; the default (`-Fix`) run hit the new `$VenvPython`-missing guard (`FIX SKIPPED: ...python.exe not found`) cleanly -- a pre-existing config gap on this machine (`skein-toolkit/.venv` doesn't exist; local-mcp.py is normally run from the Electron-Splines repo's `.venv` instead), not a new bug, and not part of AT-1142's scope -- without crashing or killing the live process. After a manual restart, `/health` reported `1264982`, matching HEAD (OK). 5 new unit tests in `mcp-server/tests/test_local_mcp_health.py` (`_get_server_commit_sha` real-repo/error-path cases, `/health` route success and `"unknown"`-commit cases); full Python suite 104/104 pass. See section 8 |
| CB-16 | **`_stream()`'s hardcoded 60s httpx timeout (separate from the non-streaming path's timeout constant) causes a Cline "thinking loop" on large kimi-k2.6 contexts** | Cline always sends `stream=true`, so every Cline request goes through `_stream()`, which opened its `httpx.AsyncClient` with a hardcoded `timeout=60.0` -- never updated when the sibling non-streaming-path constant (`CF_NON_STREAM_TIMEOUT_SECONDS`) was raised to 290s for kimi-k2.6 (2026-06-11, test #10). Once a conversation's context grows large enough that kimi-k2.6 needs >60s, `_stream()` raises `httpcore.ReadTimeout`/`httpx.ReadTimeout`; Cline retries with the now-larger context (including the failed turn), `_detect_multi_step_ask` re-fires its planner pass on the retry (an extra LLM call that produces no new steps), and the cycle repeats indefinitely with CF spend climbing each iteration | **Fixed 2026-06-12** -- `CF_NON_STREAM_TIMEOUT_SECONDS` renamed to `CF_FORWARD_TIMEOUT_SECONDS` (still 290.0) and shared by both `_cf_complete_once`/`_cf_proxy` and `_stream()`; 57/57 tests pass | Found live in `cf_proxy_live.err.log`: 16 consecutive identical `POST /cfproxy/.../chat/completions` 200s on one connection, each followed by "multi-step ask detected" -> "planner pass returned no numbered steps... forwarding original request unchanged" -> `ERROR: Exception in ASGI application` -> `httpcore.ReadTimeout`, with message count growing 13->14->17->18->19 and prompt size growing 50492->59281 chars, and observed spend climbing $2.1718->$2.2643 USD over the window. Fix: `_stream()`'s `httpx.AsyncClient(timeout=60.0)` -> `httpx.AsyncClient(timeout=CF_FORWARD_TIMEOUT_SECONDS)`. Server restarted (PID 33920 killed, relaunched) so the fix takes effect for the next Cline turn. See section 8 |
| CB-17 | **Orchestrator `status: "running"` (non-paused) runs interrupted by `run-cline.ps1`'s own `-TimeoutSec` wrapper ceiling have no resume path -- naive re-send of the trigger prompt re-plans from scratch and overwrites the in-progress state at the same key** | `_orchestrator_key` is a content hash of the first user message, so re-sending that exact text in a fresh session re-derives the same key; but `_handle_orchestrated_request` runs `_detect_multi_step_ask`'s planner pass again unconditionally on a fresh first message, producing a new (non-deterministic) plan that overwrites any existing `running`/`paused_for_oq` state for that key, discarding `current`/`findings`/progress | **Found 2026-06-12 (essay task 1, run `81c97430204a89e0`) -- not yet fixed; `--print-resume-prompt`/Option A (CB-9/OQ-262) only covers `status == "paused_for_oq"`, not a wrapper-killed `status == "running"` run** | Confirmed 2026-06-12: a 7-step essay-writing run (`81c97430204a89e0`, model `cf/kimi-k2.6`) reached `status: "running", current: 4` (steps 1-3 resolved, essay file at 394 lines/3194 words) when `run-cline.ps1 -TimeoutSec 1800` killed the Cline process mid-step-4 (exit 124) -- a separate ceiling from `CF_FORWARD_TIMEOUT_SECONDS`/`ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS`, neither of which was exceeded (0 `ReadTimeout` across the whole run). Re-sending the identical 889-char trigger prompt (verified `sha256(text.strip())[:16] == "81c97430204a89e0"`) in a fresh `run-cline.ps1` session did NOT resume step 4 -- the planner ran again, produced a different 11-step plan, and overwrote the state file's `current`/`findings` for steps 1-3. The new plan's step 1 re-hit the same "directory already exists" ambiguity as the original step 1, raising **OQ-267** (near-duplicate of the already-resolved **OQ-266**). See section 8 |
| CB-18 | **`_next_oq_id` reuses IDs that have already been retired from the live OQ table, causing collisions with unrelated, already-answered questions** | `_next_oq_id` only scans the live `| OQ-NNN |` table rows in `architect-open-questions.md` for the highest existing ID and increments; it does not account for IDs that were assigned, answered, and then removed from the live table (moved into the "Last updated" changelog narrative) | **First flagged 2026-06-11** (OQ-259 collision); **recurred TWICE more on 2026-06-12** (essay task 2, run `90c2dbb2a162a15b`, both OQ-266 and OQ-267 reused within the same session) -- not yet fixed | Confirmed 2026-06-12: earlier in this same session, OQ-266 and OQ-267 (both raised by essay-task-1 run `81c97430204a89e0`) were resolved Option A and their table rows removed (folded into the "Last updated" changelog entry). The very next orchestrator run (essay task 2, run `90c2dbb2a162a15b`, a DIFFERENT run/key/topic) raised a NEW ambiguity at its step 2/12 and `_next_oq_id` assigned it **OQ-266** again. After OQ-266 (second occurrence) was resolved Option A and the run resumed, step 3/12 raised yet ANOTHER new, unrelated ambiguity (the CB-19 "step overshoot" finding below) and `_next_oq_id` assigned it **OQ-267** -- the SAME ID retired minutes earlier for the unrelated essay-task-1 pair. Three reuse collisions in one session (OQ-259, OQ-266, OQ-267), all involving completely unrelated questions sharing an ID. Candidate fix: persist a monotonic "highest ID ever issued" counter (e.g. a small JSON file alongside `~/.cf_proxy_orchestrator/`) instead of re-deriving from the live table on each call, so retired/removed rows don't free up their IDs for reuse. See section 8 |
| CB-19 | **A single orchestrator step's executor session can silently perform multiple subsequent steps' worth of work, desynchronizing the orchestrator's step counter from the actual working-tree state** | The executor (`cf/kimi-k2.6` via Cline, AutoApprove) is dispatched one step's instruction text but, given full task context, may continue working past that instruction within the same session/dispatch -- writing content that belongs to later steps in the plan. The orchestrator's bookkeeping (`current`, per-step validator pass) has no way to detect this; the NEXT step's validator then finds the file already contains its expected output and returns AMBIGUOUS | **Found 2026-06-12 (essay task 2, run `90c2dbb2a162a15b`, step 3/12)** -- not yet fixed | Confirmed 2026-06-12: step 2/12 ("Create a new empty file at `essay-toolchain-comparison-odysseus-2026-06-12.md`") was dispatched and its own finding/read-back reported the file as empty (a single blank line) -- this was the basis for OQ-266 (second occurrence, CB-11 untracked-file variant). One resume cycle later, step 3/12 ("Write the frontmatter block and document title into the new file") found the SAME file already contained frontmatter, title, AND two full body sections ("Introduction: The Electron-Splines Toolchain" and "The Odysseus Architecture", ~529 words) -- i.e. steps 3, 4, AND 5's output already existed, written sometime during step 2's dispatch (445.8s) despite step 2's own report saying otherwise. `_run_validator_pass` correctly returned AMBIGUOUS for step 3 (0 files changed vs. its own pre-step snapshot, since the content was already present before step 3 was even dispatched), raising OQ-267 (third CB-18 reuse). Stopped here by architect decision rather than continuing the cascade into steps 4-5 (whose content also already exists and would likely repeat this pattern). Candidate fix directions (untried): (a) after each step, re-run the validator against the ORIGINAL pre-run snapshot (not just the pre-this-step snapshot) and detect when multiple subsequent steps' acceptance criteria are already met, auto-advancing past them with synthesized findings; (b) constrain the executor's system prompt to do ONLY the current step and explicitly stop, even if it can see further steps in context. See section 8 |
| CB-20 | **All `run-cline.ps1` dispatch routes (`claude/sonnet-4` and `cf/*`) are currently unusable -- one by real billing exhaustion, one by missing credentials** | N/A -- this is an infrastructure-availability finding, not a model-behavior hypothesis | **Found 2026-06-15** -- blocks all unsupervised Cline dispatch until the user resolves one of the two routes; not a code fix | Confirmed 2026-06-15: a `run-cline.ps1 -Model claude/sonnet-4` dispatch for AT-1110 (Lane 111) got through `toolchain-doctor.ps1` preflight, ran for 268.6s making real edits via the LiteLLM proxy, then exited 1 with `litellm.BadRequestError: AnthropicException - "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."` -- this is a real Anthropic account billing wall, not a code bug; AT-1110's partial edits were salvaged, verified (`yarn build` clean for the changed files), and committed (`e3b0a60b`) by the primary Claude session. Separately, the same preflight reported `cf/*` models' Cloudflare API token check `SKIPPED: skein-toolkit/mcp-server/litellm.env not found`; a direct `curl` to the LiteLLM proxy for `cf/kimi-k2.6`, `claude/sonnet-4`, `groq/kimi-k2`, and `deepseek/v4-flash` (no `Authorization` header) all returned `401 "No api key passed in"` -- consistent with no provider keys being loaded for an unauthenticated request, though Cline's own request (with its configured LiteLLM master key) got past this layer and reached Anthropic's billing check for `claude/sonnet-4` specifically, so `cf/*`'s actual availability (once a CF token is configured in `litellm.env`) is untested. Resolution requires the user to either (a) add Anthropic API credits (unblocks `claude/sonnet-4`, the route validated by AT-1115/AT-1158/AT-1156/AT-1110 earlier today), or (b) populate `skein-toolkit/mcp-server/litellm.env` from `litellm.env.example` with a valid Cloudflare Workers AI token and restart the LiteLLM proxy (unblocks `cf/*`). Until then, well-specified Small/Tier-R tasks are being done directly by the primary Claude session instead of via Cline, at higher per-task cost but keeping the "completed or blocked by OQs" goal on track. See section 8 |

---

## 6. Validation methodology

For any strategy above, "measured" means at minimum:

1. Use `run-cline.ps1` with a fixed task prompt (reuse the Test 3 investigation-style prompt
   from 2026-06-11, or a new one of similar shape: 3+ tool calls expected, ~15-20K tokens of
   accumulated tool output without the change).
2. Capture `cf_proxy_live.err.log` for the run. Look specifically for:
   - `degenerate empty response ... persisted across N attempts -- giving up` (the failure
     signature)
   - `prompt=NNNNN` token counts on the call(s) immediately before any degenerate response
   - whether the orchestrator (if active) reaches `status: "complete"` or stalls at
     `"running"` with no further log entries
3. Before/after: run the same prompt with the change disabled and enabled (or before/after
   the commit), and compare the above. A strategy "works" if the degenerate-response
   signature disappears or the prompt-token count at failure moves measurably higher.
4. Attach (or reference by path/timestamp) both log excerpts in the experiment log entry.

This mirrors the SR-1.16 headless-harness closed-loop RCA pattern (CLAUDE.md "Debugging UI /
Renderer Bugs"), adapted for the CF proxy: log-driven evidence, not "I changed it and it
felt better."

---

## 7. Research starting points (gathered 2026-06-11)

- Anthropic, "Context Engineering" (Sept 2025) -- curating the optimal token set per
  inference call; multi-agent subagents return condensed 1-2K token summaries, never raw
  tool output, to the orchestrator.
- Chroma, "Context Rot" -- model performance degrades as input token count grows, with
  degradation strongly position- and content-shape-dependent, not purely length-dependent;
  "lost in the middle" effect for long contexts.
- Factory.ai evaluation (36,000 real engineering sessions) -- merging new summaries into a
  persistent state (vs. raw accumulation) improved accuracy/completeness/continuity; ACON
  reduced memory usage 26-54% while preserving 95%+ task accuracy.
- General LLM-agent task-decomposition literature -- decomposition reduces reasoning
  complexity, enables tool-to-subtask mapping, and isolates failures for targeted
  retry/replan (directly supports CB-4/CB-5).
- Cloudflare Workers AI docs -- gpt-oss-20b/120b context window documented at 128K tokens;
  CF's OpenAI-compatible endpoint passes through extra fields like `reasoning_effort`
  (already exploited, see §3).

When picking up a strategy from §5, do a *fresh* short search before starting -- "context
engineering" is moving fast and these notes will age.

---

## 8. Experiment log

_Append one entry per experiment, newest first. Template:_

```
### YYYY-MM-DD -- CB-N: <one-line description>

**Hypothesis:** ...
**Change:** <commit hash or "none -- baseline run">
**Test prompt:** <verbatim or pointer>
**Before:** <log excerpt / metrics>
**After:** <log excerpt / metrics>
**Result:** Adopted / Rejected / Inconclusive -- why
**Next:** <what this suggests trying next, if anything>
```

### 2026-06-12 -- essay task 2 resume (run `90c2dbb2a162a15b`, step 3/12): CB-16 holds at 164 requests/0 ReadTimeout; new CB-19 (step-session "overshoot") found, CB-18 recurs a third time, run stopped by architect decision

**Hypothesis:** Resolving OQ-266 (second occurrence) Option A and resuming run `90c2dbb2a162a15b` via the safe `paused_for_oq` path (CB-9/OQ-262 Option C) should continue steps 3-12 cleanly and gather further CB-16 evidence.
**Change:** none -- diagnosis/live-test only.
**Test prompt:** `resume-orchestrator-run.ps1 -Key 90c2dbb2a162a15b -TimeoutSec 1800 -AutoApprove` (PowerShell tool, not Bash -- `run-cline.ps1` is blocked by Windows PowerShell's execution policy under the Bash tool's `powershell.exe`).
**Before:** `status: paused_for_oq, current: 2`, OQ-266 (second occurrence) resolved Option A; essay file confirmed empty (1 blank line) per step 2's finding.
**After:** `resume-orchestrator-run.ps1` correctly built the resume prompt ("Step 2/12 is resolved (treat as complete). proceed with step 3/12...") and `run-cline.ps1` completed cleanly (exit 0, 296.8s). Step 3/12 ("Write the frontmatter block and document title into the new file") came back AMBIGUOUS: the executor read the target file and found it ALREADY contained frontmatter, title, AND two full body sections ("Introduction: The Electron-Splines Toolchain" and "The Odysseus Architecture", ~529 words total) -- the output of steps 3, 4, AND 5 combined -- despite step 2 (445.8s, one resume-cycle earlier) having reported the same file as empty. `_run_validator_pass` returned AMBIGUOUS (0 files changed vs. its pre-step-3 snapshot, since the content predated step 3's dispatch) and `_next_oq_id` assigned the new ambiguity **OQ-267** -- the SAME ID retired earlier this session for the unrelated essay-task-1 pair, a THIRD CB-18 collision (OQ-259, OQ-266, OQ-267 all reused in one session). `cf_proxy_live.err.log` still shows 0 `ReadTimeout` across all 164 cumulative CF requests (up from 161) -- **CB-16 remains confirmed fixed** under a third independent run/resume.
**Result:** CB-16 -- Adopted (conclusively confirmed: 0/164 across 3 independent runs spanning the day). New finding CB-19 -- a step's executor session can silently complete several subsequent steps' work in one dispatch, desynchronizing the orchestrator's step counter from the working tree; every step that assumes a smaller diff than what's already on disk comes back AMBIGUOUS. CB-18 -- now confirmed 3 times in one session (OQ-259, OQ-266, OQ-267).
**Next:** Architect chose to STOP this run here (not continue into steps 4-5, whose content already exists and would likely repeat the OQ-267 pattern, each burning another reused ID) given CB-16 is conclusively validated and cumulative spend ($3.02 USD/164 requests) is well over the ~$3.33 AUD/day threshold. The 529-word partial essay (frontmatter, title, intro, Odysseus section) is committed as a partial draft, mirroring the task-1 stop. CB-18 and CB-19 both need real fixes (see their roadmap rows) before any further orchestrated multi-step run is likely to complete without architect round-trips.

### 2026-06-12 -- essay task 2 (run `90c2dbb2a162a15b`): CB-16 holds at 161 requests/0 ReadTimeout; new CB-11 variant (untracked-new-file diff blindness) and CB-18 (`_next_oq_id` reuses a just-retired ID) found at step 2/12

**Hypothesis:** A second essay-writing orchestrator run (Odysseus/open-source toolchain comparison, `cf/kimi-k2.6`, 12-step plan) should continue validating CB-16 (0 ReadTimeout) on a fresh run/key, independent of the CB-17 finding from essay task 1.
**Change:** none -- diagnosis/live-test only.
**Test prompt:** a new ~1226-char trigger (read roadmap sections 1-5, write a comparison essay against Odysseus/Aider/OpenHands to `foundation/SR-1.4-ai-guidance/docs/essay-toolchain-comparison-odysseus-2026-06-12.md`), launched via `run-cline.ps1 -Model cf/kimi-k2.6 -TimeoutSec 1800 -AutoApprove` (new key `90c2dbb2a162a15b`, distinct from task 1's `81c97430204a89e0`).
**Before:** fresh key, no prior state.
**After:** `run-cline.ps1` completed cleanly (exit 0, 445.8s). Step 1/12 ("read roadmap sections 1-5") validated YES and recorded a correct finding summarizing the toolchain. Step 2/12 ("Create a new empty file at `essay-toolchain-comparison-odysseus-2026-06-12.md`") executed correctly -- the file was created and confirmed empty via read-back -- but `_run_validator_pass` returned AMBIGUOUS (`0 file(s) changed, head_changed=False`) because a brand-new **untracked** file doesn't appear in a `git diff`-based change check. This raised an OQ that `_next_oq_id` labeled **OQ-266** -- the SAME ID just retired earlier in this session for an unrelated essay-task-1 ambiguity (now CB-18). `cf_proxy_live.err.log` shows 0 `ReadTimeout` across all 161 CF requests so far (up from ~150 at the end of task 1) -- **CB-16 remains confirmed fixed** under a second independent run.
**Result:** CB-16 -- Adopted (further confirmed). New CB-11 variant -- the snapshot-diff validator is blind to untracked new files, a third shape of the same root cause (see CB-11 row). CB-18 -- `_next_oq_id`'s reuse-after-retirement bug, first flagged 2026-06-11, has now recurred and collided across two completely unrelated runs in the same session.
**Next:** resolve this OQ-266 (second occurrence, run `90c2dbb2a162a15b` step 2/12) Option A via the safe `paused_for_oq` resume path (`resume-orchestrator-run.ps1`/`--print-resume-prompt`, CB-9/OQ-262 Option C -- this run was cleanly `paused_for_oq`, not a CB-17 `running`-interrupt) and continue steps 3-12. CB-11's untracked-file variant and CB-18 both need real fixes (see their roadmap rows) but do not block resuming this run via Option A.

### 2026-06-12 -- CB-17: naive re-send "resume" of a wrapper-killed `status: "running"` orchestrator run overwrites its state with a fresh, conflicting plan (essay task 1, run `81c97430204a89e0`)

**Hypothesis:** Following the CB-16 fix, a 7-step essay-writing orchestrator run (`81c97430204a89e0`, `cf/kimi-k2.6`) was launched as part of CB-16's live validation. After it reached `status: "running", current: 4` and was killed by `run-cline.ps1 -TimeoutSec 1800` (exit 124, a wrapper-level ceiling separate from `CF_FORWARD_TIMEOUT_SECONDS`/`ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS`), re-sending the SAME 889-char trigger prompt (which re-derives the same `_orchestrator_key` by content hash) in a fresh `run-cline.ps1` session should hit the "(b) Mid-step continuation" branch (anchor_index from the dead session > the fresh session's single message, so `new_user_idx is None`) and re-dispatch `state["current"]` (step 4/7) with an empty tail.
**Change:** none -- diagnosis/live-test only.
**Test prompt:** the original essay-task-1 trigger (`scripts/run-cline.ps1 -Task <889-char essay prompt> -Model cf/kimi-k2.6 -TimeoutSec 1800 -AutoApprove`), re-sent verbatim. Confirmed offline: `hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16] == "81c97430204a89e0"`, matching the existing state file's key.
**Before:** `C:\Users\jakeh\.cf_proxy_orchestrator\81c97430204a89e0.json` had `status: "running", current: 4, steps: [7 items]`, `findings: [step 1]`, after steps 1-3 resolved/validated (step 1 via OQ-266/Option A, steps 2-3 YES). `essay-agentic-dev-landscape-2026-06-12.md` was 394 lines / 3194 words, covering sections 1-3 (front matter, major tools, tech stacks) of the 7-step plan.
**After:** the resumed `run-cline.ps1` invocation completed (exit 0, 182.7s), but `81c97430204a89e0.json` now has `status: "paused_for_oq", current: 1, steps: [11 items]` -- a DIFFERENT, freshly-planned 11-step breakdown for the same essay, with step 1 reworded ("Create the directory ... if it does not already exist") vs. the original step 1 ("Create the directory ..."). `_detect_multi_step_ask`'s planner pass ran again on the identical first message and its non-deterministic output overwrote the prior `running` state's `current`/`findings`/7-step plan entirely. The new step 1 immediately hit the same "directory already exists" diff-empty ambiguity as the original and raised **OQ-267**, duplicating the already-resolved **OQ-266**. `cf_proxy_live.err.log` shows 0 `ReadTimeout` across this and all prior calls (~150 requests total, up to 108K chars) -- CB-16 remains separately confirmed fixed.
**Result:** Rejected as a resume mechanism -- re-sending the trigger prompt is NOT equivalent to resuming a `running` run; it silently discards in-progress state and re-litigates settled ambiguities (new OQ for an already-answered question). The essay file's sections 1-3 content (3194 words, real filesystem state) survives, but the orchestrator's record of having produced it does not.
**Next:** `_format_resume_prompt`/`--print-resume-prompt` (CB-9/OQ-262 Option C) only fires for `status == "paused_for_oq"`. `status == "running"` interrupted by `run-cline.ps1`'s own `-TimeoutSec` (independent of `CF_FORWARD_TIMEOUT_SECONDS`) has no analogous path. Two candidate fixes: (a) extend the marker-based resume to also cover `status == "running"`, re-dispatching `state["current"]` (not `current + 1`) for a fresh session; (b) in `_handle_orchestrated_request`, check for an existing `running`/`paused_for_oq` state for the derived key BEFORE invoking `_detect_multi_step_ask`'s planner pass, so a content-hash match against existing state always wins over re-planning. OQ-267 should be resolved with the same Option A reasoning as OQ-266 (directory genuinely exists); the original 7-step plan's steps 4-7 (tactics/strategies, integration, tradeoffs/conclusion, verification) remain undone -- `essay-agentic-dev-landscape-2026-06-12.md` is a 3194-word partial draft (sections 1-3 only). See `architecture-docs/global/architect-open-questions.md` OQ-266/OQ-267.

### 2026-06-12 -- CB-16: Cline "thinking loop" traced to `_stream()`'s stale 60s timeout, separate from the CB-10(a)/test#10 290s fix

**Hypothesis:** A live Cline session reported as "caught in a thinking loop" is repeatedly hitting `httpx.ReadTimeout` in `_stream()` (the SSE path Cline always uses, since it sends `stream=true`), because `_stream()` has its own hardcoded `timeout=60.0` that was never updated when the non-streaming path's timeout was raised to 290s for kimi-k2.6 (2026-06-11, test #10) -- and each retry's growing context re-triggers `_detect_multi_step_ask`'s planner pass, compounding the cost.
**Change:** `scripts/local-mcp.py` -- renamed `CF_NON_STREAM_TIMEOUT_SECONDS` -> `CF_FORWARD_TIMEOUT_SECONDS` (still 290.0, comment broadened to cover both paths) and changed `_stream()`'s `httpx.AsyncClient(timeout=60.0)` to `httpx.AsyncClient(timeout=CF_FORWARD_TIMEOUT_SECONDS)`; `scripts/tests/test_local_mcp_dispatch_timeout.py` updated to reference the renamed constant.
**Test prompt:** n/a -- diagnosis from `cf_proxy_live.err.log`/`cf_proxy_live.log` during a live, in-progress Cline session (no synthetic reproduction run).
**Before:** `cf_proxy_live.err.log` lines ~376-982 show 16 consecutive identical `POST /cfproxy/.../chat/completions` 200 OKs on connection `54134`, each cycle: "multi-step ask detected" -> "planner pass returned no numbered steps... forwarding original request unchanged" -> `ERROR: Exception in ASGI application` -> `httpcore.ReadTimeout`/`httpx.ReadTimeout`. Message count grew 13->14->17->18->19 and prompt size grew 50492->52150->55963->57622->59281 chars across the window; logged CF spend climbed $2.1718 -> $2.2643 USD.
**After:** `_stream()` now uses `CF_FORWARD_TIMEOUT_SECONDS` (290s, matching the documented kimi-k2.6 worst case of ~175s for a 9153-token completion, test #10). Full suite re-run: 57/57 tests pass. Server restarted (PID 33920 killed and relaunched via the standard `Start-Process` procedure) so the running process picks up the fix.
**Result:** Adopted -- root cause matches all observed symptoms (timeout threshold, retry pattern, planner re-fire, spend growth) and the fix is a minimal, targeted constant-sharing change with no behavioral change to the non-streaming path. Not yet re-validated against a live large-context Cline turn (the looping session was still in progress; user asked to cancel it separately to stop spend).
**Next:** Watch the next large-context Cline turn for either a clean completion past 60s or a new failure mode at the 290s ceiling. If `_detect_multi_step_ask` continues to re-fire wastefully on Cline's automatic retries (a related but separate issue -- it shouldn't re-plan on a retry of the same user ask), consider gating the planner pass on "first time seeing this user message" rather than "every dispatch".

### 2026-06-12 -- AT-1140 test #17 complete: 9/9, CB-11/CB-12/CB-13/CB-14 all confirmed live (commit `acb590c8`)

**Hypothesis:** After restarting local-mcp.py (CB-15 workaround) and resolving OQ-265 Option A, test #17 should resume cleanly from step 5/9 and validate CB-13 (file lands in the correct repo path despite a `$env:USERPROFILE` cwd) and CB-14 (extract-sentence steps route through `_finish_step` without stranding) end-to-end for the first time.
**Change:** none -- continuation of the same run (`be93f4ca79f39b49`) against the restarted server (PID 33920, postdating commit `72eb75cc`).
**Test prompt:** `scripts/resume-orchestrator-run.ps1 -Key be93f4ca79f39b49 -TimeoutSec 1800`, invoked from `$env:USERPROFILE` (non-repo-root cwd, the CB-13 reproduction condition), feeding `--print-resume-prompt`'s marker-based "continue" message: `[orchestrator-key: be93f4ca79f39b49] continue -- resuming the paused 9-step run. Step 4/9 is resolved (treat as complete). proceed with step 5/9: ...`.
**Before:** `status: "paused_for_oq", current: 4, findings: 3`.
**After:** Steps 5-9 all auto-advanced YES on first try, no further OQs:
- Step 5/9 ("Extract the exact sentence describing the \"Precedence for mixed tool_calls\" rule from the CB-14 row.") -- YES.
- Step 6/9 ("Extract the exact sentence stating the new test count and the total pass count across the suite from the CB-14 row.") -- YES.
- Step 7/9 (create `foundation/SR-1.4-ai-guidance/docs/at1140-validation-summary-test17.md` with 4 verbatim bullets) -- file created at the **correct repo path** despite the `$env:USERPROFILE` launch cwd. **CB-13's `-WorkingDirectory $repoRoot` fix confirmed live for the first time.**
- Step 8/9 (`git add` the new file) -- YES.
- Step 9/9 (`git commit`) -- YES, `head_changed=True`, commit `acb590c8` ("docs: add AT-1140 live-validation summary (cf/kimi-k2.6 orchestrator test #17)").

Final state: `status: "complete", current: 9, findings: 9`. The committed file's 4 bullets are all verbatim-correct against the CB-14 row's source text (Status, the "Fix (AT-1141, 2026-06-12)" sentence, the "Precedence for mixed tool_calls" sentence, the 57/57 test-count sentence). Run completed in 370.7s (one cline invocation, steps 5-9).

**Result:** **AT-1140 = PASS.** CB-11 (`_VALIDATOR_RECORD_ONLY_STEP_RE`, including the "extract" verb): confirmed live, zero AMBIGUOUS false positives on the current code (step 4's earlier AMBIGUOUS was CB-15, a stale-server artifact, not a CB-11 regression). CB-12 (resolved-step findings carry-forward): confirmed -- step 4's finding was recorded via the resume path, bringing `findings` to 9/9, and reached steps 5-9's "Prior step findings" block. **CB-13** (`run-cline.ps1 -WorkingDirectory $repoRoot`): confirmed live for the first time -- step 7 wrote to the correct repo path from a non-repo-root (`$env:USERPROFILE`) cwd. **CB-14** (`_cline_terminal_tool_summary`): confirmed live -- steps 5/9 and 6/9 (text-answer "extract" steps, the exact shape that stranded test #16's step 7) both completed cleanly with no `status: "running"` strand. CB-15's restart workaround was effective for this run.

**Next:** Mark AT-1140 Done in `ai-task-queue.md`. Update CB-13 and CB-14 rows in section 5 to **Verified**. CB-15's systemic fix (startup commit-SHA logging / health-check staleness field, so `toolchain-doctor.ps1` can distinguish "up" from "up but stale") remains open as an untried follow-up.

### 2026-06-12 -- AT-1140 test #17 step 4/9: new chronic problem CB-15 -- stale local-mcp.py server process served pre-CB-11/CB-14 code, causing a false-positive AMBIGUOUS (OQ-265, resolved Option A)

**Hypothesis:** None going in -- this was AT-1140's re-run (test #17, fresh key `be93f4ca79f39b49`) of the CB-11/CB-13/CB-14 live-validation chain, immediately following the CB-14 fix (commit `72eb75cc`), per CB-14's "do not reuse `eb45b9846fdc72f1`" guidance.
**Change:** none -- baseline run against `72eb75ccbbcaf001957b9c181b9df1781b8d3050` (CB-14 fix commit, HEAD at the time).
**Test prompt:** `run_cb7_ac2_test17.ps1` (untracked, repo root) -- read the CB-14 row in this roadmap's section 5, then create `foundation/SR-1.4-ai-guidance/docs/at1140-validation-summary-test17.md` with 4 verbatim-quoted bullets (the Status column; the "Fix (AT-1141, 2026-06-12)" sentence; the "Precedence for mixed tool_calls" sentence; the test-count sentence), then commit.
**Before:** N/A (first attempt at fresh key `be93f4ca79f39b49`).
**After:** Planner produced a 9-step breakdown (`~/.cf_proxy_orchestrator/be93f4ca79f39b49.json`). Steps 1-3 auto-advanced YES. Step 4/9 ("Extract the exact sentence from the Notes column that begins with the bolded label \"Fix (AT-1141, 2026-06-12)\".") returned **AMBIGUOUS** -- "the step's own wording implies a working-tree change, but the diff is empty and the summary doesn't explain why" -- even though the executor's extraction was verbatim-correct. Offline `re.search` against the current source (`25071d8c`'s `_VALIDATOR_RECORD_ONLY_STEP_RE`) confirms this step's text matches (`span=(0, 26), match='Extract the exact sentence'`), so `is_record_only_step` should be `True` and the verdict should have been YES. Run paused `status: "paused_for_oq", current: 4`; OQ-265 raised.

Root-caused via process-vs-commit timestamps: the running local-mcp.py server (PID 2932, parent 23732, port 3100) had `CreationDate` 12/06/2026 09:18:46, predating BOTH `25071d8c` (CB-11 fix, 10:01:11) and `72eb75cc` (CB-14 fix, 11:01:40). It was serving pre-CB-11 validator logic, where this step's wording (containing the change-verb "fix") with `is_record_only_step=False` produces exactly the observed AMBIGUOUS. `toolchain-doctor.ps1`'s pre-flight health check (`/sse` responds -- "OK - local-mcp.py is up and /sse responds correctly") ran immediately before this and reported healthy, because it checks liveness only, not code freshness.

**Result:** Inconclusive for step 4 itself (false positive, not a real CB-11 regression) -- but a new chronic problem, **CB-15**: the local-mcp.py uvicorn process (`uvicorn.run(..., port=3100, log_level="info")`, no `reload=`) is a long-running dev-toolchain process with no restart-on-edit mechanism and no version/staleness observability (no startup log of `git rev-parse HEAD`, no health-check commit-SHA field). The VS Code "Local MCP Server" debug config (`.vscode/launch.json`, `type: "debugpy"`, `preLaunchTask: "Kill port 3100"`) is the documented restart path, but `debugpy` provides no code-reload over a plain relaunch -- it just attaches a debugger to a freshly-started process.

**Fix (2026-06-12):** `Stop-Process -Id 2932,23732 -Force` (kill port 3100), then relaunch via toolchain-doctor's plain-background-process path (`.venv\Scripts\python.exe scripts\local-mcp.py`, `-WorkingDirectory` repo root, `-WindowStyle Hidden`, logs to `cf_proxy_live.log`/`cf_proxy_live.err.log`). New process (PID 33920) `CreationDate` 12/06/2026 12:57:00, postdating `72eb75cc` (11:01:40) -- confirmed via `Get-CimInstance Win32_Process` vs. `git log -1 --format=%ci 72eb75cc`. `cf_proxy_live.err.log` shows a clean startup ("Application startup complete", "Uvicorn running on http://127.0.0.1:3100"). OQ-265 resolved Option A (step 4's extraction was verbatim-correct; treat as complete) per architect approval; test #17 resumed from step 5/9 against the now-current code.

**Next:** Systemic fix (untried, follow-up): log the running `git rev-parse HEAD` (or short SHA) at local-mcp.py startup, and/or add a commit-SHA field to the `/sse` or a health-check response, so `toolchain-doctor.ps1` can detect "server up but stale" as a distinct, named, observable state (per CLAUDE.md First-Class Scenarios policy) rather than reporting bare liveness as "OK". Also consider folding the kill-port-3100 + plain-relaunch sequence into `toolchain-doctor.ps1` itself as an explicit "restart to pick up code changes" mode, since it is equivalent to (and simpler than) the debugpy debug-config restart.

### 2026-06-12 -- AT-1140 test #16: new chronic problem CB-14 -- a text-step's `attempt_completion` tool call permanently strands the orchestrator in `status: "running"` (steps 1-6/11 confirm CB-11/CB-12 still hold)

**Hypothesis:** None going in -- this was AT-1140's mechanical live-validation re-run of the CB-11 "copy ... after the fix" regex fix and the CB-13 `-WorkingDirectory` fix, invoked from `$env:USERPROFILE` (non-repo-root cwd) per the AT-1140 spec.
**Change:** none -- baseline run against `7280bacd` (OQ-264 decision commit), using a fresh task/key so as not to re-hit test #15's "nothing to commit" confound.
**Test prompt:** `run_cb7_ac2_test16.ps1` (untracked, repo root) -- read the "Architect decision 2026-06-12" text on the OQ-264 row in `architect-open-questions.md`, then create `foundation/SR-1.4-ai-guidance/docs/at1140-validation-summary.md` with 4 verbatim-quoted bullets (Option/model confirmed; CB-1/2/3 backlog + triggers; the deferred heavyweight-model list; the AT-1140-approved closing sentence), then commit. Invoked via `Push-Location $env:USERPROFILE; & "...\run_cb7_ac2_test16.ps1"`.
**Before:** N/A (first attempt at a fresh key, `eb45b9846fdc72f1`).
**After:** Planner produced an 11-step breakdown (`~/.cf_proxy_orchestrator/eb45b9846fdc72f1.json`). Steps 1-6 all auto-advanced YES (read/locate/extract/copy steps, `0 file(s) changed, head_changed=False` -- the simple no-diff-no-failure-language YES path, not the CB-11 `_VALIDATOR_RECORD_ONLY_STEP_RE` branch specifically, since none of steps 1-6's wording happened to contain an incidental change-verb like "fix"). At 01:10:15Z step 6 validated YES and dispatched step 7/11 ("Copy the exact closing sentence stating whether AT-1140 is approved to proceed."). The state file's log ends there -- no `step 7/11 validator verdict` entry was ever written, `state["status"]` remains `"running"`, `state["current"]` remains `7`. `run-cline.ps1` nonetheless exited cleanly (exit 0, 672.8s) and Cline's CLI printed step 7's answer text ("Here is the full ... text: ... AT-1140 is approved to proceed.") as if it were the final response to the whole task. `foundation/SR-1.4-ai-guidance/docs/at1140-validation-summary.md` was never created (`git status` clean; confirmed no stray copy under `$env:USERPROFILE\foundation\...` either).
**Result:** Inconclusive for AT-1140's exit criteria (b) (file-creation step never reached, so CB-13's non-repo-root path is unconfirmed by this run) -- but a genuinely new chronic problem found and logged as **CB-14**. By elimination of `_dispatch_step`'s branches (a `result is None` transport-error halt would have logged "dispatch failed"; an empty-`tool_calls` response would have called `_finish_step` and logged a verdict; neither happened), step 7's response from `cf/kimi-k2.6` must have included a non-empty `tool_calls` list -- most likely a Cline-native `attempt_completion` call (in `_KNOWN_TOOLS`, local-mcp.py:503), since the model had already gathered everything it needed in steps 1-3 and a "Copy the exact sentence ..." step looks, from the model's perspective, like the natural final answer to the whole multi-turn task. `_dispatch_step`'s `if tool_calls: return _synthetic_assistant_response(..., tool_calls=tool_calls)` (local-mcp.py:2304-2305) relays this to Cline unconditionally; Cline executes `attempt_completion` by ending the session -- there is no tool-result round trip for the orchestrator's "(b) Mid-step continuation" branch to catch, so `_finish_step` (and therefore the validator pass, finding recording, and auto-advance) never runs for step 7. The run is permanently stuck at `status: "running", current: 7` with **no halt, no OQ, no error** -- a silent-fallback violation per CLAUDE.md's First-Class Scenarios policy (every `catch`/terminal branch must have an observable side effect; this one has none). State file `eb45b9846fdc72f1.json` is left as-is (status `"running"`) as evidence; do not reuse this key for a fresh run -- a re-invocation with the same trigger text will re-enter the "(b) Mid-step continuation" branch and most likely re-dispatch step 7 into the same stall.
**Next:** CB-14 fix sketch (not yet implemented): in `_dispatch_step`, before relaying `tool_calls` to Cline, check whether the tool-call list is *only* a Cline-terminal call (`attempt_completion`, possibly `ask_followup_question`/`plan_mode_respond`) -- if so, treat the call's `result`/`response` text (or `content`, if present) as the step's final answer and route through `_finish_step` directly, the same as the empty-`tool_calls` path, instead of relaying it to Cline. This needs a named scenario + unit test (`test_local_mcp_orchestrator_*`) per the First-Class Scenarios policy before AT-1140 can be re-attempted. Once fixed, AT-1140 should be re-run with a *new* task/key (e.g. test #17) -- `eb45b9846fdc72f1`'s state is now contaminated and should not be resumed. The positive result from steps 1-6 (CB-11/CB-12's auto-advance + findings-carry-forward machinery still works correctly post-OQ-264) does NOT need to be re-verified; only the file-creation (CB-13) and commit steps remain unvalidated.

### 2026-06-11 -- kimi-k2.6 succeeds with 100x max_tokens; community-prevalence research; proxy 60s timeout was a second, independent bug (test #10)

**Hypothesis:** (1) Test #9's `content: null` / all-reasoning result for `cf/kimi-k2.6` on
the 120-char prompt was an artifact of an unrealistically tight `max_tokens=256`, not a
fundamental defect -- giving the model ~100x the budget (25600) on the *same prompt* would
let it finish reasoning and emit `content`. (2) The CB-1/CB-1-like reasoning/`content`
channel-split failures observed across gpt-oss-120b, gemma-4-26b, and kimi-k2.6 this session
are a known, broadly-reported class of problem in the self-hosted/local-LLM community, not
something specific to this proxy or to CF's deployment.

**Research findings (community prevalence):** This is a widely documented, active problem
across the reasoning-model serving ecosystem, independent of CF or this toolchain:

- **vLLM issue #30498** ("GPT-OSS-120B returns null content when hitting max_tokens without
  `--enforce-eager`") -- a *known vLLM serving bug* for gpt-oss-120b, with a documented
  100% fix rate via `--enforce-eager`. CF Workers AI's serving stack is opaque to us, but if
  it is vLLM-based and does not pass `--enforce-eager`, this single flag could be the entire
  CB-1 root cause -- something we cannot control or even detect from the client side.
- **vLLM issue #23905** ("gpt-oss-120b has high possibility to generate response as part of
  reasoning") and **#29641** ("Max Tokens not being honoured in Chat Completions for GPTOSS
  model") -- corroborating, independent reports of the same channel-confusion family.
- **HuggingFace gpt-oss-120b discussion #67** ("Empty response from chat call with small
  max_token set when running on vLLM") and the general finding that **`max_tokens < 1000`
  makes empty responses for gpt-oss-class models likely, and the model "generally needs
  space for chain of thought"** -- consistent with test #7's degeneration at 1024
  `max_tokens` (the planner pass's budget) on a 1879-token prompt: 1024 is already at the
  bottom of the community-recommended floor, and CB-1 occurs even there.
- **DeepSeek R1 real-world report**: a team running `max_tokens: 200` saw R1 average ~800
  reasoning tokens/call, with **40% of calls hitting the cap mid-reasoning and returning
  empty** -- the same shape as test #9's kimi-k2.6 result (256-token cap, content: null).
  Community guidance: "for reasoning models, use significantly higher token limits --
  1024-4096 tokens at minimum" -- and today's data suggests even that floor is not always
  enough (kimi-k2.6 used ~6300-9150 completion tokens for one short prompt below).
- **MoonshotAI/Kimi-K2 issue #128**: "K2.6 deterministically emits empty `<|im_end|>` after
  `</think>` on multi-turn tool-call followups (OSS deployments ~87% failure rate; the
  *hosted Moonshot API* works on the same context)" -- i.e. Moonshot's own self-hosted-style
  OSS deployments (the category CF's deployment likely falls into) have a much higher
  failure rate than Moonshot's first-party hosted API on multi-turn tool-call conversations
  specifically. Relevant to the orchestrator's per-step tool-call turns (test #6).

**Conclusion:** What we're seeing is **not specific to this toolchain or to CF** -- it is
the current, actively-discussed state of reasoning-model serving across vLLM/SGLang/Bedrock
deployments generally, gpt-oss and Kimi-K2 specifically. The "context budget" framing (§2)
undersold the problem: even the community-recommended `max_tokens` floors (1000-4096) are
sometimes insufficient, and at least one root cause (vLLM's `--enforce-eager` requirement)
is a server-flag issue entirely outside client control.

**Test #10 (`cf/kimi-k2.6`, same prompt as test #9, `max_tokens=25600` = 100x):**
- **Direct CF call** (bypassing the proxy, 280s curl timeout): **200 OK, finish_reason
  "stop"**, `reasoning_content` 25055 chars, `content` 14611 chars (a complete, well-formed
  multi-section answer covering build config, the requested function, tests, and docs).
  `usage.completion_tokens = 9153` (of 25600 budget) in **175s** (~52 tokens/sec).
- **Result: kimi-k2.6 is not degenerate on this prompt** -- test #9's `content: null` was
  purely a `max_tokens=256` budget exhaustion (256 << ~9150 tokens this response actually
  needed), exactly the DeepSeek-R1 community pattern above, not a kimi-specific defect.

**New, independent bug found:** the first attempt to replay this *through the proxy*
(`local-mcp.py`'s `/cfproxy/...` endpoint, `max_tokens=25600`, non-streaming) failed with
**`httpx.ReadTimeout` -> unhandled 500** after exactly 60s. `_cf_proxy`'s non-streaming
forward call used a hardcoded `httpx.AsyncClient(timeout=60.0)`, tuned around gpt-oss's
fast (often degenerate-empty, sub-10s) responses. At kimi-k2.6's ~52 tokens/sec and its
*configured* `max_tokens=8192` (`litellm_config.yaml`), a full-budget response needs ~158s
-- already past 60s even before today's 25600 experiment. **This is a second, independent
failure mode from CB-1/content-degeneracy**: even a kimi-k2.6 call that *would* produce
correct `content` given enough wall-clock time was being killed by the proxy itself at the
60s mark, with `num_retries: 2` then repeating the same doomed 60s wait two more times.
This plausibly explains a meaningful share of kimi-k2.6's poor track record in tests #4-6
(slow, sometimes-failing) independent of any content-quality issue.

**Fixed in commit `f952445b`**: `CF_NON_STREAM_TIMEOUT_SECONDS = 290` (just under LiteLLM's
own `request_timeout: 300`), with a named `cf_proxy_timeout` (504) response + log line on
timeout instead of an unhandled traceback. **Re-verified through the fixed proxy**: the
identical 25600-max_tokens request completed in **121s**, `finish_reason: "stop"`,
`completion_tokens: 6324`, `content` 11897 chars, no spurious tool-call rewrite from
`_parse_any_tool_call` despite the response containing fenced code blocks (Dockerfile,
YAML with `${{ }}` template syntax) that could plausibly have looked tool-call-shaped.

**Result:** Adopted (commit `f952445b`). kimi-k2.6's earlier "degeneration" (test #9) and a
chunk of its earlier slowness/failures (tests #4-6) both trace to **insufficient headroom**
-- token budget in one case, wall-clock timeout in the other -- not to an unfixable model
defect. With both fixed/understood, kimi-k2.6 looks meaningfully more viable than tests
#4-6 suggested. However: **~6300-9150 completion tokens and 120-175s latency for one short
(~30-prompt-token) request** is a real cost/latency profile -- at $4.00/M output tokens
that's $0.025-0.037 per call, and 2-3 minutes of wall-clock per call is slow for an
interactive daily driver. This still points toward kimi-k2.6 as a **Tier B-shaped (batch)
workload** rather than Tier A daily-driver, but it is now a *working* Tier B/escalation
option rather than one blocked by an unexplained 500.

**Next:** Re-attempt the deferred kimi-k2.6 CB-7/AC-2 orchestrator validation (todo from
the previous entry) now that the 60s-timeout bug is fixed -- expect each per-step executor
call to take 1-3 minutes, so budget wall-clock accordingly (a 4-9 step task could
legitimately take 10-25+ minutes, which is fine for a Tier B framing but should not be
mistaken for a stalled/broken run). Also worth testing whether `--enforce-eager`-equivalent
serving-side fixes are available/already applied on CF (no client-side lever exists if not
-- this strengthens the case for the `groq/gpt-oss-120b` alternative-host test once a Groq
key is available, since Groq's custom LPU serving stack is not vLLM and would not share
this specific bug class).

### 2026-06-11 -- CB-7/AC-2 attempt #2: CB-1 reproduces on kimi-k2.6 at ~13.6K-token prompts; planner pass degenerates on every turn (test #11)

**Hypothesis:** With the proxy timeout fixed (commit `f952445b`), a small CB-7-targeted task
(read a section of the roadmap doc, transcribe four facts verbatim into a new file, commit)
run via `run-cline.ps1 -Model cf/kimi-k2.6 -TimeoutSec 1200 -AutoApprove` would reach the
orchestrator's per-step executor and either confirm or refute CB-7's verbatim-quoting fix
(commit `cfa3a2d4`).

**Test prompt:** ~1101-char task: read the test #10 section of
`cf-proxy-cheap-model-context-budget-roadmap.md`, create
`foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md` with four bullets quoting
specific facts (the new `CF_NON_STREAM_TIMEOUT_SECONDS` value + commit hash, test #10's
direct-call and through-proxy `completion_tokens`/elapsed-time pairs, and kimi-k2.6's
per-call cost range) verbatim, then commit.

**Result:** **Failed after 362.9s** (`run-cline` exit 1). Cline's CLI emitted `error: hook
dispatch failed: session.hook requires a valid hook event payload` and `error: The operation
timed out` -- the session's final assistant message has empty `content` (no tool call, no
text). No file was created; working tree unchanged (only this run's own log file is
untracked). Sequence from `cf_proxy_live.err.log`:

1. Two `read_files` calls (full doc, then the test #10 section) + one `git status --short`
   (the orchestrator/Cline checking the tree before committing, per CLAUDE.md's pre-commit
   guidance) -- prompt grew 4716 -> 10238 -> 13019 -> 13629 tokens across 4 CF calls.
2. **`_run_planner_pass` degenerated on all 3/3 calls where it ran**
   (`planner pass returned no content (reasoning_content present: True) -- forwarding
   original request unchanged`). The planner's hardcoded `max_tokens: 1024`
   (`scripts/local-mcp.py` `_run_planner_pass`) is -- per the community research in the
   previous entry -- already below the floor reasoning-model serving guides recommend
   (1024-4096 minimum), so for kimi-k2.6 it appears to **always** degenerate, on every
   turn, not just large ones. The proxy's existing `None`-content guard (commit
   `3d724d79`) handled this correctly (no crash, "forwarding unchanged" is a named,
   logged path) -- but the practical effect is **`_ORCHESTRATOR_STEP_SYSTEM_PROMPT` /
   `_build_step_dispatch_body` (CB-7's fix) is never reached for kimi-k2.6**, because the
   step-list it depends on is never produced. CB-7 remains formally untested for a second
   session in a row, for a different reason than tests #4/#5 (gpt-oss CB-1 on first turn).
3. The 4th call (prompt=13629 tokens, the largest seen this session) hit
   `WARN finish_reason=length ... response truncated at token limit (current buffered=0
   chars, reasoning=32298 chars)` -- kimi-k2.6 spent its **entire 8192-token
   `max_tokens` budget on reasoning** (32298 chars =~ 8192 tokens at this model's
   tokenizer ratio) and emitted **zero `content`** chars. This is CB-1
   (degenerate-empty-response), reproduced on kimi-k2.6, at 13629 prompt tokens --
   `completion_tokens=8192`, cost $0.0328 for this one call (spend $0.7988 -> $0.8489).
4. Proxy retry 2/3 (temperature 0.7) got a `200 OK` at 16:05:52 but no further `[cfproxy]`
   log line was written before Cline's own client-side read-timeout fired ~75s later,
   killing the session mid-stream.

**New finding (revises test #3/#10's framing):** kimi-k2.6's configured `max_tokens: 8192`
does **not** unconditionally "absorb the reasoning/content split" as tests #3/#10
tentatively concluded -- it only does so for *small* prompts. At ~13.6K prompt tokens (a
realistic 4th-turn orchestrator state, not an edge case), kimi-k2.6's reasoning alone
exceeded 8192 tokens with **zero** `content` produced, i.e. **CB-1 is not gpt-oss-specific
or CF-specific -- it is a function of (prompt size x model's reasoning verbosity) vs
`max_tokens`, and kimi-k2.6 is simply farther along the same curve than gpt-oss-120b
(needs ~9K tokens for a 30-token prompt per test #10; presumably even more at 13.6K
prompt tokens)**. Raising `max_tokens` further (test #10 used 25600 successfully on a
30-token prompt) is unbounded as a fix -- there is no observed prompt-size-independent
ceiling, and at ~52 tokens/sec each +8192 tokens of headroom costs ~+157s of wall-clock
and ~+$0.033.

**Result:** Inconclusive for CB-7/AC-2 (still formally untested) -- but newly conclusive
for CB-1's scope: **CB-1 is confirmed prompt-size x model-reasoning-verbosity correlated
across both gpt-oss-120b AND kimi-k2.6**, not a gpt-oss/CF-specific defect. New,
independent finding: **`_run_planner_pass`'s hardcoded `max_tokens: 1024` makes the
planner pass degenerate on essentially every kimi-k2.6 call**, silently disabling CB-7's
fix path (handled gracefully, but worth fixing -- raising the planner's `max_tokens` to
~2048-4096 for reasoning models is a small, isolated change distinct from the per-step
`max_tokens` question). Today's CF spend: **$0.8489 of the $2.00 cap** (this run added
~$0.12 on top of test #10's ~$0.79).

**Next:** Two independent small fixes before re-attempting CB-7/AC-2: (a) raise
`_run_planner_pass`'s `max_tokens` from 1024 to ~4096 so the planner pass stops degenerating
on every kimi-k2.6 turn (cheap, isolated, testable on its own with a single direct CF call
mirroring test #10's methodology); (b) for the per-step executor, raise `cf/kimi-k2.6`'s
`max_tokens` in `litellm_config.yaml` past 8192 (e.g. 16384) *only* once (a) is in place,
since the planner-pass fix may itself reduce how large the per-step prompt grows (a working
planner produces a real step list, which `_build_step_dispatch_body` uses to narrow context
per CB-2/`_build_step_dispatch_body`'s existing context-narrowing -- see section 2). Budget
~$0.10-0.15 and ~5-10 min for fix (a)'s isolated test before spending more on a full
orchestrator re-run.

### 2026-06-11 -- CB-7/AC-2 attempt #3: planner fix confirmed (8-step breakdown produced); new blocker is a validator false positive on quoted source text (test #12)

**Hypothesis:** With both fixes from attempt #2's "Next" applied -- `_run_planner_pass`
`max_tokens` raised 1024 -> 8192 with its timeout matched to `CF_NON_STREAM_TIMEOUT_SECONDS`
(commit `b864277b`), and model-aware prompt-shrinking budgets giving kimi-k2.6 10x headroom
(commit `2e03ed2d`) -- a re-run of the identical CB-7/AC-2 task (same 1101-char prompt as
test #11) would produce a real step list and reach `_build_step_dispatch_body`'s per-step
executor without the planner degenerating.

**Change:** commits `b864277b`, `2e03ed2d` (both already landed before this run).

**Test prompt:** identical to test #11 -- read test #10's section verbatim, transcribe 4
facts into `cb7-ac2-validation-summary.md`, commit.

**Result:** **Partial success -- planner fix confirmed; new, distinct blocker found.**
`run-cline` exited **0** in **204.4s** (vs test #11's 362.9s failure), with only **2 CF
calls** (planner pass + step 1 executor) vs test #11's 4 -- no degenerate
8192-completion-tokens call this time.

1. **Planner pass succeeded**: `[cfproxy] multi-step ask detected ... running planner pass`
   -> `[cfproxy][orchestrator] auto-confirmed 8-step breakdown ... dispatching step 1/8:
   'Read the section titled "2026-06-11 -- kimi-k2.6 succeeds with 100x max_tokens..." in
   foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-roadmap.md.'`. This
   directly resolves attempt #2's open finding that the planner degenerated on every
   kimi-k2.6 turn -- raising its `max_tokens` to 8192 (commit `b864277b`) fixed it.
   **CB-7's per-step dispatch path (`_ORCHESTRATOR_STEP_SYSTEM_PROMPT` /
   `_build_step_dispatch_body`) was reached for the first time for kimi-k2.6.**
2. **Step 1/8 executor call** (4 msgs, 61162 chars, ~75s) returned a correct, on-task
   response: it read the file and quoted the requested section verbatim (lines 189-286),
   including the "Hypothesis" and "Research findings (community prevalence)" text reproduced
   character-for-character (e.g. "GPT-OSS-120B returns null content when hitting max_tokens
   without `--enforce-eager`").
3. **Step 1/8 validator returned NO**: `[cfproxy][orchestrator] step 1/8 validator verdict:
   NO -- summary contains explicit failure language (error / failed / could not / ...) (0
   file(s) changed)`. Per the (correct, intentional) no-auto-retry policy -- the $47K
   runaway-loop postmortem guard -- the run halted immediately: `git status` confirmed no
   working-tree changes, nothing committed, no further steps dispatched.

**New finding:** `_run_validator_pass`'s `_VALIDATOR_FAILURE_RE` /
`_VALIDATOR_NEGATED_FAILURE_RE` pair (local-mcp.py:1600-1658) is a **false positive on
quote/transcription steps whose source material itself discusses failures** -- which is the
entire premise of this roadmap doc. The executor's summary legitimately contained "...
channel-split **failures** observed across gpt-oss-120b, gemma-4-26b, and kimi-k2.6..." (a
verbatim quote from the section it was asked to transcribe), and the negation-aware regex
covers "no/not/without X failures" shapes but not "X failures observed/are a known problem"
framings used when *describing* failures rather than denying them. The validator cannot
currently distinguish "the executor reports its own step failed" from "the executor's output
contains a verbatim quote using the word 'failures' to describe something else."

**Result:** Inconclusive for CB-7/AC-2 (still formally untested for a *third* session in a
row, for a *third* distinct reason) -- but **both of attempt #2's open findings are now
resolved**: the planner pass no longer degenerates, and the per-step executor produced
correct, on-task, verbatim-quoted output on its first try. The remaining blocker is purely
mechanical and proxy-side, not model-side -- kimi-k2.6's actual output on this task was
correct. New backlog item **CB-8** (validator false-positive on quoted source text) tracks
the fix.

**Next:** Fix `_run_validator_pass`'s false-positive on quoted/reproduced source text (CB-8)
before re-attempting CB-7/AC-2 a 4th time -- e.g. scope `_VALIDATOR_FAILURE_RE` to skip
fenced-quote/reproduced-source-text spans, or restrict the failure-language scan to the
executor's own framing sentences outside any blockquoted material. Today's run was cheap
(204.4s, 2 CF calls, no degenerate completions) -- once CB-8 is fixed, re-running this exact
test (no prompt change needed) should be low-cost and is the most direct remaining path to a
CB-7/AC-2 "yes".

### 2026-06-11 -- CB-1 floor shrinks further (1879 tokens); gemma-4-26b ruled out; planner-pass None-content crash fixed (tests #7/#8/#9)

**Hypothesis:** Re-run the CB-1 baseline on `cf/gpt-oss-120b` to see whether the
degenerate-empty-response floor (4174 tokens, tests #4/#5) has moved, and evaluate
`cf/gemma-4-26b-a4b-it` (newly added to `litellm_config.yaml` this session as a candidate
"compact/efficient" Tier A model) and `cf/kimi-k2.6` against the same small probes.

**Change:** `cf/gemma-4-26b` added to `litellm_config.yaml` (model_list) for this test only.

**Test #7 (`cf/gpt-oss-120b`, refreshed CB-1 baseline):** A read-only governance-doc
analysis prompt (no edits requested) at **1879 prompt tokens** -- smaller than test #4/#5's
4174-token failure and well below the originally-assumed 12-20K floor -- produced a
degenerate response: all 1024 `max_tokens` spent in `reasoning_content`, `content` empty.
**The CB-1 floor has not stabilized; it has moved down again** (4174 -> 1879). This further
undermines the "context budget" framing as primarily size-driven (see test #4/#5's
content-correlation finding) -- the failure surface appears to be expanding, not shrinking,
as more prompt shapes are sampled.

**Test #8 (`cf/gemma-4-26b-a4b-it`, two probes):**
- Trivial probe: 24-token prompt ("say OK and nothing else"), `max_tokens=64`. Result:
  `content: null`, all 64 tokens in `reasoning_content`, cut off mid-sentence
  (`finish_reason: "length"`). **Degenerates on a prompt far too small to blame on context
  budget at all** -- worse than gpt-oss-120b's (already-shrinking) threshold.
- Moderate probe: 438-char / 98-prompt-token multi-step-shaped message, `max_tokens=256`
  (this was the proxy's own `_run_planner_pass` call, triggered by `_detect_multi_step_ask`
  firing on the trivial probe's surrounding test prompt -- see below). Result: **succeeded**
  -- produced 17 valid numbered steps (content present, no degeneration).
- **Reading:** gemma-4-26b exhibits the same Harmony-style reasoning/`content` channel
  split as gpt-oss, but unlike gpt-oss its failures are not threshold-correlated in any
  obvious way across these two data points -- it failed on the *smaller, simpler* prompt
  and succeeded on the *larger, more complex* one. Unpredictability is itself
  disqualifying for a daily-driver tier: at least gpt-oss-120b's (moving) floor gives a
  size-based heuristic something to route around (CB-3); gemma gave none here.

**Test #9 (`cf/kimi-k2.6`, two probes):**
- Trivial probe: 24-token "say OK" prompt, `max_tokens=64`. Result: clean -- `content:
  "OK"`, `reasoning_content` populated separately, `finish_reason: "stop"`. Correct
  Harmony-channel handling on this input.
- Moderate probe: 120-char / 29-prompt-token prompt ("configure the build, implement...,
  test..., document..."), `max_tokens=256`. Result: **degenerated** -- `content: null`, all
  256 tokens in `reasoning_content`, `finish_reason: "length"`. So kimi-k2.6 is *not*
  immune to the reasoning/content split either; it just has more headroom before hitting
  it. `litellm_config.yaml` configures `cf/kimi-k2.6` with `max_tokens: 8192` (vs the 64/256
  used in these adversarial probes), which likely gives enough room to finish reasoning and
  still emit `content` on real tasks -- but this specific mitigation (sufficient
  `max_tokens` headroom) is **unverified at the configured 8192 value** for kimi, and
  **CF does not appear to apply it for gemma** (test #8's moderate probe used only 256 and
  succeeded, the trivial one used 64 and failed -- size alone doesn't explain either
  result).

**New bug found and fixed (independent of the above):** While probing the moderate prompt
above, `_run_planner_pass` (`scripts/local-mcp.py:1246`) crashed with `AttributeError:
'NoneType' object has no attribute 'splitlines'` when the underlying CF call (the planner
pass's own internal request, on `cf/gemma-4-26b-a4b-it`) returned `content: None` --
exactly test #8's degenerate-response shape, just hitting an *unguarded* code path inside
the proxy itself. This converted a recoverable "model didn't answer cleanly" case into a
hard `500 Internal Server Error` surfaced to the client (with `num_retries: 2`, this
produced 6 consecutive 500s in the log for one request). **Fixed in commit `3d724d79`**:
`_run_planner_pass` now checks for empty/`None` `content` before calling `.splitlines()`,
logs `[cfproxy] planner pass returned no content (reasoning_content present: <bool>)`, and
returns `None` so the caller forwards the original request unchanged, per the function's
existing documented contract. `local-mcp.py` restarted to pick up the fix and re-verified:
the same multi-step-shaped prompt now completes 200 OK end-to-end (planner pass either
produces steps or backs off cleanly, no crash either way).

**Separately observed (not fixed today):** `_detect_multi_step_ask` fired on test #8's
prompt because the message text itself contained action-verb-shaped words
(configure/implement/test/document/refactor/deploy), triggering an unwanted planner pass on
what was conceptually a small adversarial probe, not a real multi-step task. This is a
variant of CB-4's "heuristic inspects the wrong text" finding -- previously the problem was
Cline truncating the real task down to a verb-free sentence; here the heuristic
over-fires on verb-shaped words appearing anywhere in the message (including pasted
reference material in earlier tests this session). Tracked as a CB-4 follow-up, not
actioned.

**Result:**
- CB-1: Reconfirmed and worsened -- floor moved 4174 -> 1879 tokens. Rejected as a
  size-threshold framing; size-aware routing (CB-3) needs a much lower trigger than
  previously assumed, if it can work at all given test #4/#5's content-correlation finding.
- `cf/gemma-4-26b`: **Rejected as a Tier A candidate.** Same Harmony-channel defect as
  gpt-oss, with no observed threshold to route around. Left in `litellm_config.yaml` with
  an updated description recording this finding (model config retained for any future
  re-test, e.g. if CF changes serving defaults, but should not be added to Tier A's active
  rotation).
- `cf/kimi-k2.6`: Inconclusive but relatively the strongest of the three -- correct on the
  trivial probe, and its existing 8192 `max_tokens` config plausibly (but not yet verified)
  absorbs the reasoning/content split seen at 256 tokens.
- Planner-pass crash: Adopted (commit `3d724d79`).

**Next:** Today's CF daily spend reached **$0.7284 of the $2.00 cap** after these probes.
A full kimi-k2.6 orchestrator run for CB-7/AC-2 validation historically costs ~$0.69 USD
(~$0.98 AUD) per attempt and risks exceeding the cap combined with today's spend -- deferred
to a session with budget headroom. Given CB-1's floor is shrinking rather than stabilizing
on CF's serving stack, and `groq/gpt-oss-120b` / `groq/kimi-k2` / `deepseek/v4-flash` are
already staged in `litellm_config.yaml` specifically to test whether this is a CF-serving
artifact (see comments there, added 2026-06-11), the next session should prioritize running
**test #7's exact 1879-token prompt against `groq/gpt-oss-120b`**: if Groq's serving stack
produces a non-degenerate `content` for the same input, that isolates the defect to CF's
OpenAI-compat/Harmony-template wrapper (as hypothesized) and reframes Tier A around an
alternative host for the *same* gpt-oss-120b model rather than abandoning it.

### 2026-06-11 -- CB-7 fix applied, untestable on gpt-oss; kimi-k2.6 correct-but-too-slow (tests #4/#5/#6)

**Hypothesis:** With CB-7's verbatim-quote instruction added to `_ORCHESTRATOR_STEP_SYSTEM_PROMPT` (commit `cfa3a2d4`) and `local-mcp.py` restarted, a fresh transcription task (write a new spec from
`agentic-budget-tiered-strategy-2026-06-11.md`, quoting tier names and budget figures verbatim) would either reproduce test #3's inversion (fix ineffective) or produce faithful output (fix effective).

**Change:** commit `cfa3a2d4` (CB-7 system-prompt fix), `local-mcp.py` restarted (new PID).

**Test prompt:** ~876-char task: read `agentic-budget-tiered-strategy-2026-06-11.md`, create `foundation/SR-1.4-ai-guidance/specs/agentic-tiered-inference-strategy.md` quoting tier names/roles, the section-4 budget table, and the section-2.4 conclusion verbatim, add an INDEX.md row, commit.

**Test #4 (`cf/gpt-oss-120b`):** First-turn prompt = 4174 tokens. Degenerate empty response 3/3 attempts (completion_tokens 69, 87, 69), including the proxy's existing temperature-perturbation retry (0.7 -> 1.0). Proxy gave up after 3 attempts and surfaced an honest error to Cline (correct first-class-scenario behavior). 7.1s total. Zero file changes. The orchestrator's planner pass never ran -- CB-7 could not be exercised.

**Test #5 (`cf/gpt-oss-120b`, immediate retry, identical prompt):** Same result -- 3/3 degenerate (completion_tokens 87, 87, 69), 7.6s, zero changes. 6/6 across tests #4+#5 at prompt=4174. By contrast test #3's prompt=3996 (different content) succeeded 6/6. **The degenerate-empty-response failure is prompt-content-correlated, not purely a size threshold** -- a ~180-token difference in prompt size flips a first-turn prompt from 100% success to 100% failure, with no tool calls or accumulated context involved yet. This means CB-1's framing ("once a turn's prompt context reaches ~12-20K tokens") is incomplete: degeneration can occur on short first-turn prompts too, and existing mitigations (temperature perturbation, retries) do not help when it's content-correlated.

**Test #6 (`cf/kimi-k2.6`, same prompt):** Multi-step ask detected, planner ran, orchestrator dispatched real tool calls (`read_files`, `apply_patch`/insert, re-`read_files` to verify). Produced ~74 lines of the new spec (sections 1-4: Design-Goal Linkage, Problem Statement, Scope, Constraints) before being killed by the 600s timeout. **No content inversion observed in the partial output** -- the $100 AUD/month ceiling, ~36 hrs/week commitment, and 1 USD = 1.42 AUD conversion rate were all transcribed correctly, and the file's own header correctly states the verbatim-quoting requirement for later sections. However: (a) it never reached the actual Tier A/B/C definitions or the section-4 budget table -- the part of the task most diagnostic for CB-7 -- so CB-7 remains **formally unverified**; (b) it never updated INDEX.md or committed; (c) cost **$0.6872 USD (~$0.98 AUD) for one incomplete 600s run** at ~21K prompt tokens/call (vs ~4K for gpt-oss) -- roughly 5x gpt-oss's per-call token cost, before counting that it didn't finish.

**Result:** Inconclusive for CB-7 (gpt-oss couldn't reach the orchestrator at all; kimi got partway through with no inversions but didn't reach the verbatim-sensitive sections or commit). New finding (not CB-7): kimi-k2.6 looks qualitatively more reliable on partial evidence but is too slow (>600s for a 4-step task) and too expensive per-call (~5x gpt-oss tokens) to use as Tier A's "harder things" escalation for interactive work -- it is closer in cost/latency profile to a Tier B (batch) workload than a Tier A (daily-driver) one. The incomplete spec file was finished manually (commit follows) so Task 1 of the user's practical-task list is still delivered.

**Next:** CB-7 needs a test prompt that (a) gpt-oss-120b can actually complete (smaller / differently-worded first turn, or pre-warm with a trivial first turn before the real task), or (b) accept kimi-k2.6 for CB-7 validation specifically but split the task into smaller steps (e.g. dispatch the spec-writing and the INDEX update as two separate `run-cline.ps1` invocations) so it finishes within 600s. Re-test CB-1's "prompt-content-correlated" finding by bisecting the ~876-char task text to find which phrase(s) trigger degeneration.

### 2026-06-11 -- Stdin-truncation fix (commit 8d2fb468) + CB-4 first real run (test #3)

**Hypothesis:** Following from the CB-4 entry below: if `run-cline.ps1` actually delivered the full task text to Cline (not a 142-char first sentence truncated by cmd.exe), CB-4's multi-step heuristic would fire and the orchestrator would run end-to-end.

**Change:** commit `8d2fb468` -- rewrote `run-cline.ps1` to write `$Task` to a UTF-8-no-BOM temp file and pipe it via `-RedirectStandardInput`, instead of embedding it in a `cmd.exe /c "..."` argument string (which truncates at the first newline). Root cause discovered via `~/.cline/data/sessions/<id>/<id>.json`, which showed the `prompt` field actually sent was just the task's first sentence.

**Test prompt:** Same task as tests #1/#2 -- "In planning_document.md at the repo root, record the System Architect's decisions on OQ-259, OQ-260, and OQ-261, and then finish the document," plus a 4-step instruction block (~1782 chars total), model `cf/gpt-oss-120b`.

**Before:** Tests #1/#2 -- 142-char prompt reached Cline, CB-4 never fired, single CF call degenerated (3/3 retries, 0 final tokens), 900s timeout, zero edits.

**After:** Full 1782-char task reached Cline. `[cfproxy] multi-step ask detected` fired, the planner pass produced a 9-step breakdown (auto-confirmed), the orchestrator dispatched steps with real tool calls (`read_files`, `search_codebase`, `apply_patch`), recovered from one degenerate response via retry, truncated one oversized tool result (27951 -> 20000 chars), compacted older turns as the conversation grew, and exited 0 in 42.1s.

However, the *content* of the edit Cline produced for `planning_document.md` was factually wrong: it inverted all three OQ-259/260/261 resolutions relative to the architect's actual answers in `architecture-docs/global/architect-open-questions.md` (e.g. wrote "OQ-260 resolved: AT-1120 will create placeholder Cloudflare zone-config files" when the real decision is "Option C -- no zone-config files exist or are needed, AT-1120 -> `cloudflare/README.md`"). Steps 2-4 of the 4-step instruction (AT-1119/1120/1128 table updates, status note, "Prepared by" footer) were skipped despite the run reporting completion. The incorrect edits were manually corrected to the canonical text in commit `811420b7` (same session, user-confirmed).

**Result:** Adopted (the stdin fix, commit `8d2fb468`) -- this is the largest mechanical improvement of the roadmap so far: Cline can now run a full orchestrated multi-step session against a real ~1800-char task without timing out, truncating input, or stalling. Context-budget (the original CB-1..CB-5 framing) is no longer the binding constraint for this task shape. But CB-7 (content fidelity, new -- section 5) is now the binding constraint: "runs to completion with exit 0" no longer implies "produced correct output."

**Next:** CB-7 -- investigate `_run_planner_pass`/`_build_step_dispatch_body` in `scripts/local-mcp.py` for whether step instructions/content quote source documents verbatim or let the model re-derive them from its own reasoning.

### 2026-06-11 -- CB-6: Disable native tool calls (`nativeToolCallEnabled=false`) -- wrong codebase (test #2)

**Hypothesis:** see CB-6 row in section 5 -- disabling native tool calls would route `cf/gpt-oss-120b` through Cline's smaller `next-gen` (XML-tag) prompt variant instead of `native-gpt-5`, reducing prompt size and possibly avoiding the degenerate-empty-response failure.

**Change:** Edited `~/.cline/data/globalState.json` to set `nativeToolCallEnabled: false` (backed up to `globalState.json.bak-20260611`). User-authorized after the auto-mode classifier flagged this as a global, repo-spanning config change.

**Test prompt:** Identical to test #1's task.

**Before:** Test #1 -- `2 msgs | 7492 chars | tools=yes | stream=yes`, `prompt=3996` tokens, degenerate response 3/3.

**After:** Byte-identical: `2 msgs | 7492 chars | tools=yes | stream=yes`, `prompt=3996` tokens. Zero observable change.

**Result:** Rejected. The `ModelFamily`/`nativeToolCallEnabled`/`native-gpt-5` prompt-variant registry this hypothesis was based on lives in `/tmp/cline_research/apps/vscode/` (the VSCode extension's `core/prompts/system-prompt/`). `run-cline.ps1` invokes `/tmp/cline_research/apps/cli/` ("cline-core", `npx cline -P openai-compatible`), a separate, much simpler codebase with its own fixed ~2922-char system prompt that does not reference `ModelFamily` or `nativeToolCallEnabled` at all. The setting has no effect on this invocation path. Reverted `globalState.json` back to its original state (property removed, default `true` restored).

**Next:** None for CB-6 itself (rejected). The investigation that led here (inspecting `~/.cline/data/sessions/<id>/<id>.json` to see the literal prompt sent) directly led to discovering the real bug -- see the stdin-truncation entry above.

### 2026-06-11 -- CB-7/AC-2 attempt #4: CB-8 fix holds through step 3; new validator false positive at step 4 (architect: Option A); resume blocked by new CB-9 (test #13)

**Hypothesis:** With CB-8's validator fix landed (`scripts/local-mcp.py` failure-language scoping + `scripts/tests/test_local_mcp_validator.py`), a re-run of the same 8-step kimi-k2.6 breakdown (read test #10's section, transcribe 4 facts into `cb7-ac2-validation-summary.md`, commit) would get past step 1's quoted-"failures" false positive and make real progress toward a CB-7/AC-2 "yes".

**Change:** CB-8 validator fix (landed prior to this run; see `scripts/tests/test_local_mcp_validator.py`).

**Test prompt:** identical to tests #11/#12 -- read the "2026-06-11 -- kimi-k2.6 succeeds with 100x max_tokens..." section of this roadmap doc, quote 4 facts verbatim into `foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md`, commit as "docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)".

**Result:** Run `97ee060abc9315f1` reached **step 4/8** (vs. step 1/8 in test #12) -- the CB-8 fix holds for the quoted-"failures" case. Step 4 ("Identify the exact sentence stating the through-proxy result for test #10 after the fix including its completion_tokens count and elapsed time in seconds") is read-only; the executor correctly found and quoted the sentence (`completion_tokens: 6324`, `121s`), but `_run_validator_pass` returned **AMBIGUOUS** rather than YES/NO -- a *different* CB-8-shaped false positive: the step's own task wording contains "...after the fix...", which most likely tripped a change-verb heuristic against the step description rather than the executor's actual (empty-diff, by-design) output. Per the bounded loop-detector, the run raised one automated OQ and paused.

**Architect decision** (recorded in `architect-open-questions.md`): Option A -- step 4's empty diff is correct for a read-only step; run resumed to step 5/8.

**New finding 1 -- OQ ID collision:** the orchestrator's auto-raised `OQ-259` collided with the already-answered 2026-06-09/06-11 `.env.example`-scope `OQ-259`. `_next_oq_id` only scans live `| OQ-NNN |` table rows and does not account for IDs already retired into changelog history, so it reused an ID. Flagged in the OQ-259 changelog entry as a `_next_oq_id` bug; not yet fixed.

**New finding 2 -- CB-9, blocks resume entirely:** resuming the paused run via the documented mechanism (`npx cline -P openai-compatible -m "cf/kimi-k2.6" --auto-approve true --id <session-id> "continue"`) failed with `error: interactive mode requires a TTY (stdin/stdout must both be terminals)`. Three further variants (stdin-piped `"continue"`; `--json -t 20`; `-i --tui -t 60`) all failed the same way or with a closely related TTY/stdin error. None executed any step -- no working-tree changes, orchestrator state file unchanged. Because `_orchestrator_key` depends on Cline replaying the paused session via `--id`, **this blocks resuming any paused orchestrator run from script** -- a structural issue independent of CB-7/AC-2 and CB-8. New backlog item **CB-9** added (section 5); raised to the architect as **OQ-262** (preemptive answer: Option C -- redesign per-step dispatch to carry a fixed orchestrator key so resume never depends on Cline session replay).

**Next:** CB-7/AC-2 remains formally untested -- run paused at step 5/8 (4 of 8 steps remain, including the validation-summary-file creation that would exercise CB-7 directly). Blocked on OQ-262/CB-9 for any further automated progress on this run. Once CB-9 is resolved, resuming from step 5/8 should not require re-running steps 1-4: the orchestrator state file `C:\Users\jakeh\.cf_proxy_orchestrator\97ee060abc9315f1.json` already records them complete.

### 2026-06-11 -- CB-4: Expand multi-step action-verb regex for investigation tasks

**Hypothesis:** Adding `review/examine/investigate/analyze/verify/summarize/locate/identify/audit/compare` to `_MULTI_STEP_ACTION_VERB_RE` would let `_detect_multi_step_ask` decompose investigation-style asks into smaller per-step contexts, avoiding the degenerate-empty-response failure on dense multi-paragraph tasks.

**Change:** commit 9632472c (regex expansion in `scripts/local-mcp.py`).

**Test prompt:** Live Cline run via `run-cline.ps1`, model `cf/gpt-oss-120b`, task: "In planning_document.md at the repo root, record the System Architect's decisions on OQ-259, OQ-260, and OQ-261, and then finish the document." plus a 4-step instruction block (~1500 chars total), scoped to one file.

**Before/After:** N/A -- the heuristic never fired. `cf_proxy_live.err.log` shows no `[cfproxy] multi-step ask detected` line for this run. Root cause: `_detect_multi_step_ask` evaluates only the trailing user-role message, which Cline reduced to a 142-char first sentence ("In planning_document.md at the repo root, record... and then finish the document.") -- well under `_MULTI_STEP_MIN_CHARS` (350) and containing none of the new verbs. The actual prompt bulk (2 msgs / 7492 chars / `prompt=3996` tokens) came entirely from Cline's own system prompt + native tool-call schema, not from the task text the heuristic inspects.

The single CF call that did happen reproduced the exact pre-CB-4 degenerate-response signature: 3/3 retries (`completion_tokens` 51/44/46, all spent in the reasoning channel, 0 in `final`), then "persisted across 3 attempts -- giving up". This happened on a TRIVIAL one-sentence task at only 3996 prompt tokens -- far below the previously-assumed 12-20K degeneracy floor (see section 3).

Separately, ~15 minutes elapsed between Cline's MCP handshake (10:29:56) and its first (only) CF proxy call (10:46:37), consuming almost the entire 900s timeout before the degenerate-response retries even started. Cline made zero tool calls and `planning_document.md` was not modified.

**Result:** Inconclusive / Rejected as the primary lever -- CB-4 cannot help here because the verb/length-based heuristic inspects the wrong text (the short user task), not the system-prompt+tool-schema overhead that actually dominates the prompt.

**Next:** Root-caused via Cline's source (`apps/vscode/src/core/prompts/system-prompt`): for `cf/gpt-oss-120b`, `nativeToolCallEnabled` (global Cline setting, default `true`) makes `enableNativeToolCalls=true`, which routes gpt-oss through the `native-gpt-5` prompt variant (`isGptOssModelFamily` matches `NATIVE_GPT_5` only when native tool calls are enabled) -- the heaviest system prompt plus a full OpenAI-format `tools` array (confirmed: this run logged `tools=yes`). With `enableNativeToolCalls=false`, gpt-oss-120b instead matches the `next-gen` variant (XML-tag tools, no native `tools` array), which should be both smaller and closer to the format gpt-oss already produces unprompted (per the `{"tool":...}` shorthand fix in 924b623f). New strategy CB-6 added to section 5 to test this. The 15-minute pre-call gap is a separate finding that needs its own investigation -- possibly a recurrence of the dormant planner-pass-latency issue, but at the Cline-CLI-startup stage rather than the orchestrator.

_(first experiment run this session; framework built in the prior session)_

### 2026-06-11 -- CB-9/OQ-262: Option C resume mechanism implemented (marker-based key, no session replay)

**Change:** `scripts/local-mcp.py`:
- `_orchestrator_key(trigger_text)` now matches an embedded `[orchestrator-key: <16-hex>]` marker (`_ORCHESTRATOR_KEY_RE`) before falling back to its existing first-message hash. A marker-bearing message reuses the run identity it names regardless of conversation history.
- `_new_orchestrator_state(steps, reason, model=None)` gained a `model` field, populated from `model_name` (the proxied request's `@cf/...` model string) at run creation -- needed so a resume script can relaunch with the same model.
- New `_format_resume_prompt(key, state)` builds a short message: `[orchestrator-key: <key>] continue -- resuming the paused N-step run. Step X/N is resolved (treat as complete). proceed with step X+1/N: <task>` (or "the run has no further steps -- mark it complete" if X==N).
- New resume branch in `_handle_orchestrated_request`, checked before the existing `paused_for_oq` gate-reply branch: if `state["status"] == "paused_for_oq"` and the trigger message is the conversation's only user turn (`trigger_idx == last_user_idx`) and it matches `_ORCHESTRATOR_KEY_RE`, treat it as the architect's "continue" verdict for the resolved step -- advance `current`, re-anchor to this session's message indexing, and `_dispatch_step` the next step (or mark the run complete if the resolved step was the last one).
- New `--print-resume-prompt <key>` CLI mode: loads `~/.cf_proxy_orchestrator/<key>.json`, validates `status == "paused_for_oq"`, and prints `_format_resume_prompt`'s output to stdout (errors to stderr, non-zero exit otherwise).

**New file:** `scripts/resume-orchestrator-run.ps1` -- looks up the run's state file, resolves `-Model` from `state["model"]` via a small reverse-map of `scripts/litellm_config.yaml`'s `cf/*` entries (or requires `-Model` explicitly if absent/unmapped), captures `--print-resume-prompt`'s output, and feeds it to a fresh (non-`--id`) `run-cline.ps1` invocation.

**New tests:** `scripts/tests/test_local_mcp_orchestrator_resume.py` (9 cases) -- marker-vs-hash key derivation, marker round-tripping through `_orchestrator_key(_format_resume_prompt(...))`, `_new_orchestrator_state`'s `model` field, and `_format_resume_prompt`'s step-description and "no further steps" / continue-keyword content. All pass, alongside the existing 5 `test_local_mcp_validator.py` cases (unaffected).

**Scope note:** this targets the specific blocker (resuming a `paused_for_oq` run without `--id` session replay), not the full Option C description's "every step is a fresh invocation" redesign -- the in-session auto-advance path (YES verdict -> next step dispatched in the same request) is unchanged because it never hits CB-9 (no TTY/`--id` involved).

**Next:** Live-validate by resuming run `97ee060abc9315f1` from step 5/8 via `scripts/resume-orchestrator-run.ps1 -Key 97ee060abc9315f1 -Model cf/kimi-k2.6` (the state file predates the `model` field, so `-Model` must be passed explicitly). Requires the local-mcp.py CF proxy and LiteLLM running.

**Live validation result (same session):** `resume-orchestrator-run.ps1 -Key 97ee060abc9315f1 -Model cf/kimi-k2.6 -AutoApprove -TimeoutSec 600` (after restarting local-mcp.py to load the new code) produced exactly the designed sequence in `cf_proxy_live.err.log`:
```
[cfproxy][orchestrator] resumed in a fresh session -- treating step 4/8 ambiguity as resolved (continue), advancing
[cfproxy][orchestrator] dispatching step 5/8: 'Identify the exact sentence stating the per-call cost range for kimi-k2.6 in USD.'
[cfproxy][orchestrator] step 5/8 validator verdict: YES -- no failure language detected; this step did not imply a working-tree change (0 file(s) changed)
[cfproxy][orchestrator] step 5/8 validated YES -- auto-advancing to step 6/8: 'Create foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md containing exactly four bullet points, one for each of the four sentences identified in steps 2-5.'
```
**CB-9 is resolved**: a fresh, non-`--id` cline invocation carrying only the `[orchestrator-key: 97ee060abc9315f1] continue -- ...` marker correctly re-derived the paused run's identity, treated it as the architect's "continue" verdict for step 4, and dispatched step 5 -- step 4's result is what was previously unreachable without a TTY. The state file's `current` advanced 4 -> 5 -> 6 and `status` left `paused_for_oq` for `running` (then `halted`, see below) -- all without any `--id` session replay.

**New finding -- CB-10, step-6 dispatch ReadTimeout on a 178K-char prompt:** step 6 ("Create `cb7-ac2-validation-summary.md` containing exactly four bullet points, one for each of the four sentences identified in steps 2-5") failed with `[cfproxy][orchestrator] step-dispatch call failed: ReadTimeout('')`, halting the run cleanly (`status: halted`, `current: 6`, no working-tree changes -- exit-evidence-clean per `_format_step_failure_report`'s sibling "transport/parse error" message). Root cause is **not** CB-9: per-step dispatch (`_build_step_dispatch_body`) has always reset to a narrow `[system, step-prompt]` frame with no carry-forward of prior steps' findings (true even for in-session auto-advance, independent of resume) -- step 6's executor therefore had no record of the four sentences identified in steps 2-5 and, after exhausting `git log`/`git reflog`/file-search dead ends, read the entire 1700+-line roadmap doc itself (the source of those four sentences) into context, growing the prompt from 32 msgs/108,946 chars to 34 msgs/178,311 chars in one jump. `_cf_complete_once`'s `httpx.AsyncClient(timeout=120.0)` could not complete that call within 120s and raised `ReadTimeout`. Two independent fixes needed: (a) raise or make configurable `_cf_complete_once`'s 120s timeout for large dispatch bodies (cheap, but doesn't address the root cause); (b) the deferred "accumulated step-output summaries passed explicitly in the prompt" half of Option C, so step N+1 doesn't have to rediscover step N's findings from scratch by reading the same source documents again. New backlog item **CB-10** to be added to section 5.

**Next:** run `97ee060abc9315f1` is `halted` at step 6/8 with steps 1-5 recorded complete (including the just-unblocked step 5). Resuming again with the current code will re-dispatch step 6 from scratch via `_handle_orchestrated_request`'s normal "halted -- stop intercepting" rule (status != "running" and != "paused_for_oq" returns `None`), so `resume-orchestrator-run.ps1` will not fire for a `halted` run -- by design (resume only targets `paused_for_oq`). Re-running step 6 needs either a `halted`-run resume path or the architect re-confirming the breakdown manually. CB-10 (a) is the smallest unblock.

### 2026-06-11 -- CB-10(b)/OQ-263: findings carry-forward implemented and live-validated (run `2b3ea4aba969d3d3`, 7/7 steps)

**Change (commit `62105b48`):** `scripts/local-mcp.py` implements the architect's Option A (mechanical, no-LLM findings carry-forward):
- `ORCHESTRATOR_FINDING_MAX_CHARS = 1000` (per-finding cap) and `ORCHESTRATOR_FINDINGS_CHAR_BUDGET = 4000` (total "Prior step findings" block budget) added near line 1957.
- `_new_orchestrator_state(...)` gained a `findings: []` field.
- `_extract_step_finding(summary)` pulls a trailing `FINDING: <text>` line out of a step's executor summary (capped to `ORCHESTRATOR_FINDING_MAX_CHARS`), or falls back to the full summary (also capped) when no `FINDING:` line is present.
- `_format_findings_block(findings)` renders accumulated findings oldest-first as `Step X/N: <text>` lines under a `Prior step findings:` header, rotating out the oldest entries once the total exceeds `ORCHESTRATOR_FINDINGS_CHAR_BUDGET` (but always keeping the newest finding even if it alone exceeds the budget).
- `_build_step_dispatch_body(...)` now takes an optional `findings` list and prepends `_format_findings_block(findings)` to the step prompt when non-empty.
- New tests: `scripts/tests/test_local_mcp_orchestrator_findings.py` (10 cases) -- all pass.

**Live validation:** ran a fresh 7-step orchestrated task (run key `2b3ea4aba969d3d3`, model `cf/kimi-k2.6`) whose step 7 ("create a summary file from facts identified in earlier steps") is structurally the same shape as the step 6 that previously `ReadTimeout`'d in `97ee060abc9315f1`. Result per `~/.cf_proxy_orchestrator/2b3ea4aba969d3d3.json`:
- `status: complete`, `current: 7`, 7/7 steps, `findings` array populated with one entry per step.
- Step 2's finding recorded `ORCHESTRATOR_FINDINGS_CHAR_BUDGET = 4000` and step 4's finding recorded `ORCHESTRATOR_FINDING_MAX_CHARS = 1000` (the two facts the run was asked to identify).
- Step 7's executor wrote `foundation/SR-1.4-ai-guidance/docs/oq-263-findings-validation.md` containing exactly the two bullet points with the correct values (4000 and 1000) and their descriptions -- **without re-reading `local-mcp.py` or the roadmap doc**, using only the carried-forward "Prior step findings" block from steps 2 and 4.

**CB-10(b) is resolved and OQ-263 is closed.** The findings-carry-forward mechanism eliminates the failure mode that caused the step-6 `ReadTimeout` in `97ee060abc9315f1` (executor re-reading large source documents to recover prior steps' results). CB-10(a) (raising `_cf_complete_once`'s 120s timeout) remains a separate, still-open, cheap config change -- it addresses prompts that grow large for *other* reasons (e.g. large file reads within a single step), independent of the findings-carry-forward fix.

### 2026-06-12 -- CB-10(a): dedicated orchestrator step-dispatch timeout (590s) implemented

**Change:** `scripts/local-mcp.py`:
- New `ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS = 590.0`, used only by `_cf_complete_once`'s `httpx.AsyncClient` for the orchestrator step-dispatch call (the other two `CF_NON_STREAM_TIMEOUT_SECONDS=290` call sites -- the planner pass and the validator pass -- are unchanged, since neither has been observed to need a prompt anywhere near CB-10's 178K-char step-6 dispatch).
- `_cf_complete_once` now catches `httpx.TimeoutException` separately from other transport/parse failures and logs a named `step-dispatch call timed out after 590s (prompt: N msgs / M chars, model=...)` message to stderr (per the First-Class Scenarios policy -- the prior generic `step-dispatch call failed: {exc!r}` gave no size/model context for diagnosing *why* a dispatch timed out).

**Change:** `scripts/litellm_config.yaml`: `litellm_settings.request_timeout` raised 300 -> 600, with a comment cross-referencing `ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS` so the two stay in the "local-mcp.py times out first with a named message" relationship the original 290/300 pair established. `CF_NON_STREAM_TIMEOUT_SECONDS`'s comment updated to match (was citing the now-stale "300").

**New tests:** `scripts/tests/test_local_mcp_dispatch_timeout.py` (3 cases) -- `ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS` is 590.0 and exceeds `CF_NON_STREAM_TIMEOUT_SECONDS`; `_cf_complete_once` returns `None` and logs the new named message (with timeout duration, prompt size, and model) when the CF call raises `httpx.ReadTimeout`. All pass, alongside the existing 5+13+9 cases in `test_local_mcp_validator.py` / `test_local_mcp_orchestrator_findings.py` / `test_local_mcp_orchestrator_resume.py` (unaffected).

**Status:** implemented but not yet live-validated -- no run since CB-10(b) landed has produced a single-step prompt large enough to approach 290s, let alone 590s (CB-10(b) removes the main known cause of such growth). This is a defense-in-depth change for the residual case (a single step legitimately reading one very large file); the next time an orchestrator run logs a step-dispatch duration approaching 290s, confirm it completes under the new 590s budget instead of `ReadTimeout`-ing.

### 2026-06-12 -- CB-7/AC-2 attempt #5: first 8/8 completion, but content-fidelity check FAILED -- 1/4 facts fabricated, 1/4 dropped (new findings CB-11, CB-12) (test #14)

**Hypothesis:** With CB-9 (Option C resume) and CB-10(a)/(b) (dispatch timeout + findings carry-forward) both implemented and live-validated, a fresh CB-7/AC-2 run should be able to run all 8 steps to completion -- resuming through any AMBIGUOUS pauses via the new resume mechanism -- and produce the first formal pass/fail verdict on CB-7's verbatim-quoting fix.

**Test prompt:** identical to tests #11-#13 -- read the "2026-06-11 -- kimi-k2.6 succeeds with 100x max_tokens..." section of this roadmap doc, quote 4 facts verbatim into `foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md` (CF_NON_STREAM_TIMEOUT_SECONDS value + introducing commit hash; direct-call test #10 result; through-proxy test #10 result after the fix; per-call cost range for kimi-k2.6), commit as "docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)".

**Result:** Run `a731f317e9507669` (model `cf/kimi-k2.6`, fresh 8-step plan) reached **`status: complete`, 8/8** -- the first formal completion of this task ever, after being blocked across 3 prior sessions (CB-1 x2, CB-8, CB-9, CB-10).

- Steps 1-3 (read section; record timeout value + commit hash; record direct-call result) all validated YES with empty diffs and auto-advanced normally.
- Step 4/8 ("Record the exact quote stating the through-proxy result for test #10 after the fix") repeated the CB-8-shaped false positive seen in test #13's step 4: the executor correctly found and quoted the sentence, but `_run_validator_pass` returned AMBIGUOUS. Auto-raised `OQ-259` (second occurrence of this exact pattern, same reasoning as test #13's OQ-259). **Architect: Option A** (read-only step, empty diff correct) -- resumed via `resume-orchestrator-run.ps1 -Key a731f317e9507669` (251.8s, `cb7_ac2_kimi_resume2.log`).
- Steps 5-7 (record cost range; create `cb7-ac2-validation-summary.md`; `git add`) all validated YES and auto-advanced.
- Step 8/8 (`git commit`) succeeded -- commit `1abe98d4` ("docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)", 1 file changed, 4 insertions) -- but `_run_validator_pass` returned AMBIGUOUS again ("the step's own wording implies a working-tree change, but the diff is empty"): a *successful commit* leaves the working tree clean vs. HEAD, which the snapshot-diff validator can't distinguish from "did nothing." Auto-raised `OQ-260`. **Architect: Option A** (commit verifiably succeeded per `git log`) -- resumed a second time (2.5s, synthetic "mark complete" short-circuit, zero CF cost, `cb7_ac2_kimi_resume3.log`) -- `status: complete`.

**Content-fidelity audit of the committed `cb7-ac2-validation-summary.md` (commit `1abe98d4`):**
```
- `CF_NON_STREAM_TIMEOUT_SECONDS = 290.0`
- `f952445b07b1517f119a3b030cf7533bee6d14f2`
- `200 OK, finish_reason "stop"`, `reasoning_content` 25055 chars, `content` 14611 chars, `usage.completion_tokens = 9153` (of 25600 budget) in **175s** (~52 tokens/sec)
- `$0.0003-$0.003 USD per call`
```
- Bullets 1-2 (timeout value + commit hash, fact (1)) -- **CORRECT**, verbatim-accurate against source lines 240-243; `git log -1 --format="%H" f952445b` = `f952445b07b1517f119a3b030cf7533bee6d14f2`.
- Bullet 3 (direct-call result, fact (2)) -- **CORRECT**, verbatim-accurate against source lines 261-262.
- Fact (3) (through-proxy result -- "Re-verified through the fixed proxy: ... completed in **121s**, `finish_reason: "stop"`, `completion_tokens: 6324`", source lines 263-267) -- **MISSING ENTIRELY**. Root cause: **CB-12** (section 5) -- step 4's finding was never recorded because it was resolved via the OQ-259/Option-A resume path, so it never entered the "Prior step findings" block step 6 used to write the file.
- Bullet 4 (cost range, fact (4)) -- **FABRICATED**: the file says `$0.0003-$0.003 USD per call`; the source (lines 273-275) says `$0.025-0.037 per call` -- wrong by ~100x, and the underlying step-5 finding text cited a fake source ("as recorded in `scripts/tests/test_local_mcp_orchestrator_findings.py`", which contains no such figure). Unlike fact (3), this is not explained by CB-12 -- step 5's *own* task was "record the cost range" and its own finding was already wrong before step 6 ran. Whether this is a standalone CB-7 verbatim-quoting failure, or a downstream confusion effect from the missing fact (3) (the model conflating/inventing a number while assembling 4 bullets from only 3 carried-forward facts), is **not yet determined** -- open question for the next clean run.

**Verdict: CB-7/AC-2 = FAIL.** The run completed 8/8 and produced a real commit, but 1 of 4 required facts was fabricated and 1 of 4 was dropped. Two new backlog items added (section 5): **CB-11** (validator false-positive on read-only/post-commit steps -- the proximate cause of both OQ pauses in this run) and **CB-12** (resume-Option-A doesn't record a finding for the resolved step -- the confirmed root cause of the missing fact (3)). CB-7 itself remains **not Verified** -- its verbatim-quoting instruction (commit `cfa3a2d4`) was exercised correctly for facts (1) and (2), but the run never produced a pipeline clean of CB-11/CB-12 interference to test it for facts (3) and (4) in isolation.

OQ-259 (this run, step 4/8) and OQ-260 (step 8/8) both resolved Option A and removed from the open-questions table; see `architecture-docs/global/architect-open-questions.md` changelog for 2026-06-12.

**Next:** implement CB-12 (the smaller, more isolated fix -- one missing `_extract_step_finding` call in the resume branch) and/or CB-11, then re-run the same 8-step CB-7/AC-2 task. If a clean run still fabricates the cost-range fact, that isolates the fabrication to CB-7's own verbatim-quoting fix being insufficient for numeric ranges specifically.

### 2026-06-12 -- CB-11 and CB-12 implemented (test #14 follow-up)

**CB-11** (validator false positives): added `_VALIDATOR_RECORD_ONLY_STEP_RE` (matches step tasks of the form "Record/Identify/Note/Quote/Locate the exact quote/sentence/wording/text/value ...") so such steps validate YES on an empty diff regardless of incidental change-verb wording elsewhere in the task text. Separately, `_run_validator_pass` gained a `head_changed: bool = False` parameter; `_finish_step` now computes it from `_git_snapshot`'s pre-/post-step `git rev-parse HEAD` (the snapshot already captured `head`, no new git calls needed) and passes it through, so a successful `git commit` step with a clean working tree validates YES ("HEAD advanced") instead of AMBIGUOUS.

**CB-12** (resume findings drop): `_finish_step`'s AMBIGUOUS branch now stores `state["ambiguity_last_summary"]` (the paused step's own executor summary) and `state["ambiguity_oq_id"]`. New helper `_record_resolved_step_finding(state, step_idx)` extracts a finding from that summary via `_extract_step_finding` (or synthesizes a placeholder citing the OQ id and "Option A" if the summary yields nothing) and appends it to `state["findings"]`. Called from both resume-resolution branches in `_handle_orchestrated_request` -- the fresh-session "(a-resume)" marker path and the in-session "(a)" continue path -- so a step resolved via architect Option A now contributes its fact to the CB-10(b) "Prior step findings" block for all later steps, matching `_finish_step`'s normal YES auto-advance behavior.

**Tests:** 10 new cases -- `TestCB11RecordOnlyStepFalsePositive` (3), `TestCB11PostCommitCleanDiff` (2) in `test_local_mcp_validator.py`; `TestRecordResolvedStepFinding` (5) in `test_local_mcp_orchestrator_findings.py`. Full suite (`test_local_mcp_validator`, `test_local_mcp_orchestrator_findings`, `test_local_mcp_orchestrator_resume`, `test_local_mcp_dispatch_timeout`): 40/40 pass, no regressions.

**Status:** both implemented, not yet live-validated. Next: re-run the CB-7/AC-2 8-step task (test #15) to check whether (a) CB-11 prevents the OQ-259/OQ-260 pauses entirely, (b) CB-12 (if a pause still occurs and is resolved Option A) correctly carries the resolved step's finding forward, and (c) whether fact (4) (cost range) is still fabricated in a run unaffected by CB-12's missing-fact-3 confusion -- which would isolate it as a standalone CB-7 gap.

### 2026-06-12 -- CB-7/AC-2 test #15: 9/9 complete, all 4 facts verbatim-correct -- CB-7 Verified; CB-11/CB-12 confirmed; new findings CB-13 and CB-11 "copy" gap

**Setup:** restarted `local-mcp.py` to load the CB-11/CB-12 fixes (commit `a1e2175f`), then re-ran the identical CB-7/AC-2 task prompt used in tests #11-#14 (read the test #10 section of this roadmap, quote 4 facts verbatim into `cb7-ac2-validation-summary.md`, commit). Same task text hashes to the same orchestrator key (`a731f317e9507669`), so this run's state overwrote test #14's state file.

**Run:** the planner produced a *9*-step breakdown this time (vs. test #14's 8 steps) -- structurally equivalent but with "Copy the exact sentence stating X" wording for steps 3-6 (one per fact) instead of test #14's phrasing.

- Steps 1-4: validated YES, auto-advanced normally.
- **Step 5/9** ("Copy the exact sentence stating the through-proxy result for test #10 after the fix, including its `completion_tokens` count and elapsed time in seconds") -- validator returned AMBIGUOUS (0 files changed). Root cause: `_VALIDATOR_RECORD_ONLY_STEP_RE` matches `record|identify|note|quote|locate` but not `copy`, so the CB-11 fix didn't cover this step's wording even though it's the same "record a fact, read-only" shape as test #13/#14's OQ-259. Auto-raised `OQ-259` a third time. **Architect: Option A** (same reasoning as precedent) -- resumed via `resume-orchestrator-run.ps1 -Key a731f317e9507669` (`cb7_ac2_kimi_test15_resume1.log`, 417.2s).
  - **CB-12 confirmed working**: the resume correctly called `_record_resolved_step_finding`, appending step 5's finding ("through-proxy result ... **121s** elapsed, `completion_tokens: 6324`, `finish_reason: \"stop\"`") to `state["findings"]`.
- Step 6/9 ("Copy the exact sentence stating the per-call cost range for kimi-k2.6 in USD") then validated YES and produced the **correct** fact: `$0.025-0.037 per call` -- this is the same fact that test #14 fabricated as `$0.0003-$0.003` (~100x off). With step 5's finding now present in the "Prior step findings" block (CB-12), step 6 read the source correctly and quoted it correctly. **This confirms the test #14 fabrication was a downstream confusion effect of the missing fact (3), not a standalone CB-7 verbatim-quoting gap.**
- **Step 7/9** ("Create `cb7-ac2-validation-summary.md` containing exactly four bullet points...") -- the executor's summary claimed success, listed the file as changed, and even ran `cmd.exe /c type C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md` to "verify" the content -- but `git status` showed the repo's working tree unchanged. The validator correctly returned AMBIGUOUS (this is the validator working *as designed* -- the step genuinely did not modify the repo). Auto-raised `OQ-260`.
  - **New finding, CB-13**: the executor wrote to `C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md` -- missing the `source\repos\Electron-Splines\` path segment. The *content* of that misplaced file was verbatim-correct for all 4 facts (verified by reading it). Root cause not yet investigated (Cline cwd vs. model-emitted path). See CB-13 row in section 5.
  - **Resolution**: copied the verified-correct content from the misplaced file into the real `foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md` by hand, then resolved `OQ-260` **Option A** ("the four facts are now correctly present in the target file; content verified verbatim-correct against source") and resumed (`cb7_ac2_kimi_test15_resume2.log`, 40s).
- Steps 8/9 (`git add`) and 9/9 (`git commit`) both validated **YES on the first try** -- step 9 via the new CB-11 `head_changed` signal ("the working tree is clean but HEAD advanced (a commit was made)"), no OQ raised. **Run reached `status: complete`, 9/9.**

**Result:** commit `f8b3bd30` ("docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)") -- `foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md` now contains all 4 required facts, verbatim-correct against the source:
1. `CF_NON_STREAM_TIMEOUT_SECONDS = 290`, commit `f952445b` -- correct.
2. Direct-call result: `completion_tokens = 9153` in **175s** -- correct.
3. Through-proxy result: `completion_tokens: 6324` in **121s** -- correct (previously dropped in test #14, traced to CB-12).
4. Cost range: `$0.025-0.037 per call` -- correct (previously fabricated as `$0.0003-$0.003` in test #14).

**Verdict: CB-7/AC-2 = PASS, CB-7 Verified.** CB-11 and CB-12 are both confirmed working live (CB-12 fully; CB-11 partially -- the `head_changed` fix worked cleanly, but the "copy"-verb regex gap still needed one Option A). Two new backlog items: the CB-11 "copy" regex gap (tracked in CB-11's row, untried fix) and **CB-13** (wrong-path file write, new row, untried fix). OQ-259 (third occurrence, same precedent) and OQ-260 (this run) both resolved Option A.

**Next:** (1) extend `_VALIDATOR_RECORD_ONLY_STEP_RE` to cover `copy` (and audit for other planner verb synonyms); (2) investigate CB-13's root cause via a minimal reproducer; (3) clean up the stray file at `C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md`.

### 2026-06-12 -- CB-11 "copy" regex gap closed; CB-13 root cause found and fixed (`run-cline.ps1` missing `-WorkingDirectory`)

Both of test #15's remaining follow-ups were resolved in the same session:

- **CB-11**: `_VALIDATOR_RECORD_ONLY_STEP_RE`'s verb alternation extended from `record|identify|note|quote|locate` to also include `copy|transcribe|extract`, all still gated by the existing "...exact quote/sentence/wording/text/value" requirement. This guard means a refactor-style step ("Extract the validation logic in foo() into a new helper function") does **not** false-positive as read-only -- confirmed by a new dedicated test (`test_extract_function_refactor_step_still_ambiguous`). 4 new tests in `TestCB11CopyVerbStepFalsePositive` (`test_local_mcp_validator.py`).

- **CB-13**: root cause confirmed empirically. `run-cline.ps1`'s `Start-Process -FilePath cmd.exe ...` had no `-WorkingDirectory`, so the spawned process's cwd is whatever the *calling* PowerShell session's current location happens to be -- not the repo root. Reproduced with a minimal harness:
  ```powershell
  Push-Location $env:USERPROFILE
  Start-Process -FilePath cmd.exe -ArgumentList '/c','cd > out.txt' -NoNewWindow -PassThru
  # out.txt contains: C:\Users\jakeh
  ```
  When `run-cline.ps1` (directly, or via `run_cb7_ac2_test15.ps1`/`resume-orchestrator-run.ps1`) is launched from a shell whose location is `$env:USERPROFILE`, the spawned `cline` process's `process.cwd()` is `$env:USERPROFILE`, and it resolves the task's relative output path (`foundation/SR-1.4-ai-guidance/docs/cb7-ac2-validation-summary.md`) against that -- producing the exact wrong path observed in test #15 step 7/9 (`C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md`). This was a launcher-script bug, not a model content-fidelity issue (the file *content* the model produced was always correct).

  **Fix**: `run-cline.ps1` now computes `$repoRoot = Split-Path -Parent $PSScriptRoot` and passes `-WorkingDirectory $repoRoot` to `Start-Process`, so the spawned `cline` process's cwd is pinned to the repo root regardless of the caller's location. Re-running the same minimal harness with `-WorkingDirectory $repoRoot` confirms `out.txt` now contains the repo root.

**Tests:** full suite (`test_local_mcp_validator`, `test_local_mcp_orchestrator_findings`, `test_local_mcp_orchestrator_resume`, `test_local_mcp_dispatch_timeout`): 44/44 pass, no regressions.

**Status:** both fixes implemented and unit-tested; not yet live-validated with a fresh orchestrator run (the CB-13 fix in particular should be exercised live to confirm a "create file X" step writes to the correct repo path when launched from a non-repo-root cwd). The stray misplaced file at `C:\Users\jakeh\foundation\SR-1.4-ai-guidance\docs\cb7-ac2-validation-summary.md` was deleted 2026-06-12 with explicit user authorization (outside the repo working directory; parent directory tree left in place).

**Next:** triaged 2026-06-12 -- live-validation of both fixes is a mechanical re-run-and-observe action, queued as **AT-1140** in `ai-task-queue.md` ("CF Proxy Orchestrator -- Goal A Live Validation"); the gpt-oss-vs-kimi-k2.6 default-cheap-tier-model decision is a real architect-level choice, escalated as **OQ-264** in `architect-open-questions.md` (preemptive answer: Option C). The toolchain spin-out (goal B) remains sequenced after both.

---

## 9. 2026-06-12 Closeout: CB items and toolchain spin-off

Per architect decision 2026-06-12 ("close out all the CB items and get on with the spin off"): this roadmap's CB-1..CB-19 backlog is closed out as of this entry. The AI dev toolchain (Cloudflare proxy, `local-mcp.py` orchestrator, Docker, MCP server) is being spun out into a standalone repository (`AT-1116`-`AT-1139` in `architecture-docs/global/ai-task-queue.md`, "LLM Tech Stack Standalone Repository"). **Further refinement of the agentic system continues in that new repo**, not in Electron-Splines.

### Verified / Implemented -- no further action needed in this repo

| ID | Final status |
|----|----|
| CB-7 | Verified 2026-06-12 (test #15, commit `f8b3bd30`) -- planner/step content fidelity confirmed 9/9, all 4 facts verbatim-correct |
| CB-9 | Implemented and live-validated 2026-06-11/12 (Option C orchestrator resume) |
| CB-10(a) | Implemented 2026-06-11 (590s dispatch timeout); superseded in practice by CB-16's `CF_FORWARD_TIMEOUT_SECONDS` fix |
| CB-10(b) | Resolved and live-validated 2026-06-11 (OQ-263 Option A, run `2b3ea4aba969d3d3`, 7/7 steps) |
| CB-11 (original: record-only / post-commit / "copy" verb) | Implemented and Verified 2026-06-12, 44/44 tests pass |
| CB-12 | Implemented and Verified 2026-06-12 (test #15 findings carry-forward confirmed) |
| CB-13 | Fixed and Verified 2026-06-12 (AT-1140 test #17, `-WorkingDirectory $repoRoot`) |
| CB-14 | Implemented and Verified 2026-06-12 (AT-1140 test #17, CB-14 terminal-tool handling) |
| CB-16 | **Fixed 2026-06-12, conclusively validated** -- 0 `ReadTimeout` across 164 CF requests / 3 runs/resumes, 57/57 tests pass |

### Deferred to the standalone toolchain repo -- carried forward, not pursued further here

| ID | Carry-forward summary |
|----|----|
| CB-1 | Compress/summarize large tool results before re-injection -- low-priority backlog per OQ-264 (gpt-oss deprioritized after `cf/kimi-k2.6` adoption); revisit only if kimi-k2.6 cost exceeds budget or an unrelated task surfaces the root cause |
| CB-2 | Tighten oversized-tool-result truncation cap -- same OQ-264 backlog/revisit triggers as CB-1 |
| CB-3 | Context-size-aware model routing away from gpt-oss -- same OQ-264 backlog/revisit triggers as CB-1 |
| CB-5 | Per-step tool-call budget / early step termination -- untried, more invasive (changes step-loop control flow); consider only after CB-2/CB-4 measured |
| CB-8 | Validator false-positive on quoted/reproduced failure language in `_VALIDATOR_FAILURE_RE` -- blocks clean validator passes on read steps that quote source text discussing failures; not yet fixed |
| CB-11 (new variant) | `git diff`-based change detection misses brand-new untracked files (essay task 2, step 2/12, OQ-266 second occurrence); candidate fix is to also diff `git status --porcelain` |
| CB-15 (systemic fix) | **Implemented and verified 2026-06-14 (AT-1142)**: `/health` commit-SHA endpoint + startup logging in `local-mcp.py`, new `toolchain-doctor.ps1` STALE state (`LocalMcpStale`) with auto-restart-on-`-Fix`, verified live against a real pre-AT-1142 stale server. See section 5 |
| CB-17 | `status: "running"` runs killed by `run-cline.ps1`'s `-TimeoutSec` wrapper have no resume path; naive re-send re-plans from scratch and overwrites in-progress state (essay task 1, run `81c97430204a89e0`); not yet fixed |
| CB-18 | `_next_oq_id` reuses retired OQ IDs -- 3 collisions in one session (OQ-259, OQ-266, OQ-267); candidate fix is a persisted monotonic "highest ID ever issued" counter |
| CB-19 | A step's executor session can silently complete multiple subsequent steps' work, desynchronizing `current` from the working tree (essay task 2, run `90c2dbb2a162a15b`, step 3/12, OQ-267 third CB-18 reuse); two candidate fix directions noted in CB-19's row, neither tried |

### Closing essay-task runs

Both essay-writing orchestrator validation runs (task 1, `81c97430204a89e0`; task 2, `90c2dbb2a162a15b`) are stopped by architect decision -- see `architect-open-questions.md` "Last updated" entries 2026-06-12. Their partial drafts and findings remain committed as evidence; neither run will be resumed in this repo.

**Next:** see `ai-task-queue.md` "LLM Tech Stack Standalone Repository (AT-1116-1139)" for the spin-off task sequence.

---

## 10. 2026-06-14 -- CB-20: multi-step detector misfired on tool-result feedback, ~34% of one day's spend wasted

Despite the section 9 closeout, `local-mcp.py` remained in active use in this repo via the Cline VS Code extension. A live session on 2026-06-14 hit the `CF_PROXY_DAILY_HARD_CAP_AUD` review threshold (~$16.75 AUD / $11.79 USD, 249 requests, 84% of the $20 AUD hard cap) for negligible output (two one-line doc edits, plus a regression -- see below).

**Root cause (CB-20):** `_detect_multi_step_ask` runs on `_latest_user_message(body)` -- the most recent `role: "user"` message. In Cline's protocol, tool-result feedback is *also* sent back as `role: "user"` (e.g. `"[read_file for 'roadmap.md'] Result: 1 | # Cheap-Model Context-Budget Improvement Roadmap..."`). Any tool result over 350 chars containing 3+ of `_MULTI_STEP_ACTION_VERB_RE`'s ~25 common verbs (`create, build, write, document, update, test, review, analyze, verify, identify, audit, compare, ...`) -- i.e. virtually any markdown doc or source file -- was misdetected as a fresh multi-step ask.

`_run_planner_pass` then re-sent the *entire tool-result payload* (observed up to 152,547 chars / ~90K prompt tokens -- the single largest prompt-token entries of the day) asking the model to "decompose" the file's contents into steps. Outcomes, all wasted:

- Most commonly, Kimi extracted one "step" per heading/section of the document, producing 13-33 steps -> exceeded `_ORCHESTRATOR_MAX_STEPS` (12) -> discarded ("forwarding original request unchanged"). **28 of ~83 billed calls (34%) hit this path.**
- Occasionally Kimi ignored the planner's "no tool calls" instruction entirely and emitted a `read_file` tool call -> "planner pass returned no numbered steps" -> discarded.
- Occasionally the doc happened to have <=12 headings -> the planner's "steps" (fragments of document structure, e.g. *"Read `agentic-tiered-inference-strategy.md` to verify it is a markdown file"*) were auto-confirmed as a real orchestrator plan and dispatched, derailing the session into executing a task unrelated to anything the architect asked. This produced the long tail of `[STALE]` / `0 round trip(s)` entries seen in `orchestrator_status.py`.

Secondary, compounding factor: no context compaction. Per-turn prompt sizes climbed 76K -> 82K -> 89K tokens turn-over-turn (full history of prior tool-result dumps resent every turn), which both multiplied the cost of every misfire above and plausibly contributed to a content-fidelity regression: the session's one substantive edit to *this very file* turned `# Cheap-Model Context-Budget Improvement Roadmap` into `# # Cheap-Model Context-Budget Improvement Roadmap` (a broken double-heading), fixed in the same commit as this entry.

**Fix (commit pending):** added `_conversation_already_in_progress(messages)` -- returns True if any earlier message shows the agent already made a tool call (assistant `tool_calls`, `role: "tool"`, or a flattened `tool_use`/`tool_result` content block). `_detect_multi_step_ask` is now skipped whenever this is True, restricting the planner pass to its intended purpose: decomposing the *initial* task description, before any tool calls have been made. CB-1/CB-2 (context compaction, still deferred per section 9) would address the secondary factor.

**Status:** Implemented, not yet live-validated (requires restarting the `local-mcp.py` debugpy session, which would interrupt the in-progress Cline run). Next: restart, then confirm via `~/.cf_proxy_spend.json` and the proxy log that `multi-step ask detected` no longer fires on tool-result turns.

---

## 11. 2026-06-15 -- CB-21: CF Workers AI `429`/code-3040 "Capacity temporarily exceeded" for `@cf/moonshotai/kimi-k2.6`, self-resolved on retry

`cf_proxy_live.err.log` shows two consecutive `@cf/moonshotai/kimi-k2.6` requests at 17:22:52 and 17:22:57 (5s apart) both got `HTTP/1.1 429 Too Many Requests` from `api.cloudflare.com` with body `{"errors":[{"message":"AiError: AiError: Capacity temporarily exceeded, please try again. (...)","code":3040}],"success":false,...}`. `_diagnose_upstream_error` has no special case for 429/3040, so it fell through to the generic `[cfproxy] CF API error (status {code}): {body}` message and was passed through to Cline with the original 429 status.

Cline retried both times, and each retry resent the *entire growing conversation* as a new request: 16 msgs/102,539 chars -> 18 msgs/104,903 chars -> 20 msgs/107,267 chars. The third attempt (17:24:00, ~63s after the first) got `200 OK`. **Self-resolved -- CF's capacity constraint was transient (seconds-to-low-minutes), and Cline's own retry-on-error behavior recovered without intervention or a code change.**

This is the same "retry -> growing-context -> repeat" shape as CB-16 (which was for `ReadTimeout`, not `429`), but for a different root cause (CF-side inference capacity, not proxy-side timeout) -- and unlike CB-16 it resolved on the 3rd attempt rather than looping. **No fix applied.** Noted here as a new named failure signature (429/code 3040) in case it recurs and starts compounding (each retry's larger prompt is itself closer to the `_LARGE_PROMPT_DIAGNOSTIC_THRESHOLD_TOKENS`/degenerate-response territory from CB-1/CB-7). If it becomes frequent, a targeted fix would be: detect 429/code-3040 in `_diagnose_upstream_error` and have the proxy itself retry with a short fixed backoff (1-3s) *before* returning to Cline, so Cline's own retry (which resends the whole growing conversation) is needed less often.

---

## 12. 2026-06-18 -- AT-1171 documented; CB-22 ID-collision flag (CB-20 reused)

**AT-1171 (model-attribution commit trailer) -- already implemented, documenting here per its exit evidence requirement.** `_build_step_dispatch_body` (local-mcp.py:2552) accepts a `model` parameter; when present, it appends an instruction to the step's system prompt telling the executor to include `Co-Authored-By: {model} <noreply@cf-proxy.local>` in any commit made during that step, alongside the existing Cline/Claude trailer. `_dispatch_step` (local-mcp.py:2830) passes `state.get("model")` through on every call, so every orchestrated step dispatch carries this instruction automatically -- no per-task opt-in needed. Implemented in skein-toolkit commit `f5f0108` ("feat: add model attribution trailer to orchestrator step commits (AT-1171)"), 2026-06-16. Addresses vibe-coding anti-patterns #6 ("model drift") and #9 ("missing AI-attribution") -- a diff's authoring model is now recoverable from `git log` directly rather than requiring a cross-reference against `~/.cf_proxy_orchestrator/*.json` timestamps.

**CB-22 (ID-collision flag, not a new bug):** while documenting AT-1171, found that **section 10's "CB-20"** (2026-06-14, multi-step detector misfiring on tool-result feedback) is a *different* bug from a second "**CB-20**" used in `skein-toolkit/mcp-server/run-cline.ps1`'s comments (2026-06-17, Cline v3.x Bun binary `stdio: "inherit"` not reading a `Start-Process -RedirectStandardInput` file-handle -- fixed via cmd.exe's pipe operator). Both were assigned independently without checking this doc, the same class of problem as CB-18 (`_next_oq_id` ID-reuse-after-retirement) but for hand-assigned CB numbers rather than orchestrator-assigned OQ numbers -- there is no `_next_cb_id` helper enforcing uniqueness. No functional impact (both bugs are independently real and independently fixed), but the duplicate ID makes this doc's CB-20 ambiguous out of context. **Recommendation:** treat `run-cline.ps1`'s CB-20 entry as **CB-22** going forward (this doc's CB-20 keeps its original number since it was assigned first chronologically, 2026-06-14 vs 2026-06-17); update the comment in `run-cline.ps1` in a follow-on pass. No `_next_cb_id` mechanism exists to prevent recurrence -- flagged for awareness, not scoped as its own fix here.
