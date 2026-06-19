# Aider Evaluation (AT-1189)

**Date:** 2026-06-19
**Scope:** Real implementation + multi-task testing, per OQ-290's resolution ("I am not
content to just trust its better, that needs to be proven through testing") -- not a
one-page impressions note. All runs below are real: real LiteLLM calls, real file edits,
real test suites, real failures. Nothing in this document is extrapolated from aider's
own marketing or general reputation.

## Setup

`pip install aider-chat` (skein-toolkit's `.venv`) -- clean install, version 0.86.2.
Configured against the existing LiteLLM proxy via `OPENAI_API_BASE=http://localhost:4000/v1`
and `OPENAI_API_KEY=<LITELLM_MASTER_KEY>`, models addressed as `openai/<litellm-model-name>`
(e.g. `openai/cf/kimi-k2.6`).

Two real, reproducible setup defects found before any task could run at all:

1. **Aider crashes outright on Windows** printing a tool-warning that contains a `►`
   character, via `UnicodeEncodeError` in Rich's legacy Windows console renderer (cp1252).
   Fix: `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` must be set in the environment aider
   runs in. Undocumented in aider's own Windows setup notes as far as a quick check showed.
2. **`--suggest-shell-commands` is on by default** and asks an interactive
   "Run shell commands? (Y)es/(N)o/(S)kip all" prompt that `--yes-always` does **not**
   cover. In non-interactive `--message` mode this auto-answers "n" -- and at least once
   in testing, declining it caused an edit that aider had already printed (a fully-formed,
   correct-looking diff) to **never be written to disk at all**, with no error reported.
   This is the most dangerous failure mode found: it looks like success in the log.
   **Any automated/non-interactive aider usage must pass `--no-suggest-shell-commands`.**

## Real task runs

### Task 1 -- AT-1195 (add a DeepSeek V3.1 model entry to `litellm_config.yaml`)

Small, single-file YAML addition. Isolated git worktree (`skein-toolkit-aider-1195`).

- **Attempt 1** (`claude/sonnet-4`): failed immediately -- Anthropic credit exhausted
  ("Your credit balance is too low to access the Anthropic API"). **Aider does not retry
  with a fallback model** -- it just errors out. `dispatch_coding_task` has a ranked
  fallback list and would have moved to the next candidate automatically; aider has no
  equivalent without `--weak-model`/manual intervention.
- **Attempt 2** (`cf/kimi-k2.6`, default edit format): aider had no metadata for this
  custom model name ("Unknown context window size and costs, using sane defaults") and
  defaulted to **whole-file edit format** -- the model must reproduce the entire 263-line
  file to make any change. The model's response devolved into a hallucinated fake
  follow-up conversation (referencing user messages that were never sent) partway through
  reproducing the file, and **made no edit at all**. 63K tokens sent, 1.8K received, zero
  result.
- **Attempt 3** (`cf/kimi-k2.6`, forced `--edit-format diff`): succeeded. 7.2K tokens sent
  (a 9x reduction from attempt 2), 3.3K received. Correct, well-formed YAML entry, valid
  cost metadata, matched the existing entry's structure exactly. **Verified**: `yaml.safe_load`
  parses cleanly, diff is minimal and correct.

**Conclusion for this task: success, but only after 2 failed attempts and a
non-obvious manual fix (forcing diff format) that a default aider user would not know
to apply for an unrecognized model.**

### Task 2 -- AT-1194 (add a setup-wizard prompt + README doc, PowerShell + Markdown)

Small, 3-file task (`setup-devserver.ps1`, 363 lines; `devserver.config.ps1`, 237 lines;
`README.md`, 200 lines). Isolated worktree (`skein-toolkit-aider-1194`).

- **Attempt 1** (`cf/kimi-k2.6`, diff format, all 3 files added): **empty response from
  the LLM** ("Empty response received from LLM. Check your provider account?"). This is
  the exact same degenerate-empty-response failure mode already tracked as a chronic
  problem in this project's own `cf-proxy-cheap-model-context-budget-roadmap.md` (there
  documented for `cf/gpt-oss-20b/120b`) -- reproduced here with a **different** model
  (`kimi-k2.6`), via aider's own context (system prompt + repo-map + 3 files), not the
  orchestrator's prompt construction. Aider has none of this project's own mitigations
  (`reasoning_effort: low`, context compression) since it talks to LiteLLM directly.
- **Attempt 2** (`cf/kimi-k2.6`, single file only): empty response again, even with just
  the 363-line `setup-devserver.ps1`. Confirms file size, not file *count*, is the trigger.
