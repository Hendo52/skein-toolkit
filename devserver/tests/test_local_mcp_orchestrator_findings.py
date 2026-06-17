#!/usr/bin/env python3
"""
Unit tests for the OQ-263 / CB-10(b) findings carry-forward mechanism in
scripts/local-mcp.py: `_extract_step_finding`, `_format_findings_block`, the
`findings` field on `_new_orchestrator_state`, and `_build_step_dispatch_body`
prepending the "Prior step findings" block.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_orchestrator_findings.py
(or `python -m unittest scripts.tests.test_local_mcp_orchestrator_findings` from repo root)
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


class TestNewOrchestratorStateFindings(unittest.TestCase):
    def test_findings_field_starts_empty(self):
        state = local_mcp._new_orchestrator_state(["a", "b"], "reason")
        self.assertEqual(state["findings"], [])


class TestExtractStepFinding(unittest.TestCase):
    def test_extracts_finding_line(self):
        summary = (
            "I read the roadmap doc and confirmed the value.\n"
            "FINDING: The per-call cost range for kimi-k2.6 is $0.0003-$0.003 USD per call.\n"
        )
        self.assertEqual(
            local_mcp._extract_step_finding(summary),
            "The per-call cost range for kimi-k2.6 is $0.0003-$0.003 USD per call.")

    def test_falls_back_to_full_summary_when_absent(self):
        summary = "Edited the file and ran the build; no standalone fact to report."
        self.assertEqual(local_mcp._extract_step_finding(summary), summary)

    def test_falls_back_summary_is_capped(self):
        summary = "x" * (local_mcp.ORCHESTRATOR_FINDING_MAX_CHARS + 500)
        result = local_mcp._extract_step_finding(summary)
        self.assertEqual(len(result), local_mcp.ORCHESTRATOR_FINDING_MAX_CHARS)

    def test_finding_line_is_capped(self):
        summary = "FINDING: " + ("y" * (local_mcp.ORCHESTRATOR_FINDING_MAX_CHARS + 500))
        result = local_mcp._extract_step_finding(summary)
        self.assertEqual(len(result), local_mcp.ORCHESTRATOR_FINDING_MAX_CHARS)

    def test_strips_whitespace_around_finding(self):
        summary = "Done.\nFINDING:   trailing spaces matter not   \n"
        self.assertEqual(local_mcp._extract_step_finding(summary), "trailing spaces matter not")


class TestFormatFindingsBlock(unittest.TestCase):
    def test_empty_findings_returns_empty_string(self):
        self.assertEqual(local_mcp._format_findings_block([]), "")

    def test_renders_oldest_first_with_step_labels(self):
        findings = [
            {"step": 1, "total": 3, "text": "first fact"},
            {"step": 2, "total": 3, "text": "second fact"},
        ]
        block = local_mcp._format_findings_block(findings)
        self.assertTrue(block.startswith("Prior step findings:\n"))
        first_pos = block.index("Step 1/3: first fact")
        second_pos = block.index("Step 2/3: second fact")
        self.assertLess(first_pos, second_pos)
        self.assertTrue(block.endswith("\n\n"))

    def test_oldest_findings_rotated_out_when_over_budget(self):
        big = "z" * (local_mcp.ORCHESTRATOR_FINDINGS_CHAR_BUDGET // 2 + 100)
        findings = [
            {"step": 1, "total": 3, "text": big},
            {"step": 2, "total": 3, "text": big},
            {"step": 3, "total": 3, "text": big},
        ]
        block = local_mcp._format_findings_block(findings)
        self.assertNotIn("Step 1/3", block)
        self.assertIn("Step 3/3", block)

    def test_newest_finding_kept_even_if_alone_exceeds_budget(self):
        huge = "w" * (local_mcp.ORCHESTRATOR_FINDINGS_CHAR_BUDGET + 1000)
        findings = [{"step": 1, "total": 1, "text": huge}]
        block = local_mcp._format_findings_block(findings)
        self.assertIn("Step 1/1", block)


class TestRecordResolvedStepFinding(unittest.TestCase):
    # CB-12 (2026-06-12): when an AMBIGUOUS-paused step is resolved via
    # architect Option A, _record_resolved_step_finding must append a finding
    # for that step -- otherwise it silently drops out of the "Prior step
    # findings" carry-forward block for every later step.

    def _paused_state(self, steps, current, ambiguity_last_summary=None, ambiguity_oq_id=None):
        state = local_mcp._new_orchestrator_state(steps, "test", model="@cf/moonshotai/kimi-k2.6")
        state.update(current=current, status="paused_for_oq",
                      ambiguity_raised_for_step=current,
                      ambiguity_last_summary=ambiguity_last_summary,
                      ambiguity_oq_id=ambiguity_oq_id)
        return state

    def test_records_finding_from_finding_line_in_paused_summary(self):
        state = self._paused_state(
            steps=["step one", "step two", "step three"],
            current=2,
            ambiguity_last_summary=(
                "Found the through-proxy result.\n"
                "FINDING: through-proxy result was completion_tokens=6324 in 121s."),
            ambiguity_oq_id="OQ-259",
        )
        local_mcp._record_resolved_step_finding(state, 2)
        self.assertEqual(len(state["findings"]), 1)
        self.assertEqual(state["findings"][0]["step"], 2)
        self.assertEqual(state["findings"][0]["total"], 3)
        self.assertEqual(state["findings"][0]["text"], "through-proxy result was completion_tokens=6324 in 121s.")

    def test_falls_back_to_full_summary_when_no_finding_line(self):
        state = self._paused_state(
            steps=["step one", "step two"],
            current=1,
            ambiguity_last_summary="Read the section and reported it back; no files changed.",
            ambiguity_oq_id="OQ-260",
        )
        local_mcp._record_resolved_step_finding(state, 1)
        self.assertEqual(state["findings"][0]["text"], "Read the section and reported it back; no files changed.")

    def test_synthesizes_placeholder_when_summary_empty(self):
        state = self._paused_state(
            steps=["do the thing"],
            current=1,
            ambiguity_last_summary="",
            ambiguity_oq_id="OQ-261",
        )
        local_mcp._record_resolved_step_finding(state, 1)
        text = state["findings"][0]["text"]
        self.assertIn("OQ-261", text)
        self.assertIn("Option A", text)
        self.assertIn("do the thing", text)

    def test_synthesized_placeholder_without_oq_id(self):
        state = self._paused_state(steps=["do the thing"], current=1, ambiguity_last_summary=None, ambiguity_oq_id=None)
        local_mcp._record_resolved_step_finding(state, 1)
        text = state["findings"][0]["text"]
        self.assertIn("an architect OQ", text)

    def test_appends_to_existing_findings_preserving_order(self):
        state = self._paused_state(
            steps=["a", "b", "c"], current=2,
            ambiguity_last_summary="FINDING: fact from step 2",
            ambiguity_oq_id="OQ-259")
        state["findings"] = [{"step": 1, "total": 3, "text": "fact from step 1"}]
        local_mcp._record_resolved_step_finding(state, 2)
        self.assertEqual([f["step"] for f in state["findings"]], [1, 2])


class TestBuildStepDispatchBodyFindings(unittest.TestCase):
    def test_findings_block_prepended_to_step_prompt(self):
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        findings = [{"step": 1, "total": 2, "text": "a fact from step 1"}]
        body = local_mcp._build_step_dispatch_body(original_body, [], "step two", 2, 2, findings)
        user_msg = body["messages"][1]["content"]
        self.assertTrue(user_msg.startswith("Prior step findings:\n"))
        self.assertIn("a fact from step 1", user_msg)
        self.assertIn("Step 2 of 2 -- do ONLY this step: step two", user_msg)

    def test_no_findings_omits_block(self):
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        body = local_mcp._build_step_dispatch_body(original_body, [], "step one", 1, 2, [])
        user_msg = body["messages"][1]["content"]
        self.assertEqual(user_msg, "Step 1 of 2 -- do ONLY this step: step one")

    def test_findings_default_argument_omits_block(self):
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        body = local_mcp._build_step_dispatch_body(original_body, [], "step one", 1, 2)
        user_msg = body["messages"][1]["content"]
        self.assertEqual(user_msg, "Step 1 of 2 -- do ONLY this step: step one")


if __name__ == "__main__":
    unittest.main()
