#!/usr/bin/env python3
"""
Unit tests for scripts/orchestrator_status.py's classify(), which flags
orchestrator runs as STALE (status running, no recent activity) or HIGH-RT
(current step has taken an unusually large number of round trips) -- the
on-demand "is Cline stuck?" health check.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_orchestrator_status.py
"""

import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "orchestrator_status.py"))

_spec = importlib.util.spec_from_file_location("orchestrator_status", _MODULE_PATH)
orchestrator_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orchestrator_status)


class TestClassify(unittest.TestCase):
    def _base_state(self, **overrides) -> dict:
        state = {
            "status": "running",
            "current": 1,
            "steps": ["do thing one", "do thing two"],
            "step_request_count": 1,
            "last_activity": datetime.now(timezone.utc).isoformat(),
        }
        state.update(overrides)
        return state

    def test_recent_activity_low_round_trips_no_flags(self):
        state = self._base_state()

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertEqual(info["flags"], [])
        self.assertEqual(info["step_text"], "do thing one")
        self.assertEqual(info["total"], 2)

    def test_stale_when_no_activity_recorded(self):
        state = self._base_state(last_activity=None)

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertIn("STALE", info["flags"])
        self.assertIsNone(info["age_seconds"])

    def test_stale_when_last_activity_old(self):
        old = datetime.now(timezone.utc) - timedelta(seconds=orchestrator_status._STALE_AFTER_SECONDS + 60)
        state = self._base_state(last_activity=old.isoformat())

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertIn("STALE", info["flags"])
        self.assertGreater(info["age_seconds"], orchestrator_status._STALE_AFTER_SECONDS)

    def test_high_round_trip_flag(self):
        state = self._base_state(step_request_count=orchestrator_status._HIGH_ROUND_TRIP_THRESHOLD + 1)

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertIn("HIGH-RT", info["flags"])

    def test_non_running_status_never_flagged(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        state = self._base_state(
            status="complete",
            last_activity=old.isoformat(),
            step_request_count=orchestrator_status._HIGH_ROUND_TRIP_THRESHOLD + 1,
        )

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertEqual(info["flags"], [])

    def test_current_out_of_range_yields_empty_step_text(self):
        state = self._base_state(current=0)

        info = orchestrator_status.classify(state, datetime.now(timezone.utc))

        self.assertEqual(info["step_text"], "")


class TestHaltStaleRun(unittest.TestCase):
    def _base_state(self, **overrides) -> dict:
        state = {
            "status": "running",
            "current": 1,
            "steps": ["do thing one", "do thing two"],
            "step_request_count": 0,
            "last_activity": None,
            "log": [],
        }
        state.update(overrides)
        return state

    def test_stale_running_run_halted(self):
        state = self._base_state()
        now = datetime.now(timezone.utc)

        halted = orchestrator_status.halt_stale_run(state, now)

        self.assertTrue(halted)
        self.assertEqual(state["status"], "halted")
        self.assertTrue(any("abandoned" in entry["message"] for entry in state["log"]))

    def test_non_stale_run_not_halted(self):
        state = self._base_state(last_activity=datetime.now(timezone.utc).isoformat())
        now = datetime.now(timezone.utc)

        halted = orchestrator_status.halt_stale_run(state, now)

        self.assertFalse(halted)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["log"], [])

    def test_non_running_status_not_halted(self):
        state = self._base_state(status="halted")
        now = datetime.now(timezone.utc)

        halted = orchestrator_status.halt_stale_run(state, now)

        self.assertFalse(halted)
        self.assertEqual(state["log"], [])


if __name__ == "__main__":
    unittest.main()
