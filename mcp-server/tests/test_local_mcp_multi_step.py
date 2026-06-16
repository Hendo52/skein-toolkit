#!/usr/bin/env python3
"""
Regression tests for _strip_cline_injected_context and _detect_multi_step_ask.
AT-1174 / BUG-SR-1.4 (2026-06-15 incident: short real question + large injected
context triggered false-positive multi-step detection).

Run with:
  cd skein-toolkit
  .venv/Scripts/python.exe mcp-server/tests/test_local_mcp_multi_step.py
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))
_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

_strip = local_mcp._strip_cline_injected_context
_detect = local_mcp._detect_multi_step_ask


class TestStripClineInjectedContext(unittest.TestCase):
    def test_strips_environment_details_block(self):
        msg = (
            "Which subsystems did we extract?\n"
            "<environment_details>\n"
            "open files: ...\n"
            "AT-1167 analyze create implement install\n"
            "</environment_details>"
        )
        result = _strip(msg)
        self.assertEqual(result, "Which subsystems did we extract?")

    def test_strips_recently_modified_files(self):
        msg = (
            "Simple question.\n"
            "Recently Modified Files\n"
            "  architecture-docs/global/ai-task-queue.md\n"
            "  some/other/file.md\n"
        )
        result = _strip(msg)
        self.assertEqual(result, "Simple question.")

    def test_passthrough_clean_message(self):
        msg = "What is the current status of AT-1076?"
        self.assertEqual(_strip(msg), msg)

    def test_empty_after_strip_returns_empty(self):
        msg = "<environment_details>everything is injected</environment_details>"
        self.assertEqual(_strip(msg), "")

    def test_multiline_environment_details_fully_removed(self):
        msg = (
            "Short question.\n"
            "<environment_details>\n"
            "Line 1\nLine 2\nLine 3\nanalyze create implement install setup test\n"
            "</environment_details>\n"
            "After block."
        )
        result = _strip(msg)
        self.assertNotIn("<environment_details>", result)
        self.assertIn("Short question.", result)
        self.assertIn("After block.", result)


class TestDetectMultiStepAfterStrip(unittest.TestCase):
    def test_incident_shape_no_longer_triggers(self):
        """Regression for 2026-06-15 incident (BUG-SR-1.4): short real question +
        large injected context with action verbs must NOT trigger multi-step detection
        after stripping."""
        real_question = "Which subsystems from Odysseus did we extract?"
        injected = (
            "<environment_details>\n"
            "Recently Modified Files: architecture-docs/global/ai-task-queue.md\n"
            "AT-1167: analyze create implement install setup test the AT task ledger\n"
            "Search all files for AT-1167. Check git log. List archive directory. "
            "Check tasks-to-add.json. Search architecture-docs. Verify if AT-1167 is tracked.\n"
            "</environment_details>"
        )
        full_message = real_question + "\n" + injected
        stripped = _strip(full_message)
        is_multi, reason = _detect(stripped)
        self.assertFalse(is_multi, f"False positive after strip: {reason!r}")

    def test_genuine_multi_step_still_detected(self):
        """Real multi-step asks in the architect's own text must still be caught.
        Must be >= 350 chars (_MULTI_STEP_MIN_CHARS) to clear the length floor."""
        msg = (
            "Search the repo for all uses of BisectorClip and analyze each call site to "
            "understand what data it consumes. Then create a detailed refactoring plan that "
            "separates the clip algorithm from the zone classification concerns. Then implement "
            "the first step of the plan (extract the bisector-plane intersection math into a "
            "standalone module) and test it with a focused unit test. Finally install the "
            "refactored module into the LoftGeometry pipeline and verify integration by running "
            "the existing BisectorClipTest suite to confirm no regressions."
        )
        self.assertGreaterEqual(len(msg), 350, "Test string must clear _MULTI_STEP_MIN_CHARS=350")
        stripped = _strip(msg)
        is_multi, reason = _detect(stripped)
        self.assertTrue(is_multi, "Genuine multi-step ask not detected after strip")

    def test_clean_short_question_not_triggered(self):
        is_multi, _ = _detect(_strip("What does AT-975 do?"))
        self.assertFalse(is_multi)


if __name__ == "__main__":
    unittest.main()
