#!/usr/bin/env python3
"""
Unit tests for the CB-14 fix (AT-1141, 2026-06-12) in mcp-server/local-mcp.py:
`_cline_terminal_tool_summary` and the new branch it adds to `_dispatch_step`.

CB-14: a step response made up entirely of Cline-terminal tool calls
(attempt_completion, ask_followup_question, plan_mode_respond) was relayed to
Cline as an ordinary mid-step tool call. Cline ends/pauses its session on
those tools instead of returning a tool result, so `_finish_step` never ran
and the orchestrator was stranded at status="running" forever (AT-1140 test
#16).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_orchestrator_cb14.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import json
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


class TestClineTerminalToolSummary(unittest.TestCase):
    def test_empty_tool_calls_returns_none(self):
        self.assertIsNone(local_mcp._cline_terminal_tool_summary([], "some content"))

    def test_attempt_completion_only_returns_result_text(self):
        tool_calls = [local_mcp._make_tool_call("attempt_completion", {"result": "Done. FINDING: the answer is 42."})]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "")
        self.assertEqual(summary, "Done. FINDING: the answer is 42.")

    def test_ask_followup_question_only_returns_question_text(self):
        tool_calls = [local_mcp._make_tool_call("ask_followup_question", {"question": "Which file should I edit?"})]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "")
        self.assertEqual(summary, "Which file should I edit?")

    def test_plan_mode_respond_only_returns_response_text(self):
        tool_calls = [local_mcp._make_tool_call("plan_mode_respond", {"response": "Here is my plan."})]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "")
        self.assertEqual(summary, "Here is my plan.")

    def test_content_is_prepended_to_terminal_tool_text(self):
        tool_calls = [local_mcp._make_tool_call("attempt_completion", {"result": "Created the file."})]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "Reasoning before the tool call.")
        self.assertEqual(summary, "Reasoning before the tool call.\n\nCreated the file.")

    def test_real_tool_call_only_returns_none(self):
        tool_calls = [local_mcp._make_tool_call("write_to_file", {"path": "foo.md", "content": "hi"})]
        self.assertIsNone(local_mcp._cline_terminal_tool_summary(tool_calls, ""))

    def test_mixed_terminal_and_real_tool_returns_none(self):
        # A real action tool alongside attempt_completion takes precedence --
        # the whole response is relayed to Cline unchanged (regression path).
        tool_calls = [
            local_mcp._make_tool_call("write_to_file", {"path": "foo.md", "content": "hi"}),
            local_mcp._make_tool_call("attempt_completion", {"result": "Done."}),
        ]
        self.assertIsNone(local_mcp._cline_terminal_tool_summary(tool_calls, ""))

    def test_multiple_terminal_calls_are_joined(self):
        tool_calls = [
            local_mcp._make_tool_call("plan_mode_respond", {"response": "Plan part one."}),
            local_mcp._make_tool_call("attempt_completion", {"result": "Plan part two."}),
        ]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "")
        self.assertEqual(summary, "Plan part one.\n\nPlan part two.")

    def test_malformed_arguments_json_does_not_raise(self):
        tool_calls = [{
            "id": "call_bad",
            "type": "function",
            "function": {"name": "attempt_completion", "arguments": "{not json"},
        }]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "Fallback content.")
        self.assertEqual(summary, "Fallback content.")

    def test_missing_text_argument_with_no_content_returns_empty_string(self):
        tool_calls = [local_mcp._make_tool_call("attempt_completion", {})]
        summary = local_mcp._cline_terminal_tool_summary(tool_calls, "")
        self.assertEqual(summary, "")
        self.assertIsNotNone(summary)


class TestDispatchStepCB14Routing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_cf_complete_once = local_mcp._cf_complete_once
        self._orig_record_metric = local_mcp._record_metric
        self._orig_finish_step = local_mcp._finish_step
        local_mcp._record_metric = self._fake_record_metric

    async def asyncTearDown(self):
        local_mcp._cf_complete_once = self._orig_cf_complete_once
        local_mcp._record_metric = self._orig_record_metric
        local_mcp._finish_step = self._orig_finish_step

    @staticmethod
    async def _fake_record_metric(name, by=1):
        return None

    def _state(self):
        return local_mcp._new_orchestrator_state(["do the thing"], "test", model="@cf/moonshotai/kimi-k2.6")

    async def test_attempt_completion_only_routes_to_finish_step(self):
        tool_calls = [local_mcp._make_tool_call("attempt_completion", {"result": "Done. FINDING: it works."})]

        async def fake_cf_complete_once(cf_url, auth_header, body):
            return ("", tool_calls, "tool_calls")
        local_mcp._cf_complete_once = fake_cf_complete_once

        finish_step_calls = []

        async def fake_finish_step(key, state, step_idx, summary_text, cf_url, auth_header, original_body, is_stream, model_name):
            finish_step_calls.append(summary_text)
            return "finish-step-result"

        local_mcp._finish_step = fake_finish_step

        state = self._state()
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        result = await local_mcp._dispatch_step("key123", state, 1, "http://cf", "auth", original_body, [], True, "x")

        self.assertEqual(result, "finish-step-result")
        self.assertEqual(finish_step_calls, ["Done. FINDING: it works."])
        self.assertTrue(any("CB-14" in entry["message"] for entry in state["log"]))

    async def test_real_tool_call_is_relayed_unchanged(self):
        tool_calls = [local_mcp._make_tool_call("write_to_file", {"path": "foo.md", "content": "hi"})]

        async def fake_cf_complete_once(cf_url, auth_header, body):
            return ("", tool_calls, "tool_calls")
        local_mcp._cf_complete_once = fake_cf_complete_once

        async def fake_finish_step(*args, **kwargs):
            raise AssertionError("_finish_step must not be called for a real tool call")
        local_mcp._finish_step = fake_finish_step

        state = self._state()
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        result = await local_mcp._dispatch_step("key123", state, 1, "http://cf", "auth", original_body, [], False, "x")

        body = json.loads(result.body)
        self.assertEqual(body["choices"][0]["message"]["tool_calls"], tool_calls)
        self.assertEqual(state.get("log", []), [])

    async def test_mixed_terminal_and_real_tool_is_relayed_unchanged(self):
        tool_calls = [
            local_mcp._make_tool_call("write_to_file", {"path": "foo.md", "content": "hi"}),
            local_mcp._make_tool_call("attempt_completion", {"result": "Done."}),
        ]

        async def fake_cf_complete_once(cf_url, auth_header, body):
            return ("", tool_calls, "tool_calls")
        local_mcp._cf_complete_once = fake_cf_complete_once

        async def fake_finish_step(*args, **kwargs):
            raise AssertionError("_finish_step must not be called when a real tool call is present")
        local_mcp._finish_step = fake_finish_step

        state = self._state()
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": True}
        result = await local_mcp._dispatch_step("key123", state, 1, "http://cf", "auth", original_body, [], False, "x")

        body = json.loads(result.body)
        self.assertEqual(body["choices"][0]["message"]["tool_calls"], tool_calls)


if __name__ == "__main__":
    unittest.main()
