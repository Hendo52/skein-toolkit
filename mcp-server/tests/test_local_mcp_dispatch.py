#!/usr/bin/env python3
"""
Unit tests for dispatch_coding_task / get_coding_task_status in
local-mcp.py (AT-1228/AT-1227). Exercises the guard-clause/orchestration
logic with a real temp git repo for the working-tree checks, but mocks
dispatch_io.resolve_model_for_tier (no real LiteLLM call) and
subprocess.Popen (no real Cline process spawn) -- the same boundary this
project already draws elsewhere (test_local_mcp_cf_capacity_retry.py mocks
the AsyncClient, not the network).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_dispatch.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


_AT_QUEUE_WITH_TIER = (
    "# AI Task Queue\n\n## Ready Pool\n\n### Newly Decomposed Tasks (Intake)\n\n"
    "| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |\n"
    "|----|------|-------------|---------------|--------|------------|\n"
    "| AT-1228 | **Do the thing. Model: Tier-C.** | spec1 | evidence1 | Medium | None |\n"
    "| AT-1222 | **No tier annotation at all.** | spec2 | evidence2 | Small | None |\n"
    "| AT-1254 | **A large cross-cutting task. Model: Tier-M.** | spec3 | evidence3 | Large | None |\n"
)


def _init_real_git_repo() -> str:
    repo = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
        f.write("seed\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


class _DispatchTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_dir = os.path.join(self._tmpdir, "state")
        self._orig_at_path = local_mcp.AT_QUEUE_PATH
        self._orig_state_dir = local_mcp.CODING_TASK_STATE_DIR
        queue_path = os.path.join(self._tmpdir, "ai-task-queue.md")
        with open(queue_path, "w", encoding="utf-8") as f:
            f.write(_AT_QUEUE_WITH_TIER)
        local_mcp.AT_QUEUE_PATH = queue_path
        local_mcp.CODING_TASK_STATE_DIR = self._state_dir
        self._repos_to_clean = []

    def tearDown(self):
        local_mcp.AT_QUEUE_PATH = self._orig_at_path
        local_mcp.CODING_TASK_STATE_DIR = self._orig_state_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        for repo in self._repos_to_clean:
            shutil.rmtree(repo, ignore_errors=True)
            # Sibling worktrees this test class's fixture AT rows can create
            # (AT-1228's dispatch tests; AT-1254 added for timeout-scaling
            # coverage) -- clean up both rather than hardcoding just one.
            for at_id in (1228, 1254):
                sibling_worktree = repo + f"-at-{at_id}-dispatch"
                shutil.rmtree(sibling_worktree, ignore_errors=True)

    def _make_repo(self) -> str:
        repo = _init_real_git_repo()
        self._repos_to_clean.append(repo)
        return repo


class TestDispatchCodingTaskGuardClauses(_DispatchTestCase):
    async def test_nonexistent_repo_root_rejected(self):
        result = await local_mcp.dispatch_coding_task(1228, os.path.join(self._tmpdir, "nope"))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("does not exist", result)

    async def test_non_git_repo_root_rejected(self):
        not_a_repo = tempfile.mkdtemp(dir=self._tmpdir)
        result = await local_mcp.dispatch_coding_task(1228, not_a_repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("not a git repository", result)

    async def test_missing_at_row_rejected(self):
        repo = self._make_repo()
        result = await local_mcp.dispatch_coding_task(9999, repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("not found", result)

    async def test_at_row_without_model_tier_rejected(self):
        repo = self._make_repo()
        result = await local_mcp.dispatch_coding_task(1222, repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("Model: Tier-X", result)

    async def test_busy_repo_rejected_per_oq_285(self):
        repo = self._make_repo()
        with unittest.mock.patch.object(local_mcp.dispatch_io, "find_busy_job_for_repo", return_value="at1228-existing"):
            result = await local_mcp.dispatch_coding_task(1228, repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("already has a running job", result)
        self.assertIn("at1228-existing", result)

    async def test_dirty_working_tree_raises_oq_not_silent_failure(self):
        repo = self._make_repo()
        with open(os.path.join(repo, "dirty.txt"), "w", encoding="utf-8") as f:
            f.write("uncommitted\n")
        with unittest.mock.patch.object(local_mcp, "create_open_question", return_value="OQ-999") as mock_oq:
            result = await local_mcp.dispatch_coding_task(1228, repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("OQ-999", result)
        mock_oq.assert_called_once()
        self.assertIn("dirty.txt", mock_oq.call_args.kwargs["question"])

    async def test_no_model_responds_rejected_with_attempted_list(self):
        repo = self._make_repo()
        with unittest.mock.patch.object(
            local_mcp.dispatch_io, "resolve_model_for_tier",
            unittest.mock.AsyncMock(return_value=(None, ["claude/sonnet-4", "cf/kimi-k2.6", "local/deepseek-r1:32b"])),
        ):
            result = await local_mcp.dispatch_coding_task(1228, repo)
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("claude/sonnet-4", result)


class TestDispatchCodingTaskHappyPath(_DispatchTestCase):
    async def test_creates_worktree_writes_job_state_returns_job_id(self):
        repo = self._make_repo()
        fake_proc = unittest.mock.MagicMock()
        fake_proc.pid = 424242
        with unittest.mock.patch.object(
            local_mcp.dispatch_io, "resolve_model_for_tier",
            unittest.mock.AsyncMock(return_value=("claude/sonnet-4", ["claude/sonnet-4"])),
        ), unittest.mock.patch.object(local_mcp.dispatch_io, "spawn_cline_process", return_value=fake_proc) as mock_spawn:
            job_id = await local_mcp.dispatch_coding_task(1228, repo)

        self.assertFalse(job_id.startswith("ERROR"))
        self.assertIn("1228", job_id)

        worktree_path = repo + "-at-1228-dispatch"
        self.assertTrue(os.path.isdir(worktree_path))
        branches = subprocess.run(
            ["git", "branch", "--list", "at-1228-dispatch"], cwd=repo, capture_output=True, text=True
        ).stdout
        self.assertIn("at-1228-dispatch", branches)

        state = local_mcp.dispatch_io.read_job_state(self._state_dir, job_id)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["model"], "claude/sonnet-4")
        self.assertEqual(state["pid"], 424242)
        self.assertEqual(state["at_id"], 1228)
        mock_spawn.assert_called_once()
        self.assertEqual(mock_spawn.call_args[0][1], worktree_path)
        self.assertEqual(mock_spawn.call_args[0][2], "claude/sonnet-4")
        self.assertEqual(mock_spawn.call_args[0][4], local_mcp.DISPATCH_TIMEOUT_BY_EFFORT_SECONDS["Medium"])

    async def test_large_effort_task_gets_a_longer_timeout(self):
        """Real incident, 2026-06-21 (AT-1254): a Large-effort task spent its
        whole 1200s default budget on legitimate research and timed out with
        zero commits. The timeout must scale from the AT row's own Effort
        column, not use one fixed budget regardless of task size."""
        repo = self._make_repo()
        fake_proc = unittest.mock.MagicMock()
        fake_proc.pid = 424243
        with unittest.mock.patch.object(
            local_mcp.dispatch_io, "resolve_model_for_tier",
            unittest.mock.AsyncMock(return_value=("claude/sonnet-4", ["claude/sonnet-4"])),
        ), unittest.mock.patch.object(local_mcp.dispatch_io, "spawn_cline_process", return_value=fake_proc) as mock_spawn:
            job_id = await local_mcp.dispatch_coding_task(1254, repo)
        self.assertFalse(job_id.startswith("ERROR"))
        self.assertEqual(mock_spawn.call_args[0][4], local_mcp.DISPATCH_TIMEOUT_BY_EFFORT_SECONDS["Large"])
        self.assertGreater(
            local_mcp.DISPATCH_TIMEOUT_BY_EFFORT_SECONDS["Large"],
            local_mcp.DISPATCH_TIMEOUT_BY_EFFORT_SECONDS["Medium"],
        )

    async def test_second_dispatch_to_same_repo_while_first_running_is_rejected(self):
        repo = self._make_repo()
        fake_proc = unittest.mock.MagicMock()
        fake_proc.pid = os.getpid()  # a PID that is genuinely alive for this test
        with unittest.mock.patch.object(
            local_mcp.dispatch_io, "resolve_model_for_tier",
            unittest.mock.AsyncMock(return_value=("claude/sonnet-4", ["claude/sonnet-4"])),
        ), unittest.mock.patch.object(local_mcp.dispatch_io, "spawn_cline_process", return_value=fake_proc):
            first_job_id = await local_mcp.dispatch_coding_task(1228, repo)
        self.assertFalse(first_job_id.startswith("ERROR"))

        second_result = await local_mcp.dispatch_coding_task(1228, repo)
        self.assertTrue(second_result.startswith("ERROR:"))
        self.assertIn(first_job_id, second_result)


class TestGetCodingTaskStatus(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_state_dir = local_mcp.CODING_TASK_STATE_DIR
        local_mcp.CODING_TASK_STATE_DIR = self._tmpdir

    def tearDown(self):
        local_mcp.CODING_TASK_STATE_DIR = self._orig_state_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_unknown_job_id_returns_error(self):
        result = local_mcp.get_coding_task_status("nope")
        self.assertTrue(result.startswith("ERROR:"))

    def test_still_running_job_reports_running_without_checking_commits(self):
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "running", "pid": os.getpid(),
            "model": "claude/sonnet-4", "repo_root": "C:/repo", "worktree_path": "C:/repo-wt",
            "branch_name": "at-1228-dispatch",
        })
        result = local_mcp.get_coding_task_status("job1")
        self.assertIn("status: running", result)

    def test_dead_pid_with_new_commits_beyond_base_transitions_to_complete(self):
        repo = _init_real_git_repo()
        try:
            base_branch = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
            ).stdout.strip()
            subprocess.run(["git", "checkout", "-q", "-b", "at-1228-dispatch"], cwd=repo, check=True)
            with open(os.path.join(repo, "new.txt"), "w", encoding="utf-8") as f:
                f.write("x\n")
            subprocess.run(["git", "add", "new.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "did the thing"], cwd=repo, check=True)

            local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
                "job_id": "job1", "at_id": 1228, "status": "running", "pid": 999999999,
                "model": "claude/sonnet-4", "repo_root": "C:/repo", "worktree_path": repo,
                "branch_name": "at-1228-dispatch", "base_branch": base_branch,
            })
            result = local_mcp.get_coding_task_status("job1")
            self.assertIn("status: complete", result)
            self.assertIn("did the thing", result)
            state = local_mcp.dispatch_io.read_job_state(self._tmpdir, "job1")
            self.assertEqual(state["status"], "complete")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_dead_pid_with_no_new_commits_transitions_to_failed(self):
        # Confirms the fix for a real bug found while writing this test: an
        # earlier version checked "does the branch have any commits at all,"
        # which is always true (every branch has at least the seed commit),
        # so the "failed" status was unreachable dead code. Comparing against
        # base_branch (base_branch..HEAD) is what actually distinguishes
        # "the job committed something" from "the job did nothing."
        repo = _init_real_git_repo()
        try:
            base_branch = subprocess.run(
                ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
            ).stdout.strip()
            subprocess.run(["git", "checkout", "-q", "-b", "at-1228-dispatch"], cwd=repo, check=True)
            # No new commits on the dispatch branch -- the job crashed or
            # produced nothing.

            local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
                "job_id": "job1", "at_id": 1228, "status": "running", "pid": 999999999,
                "model": "claude/sonnet-4", "repo_root": "C:/repo", "worktree_path": repo,
                "branch_name": "at-1228-dispatch", "base_branch": base_branch,
            })
            result = local_mcp.get_coding_task_status("job1")
            self.assertIn("status: failed", result)
            state = local_mcp.dispatch_io.read_job_state(self._tmpdir, "job1")
            self.assertEqual(state["status"], "failed")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

class TestPromoteCodingTask(unittest.TestCase):
    """Tests for promote_coding_task (AT-1230). Uses real temp git repos so
    that the git merge/worktree operations are exercised end-to-end, the same
    way TestGetCodingTaskStatus uses real repos for commit-count checks."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_state_dir = local_mcp.CODING_TASK_STATE_DIR
        local_mcp.CODING_TASK_STATE_DIR = self._tmpdir
        self._repos_to_clean = []

    def tearDown(self):
        local_mcp.CODING_TASK_STATE_DIR = self._orig_state_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        for repo in self._repos_to_clean:
            shutil.rmtree(repo, ignore_errors=True)

    def _make_repo_with_dispatch_branch(self):
        """Returns (repo_root, base_branch, worktree_path, branch_name).
        The dispatch branch has one commit beyond base and a worktree is
        attached at worktree_path -- the exact post-dispatch_coding_task
        state that promote_coding_task expects to receive."""
        repo = _init_real_git_repo()
        self._repos_to_clean.append(repo)

        base_branch = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()

        branch_name = "at-1228-dispatch"
        worktree_path = repo + "-wt-promote-test"
        self._repos_to_clean.append(worktree_path)

        ok, err = local_mcp.dispatch_io.create_worktree(repo, worktree_path, branch_name)
        self.assertTrue(ok, f"create_worktree failed: {err}")

        # Write a commit on the dispatch branch (inside the worktree)
        with open(os.path.join(worktree_path, "feature.txt"), "w", encoding="utf-8") as f:
            f.write("implemented\n")
        subprocess.run(["git", "add", "feature.txt"], cwd=worktree_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "feat: implement the feature"],
            cwd=worktree_path, check=True,
        )

        return repo, base_branch, worktree_path, branch_name

    # ------------------------------------------------------------------
    # Guard-clause tests (validator-at-the-boundary per exit evidence)
    # ------------------------------------------------------------------

    def test_unknown_job_id_returns_error(self):
        result = local_mcp.promote_coding_task("does-not-exist")
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("no job found", result)

    def test_running_job_rejected_with_clear_error(self):
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "running",
            "pid": os.getpid(), "model": "claude/sonnet-4",
            "repo_root": self._tmpdir, "worktree_path": self._tmpdir,
            "branch_name": "at-1228-dispatch", "base_branch": "main",
        })
        result = local_mcp.promote_coding_task("job1")
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("still running", result)
        self.assertIn("job1", result)

    def test_failed_job_rejected_with_clear_error(self):
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "failed",
            "model": "claude/sonnet-4", "repo_root": self._tmpdir,
            "worktree_path": self._tmpdir, "branch_name": "at-1228-dispatch",
        })
        result = local_mcp.promote_coding_task("job1")
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("failed", result)
        self.assertIn("job1", result)

    def test_already_promoted_job_rejected_with_clear_error(self):
        import time as _time
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "promoted",
            "model": "claude/sonnet-4", "repo_root": self._tmpdir,
            "worktree_path": self._tmpdir, "branch_name": "at-1228-dispatch",
            "promoted_at": _time.time(), "merged_sha": "abc123",
        })
        result = local_mcp.promote_coding_task("job1")
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("already promoted", result)
        self.assertIn("job1", result)

    # ------------------------------------------------------------------
    # Happy-path: real merge exercised end-to-end
    # ------------------------------------------------------------------

    def test_promote_complete_job_merges_branch_removes_worktree_updates_state(self):
        repo, base_branch, worktree_path, branch_name = (
            self._make_repo_with_dispatch_branch()
        )
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "complete",
            "model": "claude/sonnet-4",
            "repo_root": repo,
            "worktree_path": worktree_path,
            "branch_name": branch_name,
            "base_branch": base_branch,
        })

        result = local_mcp.promote_coding_task("job1")

        self.assertFalse(result.startswith("ERROR:"), f"unexpected error: {result}")
        self.assertIn("promoted", result)
        self.assertIn(branch_name, result)
        self.assertIn(base_branch, result)

        # Worktree must be removed
        self.assertFalse(os.path.isdir(worktree_path), f"worktree not removed: {worktree_path}")

        # Default branch must now contain the dispatch commit
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo, capture_output=True, text=True,
        )
        self.assertIn("implement the feature", log_result.stdout)

        # Job state must reflect promotion
        state = local_mcp.dispatch_io.read_job_state(self._tmpdir, "job1")
        self.assertEqual(state["status"], "promoted")
        self.assertIn("merged_sha", state)
        self.assertEqual(state["merged_into"], base_branch)
        self.assertTrue(state.get("worktree_removed"))

    def test_promote_complete_job_no_base_branch_falls_back_to_repo_head(self):
        """When base_branch is not recorded in job state (edge case from older
        dispatches), promote_coding_task falls back to querying the repo's
        current HEAD branch."""
        repo, _base_branch, worktree_path, branch_name = (
            self._make_repo_with_dispatch_branch()
        )
        # Write state WITHOUT base_branch
        local_mcp.dispatch_io.write_job_state(self._tmpdir, "job1", {
            "job_id": "job1", "at_id": 1228, "status": "complete",
            "model": "claude/sonnet-4",
            "repo_root": repo,
            "worktree_path": worktree_path,
            "branch_name": branch_name,
            # base_branch intentionally omitted
        })

        result = local_mcp.promote_coding_task("job1")
        self.assertFalse(result.startswith("ERROR:"), f"unexpected error: {result}")

        state = local_mcp.dispatch_io.read_job_state(self._tmpdir, "job1")
        self.assertEqual(state["status"], "promoted")


if __name__ == "__main__":
    unittest.main()
