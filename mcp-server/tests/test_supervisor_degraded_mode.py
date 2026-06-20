#!/usr/bin/env python3
"""
Unit tests for supervisor_degraded_mode.py (AT-1233's remaining piece,
OQ-294). Run with:
.venv\\Scripts\\python.exe mcp-server\\tests\\test_supervisor_degraded_mode.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MCP_DIR = os.path.normpath(os.path.join(_THIS_DIR, ".."))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)


def _load(name):
    # Registers in sys.modules (not just returned) -- supervisor_degraded_mode.py
    # does a plain `import dispatch_io` inside run_degraded_supervision_cycle;
    # without this, that lazy import would resolve to a SEPARATE module
    # object than the one this test patches, and unittest.mock.patch.object
    # calls here would silently have no effect on the code under test.
    path = os.path.join(_MCP_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


supervisor_triage_module = _load("supervisor_triage")
dispatch_io = _load("dispatch_io")
degraded = _load("supervisor_degraded_mode")


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.heartbeat_path = os.path.join(self.tmpdir, "heartbeat.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_heartbeat_ever_recorded_is_silent(self):
        silent, reason = degraded.is_full_supervisor_silent(self.heartbeat_path, max_age_seconds=3600)
        self.assertTrue(silent)
        self.assertIn("ever been recorded", reason)

    def test_fresh_heartbeat_is_not_silent(self):
        degraded.record_heartbeat(self.heartbeat_path)
        silent, reason = degraded.is_full_supervisor_silent(self.heartbeat_path, max_age_seconds=3600)
        self.assertFalse(silent)
        self.assertIn("recent", reason)

    def test_stale_heartbeat_is_silent(self):
        with open(self.heartbeat_path, "w", encoding="utf-8") as f:
            json.dump({"last_heartbeat_unix": 0}, f)  # 1970 -- maximally stale
        silent, reason = degraded.is_full_supervisor_silent(self.heartbeat_path, max_age_seconds=3600)
        self.assertTrue(silent)
        self.assertIn("threshold", reason)

    def test_corrupt_heartbeat_file_treated_as_never_recorded(self):
        with open(self.heartbeat_path, "w", encoding="utf-8") as f:
            f.write("not json{{{")
        self.assertIsNone(degraded.seconds_since_heartbeat(self.heartbeat_path))
        silent, _ = degraded.is_full_supervisor_silent(self.heartbeat_path, max_age_seconds=3600)
        self.assertTrue(silent)

    def test_heartbeat_write_is_atomic_no_tmp_file_left_behind(self):
        degraded.record_heartbeat(self.heartbeat_path)
        self.assertTrue(os.path.isfile(self.heartbeat_path))
        self.assertFalse(os.path.isfile(self.heartbeat_path + ".tmp"))


class TestJobLogTail(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_log_file_returns_empty_string_not_exception(self):
        self.assertEqual(degraded.job_log_tail(self.tmpdir, "no-such-job"), "")

    def test_reads_real_log_content(self):
        with open(os.path.join(self.tmpdir, "job1.log"), "w", encoding="utf-8") as f:
            f.write("PROBLEM: LiteLLM is not responding on http://127.0.0.1:4000.")
        tail = degraded.job_log_tail(self.tmpdir, "job1")
        self.assertIn("LiteLLM is not responding", tail)

    def test_truncates_to_max_chars_from_the_end(self):
        with open(os.path.join(self.tmpdir, "job2.log"), "w", encoding="utf-8") as f:
            f.write("x" * 10000 + "REAL FAILURE SIGNATURE AT THE END")
        tail = degraded.job_log_tail(self.tmpdir, "job2", max_chars=50)
        self.assertIn("REAL FAILURE SIGNATURE AT THE END", tail)
        self.assertLessEqual(len(tail), 50)


class TestRecommendActionDegraded(unittest.TestCase):
    def test_retry_signature_passes_through_unchanged(self):
        log = "Your credit balance is too low to access the Anthropic API."
        action, reasoning = degraded.recommend_action_degraded(log)
        self.assertEqual(action, "retry")
        self.assertNotIn("downgrad", reasoning.lower())  # not downgraded -- nothing to downgrade

    def test_restart_dependency_signature_is_downgraded_to_raise_oq(self):
        # OQ-294's explicit boundary: degraded mode must never authorize a
        # dependency restart -- only the full-capability supervisor may.
        log = "PROBLEM: LiteLLM is not responding on http://127.0.0.1:4000."
        action, reasoning = degraded.recommend_action_degraded(log)
        self.assertEqual(action, "raise_oq")
        self.assertIn("restart_dependency", reasoning)
        self.assertIn("Tier-2-degraded", reasoning)

    def test_unrecognized_failure_is_raise_oq(self):
        action, _ = degraded.recommend_action_degraded("some totally novel failure text")
        self.assertEqual(action, "raise_oq")

    def test_never_returns_restart_dependency_or_revert(self):
        sample_logs = [
            "", "429", "LiteLLM is not responding", "running scripts is disabled on this system",
            "credit balance too low", "some completely novel error",
        ]
        for log in sample_logs:
            action, _ = degraded.recommend_action_degraded(log)
            self.assertIn(action, ("retry", "raise_oq"), f"degraded mode returned disallowed action {action!r} for {log!r}")


class TestRunDegradedSupervisionCycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.status_path = os.path.join(self.tmpdir, "supervision-status.json")
        self.state_dir = os.path.join(self.tmpdir, "state")
        os.makedirs(self.state_dir)
        self.heartbeat_path = os.path.join(self.tmpdir, "heartbeat.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_status(self, jobs):
        with open(self.status_path, "w", encoding="utf-8") as f:
            json.dump({"codingTaskJobs": jobs}, f)

    def test_does_not_activate_when_full_supervisor_heartbeat_is_fresh(self):
        degraded.record_heartbeat(self.heartbeat_path)
        self._write_status([{"jobId": "job1", "atId": 1234, "stuck": True}])
        result = asyncio.run(degraded.run_degraded_supervision_cycle(
            self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
        ))
        self.assertFalse(result["activated"])
        self.assertEqual(result["recommendations"], [])

    def test_activates_and_skips_non_stuck_jobs(self):
        self._write_status([{"jobId": "healthy-job", "atId": 1, "stuck": False}])
        result = asyncio.run(degraded.run_degraded_supervision_cycle(
            self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
        ))
        self.assertTrue(result["activated"])
        self.assertEqual(result["recommendations"], [])

    def test_missing_status_file_reports_an_error_not_a_crash(self):
        result = asyncio.run(degraded.run_degraded_supervision_cycle(
            os.path.join(self.tmpdir, "does-not-exist.json"), self.state_dir,
            master_key="x", heartbeat_path=self.heartbeat_path,
        ))
        self.assertTrue(result["activated"])
        self.assertIn("error", result)

    def test_raise_oq_recommendation_does_not_attempt_model_resolution(self):
        with open(os.path.join(self.state_dir, "stuck-job.log"), "w", encoding="utf-8") as f:
            f.write("AssertionError: something genuinely novel and unmatched")
        self._write_status([{"jobId": "stuck-job", "atId": 9999, "stuck": True}])
        with unittest.mock.patch.object(dispatch_io, "resolve_model_for_tier") as mock_resolve:
            result = asyncio.run(degraded.run_degraded_supervision_cycle(
                self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
            ))
        mock_resolve.assert_not_called()
        self.assertEqual(result["recommendations"][0]["action"], "raise_oq")

    def test_retry_recommendation_resolves_a_model_via_the_fallback_ladder(self):
        with open(os.path.join(self.state_dir, "retryable-job.log"), "w", encoding="utf-8") as f:
            f.write("Your credit balance is too low to access the Anthropic API.")
        self._write_status([{"jobId": "retryable-job", "atId": 1111, "stuck": True}])
        with unittest.mock.patch.object(
            dispatch_io, "resolve_model_for_tier",
            new=unittest.mock.AsyncMock(return_value=("cf/kimi-k2.6", ["cf/kimi-k2.6"])),
        ) as mock_resolve:
            result = asyncio.run(degraded.run_degraded_supervision_cycle(
                self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
            ))
        mock_resolve.assert_called_once()
        entry = result["recommendations"][0]
        self.assertEqual(entry["action"], "retry")
        self.assertEqual(entry["resolved_retry_model"], "cf/kimi-k2.6")

    def test_retry_recommendation_escalates_to_raise_oq_if_no_model_is_reachable(self):
        # Real scenario this guards against: if Claude itself is down for
        # account-wide reasons (credit exhaustion), other models on the same
        # account/provider might be down too -- retrying with nothing
        # actually available to retry with would just spin uselessly.
        with open(os.path.join(self.state_dir, "retryable-job.log"), "w", encoding="utf-8") as f:
            f.write("Your credit balance is too low to access the Anthropic API.")
        self._write_status([{"jobId": "retryable-job", "atId": 1111, "stuck": True}])
        with unittest.mock.patch.object(
            dispatch_io, "resolve_model_for_tier",
            new=unittest.mock.AsyncMock(return_value=(None, ["cf/kimi-k2.6", "local/qwen3.6"])),
        ):
            result = asyncio.run(degraded.run_degraded_supervision_cycle(
                self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
            ))
        entry = result["recommendations"][0]
        self.assertEqual(entry["action"], "raise_oq")
        self.assertIn("no Tier-C candidate model is currently reachable", entry["reasoning"])

    def test_every_recommendation_is_tagged_with_the_degraded_mode_label(self):
        with open(os.path.join(self.state_dir, "job1.log"), "w", encoding="utf-8") as f:
            f.write("some novel unmatched failure")
        self._write_status([{"jobId": "job1", "atId": 1, "stuck": True}])
        result = asyncio.run(degraded.run_degraded_supervision_cycle(
            self.status_path, self.state_dir, master_key="x", heartbeat_path=self.heartbeat_path,
        ))
        self.assertEqual(result["recommendations"][0]["mode"], "Tier-2-degraded")
        self.assertIn("Tier-2-degraded", result["recommendations"][0]["reasoning"])


if __name__ == "__main__":
    unittest.main()
