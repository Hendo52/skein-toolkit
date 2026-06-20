#!/usr/bin/env python3
"""
supervisor_degraded_mode.py -- AT-1233's remaining piece, per OQ-294
(resolved Option B): when the full-capability Tier-2 supervisor (Claude)
itself is unavailable (credit exhausted, rate-limited, or simply no live
session woke on schedule), hand off to a cheaper model with a narrowed
action set -- retry + raise_oq only. restart_dependency and revert stay
reserved for the full-capability supervisor (OQ-294's explicit boundary):
restarting a dependency or discarding a job's work both require judgment
about whether the action is actually safe, which a weak model should not
be trusted to make alone.

Detection of "Claude is unavailable" cannot rely on Claude's own
introspection -- if Claude truly cannot run, nothing running AS Claude can
notice that. Instead: the full supervisor records a heartbeat every time it
completes a wake cycle (record_heartbeat()). A separate, Claude-independent
entry point (this module, invokable as a standalone script from a
Scheduled Task/cron, mirroring cline_completion_watcher.py's own pattern)
checks whether that heartbeat has gone stale -- if so, Claude has not been
waking on schedule for some external reason, and this module's degraded
triage takes over for that cycle.

Per the First-Class Scenarios policy: this is a named, observable
alternative mode, not a silent fallback. Every activation's recommendation
is tagged "Tier-2-degraded" and states the heartbeat-staleness reason that
triggered it.
"""

import asyncio
import json
import os
import sys
import time

import supervisor_triage

DEFAULT_STATUS_PATH = os.path.join(
    os.path.expanduser("~"), ".cf_proxy_orchestrator", "supervision-status.json"
)
DEFAULT_CODING_TASK_STATE_DIR = os.environ.get(
    "CODING_TASK_STATE_DIR", os.path.join(os.path.expanduser("~"), ".coding_task_dispatch")
)

DEFAULT_HEARTBEAT_PATH = os.path.join(os.path.expanduser("~"), ".supervisor_heartbeat.json")

# The full supervisor's own wake interval is whatever ScheduleWakeup/
# CronCreate is configured with -- this threshold must be generously
# larger than that interval, or a single slow-but-fine wake cycle would
# misfire degraded mode while the full supervisor is still genuinely
# active. 3 hours is well beyond any wake interval used this session
# (minutes-to-an-hour range), so a real silence, not just a slow cycle,
# is what trips this.
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 3 * 3600

DEGRADED_MODE_LABEL = "Tier-2-degraded"


def record_heartbeat(heartbeat_path: str = DEFAULT_HEARTBEAT_PATH) -> None:
    """Called by the full-capability supervisor (Claude) at the end of every
    wake cycle that successfully read supervision-status.json -- whether or
    not there was anything to act on. Absence of a recent heartbeat is what
    this module treats as "Claude is unavailable," so a wake cycle that
    crashes before reaching this call correctly leaves the heartbeat stale."""
    tmp_path = heartbeat_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_heartbeat_unix": time.time()}, f)
    os.replace(tmp_path, heartbeat_path)


