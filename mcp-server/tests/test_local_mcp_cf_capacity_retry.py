#!/usr/bin/env python3
"""
Unit tests for the CB-23 fix (2026-06-18) in mcp-server/local-mcp.py:
_cf_proxy's non-streaming path now retries CF's transient 429 "Capacity
temporarily exceeded" error within the existing degenerate-response retry
budget, instead of surfacing it to the client immediately like a genuine
(non-transient) auth/permission failure.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_cf_capacity_retry.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import json
import os
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

from starlette.requests import Request as StarletteRequest  # noqa: E402


def _make_request(body: dict) -> StarletteRequest:
    """Build a minimal real Starlette Request carrying `body` as its JSON
    payload, with path_params set the way the route would inject them --
    avoids hand-rolling a fake duck-typed Request that could silently drift
    from what _cf_proxy actually calls on the real thing."""
    payload = json.dumps(body).encode("utf-8")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/cfproxy/test-account/v1/chat/completions",
        "headers": [(b"authorization", b"Bearer test-token"), (b"content-type", b"application/json")],
        "path_params": {"account_id": "test-account", "rest": "v1/chat/completions"},
        "query_string": b"",
    }
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return StarletteRequest(scope, receive)


# A body shaped so _cf_proxy's pre-forward logic is a no-op: a prior
# assistant tool_calls entry makes _conversation_has_tool_use True, skipping
# the multi-step-ask planner-pass detection entirely, and the messages don't
# match any orchestrator-step-dispatch shape, so _handle_orchestrated_request
# returns None immediately. What's left to exercise is exactly the retry
# logic this test targets.
_PASSTHROUGH_BODY = {
    "model": "@cf/moonshotai/kimi-k2.6",
    "stream": False,
    "messages": [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        {"role": "user", "content": "now do the next thing"},
    ],
}


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text or json.dumps(self._json_body)

    def json(self):
        return self._json_body


class _ScriptedAsyncClient:
    """Fake httpx.AsyncClient.post() that returns a scripted sequence of
    responses, one per call -- the minimum needed to prove a retry loop
    actually re-issues the request rather than giving up after one 429."""
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, url, json=None, headers=None, **kwargs):
        _ScriptedAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        idx = len(_ScriptedAsyncClient.calls) - 1
        return _ScriptedAsyncClient.responses[min(idx, len(_ScriptedAsyncClient.responses) - 1)]


class TestCfProxyCapacityRetry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _ScriptedAsyncClient.calls = []

    async def test_429_then_success_retries_and_returns_the_success(self):
        _ScriptedAsyncClient.responses = [
            _FakeResponse(429, {"errors": [{"message": "AiError: Capacity temporarily exceeded, please try again.", "code": 3040}]}),
            _FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": "ok, done"}}]}),
        ]
        with patch.object(local_mcp.httpx, "AsyncClient", _ScriptedAsyncClient), \
                patch.object(local_mcp.asyncio, "sleep") as mock_sleep, \
                patch("sys.stderr"):
            response = await local_mcp._cf_proxy(_make_request(_PASSTHROUGH_BODY))

        self.assertEqual(len(_ScriptedAsyncClient.calls), 2, "expected exactly one retry after the 429")
        mock_sleep.assert_awaited()
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body)
        self.assertEqual(body["choices"][0]["message"]["content"], "ok, done")

    async def test_429_exhausts_retry_budget_and_surfaces_honest_error(self):
        all_429 = _FakeResponse(429, {"errors": [{"message": "AiError: Capacity temporarily exceeded, please try again.", "code": 3040}]})
        _ScriptedAsyncClient.responses = [all_429]  # every call (idx clamped) returns 429
        with patch.object(local_mcp.httpx, "AsyncClient", _ScriptedAsyncClient), \
                patch.object(local_mcp.asyncio, "sleep") as mock_sleep, \
                patch("sys.stderr"):
            response = await local_mcp._cf_proxy(_make_request(_PASSTHROUGH_BODY))

        expected_attempts = len(local_mcp.CF_CAPACITY_RETRY_BACKOFF_SECONDS) + 1
        self.assertEqual(len(_ScriptedAsyncClient.calls), expected_attempts)
        self.assertEqual(mock_sleep.await_count, expected_attempts - 1)
        self.assertEqual(response.status_code, 429)
        body = json.loads(response.body)
        self.assertIn("429", body["error"]["message"])

    async def test_500_then_success_retries_and_returns_the_success(self):
        """Real incident (AT-1196, 2026-06-20): a CF 'Internal server error'
        (status 500, code 8004) hit mid-dispatch and lost a long, otherwise-
        successful run -- this status code wasn't retried at all before this
        fix (only 429 was). Mirrors the 429 retry test exactly."""
        _ScriptedAsyncClient.responses = [
            _FakeResponse(500, {"errors": [{"message": "AiError: AiError: Internal server error", "code": 8004}]}),
            _FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": "ok, done"}}]}),
        ]
        with patch.object(local_mcp.httpx, "AsyncClient", _ScriptedAsyncClient), \
                patch.object(local_mcp.asyncio, "sleep") as mock_sleep, \
                patch("sys.stderr"):
            response = await local_mcp._cf_proxy(_make_request(_PASSTHROUGH_BODY))

        self.assertEqual(len(_ScriptedAsyncClient.calls), 2, "expected exactly one retry after the 500")
        mock_sleep.assert_awaited()
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.body)
        self.assertEqual(body["choices"][0]["message"]["content"], "ok, done")

    async def test_401_does_not_retry_and_fails_immediately(self):
        """Non-transient auth failures must still fail on the first attempt --
        the 429 carve-out must not accidentally swallow genuine permission
        errors into a multi-attempt retry loop."""
        _ScriptedAsyncClient.responses = [
            _FakeResponse(401, {"errors": [{"message": "Authentication error", "code": 10000}]}),
        ]
        with patch.object(local_mcp.httpx, "AsyncClient", _ScriptedAsyncClient), \
                patch.object(local_mcp.asyncio, "sleep") as mock_sleep, \
                patch("sys.stderr"):
            response = await local_mcp._cf_proxy(_make_request(_PASSTHROUGH_BODY))

        self.assertEqual(len(_ScriptedAsyncClient.calls), 1, "401 must not be retried")
        mock_sleep.assert_not_awaited()
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
