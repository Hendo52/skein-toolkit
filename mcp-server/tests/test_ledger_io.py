#!/usr/bin/env python3
"""
Unit tests for ledger_io.py -- the pure OQ/AT ledger-text functions used by
local-mcp.py's create_open_question/create_actionable_task (existing,
AT-1137/AT-1138) and list_open_questions/get_open_question/resolve_open_question
(AT-1162).

Run with: .venv\\Scripts\\python.exe mcp-server\\tests\\test_ledger_io.py
(or `python -m unittest discover mcp-server/tests` from repo root)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import ledger_io


_OQ_DOC = """# Architect Open Questions

**Last updated:** 2026-06-15 (something happened)

## Open Questions

| ID | Question | Context / Spec | Unblocks | Date Added |
|----|----------|---------------|----------|-----------|
| OQ-271 | **Some single-line question?** | context | unblocks | 2026-06-15 |
| OQ-270 | **[ORCHESTRATOR] Multi-line question?**

**Problem.** Some prose that spans multiple lines and paragraphs.

**Options considered:** (A) do this. (B) do that.
| OQ-269 | **Another single-line question?** | context2 | unblocks2 | 2026-06-14 |

## Resolved

Some resolved history here.
"""


class TestNextOqId(unittest.TestCase):
    def test_continues_live_sequence_ignoring_high_outliers(self):
        doc = "| OQ-5 | a | b | c | 2026-06-01 |\n| OQ-900 | one-off | b | c | 2025-01-01 |\n"
        self.assertEqual(ledger_io.next_oq_id(doc), 6)

    def test_empty_doc_starts_at_one(self):
        self.assertEqual(ledger_io.next_oq_id(""), 1)

    def test_uses_high_water_mark_when_rows_have_been_cleaned_up(self):
        # CB-18: once resolved rows are deleted, the row-scan alone would
        # under-count and re-mint an already-used id. The marker must win.
        doc = (
            "**Highest OQ ID ever minted (do not reuse below this number):** 284\n\n"
            "| OQ-190 | only open row left | ctx | unblocks | 2026-04-30 |\n"
        )
        self.assertEqual(ledger_io.next_oq_id(doc), 285)

    def test_row_scan_wins_when_higher_than_marker(self):
        doc = (
            "**Highest OQ ID ever minted (do not reuse below this number):** 5\n\n"
            "| OQ-300 | a fresher row than the marker knows about | ctx | unblocks | 2026-06-18 |\n"
        )
        self.assertEqual(ledger_io.next_oq_id(doc), 301)

    def test_missing_marker_falls_back_to_row_scan(self):
        doc = "| OQ-5 | a | b | c | 2026-06-01 |\n"
        self.assertEqual(ledger_io.next_oq_id(doc), 6)


class TestBumpOqHighWaterMark(unittest.TestCase):
    _DOC = "**Highest OQ ID ever minted (do not reuse below this number):** 284\n\nbody\n"

    def test_raises_marker_when_new_id_is_higher(self):
        new_doc, bumped = ledger_io.bump_oq_high_water_mark(self._DOC, 285)
        self.assertTrue(bumped)
        self.assertIn("Highest OQ ID ever minted (do not reuse below this number):** 285", new_doc)

    def test_noop_when_new_id_not_higher(self):
        new_doc, bumped = ledger_io.bump_oq_high_water_mark(self._DOC, 200)
        self.assertFalse(bumped)
        self.assertEqual(new_doc, self._DOC)

    def test_noop_when_new_id_equal(self):
        new_doc, bumped = ledger_io.bump_oq_high_water_mark(self._DOC, 284)
        self.assertFalse(bumped)
        self.assertEqual(new_doc, self._DOC)

    def test_missing_marker_returns_unchanged_and_false(self):
        doc = "no marker here\n"
        new_doc, bumped = ledger_io.bump_oq_high_water_mark(doc, 300)
        self.assertFalse(bumped)
        self.assertEqual(new_doc, doc)


class TestFormatOqRow(unittest.TestCase):
    def test_format(self):
        row = ledger_io.format_oq_row(300, "**Q?**", "ctx", "unblocks", "2026-06-15")
        self.assertEqual(row, "| OQ-300 | **Q?** | ctx | unblocks | 2026-06-15 |\n")


class TestInsertOqRow(unittest.TestCase):
    def test_inserts_below_header_separator(self):
        doc = (
            "# Title\n\n## Open Questions\n\n"
            "| ID | Question | Context / Spec | Unblocks | Date Added |\n"
            "|----|----------|---------------|----------|-----------|\n"
            "| OQ-5 | existing | ctx | unblocks | 2026-06-01 |\n"
        )
        new_doc, inserted = ledger_io.insert_oq_row(doc, "| OQ-6 | new | ctx | unblocks | 2026-06-15 |\n")
        self.assertTrue(inserted)
        lines = new_doc.splitlines()
        sep_idx = next(i for i, l in enumerate(lines) if l.startswith("|---"))
        self.assertTrue(lines[sep_idx + 1].startswith("| OQ-6 |"))
        self.assertTrue(lines[sep_idx + 2].startswith("| OQ-5 |"))

    def test_no_separator_returns_unchanged_and_false(self):
        doc = "# Title\n\nNo table here.\n"
        new_doc, inserted = ledger_io.insert_oq_row(doc, "| OQ-6 | new | ctx | unblocks | 2026-06-15 |\n")
        self.assertFalse(inserted)
        self.assertEqual(new_doc, doc)


class TestParseOqSummaries(unittest.TestCase):
    def test_parses_all_rows_in_document_order(self):
        entries = ledger_io.parse_oq_summaries(_OQ_DOC)
        self.assertEqual([e["id"] for e in entries], [271, 270, 269])

    def test_single_line_row_gets_bold_summary_and_date(self):
        entries = ledger_io.parse_oq_summaries(_OQ_DOC)
        oq271 = next(e for e in entries if e["id"] == 271)
        self.assertEqual(oq271["summary"], "Some single-line question?")
        self.assertEqual(oq271["date"], "2026-06-15")

    def test_multiline_row_first_line_has_no_trailing_date(self):
        entries = ledger_io.parse_oq_summaries(_OQ_DOC)
        oq270 = next(e for e in entries if e["id"] == 270)
        self.assertEqual(oq270["summary"], "[ORCHESTRATOR] Multi-line question?")
        self.assertIsNone(oq270["date"])

    def test_empty_doc_returns_empty_list(self):
        self.assertEqual(ledger_io.parse_oq_summaries(""), [])


class TestGetOqBlock(unittest.TestCase):
    def test_single_line_block(self):
        block = ledger_io.get_oq_block(_OQ_DOC, 271)
        self.assertEqual(block, "| OQ-271 | **Some single-line question?** | context | unblocks | 2026-06-15 |\n")

    def test_multiline_block_extends_to_next_oq_row(self):
        block = ledger_io.get_oq_block(_OQ_DOC, 270)
        self.assertTrue(block.startswith("| OQ-270 |"))
        self.assertIn("**Problem.**", block)
        self.assertIn("**Options considered:**", block)
        self.assertNotIn("OQ-269", block)

    def test_last_row_block_stops_before_heading(self):
        block = ledger_io.get_oq_block(_OQ_DOC, 269)
        self.assertTrue(block.startswith("| OQ-269 |"))
        self.assertNotIn("## Resolved", block)
        self.assertNotIn("Some resolved history", block)

    def test_missing_id_returns_none(self):
        self.assertIsNone(ledger_io.get_oq_block(_OQ_DOC, 999))


class TestRemoveOqBlock(unittest.TestCase):
    def test_removes_multiline_block_and_leaves_neighbors_intact(self):
        new_doc, removed = ledger_io.remove_oq_block(_OQ_DOC, 270)
        self.assertIsNotNone(removed)
        self.assertIn("**Problem.**", removed)
        self.assertIn("| OQ-271 |", new_doc)
        self.assertIn("| OQ-269 |", new_doc)
        self.assertNotIn("OQ-270", new_doc)
        self.assertNotIn("**Problem.**", new_doc)

    def test_missing_id_returns_unchanged_and_none(self):
        new_doc, removed = ledger_io.remove_oq_block(_OQ_DOC, 999)
        self.assertIsNone(removed)
        self.assertEqual(new_doc, _OQ_DOC)


class TestNextAtId(unittest.TestCase):
    def test_continues_from_highest_id_ignoring_subtask_suffixes(self):
        without_intake = "| AT-1146.2 | **Subtask of AT-1146** | spec | evidence | Small | AT-1146 |\n"
        self.assertEqual(ledger_io.next_at_id(without_intake), 1147)

    def test_empty_queue_starts_at_one(self):
        self.assertEqual(ledger_io.next_at_id(""), 1)


class TestFormatAtRow(unittest.TestCase):
    def test_ready_state_has_no_prefix(self):
        row = ledger_io.format_at_row(1200, "Do the thing", "spec", "None", "evidence", "Small", "Ready")
        self.assertEqual(row, "| AT-1200 | **Do the thing** | spec | evidence | Small | None |\n")

    def test_non_ready_state_prefixes_task_cell(self):
        row = ledger_io.format_at_row(1200, "Do the thing", "spec", "None", "evidence", "Small", "Blocked")
        self.assertEqual(row, "| AT-1200 | **Blocked** -- **Do the thing** | spec | evidence | Small | None |\n")


class TestInsertAtRow(unittest.TestCase):
    _WITH_INTAKE = """# AI Task Queue

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

    _WITHOUT_INTAKE = """# AI Task Queue

## Ready Pool — Top Priority

| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |
|----|------|-------------|---------------|--------|------------|
| AT-1146.2 | **Subtask of AT-1146** | spec | evidence | Small | AT-1146 |
"""

    def test_appends_to_existing_intake_section_newest_first(self):
        row = ledger_io.format_at_row(1151, "Do the new thing", "spec", "None", "evidence", "Small", "Blocked")
        new_text, inserted = ledger_io.insert_at_row(self._WITH_INTAKE, row)
        self.assertTrue(inserted)
        lines = new_text.splitlines()
        intake_idx = next(i for i, l in enumerate(lines) if l == ledger_io._AT_INTAKE_HEADING)
        sep_idx = next(i for i in range(intake_idx, len(lines)) if lines[i].lstrip().startswith("|---"))
        self.assertTrue(lines[sep_idx + 1].startswith("| AT-1151 |"))
        self.assertTrue(lines[sep_idx + 2].startswith("| AT-1150 |"))

    def test_creates_intake_section_when_absent(self):
        row = ledger_io.format_at_row(1147, "Do the new thing", "SR-1.12", "None", "The thing is done", "Small", "Ready")
        new_text, inserted = ledger_io.insert_at_row(self._WITHOUT_INTAKE, row)
        self.assertTrue(inserted)
        self.assertIn(ledger_io._AT_INTAKE_HEADING, new_text)
        self.assertIn("| AT-1147 | **Do the new thing** | SR-1.12 | The thing is done | Small | None |", new_text)
        self.assertIn("| AT-1146.2 | **Subtask of AT-1146** | spec | evidence | Small | AT-1146 |", new_text)

    def test_no_intake_no_ready_pool_returns_unchanged_and_false(self):
        doc = "# AI Task Queue\n\nNothing here.\n"
        new_text, inserted = ledger_io.insert_at_row(doc, "| AT-1 | **x** | s | e | Small | None |\n")
        self.assertFalse(inserted)
        self.assertEqual(new_text, doc)