def seconds_since_heartbeat(heartbeat_path: str = DEFAULT_HEARTBEAT_PATH) -> "float | None":
    """None means no heartbeat has ever been recorded -- treated the same as
    "very stale" by is_full_supervisor_silent, not as "assume healthy"."""
    try:
        with open(heartbeat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    last = data.get("last_heartbeat_unix")
    if last is None:
        return None
    return time.time() - last


def is_full_supervisor_silent(
    heartbeat_path: str = DEFAULT_HEARTBEAT_PATH,
    max_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> "tuple[bool, str]":
    """Returns (silent, reason). silent=True means this module's degraded
    triage should activate for this cycle."""
    age = seconds_since_heartbeat(heartbeat_path)
    if age is None:
        return True, "no full-supervisor heartbeat has ever been recorded"
    if age > max_age_seconds:
        return True, f"last full-supervisor heartbeat was {age:.0f}s ago (threshold {max_age_seconds:.0f}s)"
    return False, f"full-supervisor heartbeat is recent ({age:.0f}s ago)"


def job_log_tail(state_dir: str, job_id: str, max_chars: int = 4000) -> str:
    """Reads the last max_chars of a coding-task job's own log file
    ({state_dir}/{job_id}.log, the same path local-mcp.py's
    dispatch_coding_task writes to) -- the same kind of text
    recommend_action was designed and tested against. Returns "" (not an
    exception) if the file doesn't exist -- recommend_action already
    treats an empty log tail as "raise_oq, nothing to classify," which is
    the correct conservative behavior here too."""
    log_path = os.path.join(state_dir, f"{job_id}.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_chars))
            return f.read()
    except OSError:
        return ""


def recommend_action_degraded(log_tail: str) -> "tuple[str, str]":
    """Wraps supervisor_triage.recommend_action with OQ-294's narrowed
    action set: only "retry" and "raise_oq" come out of this function. A
    full-mode "restart_dependency" recommendation is downgraded to
    "raise_oq" here, not silently turned into a retry -- restarting a
    dependency (or reverting a job's work, which recommend_action itself
    never auto-recommends) requires judgment about whether the action is
    actually safe, which OQ-294 reserves for the full-capability
    supervisor."""
    action, reasoning = supervisor_triage.recommend_action(log_tail)
    if action == "restart_dependency":
        return "raise_oq", (
            f"{DEGRADED_MODE_LABEL}: full-mode triage would recommend restart_dependency "
            f"({reasoning}), but degraded mode is restricted to retry/raise_oq -- escalating "
            f"instead of auto-restarting a dependency without the full-capability supervisor's judgment"
        )
    return action, reasoning


async def run_degraded_supervision_cycle(
    status_path: str,
    state_dir: str,
    master_key: str,
    base_url: "str | None" = None,
    heartbeat_path: str = DEFAULT_HEARTBEAT_PATH,
    max_heartbeat_age_seconds: float = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
    dispatch_tier: str = "Tier-C",
) -> dict:
    """The standalone, Claude-Code-independent entry point -- invokable from
    a Scheduled Task the same way cline_completion_watcher.py is, with no
    live Claude Code session required. Only acts if the full supervisor's
    heartbeat has gone stale (is_full_supervisor_silent); otherwise returns
    immediately with activated=False so a healthy full supervisor is never
    second-guessed or duplicated.

    For each stuck coding-task job: recommend_action_degraded() decides
    retry/raise_oq. A "retry" recommendation additionally resolves which
    model the retry dispatch should actually use via
    dispatch_io.resolve_model_for_tier's existing fallback-ladder (the
    "hand off to a cheaper model" OQ-294 describes) -- this module never
    assumes the job's original model is still usable; if Claude itself is
    unavailable, an architect-tier model may be unavailable for the same
    underlying reason (e.g. account-wide credit exhaustion isn't specific
    to one model)."""
    import dispatch_io

    silent, reason = is_full_supervisor_silent(heartbeat_path, max_heartbeat_age_seconds)
    if not silent:
        return {"activated": False, "reason": reason, "recommendations": []}

    if base_url is None:
        base_url = dispatch_io.DEFAULT_LITELLM_BASE_URL

    try:
        with open(status_path, "r", encoding="utf-8") as f:
            status = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return {
            "activated": True,
            "reason": reason,
            "recommendations": [],
            "error": f"{DEGRADED_MODE_LABEL}: could not read {status_path} -- {exc}",
        }

    recommendations = []
    for job in status.get("codingTaskJobs", []):
        if not job.get("stuck"):
            continue
        job_id = job.get("jobId")
        log_tail = job_log_tail(state_dir, job_id)
        action, triage_reasoning = recommend_action_degraded(log_tail)

        entry = {
            "mode": DEGRADED_MODE_LABEL,
            "job_id": job_id,
            "at_id": job.get("atId"),
            "action": action,
            "reasoning": (
                f"{DEGRADED_MODE_LABEL}: weak-model active because Claude unavailable "
                f"({reason}) -- {triage_reasoning}"
            ),
        }
        if action == "retry":
            model, attempted = await dispatch_io.resolve_model_for_tier(dispatch_tier, master_key, base_url)
            entry["resolved_retry_model"] = model
            entry["models_attempted"] = attempted
            if model is None:
                entry["action"] = "raise_oq"
                entry["reasoning"] += (
                    f" -- but no {dispatch_tier} candidate model is currently reachable either "
                    f"({attempted}), escalating instead of retrying with nothing to retry with"
                )
        recommendations.append(entry)

    return {"activated": True, "reason": reason, "recommendations": recommendations}


def _main() -> int:
    """Standalone CLI entry point -- invokable from a Scheduled Task with no
    live Claude Code session, the same way cline_completion_watcher.py is.
    Prints a JSON result to stdout (--json) or a human-readable summary by
    default; exits 0 in all non-crash cases (a "nothing to do" result is not
    an error)."""
    import dispatch_io

    master_key = dispatch_io.load_litellm_master_key(os.path.dirname(os.path.abspath(__file__)))
    result = asyncio.run(run_degraded_supervision_cycle(
        status_path=DEFAULT_STATUS_PATH,
        state_dir=DEFAULT_CODING_TASK_STATE_DIR,
        master_key=master_key,
    ))

    if "--json" in sys.argv:
        print(json.dumps(result))
        return 0

    if not result["activated"]:
        print(f"[supervisor-degraded-mode] not activated -- {result['reason']}")
        return 0
    if "error" in result:
        print(f"[supervisor-degraded-mode] ACTIVATED but could not read status -- {result['error']}")
        return 0
    if not result["recommendations"]:
        print(f"[supervisor-degraded-mode] ACTIVATED ({result['reason']}) -- no stuck jobs found")
        return 0
    print(f"[supervisor-degraded-mode] ACTIVATED ({result['reason']})")
    for entry in result["recommendations"]:
        print(f"  job {entry['job_id']} (AT-{entry['at_id']}): {entry['action']} -- {entry['reasoning']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
