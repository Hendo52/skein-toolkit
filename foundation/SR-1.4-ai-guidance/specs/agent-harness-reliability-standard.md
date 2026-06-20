# Spec: Agent Harness Reliability Standard

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.4 (AI toolchain governance) -- this SR's charter already covers "how AI agents are dispatched" (design-goals.md), which is exactly this document's subject |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | A full-session retrospective: 26 CB-numbered incidents, AT-1196/AT-1197's dispatch sagas (today, live), and external research into production agent-harness practices (cited inline, §3) |
| **Agent** | `docs` |
| **Model** | Tier-C (cross-cutting judgment across many incidents, not a routine writeup) |

---

## 1. What we are trying to do, and why

**What:** Turn the accumulated pattern of harness bugs found and fixed this
session into a standing set of numbered requirements that future work is
checked against -- so the next harness change is evaluated against a
standard, not reinvented from scratch or caught by accident the way most of
today's findings were.

**Why now:** The architect's own framing, verified rather than assumed: "I
have a hunch that our agent harness is the weakest link rather than our
model." That hunch is now backed by hard counts (§2) and external
corroboration (§3), not just today's incidents. The architect separately
asked for this to be formalized because dispatch infrastructure is
something "we build upon for a very long time" -- a one-off incident
writeup would not survive past this session; a spec with numbered
requirements and acceptance criteria does, the same way every other piece
of this project's governance works (CLAUDE.md's own policies, the risk
framework, the dashboard design spec).

