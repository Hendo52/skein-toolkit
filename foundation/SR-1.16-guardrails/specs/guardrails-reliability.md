# Spec: Resilience Guardrails Reliability

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.16 (Guardrails) |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | `agent-harness-reliability-standard.md` (SR-1.4), CB-23/CB-16, AT-1196/1197 incidents, external research (cited inline) |
| **Agent** | `docs` |
| **Model** | Tier-C |

---

## 1. Scope

Owns retry/backoff policy for transient upstream failures, health/probe
timeout calibration, and candidate-fallback-chain resilience state. Explicitly
**not** `autonomous-dispatch-risk-framework.md`'s territory (SR-1.4) -- that
framework decides which *actions* need human approval before proceeding
(force-push, branch deletion, cloud spend); this SR decides how a
*retry/backoff/timeout* is handled once an action is already approved and
in flight.

## 2. Confirmed-good existing practice, with one externally-flagged gap

This project's retry design (CB-23, extended today to GUARD-1) already
implements two of circuit-breaker literature's core recommendations:
exponential backoff, and differentiating transient (429/500) from
permanent (401/403) failure codes -- "a 429 is different from a 500 is
different from a 401; rate limits often clear within seconds" (Portkey,
"Retries, fallbacks, and circuit breakers in LLM apps"). The gap that same
research flags and we don't yet have: a **circuit-breaker state** distinct
from per-call retry -- skip a repeatedly-failing candidate for a cooldown
window instead of re-probing it fresh on every new dispatch -- and
**jitter** on backoff delays to avoid retry storms (lower priority here:
this is a single-user, single-machine setup, not a high-concurrency
service, so the thundering-herd risk jitter defends against is much
smaller than in the literature's typical context).

## 3. Requirements

### GUARD-1 (= master spec REQ-3): New transient-failure signatures must be added to every consumer of the pattern, in the same change

A new transient (retryable) failure signature discovered from any upstream
must be added to the proxy-level retry logic AND the supervisor's triage
pattern-matcher in the same commit. **Status: Implemented 2026-06-20** for
CF 500 (both consumers updated together). The prior 429 fix (CB-23) only
updated the proxy at the time; the supervisor's pattern was added in a
separate, later change -- this requirement exists specifically because
that gap was real and is the kind of gap that recurs if not named.

### GUARD-2 (= master spec REQ-2): Health/probe timeouts must account for cold-start cost, not just response latency

Local (self-hosted, cold-loadable) candidates need a timeout budget sized
for the slowest realistic cold load on the actual hardware; cloud
candidates keep a short budget and still fail fast on genuine outages.
**Status: Implemented 2026-06-20** (`_LOCAL_PROBE_TIMEOUT_SECONDS = 90.0`
vs. `_PROBE_TIMEOUT_SECONDS = 15.0`) -- independently corroborated by
production Ollama deployment guidance: "the health check's start_period
must be long enough for the model to load; setting it too short can cause
[repeated, spurious] restarts."

### GUARD-3 (= master spec REQ-10): A circuit-breaker state for repeatedly-failing candidates (Planned)

A model candidate that fails N consecutive probes within a short window
should be skipped (without re-probing) for a cooldown period, rather than
being re-tried from scratch on every new dispatch. **Status: Not
implemented.** No incident has yet shown the current per-dispatch-fresh-
probe behavior causing real harm (only theoretical wasted probe time) --
lower priority than GUARD-1/GUARD-2, which were both incident-driven.

### GUARD-4: Backoff jitter (Planned, low priority)

Add a small random jitter to retry backoff delays to avoid synchronized
retry storms. **Status: Not implemented; explicitly low priority** -- this
project's actual usage pattern (single machine, rarely more than 1-2
concurrent dispatches even after today's parallel-dispatch relaxation) has
a much smaller thundering-herd risk than the literature's typical
high-concurrency-service context this recommendation comes from. Worth
revisiting if parallel dispatch volume grows meaningfully.

## 4. AT tasks spawned

- GUARD-3 and GUARD-4: not spawned as ATs yet -- per this project's own
  evidence-based-requirement bar (a requirement needs a trigger, not just
  a research citation), these wait for either a real incident or a
  deliberate architect decision to build ahead of one.

## 5. Relationship to other SRs

- `autonomous-dispatch-risk-framework.md` (SR-1.4) gates *whether* an
  action proceeds; this SR governs *how robustly* it proceeds once gated
  through.
- SR-1.13 (Tool orchestration) owns the process mechanics being retried;
  this SR owns the policy of *when* to retry them.
