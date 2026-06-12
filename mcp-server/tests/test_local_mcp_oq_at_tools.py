#!/usr/bin/env python3
"""
Unit tests for the ADR-011 OQ/AT authoring MCP tools in local-mcp.py
(AT-1137/AT-1138): `create_open_question` (and its helpers `_next_oq_id`,
`_format_oq_row`, `_append_oq_row`) and `create_actionable_task` (and its
helpers `_next_at_id`, `_format_at_row`, `_append_at_row`).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_local_mcp_oq_at_tools.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import importlib.util
import os
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "local-mcp.py"))

_spec = importlib.util.spec_from_file_location("local_mcp", _MODULE_PATH)
local_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(local_mcp)


_OQ_DOC_TEMPLATE = """# Architect Open Questions

| ID | Question | Context / Spec | Unblocks | Date Added |
|----|----------|-----------------|----------|------------|
| OQ-5 | Existing question? | Some spec | Some unblock | 2026-06-01 |
"""

_AT_QUEUE_WITH_INTAKE = """# AI Task Queue

## Ready Pool — Top Priority

### Newly Decomposed Tasks (Intake)

> intro text

| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |
|----|------|-------------|---------------|--------|------------|
| AT-1150 | **Existing intake task** | spec | evidence | Small | None |

| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |
|----|------|-------------|---------------|--------|------------|
| AT-1140 | **Ready pool task** | spec | evidence | Small | None |
"""

_AT_QUEUE_WITHOUT_INTAKE = """# AI Task Queue

## Ready Pool — Top Priority

| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |
|----|------|-------------|---------------|--------|------------|
| AT-1146.2 | **Subtask of AT-1146** | spec | evidence | Small | AT-1146 |
"""


class _LedgerTestCase(unittest.TestCase):
    """Base class: points local_mcp's path resolution at a scratch temp dir
    and writes the given OQ/AT file contents, restoring the originals on
    tearDown."""

    def _write_ledger(self, contents: str, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, dir=self._tmpdir)
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(contents)
        return path

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_oq_path = local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH
        self._orig_at_path = local_mcp.AT_QUEUE_PATH

    def tearDown(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._orig_oq_path
        local_mcp.AT_QUEUE_PATH = self._orig_at_path


class TestNextOqId(unittest.TestCase):
    def test_continues_live_sequence_ignoring_high_outliers(self):
        doc = "| OQ-5 | a | b | c | 2026-06-01 |\n| OQ-900 | one-off | b | c | 2025-01-01 |\n"
        self.assertEqual(local_mcp._next_oq_id(doc), 6)

    def test_empty_doc_starts_at_one(self):
        self.assertEqual(local_mcp._next_oq_id(""), 1)


class TestCreateOpenQuestion(_LedgerTestCase):
    def _valid_kwargs(self, **overrides):
        kwargs = dict(
            question="**[TEST] Some question?**",
            options=["(A) Do this.", "(B) Do that."],
            preemptive_answer="(A) Do this.",
            preemptive_reasoning="Because of reasons.",
            reversibility="Reversible",
            context_spec="Some context",
            unblocks="Some unblock",
            precedent_search_note="No precedent search performed.",
        )
        kwargs.update(overrides)
        return kwargs

    def test_rejects_missing_question(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._write_ledger(_OQ_DOC_TEMPLATE, ".md")
        before = open(local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH, encoding="utf-8").read()
        result = local_mcp.create_open_question(**self._valid_kwargs(question="  "))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("question", result)
        after = open(local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH, encoding="utf-8").read()
        self.assertEqual(before, after)

    def test_rejects_fewer_than_two_options(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._write_ledger(_OQ_DOC_TEMPLATE, ".md")
        result = local_mcp.create_open_question(**self._valid_kwargs(options=["(A) Only one."]))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("options", result)

    def test_rejects_invalid_reversibility(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._write_ledger(_OQ_DOC_TEMPLATE, ".md")
        result = local_mcp.create_open_question(**self._valid_kwargs(reversibility="Maybe"))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("reversibility", result)

    def test_rejects_missing_precedent_search_note(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._write_ledger(_OQ_DOC_TEMPLATE, ".md")
        result = local_mcp.create_open_question(**self._valid_kwargs(precedent_search_note=""))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("precedent_search_note", result)

    def test_successful_append_returns_id_and_inserts_row_at_top(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = self._write_ledger(_OQ_DOC_TEMPLATE, ".md")
        result = local_mcp.create_open_question(**self._valid_kwargs())
        self.assertEqual(result, "OQ-6")
        contents = open(local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH, encoding="utf-8").read()
        lines = contents.splitlines()
        sep_idx = next(i for i, line in enumerate(lines) if line.lstrip().startswith("|---"))
        self.assertTrue(lines[sep_idx + 1].startswith("| OQ-6 |"))
        self.assertIn("**[TEST] Some question?**", lines[sep_idx + 1])
        # the pre-existing row is still present, below the new one
        self.assertTrue(any(line.startswith("| OQ-5 |") for line in lines))

    def test_io_failure_returns_error_for_missing_ledger(self):
        local_mcp.ORCHESTRATOR_OQ_LEDGER_PATH = os.path.join(self._tmpdir, "does-not-exist.md")
        result = local_mcp.create_open_question(**self._valid_kwargs())
        self.assertTrue(result.startswith("ERROR:"))


class TestNextAtId(unittest.TestCase):
    def test_continues_from_highest_id_ignoring_subtask_suffixes(self):
        # AT-1146.2 contributes 1146, not a separate sequence; AT-1150 is the
        # highest base id, so the next one is 1151.
        self.assertEqual(local_mcp._next_at_id(_AT_QUEUE_WITHOUT_INTAKE), 1147)
        self.assertEqual(local_mcp._next_at_id(_AT_QUEUE_WITH_INTAKE), 1151)

    def test_empty_queue_starts_at_one(self):
        self.assertEqual(local_mcp._next_at_id(""), 1)


class TestFormatAtRow(unittest.TestCase):
    def test_ready_state_has_no_prefix(self):
        row = local_mcp._format_at_row(1200, "Do the thing", "spec", "None", "evidence", "Small", "Ready")
        self.assertEqual(row, "| AT-1200 | **Do the thing** | spec | evidence | Small | None |\n")

    def test_non_ready_state_prefixes_task_cell(self):
        row = local_mcp._format_at_row(1200, "Do the thing", "spec", "None", "evidence", "Small", "Blocked")
        self.assertEqual(row, "| AT-1200 | **Blocked** -- **Do the thing** | spec | evidence | Small | None |\n")


class TestCreateActionableTask(_LedgerTestCase):
    def _valid_kwargs(self, **overrides):
        kwargs = dict(
            description="Do the new thing",
            spec_issue="SR-1.12",
            dependencies="None",
            exit_evidence="The thing is done",
            effort="Small",
        )
        kwargs.update(overrides)
        return kwargs

    def test_rejects_missing_description(self):
        local_mcp.AT_QUEUE_PATH = self._write_ledger(_AT_QUEUE_WITHOUT_INTAKE, ".md")
        before = open(local_mcp.AT_QUEUE_PATH, encoding="utf-8").read()
        result = local_mcp.create_actionable_task(**self._valid_kwargs(description=""))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("description", result)
        after = open(local_mcp.AT_QUEUE_PATH, encoding="utf-8").read()
        self.assertEqual(before, after)

    def test_rejects_invalid_state(self):
        local_mcp.AT_QUEUE_PATH = self._write_ledger(_AT_QUEUE_WITHOUT_INTAKE, ".md")
        result = local_mcp.create_actionable_task(**self._valid_kwargs(state="Sometimes"))
        self.assertTrue(result.startswith("ERROR:"))
        self.assertIn("state", result)

    def test_creates_intake_section_when_absent(self):
        local_mcp.AT_QUEUE_PATH = self._write_ledger(_AT_QUEUE_WITHOUT_INTAKE, ".md")
        result = local_mcp.create_actionable_task(**self._valid_kwargs())
        self.assertEqual(result, "AT-1147")
        contents = open(local_mcp.AT_QUEUE_PATH, encoding="utf-8").read()
        self.assertIn(local_mcp._AT_INTAKE_HEADING, contents)
        self.assertIn("| AT-1147 | **Do the new thing** | SR-1.12 | The thing is done | Small | None |", contents)
        # the pre-existing Ready Pool row is untouched
        self.assertIn("| AT-1146.2 | **Subtask of AT-1146** | spec | evidence | Small | AT-1146 |", contents)

    def test_appends_to_existing_intake_section_newest_first(self):
        local_mcp.AT_QUEUE_PATH = self._write_ledger(_AT_QUEUE_WITH_INTAKE, ".md")
        result = local_mcp.create_actionable_task(**self._valid_kwargs(state="Blocked"))
        self.assertEqual(result, "AT-1151")
        contents = open(local_mcp.AT_QUEUE_PATH, encoding="utf-8").read()
        lines = contents.splitlines()
        intake_idx = next(i for i, line in enumerate(lines) if line == local_mcp._AT_INTAKE_HEADING)
        sep_idx = next(i for i in range(intake_idx, len(lines)) if lines[i].lstrip().startswith("|---"))
        self.assertTrue(lines[sep_idx + 1].startswith("| AT-1151 |"))
        self.assertIn("**Blocked** -- **Do the new thing**", lines[sep_idx + 1])
        # the previously-newest intake row is still present, now second
        self.assertTrue(lines[sep_idx + 2].startswith("| AT-1150 |"))

    def test_io_failure_returns_error_for_missing_queue(self):
        local_mcp.AT_QUEUE_PATH = os.path.join(tempfile.mkdtemp(), "does-not-exist.md")
        result = local_mcp.create_actionable_task(**self._valid_kwargs())
        self.assertTrue(result.startswith("ERROR:"))


if __name__ == "__main__":
    unittest.main()
