#!/usr/bin/env python3
"""
Unit tests for `_run_validator_pass` in mcp-server/local-mcp.py (CB-8, 2026-06-11).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_validator.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)

_run_validator_pass = local_mcp._run_validator_pass


class TestValidatorFailureLanguage(unittest.TestCase):
    def test_genuine_self_reported_failure_is_flagged(self):
        verdict, reason = _run_validator_pass(
            step_task="Run the build for this step's change.",
            summary_text="I ran `npm run build` and it failed with a TypeScript error.",
            changed_files=[],
        )
        self.assertEqual(verdict, "no")
        self.assertIn("failure language", reason)

    def test_negated_failure_language_passes(self):
        verdict, _ = _run_validator_pass(
            step_task="Check whether the build succeeds.",
            summary_text="I ran `npm run build`. No errors were found; build succeeded.",
            changed_files=[],
        )
        self.assertEqual(verdict, "yes")

    def test_blockquoted_source_quote_with_failure_word_not_flagged(self):
        # Reproduces test #12 (2026-06-11): the executor's own framing is
        # clean, but the verbatim-quoted source text discusses CB-1
        # "failures". Per the updated _ORCHESTRATOR_STEP_SYSTEM_PROMPT, such
        # reproduced text must be blockquoted -- the validator must not treat
        # words inside it as a self-report of this step's outcome.
        summary = (
            "Here is the requested section from the document (lines 189-286):\n\n"
            "> ### 2026-06-11 -- kimi-k2.6 succeeds with 100x max_tokens\n"
            ">\n"
            "> The CB-1/CB-1-like reasoning/content channel-split failures observed\n"
            "> across gpt-oss-120b, gemma-4-26b, and kimi-k2.6 this session are a\n"
            "> known, broadly-reported class of problem.\n\n"
            "I copied the section verbatim as requested; no files were changed."
        )
        verdict, reason = _run_validator_pass(
            step_task='Read the section titled "..." and report it back.',
            summary_text=summary,
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)

    def test_fenced_source_quote_with_failure_word_not_flagged(self):
        summary = (
            "I copied the section as a fenced block:\n\n"
            "```\n"
            "channel-split failures observed across gpt-oss-120b and kimi-k2.6\n"
            "```\n\n"
            "No files were changed; this was a read-only step."
        )
        verdict, reason = _run_validator_pass(
            step_task='Read the section titled "..." and report it back.',
            summary_text=summary,
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)

    def test_failure_word_in_executors_own_framing_outside_quote_still_flagged(self):
        # The blockquote only shields *quoted* text. If the executor's own
        # (non-quoted) sentence claims a failure, it must still be caught.
        summary = (
            "> some quoted source text with no issues\n\n"
            "However, I was unable to complete this step: the build failed."
        )
        verdict, reason = _run_validator_pass(
            step_task="Run the build for this step's change.",
            summary_text=summary,
            changed_files=[],
        )
        self.assertEqual(verdict, "no")
        self.assertIn("failure language", reason)


class TestCB11RecordOnlyStepFalsePositive(unittest.TestCase):
    # CB-11 (2026-06-12, test #13/#14, second occurrence): a step whose task
    # is "Record/Identify the exact quote/sentence stating X" is read-only by
    # design, but the task wording sometimes contains an incidental
    # change-verb word (e.g. "...after the fix...") that previously tripped
    # _VALIDATOR_CHANGE_VERB_RE and produced a spurious AMBIGUOUS verdict on
    # an empty (correct) diff.

    def test_record_exact_quote_step_with_incidental_fix_word_passes(self):
        verdict, reason = _run_validator_pass(
            step_task=("Record the exact quote stating the through-proxy result for test #10 "
                       "after the fix including its completion_tokens count and elapsed time "
                       "in seconds."),
            summary_text=("Found the sentence in the roadmap doc: \"Re-verified through the "
                           "fixed proxy: ... completed in 121s, completion_tokens: 6324\". "
                           "No files were changed.\n"
                           "FINDING: through-proxy result was completion_tokens=6324 in 121s."),
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)
        self.assertIn("read-only", reason)

    def test_identify_exact_sentence_step_with_incidental_change_word_passes(self):
        verdict, reason = _run_validator_pass(
            step_task="Identify the exact sentence stating the new value of X after the fix that introduced it.",
            summary_text="Found the sentence. No files were changed.",
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)

    def test_record_only_regex_does_not_mask_genuine_change_step(self):
        # A step that genuinely implies a change (no "record/identify the
        # exact ..." framing) with an empty diff must still be AMBIGUOUS.
        verdict, reason = _run_validator_pass(
            step_task="Update the config file to fix the timeout value.",
            summary_text="Looked at the config file. No files were changed.",
            changed_files=[],
        )
        self.assertEqual(verdict, "ambiguous")


class TestCB11CopyVerbStepFalsePositive(unittest.TestCase):
    # CB-11 (2026-06-12, test #15, fourth occurrence): "Copy the exact
    # sentence stating X" is the same read-only-by-design shape as
    # "Record/Identify the exact ..." above, but "copy" was missing from the
    # verb alternation, so this still produced a spurious AMBIGUOUS verdict
    # on an empty (correct) diff and needed an architect Option A resolution
    # (OQ-259, third occurrence).

    def test_copy_exact_sentence_step_with_incidental_fix_word_passes(self):
        verdict, reason = _run_validator_pass(
            step_task=("Copy the exact sentence stating the through-proxy result for test #10 "
                       "after the fix including its completion_tokens count and elapsed time "
                       "in seconds."),
            summary_text=("Found the sentence in the roadmap doc: \"Re-verified through the "
                           "fixed proxy: ... completed in 121s, completion_tokens: 6324\". "
                           "No files were changed.\n"
                           "FINDING: through-proxy result was completion_tokens=6324 in 121s."),
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)
        self.assertIn("read-only", reason)

    def test_transcribe_exact_wording_step_passes(self):
        verdict, reason = _run_validator_pass(
            step_task="Transcribe the exact wording of the conclusion after the fix.",
            summary_text="Found the sentence. No files were changed.",
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)

    def test_extract_exact_value_step_passes(self):
        verdict, reason = _run_validator_pass(
            step_task="Extract the exact value stated for the timeout after the fix.",
            summary_text="Found the value. No files were changed.",
            changed_files=[],
        )
        self.assertEqual(verdict, "yes", reason)

    def test_extract_function_refactor_step_still_ambiguous(self):
        # "Extract" also names a refactor verb ("extract this into a
        # function"); without the "exact quote/sentence/wording/text/value"
        # guard this would wrongly be treated as read-only-by-design.
        verdict, reason = _run_validator_pass(
            step_task="Extract the validation logic in foo() into a new helper function after the fix.",
            summary_text="Refactored the function. No files were changed.",
            changed_files=[],
        )
        self.assertEqual(verdict, "ambiguous")


class TestCB11PostCommitCleanDiff(unittest.TestCase):
    # CB-11 (2026-06-12, test #14, third occurrence): a `git commit` step
    # leaves the working tree clean vs. the NEW HEAD, so the working-tree
    # diff is empty even though the step succeeded. `head_changed=True` is
    # the corresponding evidence of success.

    def test_commit_step_with_clean_diff_but_head_changed_passes(self):
        verdict, reason = _run_validator_pass(
            step_task='Commit it with the message "docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)".',
            summary_text="Ran `git add` and `git commit`. The commit succeeded.",
            changed_files=[],
            head_changed=True,
        )
        self.assertEqual(verdict, "yes", reason)
        self.assertIn("HEAD advanced", reason)

    def test_commit_step_with_clean_diff_and_no_head_change_still_ambiguous(self):
        # Without head_changed evidence, the same step+summary is still
        # ambiguous -- this is the pre-fix behavior for a step that did NOT
        # actually commit anything.
        verdict, reason = _run_validator_pass(
            step_task='Commit it with the message "docs: add CB-7/AC-2 validation summary (cf/kimi-k2.6 orchestrator test)".',
            summary_text="Ran `git add` and `git commit`. The commit succeeded.",
            changed_files=[],
            head_changed=False,
        )
        self.assertEqual(verdict, "ambiguous")


if __name__ == "__main__":
    unittest.main()
