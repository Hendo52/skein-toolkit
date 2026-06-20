# Spec: Harness Observability Reliability

| Field | Value |
|-------|-------|
| **SR Owner** | SR-1.17 (Harness observability) |
| **Status** | Draft |
| **Date** | 2026-06-20 |
| **Source** | `agent-harness-reliability-standard.md` (SR-1.4), CB-15, `toolchain-doctor.ps1`'s existing design, external research (cited inline) |
| **Agent** | `docs` |
| **Model** | Tier-C |

---

## 1. Scope

Owns whether a human or supervisor agent can tell what a dispatched job
actually did, and whether the toolchain itself is healthy, without reading
raw subprocess output by hand. This is the layer that made every other
layer's findings in this session *findable* -- every incident in
`agent-harness-reliability-standard.md` was diagnosed by reading a job
state file or a `toolchain-doctor.ps1` report, not by guessing.

## 2. Confirmed-good existing practice, sized appropriately for this project's scale

External research on production AI-agent observability emphasizes
structured, stable-schema records over free-form logs, correlation IDs,
and (at the high end) OpenTelemetry-standard trace formats and
cryptographic audit signatures (Coralogix, "Agentic AI Observability";
DigitalApplied, "Agent Audit Trail Design"). Most of that is correctly
out of scope for a single-developer, single-machine toolchain -- but the
core principle this project already follows is the right-sized version of
it: job-state files (`dispatch_io.write_job_state`) are a stable,
structured schema (job_id, at_id, repo_root, worktree_path, branch_name,
pid, status, log_path, timestamps), not free text, and `job_id` itself
(`at{id}-{hex}`) functions as the correlation ID tying a dispatch to its
worktree, branch, and log file. `toolchain-doctor.ps1`'s CB-15 fix
(startup commit-SHA logging + a `/health` endpoint) is this project's
version of a staleness/drift health check, independently matching the
"automated recovery actions" pattern production Ollama health-check
guidance recommends.

## 3. The one real gap: raw job logs are unstructured terminal capture, not structured spans

Every diagnosis this session (the qwen2.5-coder:7b hallucination, the CF
500, the orphaned-process pattern) required a human (this session, an
agent acting as the human's delegate) to read a raw, ANSI-colored terminal
transcript and recognize a pattern by eye. Production observability
guidance's "layered trace architecture" (agent/LLM layer, framework/
orchestrator layer, as separate structured spans) would make this
queryable instead of eyeballed -- but building that requires intercepting
and re-structuring Cline's own terminal output, a real implementation cost
this spec does not propose taking on speculatively.

## 4. Requirements

### OBS-1: Job state must remain a structured, stable schema -- not free text

**Status: Implemented, predates this spec.** Formalized here as a standing
property: any new field added to job state must extend the existing
schema, not introduce a parallel free-text convention.

### OBS-2: A health-check mechanism must detect stale/drifted long-running processes, not just up/down

**Status: Implemented, predates this spec** (CB-15: `local-mcp.py`'s
startup-SHA logging + `/health` endpoint, extended by `toolchain-doctor.ps1`'s
staleness checks). Today's session relied on this repeatedly (e.g. catching
`local-mcp.py` serving stale code after an edit) -- formalized as a
standing requirement so future long-running processes added to this
toolchain get the same treatment by default, not as an afterthought.

### OBS-3: Structured per-step/per-tool-call tracing (Planned, explicitly deferred)

**Status: Not implemented, and not currently recommended.** Named here so
the gap is acknowledged rather than silently absent, but per this spec's
own evidence-based-requirement bar, no incident this session was actually
*blocked* by the lack of structured tracing -- every incident was diagnosed
successfully via the existing raw-log-plus-job-state combination, just with
more manual reading than a structured trace would need. Revisit if a
future incident genuinely cannot be diagnosed without it.

## 5. AT tasks spawned

None -- OBS-1 and OBS-2 are already-met requirements (formalized, not
built); OBS-3 is explicitly deferred pending an actual triggering incident.

## 6. Relationship to other SRs

- Every other SR (1.13-1.16)'s incidents in this session were *found*
  via this SR's existing mechanisms (job-state files, toolchain-doctor.ps1).
  This SR is the precondition for the others' findings being discoverable
  at all, not a peer concern competing for the same incidents.
