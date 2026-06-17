#!/usr/bin/env python3
"""
Unit tests for `_conversation_already_in_progress` in scripts/local-mcp.py
(CB-20, 2026-06-14 over-spend investigation).

Background: `_detect_multi_step_ask` runs on `_latest_user_message(body)`,
the most recent `role: "user"` message. In Cline's protocol, tool-result
feedback is *also* sent back as `role: "user"` (e.g. "[read_file for
'roadmap.md'] Result: 1 | # Cheap-Model Context-Budget Improvement
Roadmap..."). Any such tool result over 350 chars containing 3+ of
`_MULTI_STEP_ACTION_VERB_RE`'s common verbs -- true of virtually any markdown
doc or source file -- was misdetected as a fresh multi-step ask, and
`_run_planner_pass` then re-sent the entire tool-result payload (observed up
to ~90K prompt tokens) asking the model to "decompose" the file's contents
into steps. 28 of ~83 billed calls in one session (34% of spend) hit this
path.

`_conversation_already_in_progress(messages)` detects whether the agent has
already made a tool call earlier in the conversation -- if so, the latest
"user" message is a tool result, not a new ask, and `_detect_multi_step_ask`
must be skipped.

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_multi_step_continuation.py
(or `python -m unittest scripts.tests.test_local_mcp_multi_step_continuation` from repo root)
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


# A real tool-result message as observed in the 2026-06-14 over-spend session:
# >350 chars, contains "Roadmap", "Improvement", and headings with "review",
# "build", "document" etc -- enough to trip _detect_multi_step_ask on its own.
_ROADMAP_TOOL_RESULT = (
    "[read_file for 'foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-"
    "context-budget-roadmap.md'] Result: 1 | # Cheap-Model Context-Budget "
    "Improvement Roadmap\n"
    + ("Review the strategy backlog, build the validation harness, and "
       "document each experiment before the next audit. " * 6)
)


class TestConversationAlreadyInProgress(unittest.TestCase):
    def test_fresh_conversation_is_not_in_progress(self):
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "user", "content": "Please review X, build Y, and document Z."},
        ]
        self.assertFalse(local_mcp._conversation_already_in_progress(messages))

    def test_prior_assistant_tool_call_marks_in_progress(self):
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "user", "content": "Please review X, build Y, and document Z."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "user", "content": _ROADMAP_TOOL_RESULT},
        ]
        self.assertTrue(local_mcp._conversation_already_in_progress(messages))

    def test_prior_tool_role_message_marks_in_progress(self):
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "user", "content": "Please review X, build Y, and document Z."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "1", "content": _ROADMAP_TOOL_RESULT},
            {"role": "user", "content": "ok continue"},
        ]
        self.assertTrue(local_mcp._conversation_already_in_progress(messages))

    def test_prior_tool_use_content_block_marks_in_progress(self):
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "user", "content": "Please review X, build Y, and document Z."},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "read_file", "input": {"path": "roadmap.md"}}
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "content": _ROADMAP_TOOL_RESULT}
            ]},
        ]
        self.assertTrue(local_mcp._conversation_already_in_progress(messages))

    def test_only_last_message_is_ignored(self):
        # A tool_use block in the *last* message (e.g. the message currently
        # being classified) must not count -- only earlier messages establish
        # that the agent has already started this task.
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "read_file", "input": {"path": "roadmap.md"}}
            ]},
        ]
        self.assertFalse(local_mcp._conversation_already_in_progress(messages))

    def test_tool_result_misfire_is_suppressed_once_in_progress(self):
        # Sanity check end-to-end: on its own, the roadmap tool-result text
        # trips _detect_multi_step_ask (>350 chars, >=3 action verbs) ...
        is_multi_step, _ = local_mcp._detect_multi_step_ask(_ROADMAP_TOOL_RESULT)
        self.assertTrue(is_multi_step)

        # ... but once the conversation shows a prior tool call, the proxy
        # must skip the detector entirely for this turn.
        messages = [
            {"role": "system", "content": "you are an assistant"},
            {"role": "user", "content": "Please review X, build Y, and document Z."},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ]},
            {"role": "user", "content": _ROADMAP_TOOL_RESULT},
        ]
        self.assertTrue(local_mcp._conversation_already_in_progress(messages))


if __name__ == "__main__":
    unittest.main()
