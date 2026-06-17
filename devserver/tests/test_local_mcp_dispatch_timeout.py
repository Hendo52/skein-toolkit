#!/usr/bin/env python3
"""
Unit tests for the orchestrator step-dispatch timeout (CB-10(a), 2026-06-11)
in scripts/local-mcp.py: `ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS` and
`_cf_complete_once`'s named handling of `httpx.TimeoutException`.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_dispatch_timeout.py
(or `python -m unittest scripts.tests.test_local_mcp_dispatch_timeout` from repo root)
"""

import importlib.util
import os
import unittest
from unittest.mock import patch

import httpx

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


class TestDispatchTimeoutConstant(unittest.TestCase):
    def test_dispatch_timeout_exceeds_general_cf_timeout(self):
        self.assertGreater(
            local_mcp.ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS,
            local_mcp.CF_FORWARD_TIMEOUT_SECONDS)

    def test_dispatch_timeout_value(self):
        self.assertEqual(local_mcp.ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS, 590.0)


class _RaisingAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ReadTimeout("simulated read timeout")


class TestCfCompleteOnceTimeoutHandling(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_returns_none_and_logs_named_message(self):
        body = {
            "model": "@cf/moonshotai/kimi-k2.6",
            "messages": [{"role": "user", "content": "x" * 100}],
            "stream": True,
        }
        with patch.object(local_mcp.httpx, "AsyncClient", _RaisingAsyncClient), \
                patch("sys.stderr") as mock_stderr:
            result = await local_mcp._cf_complete_once("https://example.invalid", "Bearer token", body)

        self.assertIsNone(result)
        logged = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
        self.assertIn("step-dispatch call timed out", logged)
        self.assertIn(f"{local_mcp.ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS:.0f}s", logged)
        self.assertIn("kimi-k2.6", logged)


if __name__ == "__main__":
    unittest.main()
