#!/usr/bin/env python3
"""
Unit tests for cline_completion_watcher.py.

The smoke-test tests use real, throwaway scripts (not mocked) -- the whole
point of this module is catching a real runtime crash a unit test mocking
subprocess would not catch. Mirrors AT-1249's real-process-spawn pattern.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_cline_completion_watcher.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "cline_completion_watcher.py"))

_spec = importlib.util.spec_from_file_location("cline_completion_watcher", _MODULE_PATH)
watcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watcher)


class TestFindEntrypointCandidates(unittest.TestCase):
    def test_matches_known_launcher_shapes(self):
        files = [
            "tray.py",
            "start-local.py",
            "start_skein.ps1",
            "launch-windows.ps1",
            "odysseus-ui.service",
            "core/auth.py",
            "tests/test_tray.py",
        ]
        result = watcher.find_entrypoint_candidates(files)
        self.assertIn("tray.py", result)
        self.assertIn("start-local.py", result)
        self.assertIn("start_skein.ps1", result)
        self.assertIn("launch-windows.ps1", result)
        self.assertIn("odysseus-ui.service", result)
        self.assertNotIn("core/auth.py", result)
        self.assertNotIn("tests/test_tray.py", result)


class TestGetLatestCompletionEvent(unittest.TestCase):
    def test_finds_completion_result_ask(self):
        tmpdir = tempfile.mkdtemp()
        try:
            messages = [
                {"type": "say", "say": "text", "ts": 1000},
                {"type": "ask", "ask": "completion_result", "ts": 2000, "text": ""},
            ]
            with open(os.path.join(tmpdir, "ui_messages.json"), "w", encoding="utf-8") as f:
                json.dump(messages, f)
            result = watcher.get_latest_completion_event(tmpdir)
            self.assertEqual(result["ts"], 2000)
            self.assertEqual(result["index"], 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_returns_none_when_no_completion_yet(self):
        tmpdir = tempfile.mkdtemp()
        try:
            messages = [{"type": "say", "say": "text", "ts": 1000}]
            with open(os.path.join(tmpdir, "ui_messages.json"), "w", encoding="utf-8") as f:
                json.dump(messages, f)
            self.assertIsNone(watcher.get_latest_completion_event(tmpdir))
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_returns_none_when_file_missing(self):
        tmpdir = tempfile.mkdtemp()
        try:
            self.assertIsNone(watcher.get_latest_completion_event(tmpdir))
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestWatcherState(unittest.TestCase):
    def test_round_trips_and_skips_already_processed(self):
        tmpdir = tempfile.mkdtemp()
        try:
            state_path = os.path.join(tmpdir, "state.json")
            state = watcher.load_watcher_state(state_path)
            self.assertEqual(state, {"processed": {}})
            state["processed"]["task1"] = 5000
            watcher.save_watcher_state(state, state_path)
            reloaded = watcher.load_watcher_state(state_path)
            self.assertEqual(reloaded["processed"]["task1"], 5000)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestSmokeTestEntrypoint(unittest.TestCase):
    """Real incident reproduction: a launcher that crashes immediately on a
    bad import must be caught as a real failure, not a mocked assumption.
    These spawn actual Python processes -- the entire point of this module."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_script_that_crashes_immediately_is_caught(self):
        # Reproduces the actual incident: ModuleNotFoundError on a bad import.
        script = os.path.join(self.tmpdir, "broken_launcher.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import this_module_does_not_exist_anywhere\n")
        passed, detail = watcher.smoke_test_entrypoint(self.tmpdir, "broken_launcher.py", timeout=5.0)
        self.assertFalse(passed)
        self.assertIn("exited early", detail)

    def test_a_long_running_script_is_treated_as_passing_and_killed(self):
        script = os.path.join(self.tmpdir, "good_launcher.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import time\ntime.sleep(600)\n")
        start = time.monotonic()
        passed, detail = watcher.smoke_test_entrypoint(self.tmpdir, "good_launcher.py", timeout=2.0)
        elapsed = time.monotonic() - start
        self.assertTrue(passed)
        self.assertIn("still running", detail)
        # Confirm it was actually killed, not left running -- this watcher
        # must not itself leave orphaned processes (today's other real
        # incident, AT-1249).
        self.assertLess(elapsed, 10.0)

    def test_killing_a_launcher_also_kills_what_it_spawned(self):
        """Real incident, 2026-06-20 (found running this live, same day):
        proc.kill() only kills the immediate process. tray.py specifically
        launches a whole service stack of its own (LiteLLM, Odysseus,
        multiple local-mcp.py instances) -- testing it left ~18 duplicate
        LiteLLM processes alone after a handful of smoke tests. Reproduces
        the actual shape: a launcher that spawns a real child process and
        writes the child's PID to a file, so this test can independently
        verify the CHILD is also dead, not just the launcher itself."""
        import psutil

        pid_file = os.path.join(self.tmpdir, "child.pid")
        script = os.path.join(self.tmpdir, "launcher_with_child.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import subprocess, sys, time\n"
                f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
                f"with open(r'{pid_file}', 'w') as f:\n"
                "    f.write(str(child.pid))\n"
                "time.sleep(600)\n"
            )
        passed, _detail = watcher.smoke_test_entrypoint(self.tmpdir, "launcher_with_child.py", timeout=3.0)
        self.assertTrue(passed)

        with open(pid_file) as f:
            child_pid = int(f.read().strip())
        # Give the OS a moment to fully reap the killed tree.
        time.sleep(1)
        self.assertFalse(psutil.pid_exists(child_pid), "child process survived the launcher's kill -- orphan leaked")

    def test_a_clean_fast_exit_is_treated_as_passing(self):
        script = os.path.join(self.tmpdir, "quick_launcher.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("print('setup done')\n")
        passed, detail = watcher.smoke_test_entrypoint(self.tmpdir, "quick_launcher.py", timeout=5.0)
        self.assertTrue(passed)

    def test_missing_file_is_a_clear_failure_not_a_crash(self):
        passed, detail = watcher.smoke_test_entrypoint(self.tmpdir, "does_not_exist.py", timeout=2.0)
        self.assertFalse(passed)
        self.assertIn("no longer exists", detail)


class TestResolvePythonFor(unittest.TestCase):
    def test_uses_repo_venv_when_present(self):
        tmpdir = tempfile.mkdtemp()
        try:
            venv_python = os.path.join(tmpdir, "venv", "Scripts")
            os.makedirs(venv_python)
            fake_python = os.path.join(venv_python, "python.exe")
            with open(fake_python, "w") as f:
                f.write("")
            self.assertEqual(watcher._resolve_python_for(tmpdir), fake_python)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_falls_back_to_own_interpreter_when_no_venv(self):
        tmpdir = tempfile.mkdtemp()
        try:
            self.assertEqual(watcher._resolve_python_for(tmpdir), sys.executable)
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestFindNewCommits(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "--quiet"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.tmpdir, check=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_finds_a_commit_after_the_given_timestamp(self):
        before = time.time()
        with open(os.path.join(self.tmpdir, "f.txt"), "w") as f:
            f.write("x")
        subprocess.run(["git", "add", "f.txt"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "commit", "-m", "test commit", "--quiet"], cwd=self.tmpdir, check=True)
        commits = watcher.find_new_commits(self.tmpdir, before - 60)
        self.assertEqual(len(commits), 1)

    def test_does_not_find_commits_before_the_timestamp(self):
        with open(os.path.join(self.tmpdir, "f.txt"), "w") as f:
            f.write("x")
        subprocess.run(["git", "add", "f.txt"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "commit", "-m", "test commit", "--quiet"], cwd=self.tmpdir, check=True)
        future = time.time() + 3600
        commits = watcher.find_new_commits(self.tmpdir, future)
        self.assertEqual(commits, [])

    def test_non_git_directory_returns_empty_not_an_error(self):
        not_a_repo = tempfile.mkdtemp()
        try:
            self.assertEqual(watcher.find_new_commits(not_a_repo, 0), [])
        finally:
            import shutil
            shutil.rmtree(not_a_repo)


class TestChangedFilesInCommits(unittest.TestCase):
    """Real performance finding (2026-06-20): the original implementation
    called `git show` once per commit hash -- several real historical
    Cline tasks matched 1000+ commits in their lookback window, meaning
    thousands of subprocess spawns for a single task. One `git log
    --name-only` call over the same window gets the same union of files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "--quiet"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.tmpdir, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.tmpdir, check=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_the_union_of_files_across_multiple_commits(self):
        before = time.time()
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("x")
            subprocess.run(["git", "add", name], cwd=self.tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", f"add {name}", "--quiet"], cwd=self.tmpdir, check=True)
        changed = watcher.changed_files_in_commits(self.tmpdir, before - 60)
        self.assertEqual(set(changed), {"a.txt", "b.txt"})

    def test_only_one_git_subprocess_regardless_of_commit_count(self):
        before = time.time()
        for i in range(10):
            with open(os.path.join(self.tmpdir, f"f{i}.txt"), "w") as f:
                f.write("x")
            subprocess.run(["git", "add", f"f{i}.txt"], cwd=self.tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", f"commit {i}", "--quiet"], cwd=self.tmpdir, check=True)
        with unittest.mock.patch.object(watcher.subprocess, "run", wraps=watcher.subprocess.run) as mock_run:
            watcher.changed_files_in_commits(self.tmpdir, before - 60)
            self.assertEqual(mock_run.call_count, 1)

    def test_non_git_directory_returns_empty(self):
        not_a_repo = tempfile.mkdtemp()
        try:
            self.assertEqual(watcher.changed_files_in_commits(not_a_repo, 0), [])
        finally:
            import shutil
            shutil.rmtree(not_a_repo)


class TestLastScanOptimization(unittest.TestCase):
    """Real performance finding (2026-06-20): a naive full scan of 28
    accumulated task directories took ~3.5 minutes even with nothing new
    to report, mostly from re-parsing every task's ui_messages.json (some
    multi-MB) on every run. last_scan_ts must skip that parse for files
    unchanged since the last scan -- confirmed here, not assumed."""

    def setUp(self):
        self.tasks_dir = tempfile.mkdtemp()
        self.repos_dir = tempfile.mkdtemp()
        self.state_path = os.path.join(tempfile.mkdtemp(), "state.json")

    def tearDown(self):
        import shutil
        for d in (self.tasks_dir, self.repos_dir, os.path.dirname(self.state_path)):
            shutil.rmtree(d, ignore_errors=True)

    def _make_task(self, task_id, completed=True):
        task_dir = os.path.join(self.tasks_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        messages = [{"type": "say", "say": "text", "ts": 1000}]
        if completed:
            messages.append({"type": "ask", "ask": "completion_result", "ts": 2000, "text": ""})
        with open(os.path.join(task_dir, "ui_messages.json"), "w", encoding="utf-8") as f:
            json.dump(messages, f)
        return task_dir

    def test_unchanged_task_is_not_reparsed_on_second_scan(self):
        self._make_task("old-task")
        time.sleep(0.05)  # ensure a clear gap between file mtime and scan-start time
        watcher.check_for_new_completions(repos={}, state_path=self.state_path, tasks_dir=self.tasks_dir)
        time.sleep(0.05)
        with unittest.mock.patch.object(watcher, "get_latest_completion_event") as mock_get:
            watcher.check_for_new_completions(repos={}, state_path=self.state_path, tasks_dir=self.tasks_dir)
            mock_get.assert_not_called()

    def test_a_task_modified_after_the_last_scan_is_still_picked_up(self):
        self._make_task("task-a", completed=False)
        watcher.check_for_new_completions(repos={}, state_path=self.state_path, tasks_dir=self.tasks_dir)
        time.sleep(0.05)
        # Simulate the task completing later -- file genuinely modified
        # after the previous scan's start time.
        self._make_task("task-a", completed=True)
        with unittest.mock.patch.object(watcher, "get_latest_completion_event", wraps=watcher.get_latest_completion_event) as mock_get:
            watcher.check_for_new_completions(repos={}, state_path=self.state_path, tasks_dir=self.tasks_dir)
            mock_get.assert_called()


class TestJsonCliMode(unittest.TestCase):
    """The Scheduled Task wrapper (PowerShell) parses this with
    ConvertFrom-Json, not regex against human-readable text -- confirm the
    --json flag actually produces valid, stably-shaped JSON on stdout."""

    def test_json_flag_produces_valid_json_with_no_completions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, _MODULE_PATH, "--json"],
                capture_output=True, text=True, timeout=30,
                # Points CLINE_TASKS_DIR (computed from %APPDATA% at import
                # time) at an empty fake dir -- no real completions to find.
                env={**os.environ, "APPDATA": tmpdir,
                     "USERPROFILE": tmpdir},
            )
        self.assertEqual(result.returncode, 0)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed, [])


if __name__ == "__main__":
    unittest.main()
