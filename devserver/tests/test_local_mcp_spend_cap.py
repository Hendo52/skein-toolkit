#!/usr/bin/env python3
"""
Unit tests for the two-tier daily CF spend protection in scripts/local-mcp.py:

- _spend_review_threshold_exceeded / _spend_review_flag_message: non-blocking,
  visible-in-chat warning once spend crosses DAILY_SPEND_REVIEW_THRESHOLD_USD.
- _spend_hard_cap_exceeded / _spend_hard_cap_error_message: true circuit
  breaker (refuses further CF requests) once spend crosses DAILY_HARD_CAP_USD.

Restored 2026-06-14 after commit b864277b (2026-06-11) converted the original
$2 USD hard cap into a stderr-only review flag -- which proved too easy to
miss mid-session. The hard cap now sits well above the review threshold so
normal troubleshooting never hits it, while the review threshold still warns
early.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_spend_cap.py
"""

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


def _spend_file_with(total_usd: float) -> str:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"date": local_mcp._today_utc(), "total_usd": total_usd, "requests": 1}, tmp)
    tmp.close()
    return tmp.name


class TestSpendCapConstants(unittest.TestCase):
    def test_hard_cap_is_above_review_threshold(self):
        self.assertGreater(local_mcp.DAILY_HARD_CAP_USD, local_mcp.DAILY_SPEND_REVIEW_THRESHOLD_USD)


class TestSpendReviewThreshold(unittest.TestCase):
    def test_not_exceeded_below_threshold(self):
        path = _spend_file_with(0.0)
        try:
            with patch.object(local_mcp, "_SPEND_FILE", path):
                exceeded, spend = asyncio.run(local_mcp._spend_review_threshold_exceeded())
            self.assertFalse(exceeded)
            self.assertEqual(spend["total_usd"], 0.0)
        finally:
            os.unlink(path)

    def test_exceeded_above_threshold(self):
        path = _spend_file_with(local_mcp.DAILY_SPEND_REVIEW_THRESHOLD_USD + 0.01)
        try:
            with patch.object(local_mcp, "_SPEND_FILE", path):
                exceeded, _ = asyncio.run(local_mcp._spend_review_threshold_exceeded())
            self.assertTrue(exceeded)
        finally:
            os.unlink(path)


class TestSpendHardCap(unittest.TestCase):
    def test_not_exceeded_between_review_and_hard_cap(self):
        mid = (local_mcp.DAILY_SPEND_REVIEW_THRESHOLD_USD + local_mcp.DAILY_HARD_CAP_USD) / 2
        path = _spend_file_with(mid)
        try:
            with patch.object(local_mcp, "_SPEND_FILE", path):
                review_exceeded, _ = asyncio.run(local_mcp._spend_review_threshold_exceeded())
                hard_exceeded, _ = asyncio.run(local_mcp._spend_hard_cap_exceeded())
            self.assertTrue(review_exceeded)
            self.assertFalse(hard_exceeded)
        finally:
            os.unlink(path)

    def test_exceeded_above_hard_cap(self):
        path = _spend_file_with(local_mcp.DAILY_HARD_CAP_USD + 0.01)
        try:
            with patch.object(local_mcp, "_SPEND_FILE", path):
                exceeded, spend = asyncio.run(local_mcp._spend_hard_cap_exceeded())
            self.assertTrue(exceeded)
        finally:
            os.unlink(path)


class TestSpendMessages(unittest.TestCase):
    def test_review_flag_message_is_non_blocking_and_mentions_hard_cap(self):
        spend = {"total_usd": local_mcp.DAILY_SPEND_REVIEW_THRESHOLD_USD, "requests": 1}
        msg = local_mcp._spend_review_flag_message(spend)

        self.assertIn("FLAG FOR REVIEW", msg)
        self.assertIn("does not block the request", msg)
        self.assertIn("CF_PROXY_DAILY_HARD_CAP_AUD", msg)
        # The stale "high spend no longer blocks requests" framing from
        # b864277b is gone now that a hard cap exists again.
        self.assertNotIn("no longer blocks requests", msg)

    def test_hard_cap_error_message_names_override_env_var(self):
        spend = {"total_usd": local_mcp.DAILY_HARD_CAP_USD, "requests": 99}
        msg = local_mcp._spend_hard_cap_error_message(spend)

        self.assertIn("hard cap reached", msg)
        self.assertIn("Refusing further CF requests", msg)
        self.assertIn("CF_PROXY_DAILY_HARD_CAP_AUD", msg)


if __name__ == "__main__":
    unittest.main()
