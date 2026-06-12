#!/usr/bin/env python3
"""
Unit tests for the orchestrator resume mechanism in mcp-server/local-mcp.py
(CB-9 / OQ-262 Option C, 2026-06-11): `_orchestrator_key`'s
`[orchestrator-key: ...]` marker path, `_format_resume_prompt`, and the
`model` field on `_new_orchestrator_state`.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_orchestrator_resume.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import hashlib
import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


class TestOrchestratorKeyMarker(unittest.TestCase):
    def test_key_from_hash_without_marker(self):
        text = "Please do A, then B, then C."
        expected = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]
        self.assertEqual(local_mcp._orchestrator_key(text), expected)

    def test_key_from_embedded_marker(self):
        key = "0123456789abcdef"
        text = f"[orchestrator-key: {key}] continue -- resuming the paused 3-step run."
        self.assertEqual(local_mcp._orchestrator_key(text), key)

    def test_marker_key_ignores_surrounding_text(self):
        key = "fedcba9876543210"
        text_a = f"[orchestrator-key: {key}] continue -- step 2/3 resolved, proceed with step 3/3."
        text_b = f"[orchestrator-key: {key}] continue -- something else entirely, a much longer message."
        self.assertEqual(local_mcp._orchestrator_key(text_a), local_mcp._orchestrator_key(text_b))
        self.assertEqual(local_mcp._orchestrator_key(text_a), key)


class TestNewOrchestratorStateModel(unittest.TestCase):
    def test_model_field_stored(self):
        state = local_mcp._new_orchestrator_state(["a"], "reason", model="@cf/moonshotai/kimi-k2.6")
        self.assertEqual(state["model"], "@cf/moonshotai/kimi-k2.6")

    def test_model_field_defaults_to_none(self):
        state = local_mcp._new_orchestrator_state(["a"], "reason")
        self.assertIsNone(state["model"])


class TestFormatResumePrompt(unittest.TestCase):
    def _paused_state(self, current=2):
        state = local_mcp._new_orchestrator_state(
            ["step one", "step two", "step three"], "test", model="@cf/moonshotai/kimi-k2.6")
        state.update(current=current, status="paused_for_oq")
        return state

    def test_embeds_orchestrator_key_marker_that_round_trips(self):
        state = self._paused_state()
        prompt = local_mcp._format_resume_prompt("abc123def4567890", state)
        self.assertIn("[orchestrator-key: abc123def4567890]", prompt)
        self.assertEqual(local_mcp._orchestrator_key(prompt), "abc123def4567890")

    def test_describes_resolved_step_and_next_step(self):
        state = self._paused_state(current=2)
        prompt = local_mcp._format_resume_prompt("abc123def4567890", state)
        self.assertIn("Step 2/3 is resolved", prompt)
        self.assertIn("step 3/3: step three", prompt)

    def test_final_step_resolved_has_no_next_step(self):
        state = self._paused_state(current=3)
        prompt = local_mcp._format_resume_prompt("abc123def4567890", state)
        self.assertIn("Step 3/3 is resolved", prompt)
        self.assertIn("no further steps", prompt)

    def test_contains_continue_keyword_for_gate_matching(self):
        state = self._paused_state()
        prompt = local_mcp._format_resume_prompt("abc123def4567890", state)
        self.assertRegex(prompt, local_mcp._ORCHESTRATOR_CONTINUE_RE)


if __name__ == "__main__":
    unittest.main()
