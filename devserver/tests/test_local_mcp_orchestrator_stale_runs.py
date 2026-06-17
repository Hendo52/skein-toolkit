#!/usr/bin/env python3
"""
Unit tests for the stale-run auto-halt added to
_handle_orchestrated_request in scripts/local-mcp.py.

Found 2026-06-14: a Cline session that ends (cancelled, crashed, or just
stops) while an orchestrator run is status=="running" leaves that run
"running" forever with no expiry. If the SAME orchestrator key is ever
triggered again (the same first user message recurs -- e.g. a Cline session
that continues after a long gap), _handle_orchestrated_request would try to
resume the run via the mid-step continuation branch against a
snapshot_before_step taken from a working tree / HEAD that may no longer
match reality. All 10 of that day's "running" states were still current=1
with no progress logged, confirming this can persist indefinitely.

A "running" run with no activity for over _ORCHESTRATOR_STALE_AFTER_SECONDS
is now treated as abandoned: auto-halted and the request passed through
untouched, rather than resumed.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_orchestrator_stale_runs.py
"""

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

_TRIGGER_TEXT = "Please do A, then B, then C, then D, then E."


class _OrchestratorStateDirCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._metrics_file = os.path.join(self._tmpdir.name, "metrics.json")
        self._state_patch = patch.object(local_mcp, "_ORCHESTRATOR_STATE_DIR", self._tmpdir.name)
        self._metrics_patch = patch.object(local_mcp, "_METRICS_FILE", self._metrics_file)
        self._state_patch.start()
        self._metrics_patch.start()

    def tearDown(self):
        self._state_patch.stop()
        self._metrics_patch.stop()
        self._tmpdir.cleanup()

    def _write_state(self, state: dict) -> str:
        key = local_mcp._orchestrator_key(_TRIGGER_TEXT)
        path = local_mcp._orchestrator_state_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        return key

    def _load_state(self, key: str) -> dict:
        with open(local_mcp._orchestrator_state_path(key), "r", encoding="utf-8") as f:
            return json.load(f)


class TestStaleRunningRunAutoHalted(_OrchestratorStateDirCase):
    def test_old_last_activity_auto_halts_and_passes_through(self):
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        state.update(current=1, status="running", anchor_index=0, last_activity=old, updated=old)
        key = self._write_state(state)

        body = {"messages": [{"role": "user", "content": _TRIGGER_TEXT}]}
        result = asyncio.run(local_mcp._handle_orchestrated_request("https://cf", "Bearer x", body, False, "model"))

        self.assertIsNone(result)
        saved = self._load_state(key)
        self.assertEqual(saved["status"], "halted")
        self.assertTrue(any("abandoned" in entry["message"] for entry in saved["log"]))

    def test_old_updated_with_no_last_activity_auto_halts(self):
        """Pre-instrumentation states have no last_activity at all -- fall
        back to `updated` (set on every _save_orchestrator_state)."""
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")
        old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        state.update(current=1, status="running", anchor_index=0, last_activity=None, updated=old)
        key = self._write_state(state)

        body = {"messages": [{"role": "user", "content": _TRIGGER_TEXT}]}
        result = asyncio.run(local_mcp._handle_orchestrated_request("https://cf", "Bearer x", body, False, "model"))

        self.assertIsNone(result)
        self.assertEqual(self._load_state(key)["status"], "halted")


class TestRecentActivityRunIsResumedNormally(_OrchestratorStateDirCase):
    def test_recent_last_activity_proceeds_to_dispatch(self):
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")
        recent = datetime.now(timezone.utc).isoformat()
        state.update(current=1, status="running", anchor_index=0, last_activity=recent, updated=recent)
        key = self._write_state(state)

        body = {"messages": [{"role": "user", "content": _TRIGGER_TEXT}]}
        with patch.object(local_mcp, "_dispatch_step", new_callable=AsyncMock) as mock_dispatch:
            mock_dispatch.return_value = "dispatched"
            result = asyncio.run(local_mcp._handle_orchestrated_request("https://cf", "Bearer x", body, False, "model"))

        self.assertEqual(result, "dispatched")
        mock_dispatch.assert_awaited_once()
        self.assertEqual(self._load_state(key)["status"], "running")


class TestPausedForOqRunIsNeverStaleHalted(_OrchestratorStateDirCase):
    def test_old_paused_for_oq_run_not_auto_halted(self):
        """paused_for_oq is an intentional pause awaiting the architect and
        can legitimately sit for hours/days -- the staleness check only
        applies to status=="running"."""
        state = local_mcp._new_orchestrator_state(["step one", "step two"], "reason")
        old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        state.update(current=1, status="paused_for_oq", anchor_index=0, last_activity=old, updated=old)
        key = self._write_state(state)

        # A long, off-script reply (not a short continue/halt gate reply) at
        # the pause: ends automation via the existing paused_for_oq branch,
        # not the new staleness check.
        body = {"messages": [
            {"role": "user", "content": _TRIGGER_TEXT},
            {"role": "user", "content": "A completely different, much longer follow-up message that is not a short gate reply at all."},
        ]}
        result = asyncio.run(local_mcp._handle_orchestrated_request("https://cf", "Bearer x", body, False, "model"))

        self.assertIsNone(result)
        saved = self._load_state(key)
        self.assertEqual(saved["status"], "halted")
        self.assertFalse(any("abandoned" in entry["message"] for entry in saved["log"]))


if __name__ == "__main__":
    unittest.main()