_AT_DOC = (
    "| AT-1228 | **[Odysseus dispatch] Add dispatch_coding_task. Agent: `typescript`. Model: Tier-C.** "
    "| spec1 | evidence1 | Medium | AT-1231 |\n"
    "| AT-1227 | **[Odysseus dispatch] Add get_coding_task_status. Agent: `docs`. Model: `Tier-R`.** "
    "| spec2 | evidence2 | Small | AT-1228 |\n"
    "| AT-1222 | **Grandfathered row with no Model annotation at all.** | spec3 | evidence3 | Tiny | -- |\n"
    "\n"
    "### Closeout log\n"
    "\n"
    "| AT-1228 | Lane N -- duplicate historical mention, not the live row | 2026-01-01 | -- | x |\n"
)


class TestGetAtBlock(unittest.TestCase):
    def test_returns_first_occurrence_not_a_later_duplicate(self):
        block = ledger_io.get_at_block(_AT_DOC, 1228)
        self.assertTrue(block.startswith("| AT-1228 |"))
        self.assertIn("dispatch_coding_task", block)
        self.assertNotIn("Lane N", block)

    def test_stops_before_next_row(self):
        block = ledger_io.get_at_block(_AT_DOC, 1228)
        self.assertNotIn("AT-1227", block)

    def test_missing_id_returns_none(self):
        self.assertIsNone(ledger_io.get_at_block(_AT_DOC, 9999))


class TestParseAtRow(unittest.TestCase):
    def test_extracts_columns_and_tier_with_no_backtick(self):
        row = ledger_io.parse_at_row(_AT_DOC, 1228)
        self.assertEqual(row["model_tier"], "Tier-C")
        self.assertEqual(row["spec_issue"], "spec1")
        self.assertEqual(row["exit_evidence"], "evidence1")
        self.assertEqual(row["effort"], "Medium")
        self.assertEqual(row["depends_on"], "AT-1231")

    def test_extracts_tier_with_backtick_wrapping(self):
        row = ledger_io.parse_at_row(_AT_DOC, 1227)
        self.assertEqual(row["model_tier"], "Tier-R")

    def test_missing_model_annotation_returns_none_tier_not_a_guess(self):
        row = ledger_io.parse_at_row(_AT_DOC, 1222)
        self.assertIsNone(row["model_tier"])

    def test_missing_id_returns_none(self):
        self.assertIsNone(ledger_io.parse_at_row(_AT_DOC, 9999))


if __name__ == "__main__":
    unittest.main()
