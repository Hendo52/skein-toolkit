# Spec: Context and Memory Management Reliability

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.15 (Context and memory management) |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | `agent-harness-reliability-standard.md` (SR-1.4), AT-1196's root-cause finding, external research (cited inline) |
| **Agent** | `docs` |
| **Model** | Tier-C |

---

## 1. Scope

Owns whether a model, once selected by SR-1.4's tier policy, is actually
given the context-window/memory configuration its own architecture
supports -- the gap between a model's *claimed* capability and its
*configured runtime* capability.

## 2. The headline finding this SR exists to prevent recurring

Every local model entry in `litellm_config.yaml` claimed a large context
window in its `description` field but never configured one via `num_ctx`.
Ollama's real runtime default without that override is as low as 2-4k
tokens regardless of the model's own architecture -- confirmed both
directly (today, end-to-end through the real LiteLLM endpoint) and via
external research: this is the single most-cited Cline+Ollama failure
mode in the community, described as turning Cline "from broken to
genuinely useful" once explicitly configured (Local AI Master, "Cline +
Ollama Setup 2026").

## 3. Requirements

### CTX-1 (= master spec REQ-1): Every model's configured runtime capability must match its advertised capability

Description text is not allowed to be aspirational -- if a model's
`model_info.description` claims a context window, `litellm_params` must
set the corresponding override. **Status: Implemented 2026-06-20** for all
8 local Ollama entries; verified end-to-end (not assumed) via a real
LiteLLM-routed request, confirmed via `ollama ps` that the model loaded at
the configured context.

### CTX-2 (= master spec REQ-8): Model candidate lists are reviewed against the inference backend's actual current contents

A model already pulled, configured, and documented in `litellm_config.yaml`
must not sit unwired from `TIER_MODEL_CANDIDATES` indefinitely -- that is
unused capacity the harness paid the download/disk cost for and never
benefits from. **Status: Implemented 2026-06-20** (`local/qwen3.6` found
pulled and described as "best local general model... tools" but never
wired; added to Tier-R).

### CTX-3 (= master spec REQ-9): Local-model keep-alive duration should be tuned to reduce cold-start frequency at the source

External research independently confirms two things found this session:
the health-check timeout must exceed cold-load time (already fixed, see
SR-1.16's GUARD-2), and separately, Ollama's default 5-minute keep_alive is
"too short if cold starts are scattered throughout the day" -- a 1-2 hour
keep_alive "would eliminate most of them" for a sporadic-use pattern like
this project's (production Ollama deployment guidance, 2026). **Status:
Implemented 2026-06-20** (AT-1250): all 8 local Ollama entries now set
`keep_alive: "2h"` via `extra_body`, with the tradeoff documented inline in
`litellm_config.yaml` -- the upper end of the recommended 1-2 h range, chosen
to keep models warm across typical dispatch session gaps without the
permanent RAM residency that `OLLAMA_KEEP_ALIVE=-1` would impose on this
machine's limited 8 GB VRAM / 64 GB RAM partial-offload hardware.

### CTX-4: Cross-step context carry-forward for multi-step orchestrated work must not silently narrow

**Status: Implemented, predates this spec** (CB-10b: per-step frames were
resetting findings between orchestrator steps; resolved 2026-06-11, OQ-263
Option A). Listed here because it is squarely this SR's territory --
context narrowing across turns is a memory-management failure, not a tool-
orchestration or guardrail one -- even though the fix predates this SR's
formal definition.

## 4. AT tasks spawned

- AT-1250 (CTX-3 implementation: keep_alive tuning, 2 h via extra_body in
  litellm_config.yaml, implemented 2026-06-20)

## 5. Relationship to other SRs

- SR-1.4 decides *which* model/tier a task needs; this SR ensures the
  chosen model actually gets the context budget its architecture supports
  once selected -- the two are sequential, not overlapping, decisions.
