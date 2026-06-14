#!/usr/bin/env python3
"""
Unit tests for the AT-1142 / CB-15 server-staleness observability additions
in mcp-server/local-mcp.py: `_get_server_commit_sha` and the `/health` route
handler `_health`.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_health.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import subprocess
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

_get_server_commit_sha = local_mcp._get_server_commit_sha
_health = local_mcp._health


class TestGetServerCommitSha(unittest.TestCase):
    def test_returns_short_sha_for_real_repo(self):
        sha = _get_server_commit_sha()
        # The real skein-toolkit working tree is a git repo, so this should
        # succeed and match `git rev-parse --short HEAD` run the same way.
        expected = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=local_mcp._SERVER_REPO_ROOT,
            capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(sha, expected)
        self.assertNotEqual(sha, "unknown")
        self.assertRegex(sha, r"^[0-9a-f]{4,40}$")

    def test_nonzero_returncode_yields_unknown(self):
        fake_result = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--short", "HEAD"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )
        with patch.object(local_mcp.subprocess, "run", return_value=fake_result):
            self.assertEqual(_get_server_commit_sha(), "unknown")

    def test_subprocess_exception_yields_unknown(self):
        with patch.object(local_mcp.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertEqual(_get_server_commit_sha(), "unknown")


class TestHealthEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_health_reports_status_and_commit(self):
        response = await _health(request=None)
        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn('"status":"ok"', body.replace(" ", ""))
        # /health must report the SHA the process was STARTED with (frozen at
        # import time), not whatever `git rev-parse HEAD` returns right now --
        # otherwise a stale in-memory process would always self-report as
        # "current" and the staleness check would be meaningless.
        self.assertIn(local_mcp._SERVER_STARTUP_COMMIT_SHA, body)

    async def test_health_reports_unknown_when_sha_unavailable(self):
        with patch.object(local_mcp, "_SERVER_STARTUP_COMMIT_SHA", "unknown"):
            response = await _health(request=None)
        body = response.body.decode("utf-8")
        self.assertIn('"commit":"unknown"', body.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
