#!/usr/bin/env python3
"""
Unit tests for dispatch_io.py (AT-1228).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_dispatch_io.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "dispatch_io.py"))

_spec = importlib.util.spec_from_file_location("dispatch_io", _MODULE_PATH)
dispatch_io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatch_io)


class TestLoadLitellmMasterKey(unittest.TestCase):
    def test_prefers_environment_variable(self):
        with patch.dict(os.environ, {"LITELLM_MASTER_KEY": "sk-from-env"}):
            self.assertEqual(dispatch_io.load_litellm_master_key("/irrelevant"), "sk-from-env")

    def test_falls_back_to_litellm_env_file(self):
        with patch.dict(os.environ, {}, clear=True):
            tmpdir = tempfile.mkdtemp()
            try:
                with open(os.path.join(tmpdir, "litellm.env"), "w", encoding="utf-8") as f:
                    f.write("# comment\nLITELLM_MASTER_KEY=sk-from-file\nOTHER=ignored\n")
                self.assertEqual(dispatch_io.load_litellm_master_key(tmpdir), "sk-from-file")
            finally:
                shutil.rmtree(tmpdir)

    def test_missing_both_returns_empty_string_not_none(self):
        with patch.dict(os.environ, {}, clear=True):
            tmpdir = tempfile.mkdtemp()
            try:
                self.assertEqual(dispatch_io.load_litellm_master_key(tmpdir), "")
            finally:
                shutil.rmtree(tmpdir)


class _FakeResponse:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self._json_body = json_body or {}

    def json(self):
        return self._json_body


class _ScriptedAsyncClient:
    """Maps a model name to a canned (status_code, json_body) response,
    matching the per-model-call shape probe_model/resolve_model_for_tier
    actually issue -- unlike test_local_mcp_cf_capacity_retry.py's
    sequential-by-call-index script, this needs to respond differently
    depending on WHICH model was requested, since resolve_model_for_tier
    tries several in one resolution."""
    responses_by_model: dict = {}
    calls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, headers=None, json=None, **kwargs):
        model = json["model"]
        _ScriptedAsyncClient.calls.append(model)
        return _ScriptedAsyncClient.responses_by_model.get(model, _FakeResponse(500))


class TestProbeModel(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _ScriptedAsyncClient.calls = []

    async def test_200_with_choices_is_success(self):
        _ScriptedAsyncClient.responses_by_model = {"m1": _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})}
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            self.assertTrue(await dispatch_io.probe_model("m1", "key"))

    async def test_non_200_is_failure(self):
        _ScriptedAsyncClient.responses_by_model = {"m1": _FakeResponse(429)}
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            self.assertFalse(await dispatch_io.probe_model("m1", "key"))

    async def test_200_with_error_field_is_failure(self):
        _ScriptedAsyncClient.responses_by_model = {"m1": _FakeResponse(200, {"error": {"message": "boom"}})}
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            self.assertFalse(await dispatch_io.probe_model("m1", "key"))

    async def test_timeout_is_failure_not_an_exception(self):
        class _TimeoutClient(_ScriptedAsyncClient):
            async def post(self, *a, **k):
                raise dispatch_io.httpx.TimeoutException("timed out")
        with patch.object(dispatch_io.httpx, "AsyncClient", _TimeoutClient):
            self.assertFalse(await dispatch_io.probe_model("m1", "key"))


class TestResolveModelForTier(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _ScriptedAsyncClient.calls = []

    async def test_returns_first_candidate_that_succeeds(self):
        candidates = dispatch_io.TIER_MODEL_CANDIDATES["Tier-C"]
        _ScriptedAsyncClient.responses_by_model = {
            candidates[0]: _FakeResponse(429),
            candidates[1]: _FakeResponse(200, {"choices": [{}]}),
        }
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            model, attempted = await dispatch_io.resolve_model_for_tier("Tier-C", "key")
        self.assertEqual(model, candidates[1])
        self.assertEqual(attempted, [candidates[0], candidates[1]])

    async def test_all_candidates_fail_returns_none_with_full_attempt_list(self):
        candidates = dispatch_io.TIER_MODEL_CANDIDATES["Tier-R"]
        _ScriptedAsyncClient.responses_by_model = {m: _FakeResponse(500) for m in candidates}
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            model, attempted = await dispatch_io.resolve_model_for_tier("Tier-R", "key")
        self.assertIsNone(model)
        self.assertEqual(attempted, list(candidates))

    async def test_unknown_tier_returns_none_no_candidates_attempted(self):
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            model, attempted = await dispatch_io.resolve_model_for_tier("Tier-NOPE", "key")
        self.assertIsNone(model)
        self.assertEqual(attempted, [])

    def test_tier_m_never_lists_phi4_reasoning(self):
        # phi4-reasoning has no tool-calling capability (ai-model-selection-
        # policy.md S6) and can never run as a Cline agent -- listing it as
        # a Tier-M candidate would be a bug, not just a bad default.
        self.assertNotIn("phi4-reasoning", dispatch_io.TIER_MODEL_CANDIDATES["Tier-M"])
        self.assertTrue(all("phi4" not in m for m in dispatch_io.TIER_MODEL_CANDIDATES["Tier-M"]))


class TestJobState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_write_then_read_round_trips(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {"status": "running", "pid": 123})
        state = dispatch_io.read_job_state(self.tmpdir, "job1")
        self.assertEqual(state, {"status": "running", "pid": 123})

    def test_read_missing_job_returns_none(self):
        self.assertIsNone(dispatch_io.read_job_state(self.tmpdir, "nope"))

    def test_list_job_states_includes_job_id_from_filename(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {"status": "running"})
        dispatch_io.write_job_state(self.tmpdir, "job2", {"status": "done"})
        states = dispatch_io.list_job_states(self.tmpdir)
        ids = {s["job_id"] for s in states}
        self.assertEqual(ids, {"job1", "job2"})

    def test_list_job_states_on_missing_directory_returns_empty(self):
        self.assertEqual(dispatch_io.list_job_states(os.path.join(self.tmpdir, "does-not-exist")), [])

    def test_write_is_atomic_no_tmp_file_left_behind(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {"status": "running"})
        self.assertEqual(os.listdir(self.tmpdir), ["job1.json"])


class TestIsPidAlive(unittest.TestCase):
    def test_current_process_is_alive(self):
        self.assertTrue(dispatch_io.is_pid_alive(os.getpid()))

    def test_none_is_not_alive(self):
        self.assertFalse(dispatch_io.is_pid_alive(None))

    def test_implausible_pid_is_not_alive(self):
        self.assertFalse(dispatch_io.is_pid_alive(999999999))


class TestFindBusyJobForRepo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_running_job_with_live_pid_is_busy(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:/repo", "pid": os.getpid(),
        })
        self.assertEqual(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"), "job1")

    def test_running_job_with_dead_pid_is_not_busy_even_if_recently_updated(self):
        # PID-liveness is authoritative when conclusive -- a confirmed-dead
        # PID means crashed, not busy, regardless of the staleness window.
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:/repo", "pid": 999999999, "updated_at": time.time(),
        })
        self.assertIsNone(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"))

    def test_running_job_no_pid_but_recently_updated_is_busy(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:/repo", "updated_at": time.time(),
        })
        self.assertEqual(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"), "job1")

    def test_running_job_no_pid_and_stale_is_not_busy(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:/repo", "updated_at": time.time() - 999999,
        })
        self.assertIsNone(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"))

    def test_different_repo_does_not_block(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:/other-repo", "pid": os.getpid(),
        })
        self.assertIsNone(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"))

    def test_completed_job_does_not_block(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "complete", "repo_root": "C:/repo", "pid": os.getpid(),
        })
        self.assertIsNone(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"))

    def test_repo_path_comparison_is_case_and_separator_insensitive(self):
        dispatch_io.write_job_state(self.tmpdir, "job1", {
            "status": "running", "repo_root": "C:\\Repo\\Path", "pid": os.getpid(),
        })
        self.assertEqual(dispatch_io.find_busy_job_for_repo(self.tmpdir, "c:/repo/path"), "job1")


class TestNewJobId(unittest.TestCase):
    def test_includes_at_id_and_is_unique(self):
        id1 = dispatch_io.new_job_id(1228)
        id2 = dispatch_io.new_job_id(1228)
        self.assertIn("1228", id1)
        self.assertNotEqual(id1, id2)


class TestGitOperations(unittest.TestCase):
    def test_is_working_tree_clean_reports_dirty_files(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": " M dirty_file.ts\n", "stderr": ""})()
            clean, detail = dispatch_io.is_working_tree_clean("C:/repo")
        self.assertFalse(clean)
        self.assertIn("dirty_file.ts", detail)

    def test_is_working_tree_clean_true_on_empty_output(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"stdout": "", "stderr": ""})()
            clean, detail = dispatch_io.is_working_tree_clean("C:/repo")
        self.assertTrue(clean)
        self.assertEqual(detail, "")

    def test_create_worktree_success(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stderr": ""})()
            ok, err = dispatch_io.create_worktree("C:/repo", "C:/repo-wt", "at-1-dispatch")
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_create_worktree_failure_surfaces_stderr(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 1, "stderr": "branch already exists"})()
            ok, err = dispatch_io.create_worktree("C:/repo", "C:/repo-wt", "at-1-dispatch")
        self.assertFalse(ok)
        self.assertIn("already exists", err)

    def test_dispatch_branch_name_format(self):
        self.assertEqual(dispatch_io.dispatch_branch_name(1228), "at-1228-dispatch")


class TestSpawnClineProcess(unittest.TestCase):
    def test_builds_expected_argv_and_passes_through_log_file_and_cwd(self):
        fake_log_file = object()
        with patch.object(dispatch_io.subprocess, "Popen") as mock_popen:
            dispatch_io.spawn_cline_process(
                "C:/run-cline.ps1", "C:/repo-wt", "claude/sonnet-4", "do the thing",
                1200, fake_log_file, cwd="C:/mcp-server",
            )
        args, kwargs = mock_popen.call_args
        argv = args[0]
        self.assertEqual(
            argv[:6],
            ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "C:/run-cline.ps1"],
        )
        self.assertIn("-RepoRoot", argv)
        self.assertIn("C:/repo-wt", argv)
        self.assertIn("-Model", argv)
        self.assertIn("claude/sonnet-4", argv)
        self.assertIn("-AutoApprove", argv)
        self.assertIs(kwargs["stdout"], fake_log_file)
        self.assertEqual(kwargs["cwd"], "C:/mcp-server")


class TestKillJobProcessTree(unittest.TestCase):
    def test_uses_taskkill_with_force_and_tree_flags(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0})()
            dispatch_io.kill_job_process_tree(12345)
        args = mock_run.call_args[0][0]
        self.assertIn("/F", args)
        self.assertIn("/T", args)
        self.assertIn("12345", args)

    def test_already_dead_pid_still_returns_true(self):
        with patch.object(dispatch_io.subprocess, "run") as mock_run, \
                patch.object(dispatch_io, "is_pid_alive", return_value=False):
            mock_run.return_value = type("R", (), {"returncode": 1})()
            self.assertTrue(dispatch_io.kill_job_process_tree(999999999))


class TestBuildTaskPrompt(unittest.TestCase):
    def test_includes_at_id_description_and_exit_evidence(self):
        at_row = {
            "description": "Do the thing",
            "spec_issue": "some-spec.md",
            "exit_evidence": "the thing is done",
        }
        prompt = dispatch_io.build_task_prompt(1228, at_row, "C:/repo")
        self.assertIn("AT-1228", prompt)
        self.assertIn("Do the thing", prompt)
        self.assertIn("some-spec.md", prompt)
        self.assertIn("the thing is done", prompt)
        self.assertIn("CLAUDE.md", prompt)


if __name__ == "__main__":
    unittest.main()