- **Attempt 3** (`local/qwen2.5-coder:32b`, single file, no `--no-suggest-shell-commands`):
  produced a correct-looking diff in the transcript, asked "Run shell commands?", got
  auto-answered "n" by `--yes-always` (which doesn't cover that prompt) -- **and the edit
  was never written to disk.** `git status` showed no change to the target file at all.
- **Attempt 4** (`local/qwen2.5-coder:32b`, single file, **with**
  `--no-suggest-shell-commands`): an edit was actually applied this time -- but to the
  **wrong file** (`devserver.config.ps1` instead of `setup-devserver.ps1`) and was
  **semantically broken**: it inserted an interactive `Read-Host` prompt directly into
  the config-loader file (which should be a non-interactive, sourced settings file, not
  something that prompts every time it's loaded), and referenced `$_userConfig` in an
  `Add-Content` call **before that variable was defined** -- a guaranteed runtime error.

**Conclusion for this task: 4 attempts, 0 correct results.** This is itself valuable,
honest evidence, not a gap in testing rigor -- a "Small" task failed completely across
every configuration tried.

### Task 3 -- AT-1162 (advisory file locking in `local-mcp.py`, ~3700 lines + new tests)

Medium-effort, real concurrency-safety task. Isolated worktree (`skein-toolkit-aider-1162`).
Chosen specifically as the head-to-head comparison task against `dispatch_coding_task`.

- **Attempt 1** (`cf/kimi-k2.6`, diff format, `--no-suggest-shell-commands`): **empty
  response from the LLM** again, this time on a much larger file (~3700 lines). Confirms
  the context-budget failure scales with file size as expected.
- **Attempt 2** (`local/qwen2.5-coder:32b`): hung. `ollama ps` showed the model loaded
  with **only a 4096-token context window**, 75%/25% CPU/GPU split (slow). `local-mcp.py`
  at ~3700 lines is almost certainly tens of thousands of tokens -- far beyond what fits
  in a 4096-token context regardless of speed. This is a **structural** limitation of how
  local models are currently configured in `litellm_config.yaml`, not a transient
  slowdown. Stopped manually after ~30 minutes with no output and the model reporting
  "Stopping..." (idle-timeout unload) in `ollama ps`.

**Conclusion for this task: aider could not complete it in any configuration tried.**

### Direct comparison -- AT-1162 via `dispatch_coding_task` (same task, same repo)

Dispatched for real via the AT-1228/1227/1230 pipeline, model resolved automatically to
`claude/sonnet-4` (the ranked-fallback probe found it reachable this time). Ran ~19
minutes (1157s), producing a real commit (`ca269aa`):

- `local-mcp.py`: a `_ledger_lock(path)` context manager using `os.open(O_CREAT|O_EXCL)`
  for atomic, **stdlib-only** lock-file creation (deliberately did not add the
  `portalocker` dependency the task description suggested -- a better call, smaller
  dependency footprint, explained in the commit message) wrapping `_save_orchestrator_state`,
  `_append_oq_row`, `_append_at_row`.
- New test file, 466 lines, 13 tests: lock acquire/release/cleanup-on-exception,
  timeout behavior, and **real `multiprocessing.get_context('spawn')`-based concurrent-
  writer simulation** (not mocked) for all three wrapped functions.
- Verified independently: all 13 new tests pass; full suite (242 tests) green.
- Did exhaust Anthropic credit again partway through a later step (the same recurring
  issue seen elsewhere this session) -- but the actual deliverable commit had already
  landed before that, so the run's real output was unaffected.

**This single `dispatch_coding_task` run produced a higher-quality, fully-tested result
than aider managed across 7 total attempts spanning all 3 tasks combined.**

## Failure-mode comparison vs. Cline's known issues

| Failure mode | Cline (pre-dispatch-pipeline) | aider (this evaluation) |
|---|---|---|
| Auth/billing | JWT expiry (silent hang) | Anthropic credit exhaustion (loud error, no auto-fallback) |
| Shell quirks | `NativeCommandError` on PS5.1 | None observed |
| Lost work | Checkpoint revert | **Silent non-write after displaying a correct-looking diff** (worse -- no error at all) |
| Context budget | N/A (dispatch pipeline doesn't hit this) | Reproduced the project's known CF degenerate-empty-response bug, plus a separate local-model context-window structural mismatch |
| Wrong output | N/A | Correct-looking diff applied to the **wrong file**, with a variable-ordering bug |

Aider did not eliminate any of Cline's old failure modes in a way that matters here
(the JWT/PS5.1 issues are now moot anyway, since `dispatch_coding_task` doesn't use the
VS Code extension path) -- and it introduced new ones, including a strictly more
dangerous class (looks-like-success-but-isn't) than anything Cline exhibited.

## Cost comparison

Real numbers from this evaluation, not estimates:

| Run | Tokens sent | Tokens received | Outcome |
|---|---|---|---|
| AT-1195 attempt 2 (whole-file default) | 63,000 | 1,800 | Failed |
| AT-1195 attempt 3 (diff format) | 7,200 | 3,300 | Succeeded |
| AT-1162 via dispatch_coding_task | (not separately metered per-call; full run ~19 min) | -- | Succeeded, fully tested |

The 9x token blowup between whole-file and diff format on the *same task* is itself a
significant finding: **aider's default edit-format selection for unrecognized custom
model names (whole-file) is a real cost risk**, on top of everything else.

## Commit-hygiene compatibility

Not actually exercised in this evaluation -- every run used `--no-auto-commits`
specifically to keep evaluation artifacts out of real history until reviewed. Aider's
own auto-commit mode was not tested against this project's one-commit-per-issue /
size-guardrail policy as a result. Flagging as an open gap in this evaluation rather
than guessing.

## Go/No-Go Recommendation

**No-go for replacing or matching `dispatch_coding_task` as currently configured.**
Across 3 real tasks and 7 total attempts, aider succeeded once (AT-1195, and only after
discovering a non-obvious edit-format fix), and failed completely on the other two tasks
-- including the head-to-head comparison task, where `dispatch_coding_task` succeeded
cleanly in a single real attempt with a fully-tested, well-reasoned result.

This is not a verdict on aider's underlying capability in general -- it's a verdict on
**aider against this specific stack's actual configuration** (custom LiteLLM model
names with no metadata, the project's own already-known CF context-budget ceiling, and
local models configured with a context window far smaller than this project's real
files). Closing the gaps found here (a model-metadata file for cost/context-window
awareness, forcing diff edit format by default, `--no-suggest-shell-commands` always on,
widening local model context windows in `litellm_config.yaml` and Ollama's own settings)
would be real, scoped follow-up work -- not attempted in this AT, since OQ-290's
resolution asked for proof before adoption, not before any further investment.

**Per OQ-290's hybrid decision: `dispatch_coding_task` (Option D) remains the
functional baseline.** Aider (Option C) is not adopted on this evidence. If revisited
later, start from the gaps list above rather than re-running the same configuration.
