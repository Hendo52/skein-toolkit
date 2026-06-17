#!/usr/bin/env python3
"""
Unit tests for the degenerate-planner-output guard in scripts/local-mcp.py
(`_planner_output_is_clarifying_question`, used by `_run_planner_pass`).

Background (OQ-268, 2026-06-12): a 9901-char multi-step ask triggered the
planner pass. The model returned a single numbered "step" --
"State the specific task, feature request, bug fix, or goal you want
decomposed into an ordered list of actionable steps." -- which is the
planner's own clarifying-question phrasing echoed back, not a decomposition
of the request. The numbered-list shape check (`if not steps`) accepted it as
a valid 1-step plan, the orchestrator auto-confirmed and dispatched it as
"step 1/1" of the user's actual task, the executor (reasonably) replied "I
don't see a specific task...", the validator returned AMBIGUOUS, and the
whole thing escalated to an OQ about a run that was never given a real task.

`_planner_output_is_clarifying_question` closes this: a single step that
shares none of the request's detected action verbs is treated as a degenerate
planner response, and `_run_planner_pass` returns None (falling back to
forwarding the original request unchanged -- the same recovery path as "no
numbered steps" or "too many steps").

Run with: .venv\\Scripts\\python.exe scripts\\tests\\test_local_mcp_planner_pass.py
(or `python -m unittest scripts.tests.test_local_mcp_planner_pass` from repo root)
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


# The actual OQ-268 planner output: a single numbered item that is the
# planner's own clarifying-question template, not a decomposition step.
_OQ_268_CLARIFYING_STEP = (
    "State the specific task, feature request, bug fix, or goal you want "
    "decomposed into an ordered list of actionable steps."
)

# The same shape as the 9901-char OQ-268 request: long enough to trigger
# _detect_multi_step_ask via >= 3 distinct action verbs.
_MULTI_VERB_REQUEST = (
    "Please audit the CI config, build the release artifacts, create a "
    "changelog entry, install the updated dependencies, port the legacy "
    "script, and review the final diff before merging."
)


class TestPlannerOutputIsClarifyingQuestion(unittest.TestCase):
    def test_oq268_degenerate_single_step_is_clarifying_question(self):
        self.assertTrue(
            local_mcp._planner_output_is_clarifying_question(
                [_OQ_268_CLARIFYING_STEP], _MULTI_VERB_REQUEST
            )
        )

    def test_real_single_step_sharing_a_verb_is_not_clarifying_question(self):
        steps = ["Build the release artifacts using the existing npm script."]
        self.assertFalse(
            local_mcp._planner_output_is_clarifying_question(steps, _MULTI_VERB_REQUEST)
        )

    def test_multi_step_plan_is_never_clarifying_question(self):
        # Even if no step happens to share a verb, >1 step is not the
        # single-clarifying-question signature.
        steps = [_OQ_268_CLARIFYING_STEP, "Something else entirely."]
        self.assertFalse(
            local_mcp._planner_output_is_clarifying_question(steps, _MULTI_VERB_REQUEST)
        )

    def test_request_with_no_detectable_verbs_is_never_clarifying_question(self):
        self.assertFalse(
            local_mcp._planner_output_is_clarifying_question(
                [_OQ_268_CLARIFYING_STEP], "Hello, how are you today?"
            )
        )

    def test_empty_steps_is_not_clarifying_question(self):
        self.assertFalse(
            local_mcp._planner_output_is_clarifying_question([], _MULTI_VERB_REQUEST)
        )


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def json(self):
        return self._data


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in returning a fixed chat-completion
    payload for every `post` call, following the pattern used by
    test_local_mcp_dispatch_timeout.py's _RaisingAsyncClient."""

    def __init__(self, response_data: dict):
        self._response_data = response_data

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse(self._response_data)


def _chat_completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content, "reasoning_content": None}}]}


class TestRunPlannerPassDegenerateResponse(unittest.IsolatedAsyncioTestCase):
    async def test_clarifying_question_response_returns_none(self):
        fake_client = _FakeAsyncClient(_chat_completion(f"1. {_OQ_268_CLARIFYING_STEP}"))
        with patch.object(local_mcp.httpx, "AsyncClient", fake_client), \
                patch("sys.stderr") as mock_stderr:
            result = await local_mcp._run_planner_pass(
                "https://example.invalid", "Bearer token", "@cf/moonshotai/kimi-k2.6", _MULTI_VERB_REQUEST
            )

        self.assertIsNone(result)
        logged = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
        self.assertIn("degenerate planner response", logged)

    async def test_real_decomposition_response_returns_steps(self):
        content = (
            "1. Audit the CI config for outdated steps.\n"
            "2. Build the release artifacts with the existing npm script.\n"
            "3. Review the final diff before merging."
        )
        fake_client = _FakeAsyncClient(_chat_completion(content))
        with patch.object(local_mcp.httpx, "AsyncClient", fake_client), \
                patch("sys.stderr"):
            result = await local_mcp._run_planner_pass(
                "https://example.invalid", "Bearer token", "@cf/moonshotai/kimi-k2.6", _MULTI_VERB_REQUEST
            )

        self.assertEqual(result, [
            "Audit the CI config for outdated steps.",
            "Build the release artifacts with the existing npm script.",
            "Review the final diff before merging.",
        ])


if __name__ == "__main__":
    unittest.main()
