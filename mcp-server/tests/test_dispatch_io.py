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
    init_kwargs: list = []

    def __init__(self, *args, **kwargs):
        _ScriptedAsyncClient.init_kwargs.append(kwargs)

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
        _ScriptedAsyncClient.init_kwargs = []

    async def test_local_candidates_get_a_longer_timeout_than_cloud(self):
        """Real incident (2026-06-20, AT-1197 dispatch attempt): every
        local/* candidate was marked unreachable because Ollama's cold-load
        time for a 12-23GB model on this hardware exceeds the short cloud-
        model probe timeout. local/* candidates must get a generous timeout;
        cloud candidates keep the short one (they have no cold-start cost
        and should still fail fast on a real outage)."""
        candidates = dispatch_io.TIER_MODEL_CANDIDATES["Tier-R"]
        _ScriptedAsyncClient.responses_by_model = {m: _FakeResponse(200, {"choices": [{}]}) for m in candidates}
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            await dispatch_io.resolve_model_for_tier("Tier-R", "key")
        # First candidate (cf/kimi-k2.6) succeeds immediately, so only it
        # was actually probed -- confirm its timeout is the short one, then
        # directly verify the local/-vs-cloud timeout selection logic itself.
        self.assertEqual(_ScriptedAsyncClient.init_kwargs[0]["timeout"], dispatch_io._PROBE_TIMEOUT_SECONDS)
        self.assertGreater(dispatch_io._LOCAL_PROBE_TIMEOUT_SECONDS, dispatch_io._PROBE_TIMEOUT_SECONDS)

    async def test_local_candidate_actually_gets_the_long_timeout_when_tried(self):
        candidates = dispatch_io.TIER_MODEL_CANDIDATES["Tier-R"]
        local_candidates = [m for m in candidates if m.startswith("local/")]
        _ScriptedAsyncClient.responses_by_model = {m: _FakeResponse(500) for m in candidates[:-1]}
        _ScriptedAsyncClient.responses_by_model[candidates[-1]] = _FakeResponse(200, {"choices": [{}]})
        with patch.object(dispatch_io.httpx, "AsyncClient", _ScriptedAsyncClient):
            await dispatch_io.resolve_model_for_tier("Tier-R", "key")
        local_timeouts = [
            kw["timeout"] for kw, model in zip(_ScriptedAsyncClient.init_kwargs, candidates)
            if model in local_candidates
        ]
        self.assertTrue(local_timeouts, "expected at least one local/* candidate to be probed")
        self.assertTrue(all(t == dispatch_io._LOCAL_PROBE_TIMEOUT_SECONDS for t in local_timeouts))

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

    def test_tier_r_does_not_try_qwen_7b_first(self):
        # Real incident (2026-06-20, AT-1196): qwen2.5-coder:7b probed
        # reachable and ran to exit 0, but never made a real tool call --
        # it hallucinated a fake one instead, producing zero files/commits.
        # ai-model-selection-policy.md S8.1 already documented this exact
        # failure mode ("works as a chat model but not as an agent") before
        # this list was written. dispatch_coding_task is always a full
        # agentic Cline session, so this candidate must never be tried
        # before a model with a confirmed working agent loop.
        candidates = dispatch_io.TIER_MODEL_CANDIDATES["Tier-R"]
        self.assertNotEqual(candidates[0], "local/qwen2.5-coder:7b")

    def test_claude_is_not_an_auto_dispatch_candidate_for_any_tier(self):
        # Architect directive (2026-06-20): "Claude's should be reserved for
        # the architect to use, not for agents or subagents." Concrete cost
        # evidence the same day: 3 concurrent Tier-C jobs all defaulting to
        # claude/sonnet-4 hit Anthropic credit exhaustion mid-session during
        # the AT-1246/1248/1249 parallel-dispatch batch. No tier's candidate
        # list may include any claude/* model -- bringing Claude in for a
        # hard task is now a conversation with the architect, not an
        # automatic background dispatch (see Tier-M's error message in
        # local-mcp.py for the one real tension this creates).
        for tier, candidates in dispatch_io.TIER_MODEL_CANDIDATES.items():
            self.assertTrue(
                all(not m.startswith("claude/") for m in candidates),
                f"{tier} lists a claude/* candidate: {candidates}",
            )


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

    def test_different_at_id_in_same_repo_does_not_block_when_at_id_given(self):
        """Relaxed 2026-06-20 (architect-requested parallel-dispatch
        experiment): two different AT-ids may run concurrently against the
        same repo -- verified safe (concurrent git worktree add, git fsck
        clean) and each AT-id gets its own worktree path/branch name, so
        there's no real collision risk between them."""
        dispatch_io.write_job_state(self.tmpdir, "job-1196", {
            "status": "running", "repo_root": "C:/repo", "pid": os.getpid(), "at_id": 1196,
        })
        self.assertIsNone(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo", at_id=1197))

    def test_same_at_id_in_same_repo_still_blocks(self):
        """The one real collision risk -- dispatching the SAME AT-id twice
        concurrently would collide on both worktree path and branch name --
        stays blocked."""
        dispatch_io.write_job_state(self.tmpdir, "job-1196", {
            "status": "running", "repo_root": "C:/repo", "pid": os.getpid(), "at_id": 1196,
        })
        self.assertEqual(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo", at_id=1196), "job-1196")

    def test_at_id_none_preserves_original_whole_repo_serialization(self):
        """Callers not yet updated to pass at_id keep the original OQ-285
        whole-repo-busy behavior -- no silent behavior change for them."""
        dispatch_io.write_job_state(self.tmpdir, "job-1196", {
            "status": "running", "repo_root": "C:/repo", "pid": os.getpid(), "at_id": 1196,
        })
        self.assertEqual(dispatch_io.find_busy_job_for_repo(self.tmpdir, "C:/repo"), "job-1196")


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



class TestKillOrphanedWorktreeProcesses(unittest.TestCase):
    """Tests for kill_orphaned_worktree_processes (AT-1249 / REQ-6 / TOOL-3).

    Unit tests use a fake psutil process list; the integration test
    (test_real_orphan_is_killed) spawns a real subprocess and verifies
    cleanup kills it -- the exit evidence real reproduction."""

    def _make_fake_proc(self, pid, cmdline):
        killed = []
        class _FakeProc:
            info = {"pid": pid, "cmdline": cmdline}
            def kill(self_inner):
                killed.append(pid)
        return _FakeProc(), killed

    def test_empty_worktree_path_returns_empty_list(self):
        self.assertEqual(dispatch_io.kill_orphaned_worktree_processes(""), [])

    def test_none_cmdline_process_is_skipped(self):
        class _NullCmdProc:
            info = {"pid": 999, "cmdline": None}
            def kill(self):
                raise AssertionError("should not be called")
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[_NullCmdProc()]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:/some/worktree")
        self.assertEqual(result, [])

    def test_matching_process_is_killed_and_pid_returned(self):
        proc, killed_list = self._make_fake_proc(
            4242, ["cline.exe", "--task", "C:\\repos\\skein-at-1249-dispatch"],
        )
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[proc]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:\\repos\\skein-at-1249-dispatch")
        self.assertEqual(result, [4242])
        self.assertEqual(killed_list, [4242])

    def test_non_matching_process_is_not_killed(self):
        proc, killed_list = self._make_fake_proc(1111, ["python.exe", "C:\\repos\\other"])
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[proc]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:\\repos\\skein-at-1249-dispatch")
        self.assertEqual(result, [])
        self.assertEqual(killed_list, [])

    def test_current_process_is_skipped(self):
        my_pid = os.getpid()
        proc, killed_list = self._make_fake_proc(
            my_pid, ["python.exe", "C:\\repos\\skein-at-1249-dispatch\\something.py"],
        )
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[proc]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:\\repos\\skein-at-1249-dispatch")
        self.assertEqual(result, [])
        self.assertEqual(killed_list, [])

    def test_no_such_process_exception_is_swallowed(self):
        class _VanishingProc:
            info = {"pid": 7777, "cmdline": ["cline.exe", "C:/repos/skein-at-1249"]}
            def kill(self):
                raise dispatch_io.psutil.NoSuchProcess(7777)
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[_VanishingProc()]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:/repos/skein-at-1249")
        self.assertEqual(result, [])

    def test_access_denied_exception_is_swallowed(self):
        class _ProtectedProc:
            info = {"pid": 8888, "cmdline": ["cline.exe", "C:/repos/skein-at-1249"]}
            def kill(self):
                raise dispatch_io.psutil.AccessDenied(8888)
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[_ProtectedProc()]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:/repos/skein-at-1249")
        self.assertEqual(result, [])

    def test_case_insensitive_path_matching(self):
        proc, killed_list = self._make_fake_proc(
            5555, ["cline.EXE", "C:\\Repos\\SKEIN-AT-1249-Dispatch"],
        )
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[proc]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:\\repos\\skein-at-1249-dispatch")
        self.assertEqual(result, [5555])

    def test_forward_slash_normalization(self):
        proc, killed_list = self._make_fake_proc(
            6666, ["cline.exe", "C:/repos/skein-at-1249-dispatch/task.txt"],
        )
        with patch.object(dispatch_io.psutil, "process_iter", return_value=[proc]):
            result = dispatch_io.kill_orphaned_worktree_processes("C:\\repos\\skein-at-1249-dispatch")
        self.assertEqual(result, [6666])
    def test_real_orphan_is_killed(self):
        """AT-1249 exit evidence: spawn a real long-running child process whose
        argv references a synthetic worktree path, call
        kill_orphaned_worktree_processes, and confirm the child is dead.

        Reproduces the incident: after the wrapper parent exits, the child
        survives as an orphan. Cleanup finds and kills by command-line match
        even though PID lineage no longer connects them."""
        import shutil
        import subprocess as _sp
        import sys as _sys
        import tempfile
        import psutil as _psutil

        tmpdir = tempfile.mkdtemp(prefix="at1249_orphan_test_")
        try:
            # Spawn a long-running process whose argv contains tmpdir --
            # stand-in for cline.exe being passed the worktree path.
            child = _sp.Popen(
                [_sys.executable, "-c", "import time; time.sleep(600)", tmpdir],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
            )
            child_pid = child.pid
            try:
                self.assertTrue(_psutil.pid_exists(child_pid),
                                f"child PID {child_pid} did not start")

                killed = dispatch_io.kill_orphaned_worktree_processes(tmpdir)

                self.assertIn(child_pid, killed,
                              f"child PID {child_pid} not in killed list {killed}")
                child.wait(timeout=5)
                self.assertFalse(_psutil.pid_exists(child_pid),
                                 f"child PID {child_pid} still alive after cleanup")
            finally:
                try:
                    child.kill()
                    child.wait(timeout=5)
                except Exception:
                    pass
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)



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

    def test_does_not_assert_a_specific_ledger_path_or_repo_specific_sections(self):
        """Real incident (2026-06-20): AT-1196 dispatched into skein-toolkit
        burned several tool calls because the prompt asserted a specific
        ai-task-queue.md path inside the dispatch target and named
        Electron-Splines-specific CLAUDE.md sections (e.g. "TypeScript
        section") unconditionally -- both false for non-Electron-Splines
        dispatch targets. The prompt must stay repo-agnostic."""
        at_row = {
            "description": "Do the thing",
            "spec_issue": "some-spec.md",
            "exit_evidence": "the thing is done",
        }
        prompt = dispatch_io.build_task_prompt(1228, at_row, "C:/some/other/repo")
        self.assertNotIn("architecture-docs/global/ai-task-queue.md", prompt)
        self.assertNotIn("TypeScript section", prompt)
        self.assertNotIn("C:/some/other/repo", prompt)


if __name__ == "__main__":
    unittest.main()
