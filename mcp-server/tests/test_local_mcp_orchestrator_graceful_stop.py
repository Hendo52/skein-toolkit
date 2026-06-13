#!/usr/bin/env python3
"""
Unit tests for the 2026-06-13 "graceful stop" fix in mcp-server/local-mcp.py:

Fix A: `_conversation_has_tool_use` gates the Phase 2 multi-step interceptor
(`_detect_multi_step_ask`) so it no longer fires on a mid-task tool-result
blob and spins up a spurious orchestrator run (observed run
`bdeaa11e30a35d7a`, 2026-06-13).

Fix B: `_terminal_completion_tool_call` / `_terminal_followup_question_tool_call`
wrap the orchestrator's terminal synthetic responses (run complete, step
failure, ambiguity pause/hard-stop, lost-contact halt) in a Cline tool call
(`attempt_completion` / `ask_followup_question`) instead of a bare
no-tool-call "stop" turn, which Cline's interactive (VS Code) harness rejects
with "[ERROR] You did not use a tool in your previous response!" and which can
escalate to its own "[YOLO MODE] Task failed" stop after 5 retries.

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_orchestrator_graceful_stop.py
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


class TestConversationHasToolUse(unittest.TestCase):
    def test_empty_messages_returns_false(self):
        self.assertFalse(local_mcp._conversation_has_tool_use([]))

    def test_no_assistant_messages_returns_false(self):
        messages = [
            {"role": "system", "content": "you are an agent"},
            {"role": "user", "content": "do the thing"},
        ]
        self.assertFalse(local_mcp._conversation_has_tool_use(messages))

    def test_assistant_plain_text_only_returns_false(self):
        messages = [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "content": "Sure, here is my plan."},
        ]
        self.assertFalse(local_mcp._conversation_has_tool_use(messages))

    def test_assistant_with_tool_calls_field_returns_true(self):
        messages = [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "content": "", "tool_calls": [
                local_mcp._make_tool_call("write_to_file", {"path": "foo.md", "content": "hi"})]},
            {"role": "user", "content": "tool result: file written"},
        ]
        self.assertTrue(local_mcp._conversation_has_tool_use(messages))

    def test_assistant_with_content_list_tool_use_block_returns_true(self):
        messages = [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Reading the file..."},
                {"type": "tool_use", "name": "read_file", "input": {"path": "foo.md"}},
            ]},
        ]
        self.assertTrue(local_mcp._conversation_has_tool_use(messages))

    def test_non_dict_and_non_assistant_entries_are_skipped(self):
        messages = [
            "not a dict",
            {"role": "user", "content": "do the thing"},
            {"role": "tool", "content": "result", "tool_calls": [{"id": "x"}]},
        ]
        self.assertFalse(local_mcp._conversation_has_tool_use(messages))

    def test_only_the_latest_of_several_assistant_turns_needs_tool_use(self):
        messages = [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "content": "Thinking out loud first."},
            {"role": "assistant", "content": "", "tool_calls": [
                local_mcp._make_tool_call("execute_command", {"command": "git status"})]},
            {"role": "user", "content": "tool result: clean tree"},
        ]
        self.assertTrue(local_mcp._conversation_has_tool_use(messages))


class TestTerminalToolCallHelpers(unittest.TestCase):
    def test_terminal_completion_tool_call_wraps_attempt_completion(self):
        tool_calls = local_mcp._terminal_completion_tool_call("Run complete -- all 3 step(s) validated.")
        self.assertEqual(len(tool_calls), 1)
        fn = tool_calls[0]["function"]
        self.assertEqual(fn["name"], "attempt_completion")
        args = json.loads(fn["arguments"])
        self.assertEqual(args["result"], "Run complete -- all 3 step(s) validated.")

    def test_terminal_followup_question_tool_call_wraps_ask_followup_question(self):
        tool_calls = local_mcp._terminal_followup_question_tool_call("Step 2/3 came back AMBIGUOUS -- continue or stop?")
        self.assertEqual(len(tool_calls), 1)
        fn = tool_calls[0]["function"]
        self.assertEqual(fn["name"], "ask_followup_question")
        args = json.loads(fn["arguments"])
        self.assertEqual(args["question"], "Step 2/3 came back AMBIGUOUS -- continue or stop?")
        self.assertEqual(json.loads(args["options"]), ["continue", "stop"])

    def test_terminal_tool_calls_are_recognized_as_cline_terminal(self):
        # The wrapped calls must round-trip through CB-14's
        # _cline_terminal_tool_summary -- they are exactly the shape Cline's
        # own attempt_completion/ask_followup_question calls take.
        completion_calls = local_mcp._terminal_completion_tool_call("All done.")
        self.assertEqual(local_mcp._cline_terminal_tool_summary(completion_calls, ""), "All done.")

        question_calls = local_mcp._terminal_followup_question_tool_call("Continue or stop?")
        self.assertEqual(local_mcp._cline_terminal_tool_summary(question_calls, ""), "Continue or stop?")


class TestSyntheticResponseWithTerminalToolCalls(unittest.TestCase):
    def test_non_stream_response_has_tool_calls_and_empty_content(self):
        tool_calls = local_mcp._terminal_completion_tool_call("Run complete.")
        response = local_mcp._synthetic_assistant_response("x", "", False, tool_calls=tool_calls)
        body = json.loads(response.body)
        message = body["choices"][0]["message"]
        self.assertEqual(message["content"], "")
        self.assertEqual(message["tool_calls"], tool_calls)
        self.assertEqual(body["choices"][0]["finish_reason"], "tool_calls")

    def test_stream_response_finish_reason_is_tool_calls(self):
        import asyncio

        tool_calls = local_mcp._terminal_followup_question_tool_call("Continue or stop?")
        response = local_mcp._synthetic_assistant_response("x", "", True, tool_calls=tool_calls)

        async def _collect():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(_collect())
        payloads = []
        for chunk in chunks:
            text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
            for line in text.splitlines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    payloads.append(json.loads(line[len("data: "):]))

        finish_reasons = [p["choices"][0]["finish_reason"] for p in payloads]
        self.assertIn("tool_calls", finish_reasons)

        tool_call_deltas = [p for p in payloads if "tool_calls" in p["choices"][0]["delta"]]
        self.assertEqual(len(tool_call_deltas), 1)
        self.assertEqual(tool_call_deltas[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"],
                         "ask_followup_question")


class TestFinishStepTerminalToolCalls(unittest.IsolatedAsyncioTestCase):
    """`_finish_step`'s YES/NO/AMBIGUOUS branches must each return a
    synthetic response wrapped in a Cline tool call (Fix B), not bare text."""

    async def asyncSetUp(self):
        self._orig_git_snapshot = local_mcp._git_snapshot
        self._orig_run_validator_pass = local_mcp._run_validator_pass
        self._orig_save_state = local_mcp._save_orchestrator_state
        self._orig_record_metric = local_mcp._record_metric
        self._orig_raise_oq = local_mcp._raise_step_ambiguity_oq

        async def fake_git_snapshot(workspace):
            return {"dirty": [], "head": "deadbeef"}
        local_mcp._git_snapshot = fake_git_snapshot

        local_mcp._save_orchestrator_state = lambda key, state: None

        async def fake_record_metric(name, by=1):
            return None
        local_mcp._record_metric = fake_record_metric

    async def asyncTearDown(self):
        local_mcp._git_snapshot = self._orig_git_snapshot
        local_mcp._run_validator_pass = self._orig_run_validator_pass
        local_mcp._save_orchestrator_state = self._orig_save_state
        local_mcp._record_metric = self._orig_record_metric
        local_mcp._raise_step_ambiguity_oq = self._orig_raise_oq

    def _state(self, steps, current):
        state = local_mcp._new_orchestrator_state(steps, "test", model="@cf/moonshotai/kimi-k2.6")
        state.update(current=current, snapshot_before_step={"dirty": [], "head": "deadbeef"})
        return state

    @staticmethod
    def _message_and_tool_call(result):
        body = json.loads(result.body)
        message = body["choices"][0]["message"]
        return message, message["tool_calls"][0]

    async def test_final_step_yes_wraps_run_complete_in_attempt_completion(self):
        local_mcp._run_validator_pass = lambda *a, **k: ("yes", "diff matches the step")
        state = self._state(["only step"], current=1)
        original_body = {"messages": [{"role": "user", "content": "do the thing"}]}

        result = await local_mcp._finish_step(
            "key123", state, 1, "Done. FINDING: it works.", "http://cf", "auth", original_body, False, "x")

        message, tool_call = self._message_and_tool_call(result)
        self.assertEqual(message["content"], "")
        self.assertEqual(tool_call["function"]["name"], "attempt_completion")
        args = json.loads(tool_call["function"]["arguments"])
        self.assertIn("Run complete", args["result"])
        self.assertEqual(state["status"], "complete")

    async def test_step_no_wraps_failure_report_in_attempt_completion(self):
        local_mcp._run_validator_pass = lambda *a, **k: ("no", "no working-tree changes detected")
        state = self._state(["step one", "step two"], current=1)
        original_body = {"messages": [{"role": "user", "content": "do the thing"}]}

        result = await local_mcp._finish_step(
            "key123", state, 1, "I looked into it but made no changes.", "http://cf", "auth", original_body, False, "x")

        message, tool_call = self._message_and_tool_call(result)
        self.assertEqual(message["content"], "")
        self.assertEqual(tool_call["function"]["name"], "attempt_completion")
        args = json.loads(tool_call["function"]["arguments"])
        self.assertIn("FAILED validation", args["result"])
        self.assertEqual(state["status"], "halted")

    async def test_step_ambiguous_first_time_wraps_pause_in_ask_followup_question(self):
        local_mcp._run_validator_pass = lambda *a, **k: ("ambiguous", "diff is bigger than expected")
        local_mcp._raise_step_ambiguity_oq = lambda *a, **k: "OQ-999"
        state = self._state(["step one", "step two"], current=1)
        original_body = {"messages": [{"role": "user", "content": "do the thing"}]}

        result = await local_mcp._finish_step(
            "key123", state, 1, "Made some changes, not sure if complete.", "http://cf", "auth", original_body, False, "x")

        message, tool_call = self._message_and_tool_call(result)
        self.assertEqual(message["content"], "")
        self.assertEqual(tool_call["function"]["name"], "ask_followup_question")
        args = json.loads(tool_call["function"]["arguments"])
        self.assertIn("AMBIGUOUS", args["question"])
        self.assertEqual(json.loads(args["options"]), ["continue", "stop"])
        self.assertEqual(state["status"], "paused_for_oq")

    async def test_step_ambiguous_second_time_wraps_hard_stop_in_attempt_completion(self):
        local_mcp._run_validator_pass = lambda *a, **k: ("ambiguous", "diff is still bigger than expected")
        state = self._state(["step one", "step two"], current=1)
        state["ambiguity_raised_for_step"] = 1  # an OQ was already raised for this step
        original_body = {"messages": [{"role": "user", "content": "do the thing"}]}

        result = await local_mcp._finish_step(
            "key123", state, 1, "Still not sure if complete.", "http://cf", "auth", original_body, False, "x")

        message, tool_call = self._message_and_tool_call(result)
        self.assertEqual(message["content"], "")
        self.assertEqual(tool_call["function"]["name"], "attempt_completion")
        args = json.loads(tool_call["function"]["arguments"])
        self.assertIn("hard stop", args["result"])
        self.assertEqual(state["status"], "halted")


class TestDispatchStepLostContactToolCall(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_cf_complete_once = local_mcp._cf_complete_once
        self._orig_record_metric = local_mcp._record_metric
        self._orig_save_state = local_mcp._save_orchestrator_state

        async def fake_record_metric(name, by=1):
            return None
        local_mcp._record_metric = fake_record_metric
        local_mcp._save_orchestrator_state = lambda key, state: None

    async def asyncTearDown(self):
        local_mcp._cf_complete_once = self._orig_cf_complete_once
        local_mcp._record_metric = self._orig_record_metric
        local_mcp._save_orchestrator_state = self._orig_save_state

    async def test_lost_contact_wraps_halt_message_in_attempt_completion(self):
        async def fake_cf_complete_once(cf_url, auth_header, body):
            return None
        local_mcp._cf_complete_once = fake_cf_complete_once

        state = local_mcp._new_orchestrator_state(["only step"], "test", model="@cf/moonshotai/kimi-k2.6")
        state.update(current=1, snapshot_before_step={"dirty": [], "head": "deadbeef"})
        original_body = {"messages": [{"role": "user", "content": "do the thing"}], "model": "x", "stream": False}

        result = await local_mcp._dispatch_step("key123", state, 1, "http://cf", "auth", original_body, [], False, "x")

        body = json.loads(result.body)
        message = body["choices"][0]["message"]
        self.assertEqual(message["content"], "")
        tool_call = message["tool_calls"][0]
        self.assertEqual(tool_call["function"]["name"], "attempt_completion")
        args = json.loads(tool_call["function"]["arguments"])
        self.assertIn("Lost contact", args["result"])
        self.assertEqual(state["status"], "halted")


if __name__ == "__main__":
    unittest.main()
