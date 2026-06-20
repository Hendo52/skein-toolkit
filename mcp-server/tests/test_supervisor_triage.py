#!/usr/bin/env python3
"""
Unit tests for supervisor_triage.py (AT-1233). Uses real log text captured
this session from actual failures, not synthetic placeholder strings --
each test traces to a specific real incident so the patterns are verified
against what actually happened, not an imagined version of it.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_supervisor_triage.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "supervisor_triage.py"))

_spec = importlib.util.spec_from_file_location("supervisor_triage", _MODULE_PATH)
supervisor_triage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(supervisor_triage)


class TestRecommendAction(unittest.TestCase):
    def test_empty_log_raises_oq(self):
        action, reasoning = supervisor_triage.recommend_action("")
        self.assertEqual(action, "raise_oq")
        self.assertIn("no log tail", reasoning)

    def test_anthropic_credit_exhaustion_recommends_retry(self):
        # Real text from this session's AT-1162 dispatch_coding_task run.
        log = (
            'error: litellm.BadRequestError: AnthropicException - b\'{"type":"error",'
            '"error":{"type":"invalid_request_error","message":"Your credit balance is '
            'too low to access the Anthropic API. Please go to Plans & Billing to upgrade '
            'or purchase credits."}\'. Received Model Group=claude/sonnet-4'
        )
        action, reasoning = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "retry")
        self.assertIn("credit balance", reasoning.lower())

    def test_cf_429_recommends_retry(self):
        log = "HTTP/1.1 429 Too Many Requests -- capacity exceeded for this model"
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "retry")

    def test_cf_500_internal_server_error_recommends_retry(self):
        # Real text from this session (AT-1196, 2026-06-20): a long,
        # otherwise-successful dispatch lost all its work to this exact
        # error with no retry at the time -- should now recommend retry,
        # not raise_oq, for the same reason 429 does.
        log = (
            '[cfproxy] CF API error (status 500): {"errors":[{"message":'
            '"AiError: AiError: Internal server error","code":8004}]}'
        )
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "retry")

    def test_litellm_down_recommends_restart_dependency(self):
        # Real text from this session's toolchain-doctor.ps1 output.
        log = "PROBLEM: LiteLLM is not responding on http://127.0.0.1:4000."
        action, reasoning = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "restart_dependency")
        self.assertIn("toolchain-down", reasoning)

    def test_execution_policy_block_recommends_restart_dependency(self):
        # Real text from this session's first AT-1228 smoke-test failure.
        log = (
            "File C:\\...\\run-cline.ps1 cannot be loaded because running scripts is "
            "disabled on this system. For more information, see about_Execution_Policies"
        )
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "restart_dependency")

    def test_execution_policy_block_with_real_line_wrapping_still_matches(self):
        # Regression test: found via this AT's own real dry run against an
        # actual captured job log (at1230-184de386). PowerShell console
        # output wraps at terminal width, so the real text was "running
        # scripts is \ndisabled on this system" -- the embedded newline
        # broke a naive substring match and silently produced raise_oq
        # instead of the correct restart_dependency.
        log = (
            "File C:\\Users\\jakeh\\source\\repos\\skein-toolkit\\mcp-server\\run-cline.ps1 "
            "cannot be loaded because running scripts is \ndisabled on this system. For more "
            "information, see about_Execution_Policies at \nhttps:/go.microsoft.com/fwlink/?LinkID=135170."
        )
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "restart_dependency")

    def test_powershell7_syntax_via_legacy_interpreter_recommends_restart_dependency(self):
        # Real text from this session's second AT-1228 smoke-test failure.
        log = "Unexpected token '?.StatusCode.value__' in expression or statement."
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "restart_dependency")

    def test_empty_response_from_llm_recommends_retry(self):
        # Real text from this session's AT-1194 aider-evaluation failure.
        log = "Empty response received from LLM. Check your provider account?"
        action, reasoning = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "retry")
        self.assertIn("transient-failure", reasoning)

    def test_restart_dependency_checked_before_retry_on_overlapping_text(self):
        # A log containing BOTH a toolchain-down signature and a generic
        # "connection error" substring should still resolve to
        # restart_dependency -- fixing the toolchain is the prerequisite,
        # retrying first would just fail again for the same reason.
        log = "PROBLEM: LiteLLM is not responding -- connection error to http://127.0.0.1:4000"
        action, _ = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "restart_dependency")

    def test_unrecognized_failure_raises_oq_not_a_guess(self):
        log = "AssertionError: profile self-intersection detected at joint 3, gamma=0.41"
        action, reasoning = supervisor_triage.recommend_action(log)
        self.assertEqual(action, "raise_oq")
        self.assertIn("revert", reasoning)  # documents why this module never auto-recommends revert

    def test_never_recommends_revert(self):
        # No log text should ever produce "revert" from this module -- that
        # requires diff/commit-content judgment this module doesn't have.
        sample_logs = [
            "", "429", "credit balance too low", "LiteLLM is not responding",
            "some completely novel error nobody has seen before",
        ]
        for log in sample_logs:
            action, _ = supervisor_triage.recommend_action(log)
            self.assertNotEqual(action, "revert")


class TestFormatRecommendation(unittest.TestCase):
    def test_formats_a_readable_line(self):
        line = supervisor_triage.format_recommendation("at1162-abc123", 1162, "retry", "credit exhausted")
        self.assertIn("at1162-abc123", line)
        self.assertIn("AT-1162", line)
        self.assertIn("retry", line)
        self.assertIn("credit exhausted", line)

    def test_rejects_revert_as_invalid_action(self):
        with self.assertRaises(AssertionError):
            supervisor_triage.format_recommendation("job1", 1, "revert", "x")


if __name__ == "__main__":
    unittest.main()