**Out of scope:** Model capability/judgment (covered by
`ai-model-selection-policy.md`'s tier classification) and the dispatch
*architecture* itself -- worktrees, job state, the supervisor wake-loop
(covered by `odysseus-agentic-dispatch-architecture.md`). This spec is
specifically about the harness's *reliability properties*: does a real,
capable model actually get a fair, correctly-configured, observable run.

---

## 2. Current state inventory (verified against code and incident history, 2026-06-20)

### 2.1 The 26-item CB incident ledger

Full inventory in `cf-proxy-cheap-model-context-budget-roadmap.md` and git
history. Categorized by root cause class, not by which CB number:

| Category | Count | Pattern |
|---|---|---|
| Harness/infrastructure | ~22-24 | Process management, ID/key generation, timeout mismatches, validator false-positives, missing retry coverage, stale-process detection gaps |
| Model-capability | 2-3 | Content-density degeneracy (CB-1), multi-step overshoot (CB-19) |

13 of 26 are fixed and verified. **Every fix was a harness fix.** None were
"use a smarter model."

### 2.2 AT-1196/AT-1197, as concentrated evidence (today, live)

One task (AT-1196), three dispatch attempts, two models, four distinct
failures -- zero of them a reasoning failure:

1. `qwen2.5-coder:7b` hallucinated a fake tool call instead of calling a
   real one. Root cause: Ollama silently defaults to a ~2-4k token context
   window; `litellm_config.yaml` claimed "32k context" in every local
   model's description but never set `num_ctx`. **Fixed, verified
   end-to-end** (a real LiteLLM-routed request now loads the model at the
   configured context, confirmed via `ollama ps`).
2. The dispatch prompt template asserted a file path that only exists when
   the dispatch target is Electron-Splines -- false for every other
   consuming repo. **Fixed.**
3. A CF 429 destroyed 14 minutes of good research output -- within the
   existing retry budget's intent, but the budget exhausted on an unusually
   long run.
4. A CF 500 (a status code the existing retry logic never checked --
   only 429 was covered) destroyed a near-complete write on the very next
   attempt. **Fixed** -- retry coverage extended to both codes, in both the
   proxy (`local-mcp.py`) and the supervisor's pattern-matcher
   (`supervisor_triage.py`) together, not just one.
5. AT rows' own `../skein-toolkit/...`-style output paths resolve to the
   wrong repo when read from inside an isolated dispatch worktree (a
   sibling directory, not a subdirectory, of the real checkout). **Found,
   worked around per-row (AT-1197), not yet fixed structurally** -- see
   REQ-5.
6. Twice in one session, a wrapper script reported "Completed... exit 0"
   while its child `cline.exe` process was still alive, holding a file
   lock. **Found, manually resolved twice, not yet fixed structurally** --
   see REQ-6.

Then AT-1197's own dispatch (immediately following, same session): **every
local model candidate** was marked unreachable by `resolve_model_for_tier`.
Root cause confirmed directly: Ollama's cold-load time for a 12-23GB model
on this machine's partial-GPU-offload hardware exceeds the probe's fixed
15-second timeout. **Fixed** -- local candidates now probe with a 90-second
budget; cloud candidates keep the short one.

---

## 3. External corroboration -- this is not specific to our setup

- Cline's own GitHub issues report file-editing reliability problems
  **across every model, including Claude and GPT-4** -- a harness-level
  pattern. ([cline/cline#4384](https://github.com/cline/cline/issues/4384))
- The single most-cited Cline+Ollama complaint in the community is exactly
  finding #1 above: Ollama's silent context-window truncation, described
  as turning Cline "from broken to genuinely useful" once explicitly
  configured. (Local AI Master, "Cline + Ollama Setup 2026")
- With proper configuration, similarly-sized local models hit 93-97%
  tool-calling reliability on real agentic workflows -- evidence that the
  ceiling is a configuration problem, not a capability ceiling, for models
  in our weight class. (PromptQuorum local-model tool-calling benchmark)
- Production Ollama deployment guidance independently confirms two of this
  session's exact findings: "the health check's start_period must be long
  enough for the model to load" (REQ-2, found and fixed independently
  before this research was done) and "Ollama's default 5-minute keep_alive
  is too short if cold starts are scattered through the day; pre-loading
  required models before accepting traffic eliminates cold starts
  entirely" (informs REQ-9, not yet implemented).
- Circuit-breaker/backoff literature confirms the general shape of the
  CB-23/this-session's retry fix (exponential backoff, differentiate
  transient vs. permanent failure codes) but flags a gap we don't yet
  have: a circuit-breaker *state* (stop probing a repeatedly-failing
  candidate for a cooldown window) distinct from per-call retry, and
  jitter on backoff to avoid retry storms. (Portkey, "Retries, fallbacks,
  and circuit breakers in LLM apps")
- Current academic/industry framing of "harness engineering" (2026) treats
  the production harness as five layers: tool orchestration, verification
  loops, context/memory, guardrails, observability -- and explicitly
  recommends channeling every production failure directly into the
  regression suite. This project has been doing the latter organically
  all session (every fix above shipped with a test reproducing the real
  incident) without a name for the practice -- REQ-7 names it.

---

## 4. Requirements

Each requirement names a trigger, an acceptance criterion, and today's
conformance status -- per CLAUDE.md's First-Class Scenarios Policy, a
requirement without these three things is not ready to be a requirement.

### REQ-1: Every model's configured runtime capability must match its advertised capability

**Trigger:** Adding or editing any model entry in `litellm_config.yaml`.
**Acceptance:** The entry's `litellm_params` sets every parameter its
`model_info.description` claims (context window via `num_ctx`, etc.) --
description text is not allowed to be aspirational. **Status: Implemented
2026-06-20** for context window (all 8 local entries); no other claimed
parameter currently lacks a corresponding override.

### REQ-2: Health/probe timeouts must account for cold-start cost, not just response latency

**Trigger:** Any health check or readiness probe against a model backend.
**Acceptance:** Local (self-hosted, cold-loadable) candidates get a timeout
budget sized for the slowest realistic cold load on this hardware; cloud
candidates keep a short budget and still fail fast on genuine outages.
**Status: Implemented 2026-06-20** (`_LOCAL_PROBE_TIMEOUT_SECONDS = 90.0` vs.
`_PROBE_TIMEOUT_SECONDS = 15.0` in `dispatch_io.py`).

### REQ-3: New transient-failure signatures get added to every consumer of the pattern, in the same change

**Trigger:** Discovering a new transient (retryable) failure signature from
any upstream (CF, Anthropic, Ollama, etc.).
**Acceptance:** The signature is added to the proxy-level retry logic
(`local-mcp.py`) AND the supervisor's triage pattern-matcher
(`supervisor_triage.py`) in the same commit -- not just whichever one was
in front of the agent when the incident was found. **Status: Implemented
2026-06-20** for CF 500 (both consumers updated together, per the actual
commit). Prior 429 fix (CB-23) only updated the proxy at the time;
`supervisor_triage.py`'s 429 pattern was added later, in a separate change
-- this requirement exists specifically because that gap was real.

### REQ-4: Dispatch prompts must be repo-agnostic

**Trigger:** Any change to `build_task_prompt` or equivalent prompt
construction for a dispatch that can target more than one repo.
**Acceptance:** The prompt makes no claim about file paths, section names,
or conventions specific to one consuming repo (Electron-Splines) when the
dispatch target may be another (skein-toolkit, Odysseus). **Status:
Implemented 2026-06-20.**

### REQ-5: AT-row file-path references must be written relative to the dispatch target's own repo root

**Trigger:** Authoring or editing an AT row whose output file lives in a
repo other than Electron-Splines.
**Acceptance:** The row's exit-evidence path is written as a path relative
to the *target* repo's root (e.g. `docs/foo.md`), never as
`../skein-toolkit/docs/foo.md` -- that convention is only correct when read
from Electron-Splines itself, and resolves to the wrong location when read
from inside an isolated dispatch worktree (a sibling directory of the real
checkout, not a subdirectory). **Status: Found 2026-06-20 (AT-1196).
Worked around per-row going forward (AT-1197 already uses the corrected
form). Not yet enforced structurally** -- no validator currently rejects
the old form at AT-authoring time. Follow-up AT needed: a lint check in
the AT-authoring flow (or `task-and-oq-authoring-standard.md`'s
Decomposition Gate) that flags a `../` -prefixed output path when the
row's target repo isn't Electron-Splines.

### REQ-6: A job's process tree must be verifiably terminated before its state is treated as terminal

**Trigger:** Any dispatched job reaching a terminal status (`complete`,
`failed`).
**Acceptance:** No process whose command line references that job's
worktree path remains alive. **Status: Found 2026-06-20 (twice, same
session). Not yet implemented.** `kill_job_process_tree`'s existing
PID-tree kill cannot catch this case -- by the time the wrapper script
reports completion, the intermediate parent (the wrapper) may have already
exited, re-parenting its child outside that PID's tree, which a
tree-rooted kill can no longer reach. The fix needs to search by
command-line match against the job's worktree path (the same method used
manually today to find and kill both orphans), not by PID lineage. Tracked
as a follow-up AT, not implemented in this spec.

### REQ-7: Every real incident produces a regression test in the same commit as its fix

**Trigger:** Any fix landing in response to a real, observed failure (not a
hypothetical).
**Acceptance:** The commit includes a test that reproduces the original
failure mode and would fail against the pre-fix code. **Status: Already
the de facto practice all session** (every fix in §2.2 shipped with a
test citing the real incident) -- this requirement formalizes an existing
habit rather than introducing a new one, per the harness-engineering
literature's explicit recommendation to channel production failures
directly into the regression suite (§3).

### REQ-8: Model candidate lists are reviewed against the inference backend's actual current contents, not just the policy doc's last edit

**Trigger:** Any tier-review or harness audit (this spec being the first).
**Acceptance:** Every model already present in the local inference backend
(`ollama list`) is checked against `TIER_MODEL_CANDIDATES` for whether it
should be a candidate -- a pulled, configured, documented model is not
allowed to sit unwired indefinitely. **Status: Implemented 2026-06-20**
(`local/qwen3.6` found pulled and described but never wired; added).

### REQ-9: Local-model keep-alive duration should be tuned to reduce cold-start frequency, not just tolerated via longer timeouts (Planned, not yet implemented)

**Trigger:** N/A yet -- this is a recommendation from external research
(§3), not yet triggered by a specific incident beyond AT-1197's timeout fix
treating the symptom.
**Acceptance (proposed):** Local models used for agentic dispatch have an
Ollama `keep_alive` set well above the 5-minute default (community
guidance suggests 1-2 hours for sporadic-use patterns like this project's),
reducing how often a cold-load (and its associated 90-second probe risk)
happens at all. **Status: Not implemented.** Tracked as a follow-up AT --
deliberately not done in this spec, since it trades VRAM/RAM residency
against cold-start frequency and is a real resource-tradeoff decision, not
a pure bug fix.

### REQ-10: A circuit-breaker state for repeatedly-failing candidates (Planned, not yet implemented)

**Trigger:** N/A yet -- a gap identified from external research (§3), not
yet caused a real incident this session (the existing per-call retry +
tier-candidate fallback has been sufficient so far).
**Acceptance (proposed):** A model candidate that fails N consecutive
probes within a short window is skipped (without re-probing) for a cooldown
period, rather than being re-tried from scratch on every new dispatch.
**Status: Not implemented.** Lower priority than REQ-5/REQ-6/REQ-9 --
no incident has yet shown the current per-dispatch-fresh-probe behavior
causing real harm, only theoretical wasted probe time.

---

## 5. Non-goals

- Model capability/judgment improvements (e.g. "use a better model") --
  explicitly the opposite of this spec's finding. Any temptation to solve a
  future incident by escalating model tier should first be checked against
  this spec's REQ list; today's evidence is that the harness, not the
  model, was the failure point in every incident examined.
- A general-purpose agent framework rewrite. This project's existing
  dispatch architecture (`odysseus-agentic-dispatch-architecture.md`) is
  sound; this spec hardens its reliability properties, it does not propose
  replacing it.

---

## 6. AT tasks spawned by this spec

- **REQ-5 enforcement:** lint/validator for `../`-prefixed AT-row output
  paths targeting non-Electron-Splines repos.
- **REQ-6 implementation:** command-line-match process cleanup for
  terminal-state jobs, replacing/supplementing PID-tree kill.
- **REQ-9 implementation:** tune Ollama `keep_alive` for the local Tier-R/
  Tier-M candidates; requires an explicit resource-tradeoff decision
  (VRAM/RAM residency vs. cold-start frequency), not a unilateral default.
- **REQ-10 implementation:** circuit-breaker state for `resolve_model_for_tier`,
  only if a real incident demonstrates the current behavior causing harm
  (per this spec's own evidence-based-requirement bar) -- not pre-built
  speculatively.

## 7. Relationship to existing specs

- `ai-model-selection-policy.md` owns *which* model/tier is right for a
  task class. This spec owns whether the harness *actually delivers* that
  model reliably once chosen -- a Tier-R task correctly assigned a capable
  model still fails if the harness can't get a real run out of it, which is
  exactly what AT-1196/1197 demonstrated.
- `odysseus-agentic-dispatch-architecture.md` owns the dispatch
  architecture (worktrees, job state, the supervisor). This spec's REQ-6
  and REQ-5 are reliability properties of that architecture's
  implementation, not changes to the architecture itself.
- `autonomous-dispatch-risk-framework.md` owns which actions need
  architect approval. Nothing in this spec changes that -- every fix
  described here was a bug fix to existing, already-approved
  infrastructure, not a new capability requiring fresh risk review.
