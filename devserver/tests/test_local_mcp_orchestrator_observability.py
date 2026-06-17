#!/usr/bin/env python3
"""
Unit tests for the per-round-trip orchestrator activity tracking added to
scripts/local-mcp.py: _new_orchestrator_state's new step_request_count /
step_request_count_for / last_activity fields, and _record_step_activity,
which increments/resets that counter and emits a stderr heartbeat.

Restored 2026-06-14 after a Cline run looked "possibly stuck" at step 1/12
for ~9 minutes with only its initial dispatch logged -- _orchestrator_log
only fires on step transitions, so a long-but-progressing step and a stuck
one were indistinguishable without manually cross-referencing
cf_proxy_live.log access lines against the state file. _record_step_activity
gives every mid-step round trip a heartbeat and a persisted counter/timestamp
that scripts/orchestrator_status.py reads.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_orchestrator_observability.py
"""

import importlib.util
import os
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


def _stderr_log(fn, *args):
    with patch("sys.stderr") as mock_stderr:
        result = fn(*args)
    logged = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
    return result, logged


class TestNewOrchestratorStateFields(unittest.TestCase):
    def test_activity_fields_initialized(self):
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")

        self.assertEqual(state["step_request_count"], 0)
        self.assertIsNone(state["step_request_count_for"])
        self.assertIsNone(state["last_activity"])


class TestRecordStepActivity(unittest.TestCase):
    def _state(self, current: int) -> dict:
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")
        state["current"] = current
        return state

    def test_first_call_sets_count_to_one(self):
        state = self._state(current=1)
        tail = [{"role": "tool", "content": "ok"}]

        count, logged = _stderr_log(local_mcp._record_step_activity, state, tail)

        self.assertEqual(count, 1)
        self.assertEqual(state["step_request_count"], 1)
        self.assertEqual(state["step_request_count_for"], 1)
        self.assertIsNotNone(state["last_activity"])
        self.assertIn("heartbeat: step 1/2 round-trip #1", logged)

    def test_consecutive_calls_on_same_step_increment(self):
        state = self._state(current=1)
        tail = [{"role": "tool", "content": "ok"}]

        local_mcp._record_step_activity(state, tail)
        count, logged = _stderr_log(local_mcp._record_step_activity, state, tail)

        self.assertEqual(count, 2)
        self.assertEqual(state["step_request_count"], 2)
        self.assertIn("round-trip #2", logged)

    def test_advancing_step_resets_counter(self):
        state = self._state(current=1)
        tail = [{"role": "tool", "content": "ok"}]
        local_mcp._record_step_activity(state, tail)
        local_mcp._record_step_activity(state, tail)
        self.assertEqual(state["step_request_count"], 2)

        state["current"] = 2
        count, logged = _stderr_log(local_mcp._record_step_activity, state, tail)

        self.assertEqual(count, 1)
        self.assertEqual(state["step_request_count"], 1)
        self.assertEqual(state["step_request_count_for"], 2)
        self.assertIn("heartbeat: step 2/2 round-trip #1", logged)

    def test_heartbeat_includes_turn_fingerprint(self):
        state = self._state(current=1)
        tail = [{"role": "tool", "content": "distinctive tool result text"}]

        _, logged = _stderr_log(local_mcp._record_step_activity, state, tail)

        self.assertIn("distinctive tool result text", logged)

    def test_does_not_append_to_log(self):
        state = self._state(current=1)
        tail = [{"role": "tool", "content": "ok"}]

        local_mcp._record_step_activity(state, tail)

        self.assertEqual(state["log"], [])


if __name__ == "__main__":
    unittest.main()
