#!/usr/bin/env python3
"""
On-demand health check for CF proxy orchestrator runs (scripts/local-mcp.py).

Scans ~/.cf_proxy_orchestrator/*.json and reports every run with
status == "running": current step, round trips taken on that step, and how
long since the run last saw any activity (state["last_activity"], written by
_record_step_activity in local-mcp.py).

This exists so "is Cline stuck or just doing a lot of processing?" has a
direct answer instead of manually cross-referencing cf_proxy_live.log access
lines, ~/.cf_proxy_metrics.json counters, and orchestrator state files by
hand:

- STALE: status is "running" but no request has been seen for this run in
  over _STALE_AFTER_SECONDS. The round-trip loop has gone idle -- Cline may
  have finished/been cancelled without the run reaching a step transition, or
  it's genuinely stopped.
- HIGH-RT: the current step has taken more than _HIGH_ROUND_TRIP_THRESHOLD
  round trips. Cline may be repeating itself (re-reading the same files,
  retrying) rather than progressing through the step.
- Neither flag + recent last_activity: the run is actively progressing --
  "genuinely doing a lot of processing", not stuck.

Run with: .venv\\Scripts\\python.exe scripts\\orchestrator_status.py

Add --apply to auto-halt every STALE "running" run found (one-time sweep for
runs left behind before the in-server auto-halt in local-mcp.py existed, or
for runs whose orchestrator key never recurs to trigger that check):
    .venv\\Scripts\\python.exe scripts\\orchestrator_status.py --apply
"""

import asyncio
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

_ORCHESTRATOR_STATE_DIR = os.path.join(os.path.expanduser("~"), ".cf_proxy_orchestrator")

_STALE_AFTER_SECONDS = 5 * 60
_HIGH_ROUND_TRIP_THRESHOLD = 15


def _load_local_mcp():
    """Load scripts/local-mcp.py so --apply reuses its state/metrics helpers
    instead of re-implementing the on-disk formats."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(this_dir, "local-mcp.py")
    spec = importlib.util.spec_from_file_location("local_mcp", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def halt_stale_run(state: dict, now: datetime, reason_suffix: str = "") -> bool:
    """Mutate a STALE 'running' state to 'halted' in place, matching the
    wording of local-mcp.py's in-server auto-halt. Returns True if halted."""
    info = classify(state, now)
    if state.get("status") != "running" or "STALE" not in info["flags"]:
        return False

    age = info["age_seconds"]
    age_desc = f"no activity for {age / 60:.0f}m" if age is not None else "no activity recorded"
    message = (
        f"run abandoned -- {age_desc} while status='running' "
        f"(last activity {state.get('last_activity')!r}); auto-halting rather than "
        f"resuming step {info['current']}/{info['total']} against a stale snapshot/working tree"
        f"{reason_suffix}"
    )
    state.setdefault("log", []).append({"ts": now.isoformat(), "message": message})
    state["status"] = "halted"
    return True


def classify(state: dict, now: datetime) -> dict:
    """Pure classification of one orchestrator state dict, given the current
    time. Kept separate from file I/O so it can be unit-tested directly."""
    last_activity_raw = state.get("last_activity")
    last_activity = datetime.fromisoformat(last_activity_raw) if last_activity_raw else None
    age_seconds = (now - last_activity).total_seconds() if last_activity else None

    steps = state.get("steps") or []
    current = state.get("current", 0)
    step_text = steps[current - 1] if 1 <= current <= len(steps) else ""

    flags = []
    if state.get("status") == "running":
        if age_seconds is None or age_seconds > _STALE_AFTER_SECONDS:
            flags.append("STALE")
        if state.get("step_request_count", 0) > _HIGH_ROUND_TRIP_THRESHOLD:
            flags.append("HIGH-RT")

    return {
        "status": state.get("status"),
        "current": current,
        "total": len(steps),
        "step_text": step_text,
        "round_trips": state.get("step_request_count", 0),
        "age_seconds": age_seconds,
        "flags": flags,
    }


def main() -> int:
    apply_halt = "--apply" in sys.argv[1:]

    if not os.path.isdir(_ORCHESTRATOR_STATE_DIR):
        print("No orchestrator state directory found -- nothing has run yet.")
        return 0

    local_mcp = _load_local_mcp() if apply_halt else None
    now = datetime.now(timezone.utc)
    rows = []
    halted_keys = []
    for name in sorted(os.listdir(_ORCHESTRATOR_STATE_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(_ORCHESTRATOR_STATE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as exc:
            print(f"{name}: failed to read ({exc})", file=sys.stderr)
            continue
        if state.get("status") != "running":
            continue
        info = classify(state, now)
        info["key"] = name[:-len(".json")]

        if apply_halt and "STALE" in info["flags"]:
            halt_stale_run(state, now, reason_suffix=" (one-time sweep via orchestrator_status.py --apply)")
            local_mcp._save_orchestrator_state(info["key"], state)
            asyncio.run(local_mcp._record_metric("orchestrator_run_halted"))
            asyncio.run(local_mcp._record_metric("orchestrator_run_auto_halted_stale"))
            halted_keys.append(info["key"])
            continue

        rows.append(info)

    if halted_keys:
        print(f"Halted {len(halted_keys)} stale 'running' run(s): {', '.join(halted_keys)}")

    if not rows:
        print("No orchestrator runs are currently 'running'.")
        return 0

    for info in rows:
        age = f"{info['age_seconds']:.0f}s ago" if info["age_seconds"] is not None else "never"
        flags = f" [{', '.join(info['flags'])}]" if info["flags"] else ""
        print(
            f"{info['key']}: step {info['current']}/{info['total']} "
            f"({info['round_trips']} round trip(s), last activity {age}){flags}"
        )
        print(f"    {info['step_text']!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
