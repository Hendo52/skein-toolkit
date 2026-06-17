#!/usr/bin/env python3
"""
Unit tests for the request-mutation logging added to
`_sanitize_messages_for_cf` and `_normalize_cf_messages` in
scripts/local-mcp.py.

Both functions mutate the request body CF actually receives
(content: null -> "", and array-typed content -> flattened string,
respectively). Previously this happened with zero observability --
indistinguishable from the client having sent that content itself. Both
now print a one-line [cfproxy] summary to stderr whenever they actually
change something, and stay silent when there is nothing to change.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_message_normalization.py
(or `python -m unittest scripts.tests.test_local_mcp_message_normalization` from repo root)
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


class TestSanitizeMessagesForCf(unittest.TestCase):
    def test_null_content_coerced_and_logged(self):
        body = {"messages": [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        ]}
        result, logged = _stderr_log(local_mcp._sanitize_messages_for_cf, body)

        self.assertEqual(result["messages"][0]["content"], "")
        self.assertIn("coerced content: null", logged)
        self.assertIn("#0 (assistant)", logged)

    def test_multiple_null_content_messages_all_listed(self):
        body = {"messages": [
            {"role": "assistant", "content": None},
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": None},
        ]}
        result, logged = _stderr_log(local_mcp._sanitize_messages_for_cf, body)

        self.assertEqual(result["messages"][0]["content"], "")
        self.assertEqual(result["messages"][1]["content"], "hello")
        self.assertEqual(result["messages"][2]["content"], "")
        self.assertIn("2 message(s)", logged)
        self.assertIn("#0 (assistant)", logged)
        self.assertIn("#2 (tool)", logged)

    def test_no_null_content_is_silent(self):
        body = {"messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]}
        result, logged = _stderr_log(local_mcp._sanitize_messages_for_cf, body)

        self.assertEqual(result, body)
        self.assertEqual(logged, "")


class TestNormalizeCfMessages(unittest.TestCase):
    def test_text_blocks_flattened_and_logged(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]},
        ]
        result, logged = _stderr_log(local_mcp._normalize_cf_messages, messages)

        self.assertEqual(result[0]["content"], "hello\nworld")
        self.assertIn("flattened array-typed content", logged)
        self.assertIn("#0 (user: text+text)", logged)

    def test_image_block_becomes_placeholder_and_is_logged(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "look:"}, {"type": "image_url", "image_url": {"url": "data:..."}}]},
        ]
        result, logged = _stderr_log(local_mcp._normalize_cf_messages, messages)

        self.assertEqual(result[0]["content"], "look:\n[image]")
        self.assertIn("#0 (user: text+image_url)", logged)

    def test_multiple_messages_all_listed(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "a"}]},
            {"role": "assistant", "content": "plain string, untouched"},
            {"role": "tool", "content": [{"type": "tool_result", "content": "ok"}]},
        ]
        result, logged = _stderr_log(local_mcp._normalize_cf_messages, messages)

        self.assertEqual(result[0]["content"], "a")
        self.assertEqual(result[1]["content"], "plain string, untouched")
        self.assertEqual(result[2]["content"], "[tool result: ok]")
        self.assertIn("2 message(s)", logged)
        self.assertIn("#0 (user: text)", logged)
        self.assertIn("#2 (tool: tool_result)", logged)

    def test_no_array_content_is_silent(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result, logged = _stderr_log(local_mcp._normalize_cf_messages, messages)

        self.assertEqual(result, messages)
        self.assertEqual(logged, "")


if __name__ == "__main__":
    unittest.main()
