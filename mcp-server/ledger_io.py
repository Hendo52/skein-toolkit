#!/usr/bin/env python3
"""
ledger_io.py -- pure text-transformation functions for the markdown ledgers
local-mcp.py reads and writes: the OQ ("open questions") ledger and the AT
(actionable task) queue.

These functions take/return plain strings (whole-document text), never touch
the filesystem, and have no dependency on local-mcp.py's globals (WORKSPACE,
ORCHESTRATOR_OQ_LEDGER_PATH, etc.). local-mcp.py's `_append_oq_row` /
`_append_at_row` etc. do the file I/O and path resolution and delegate the
"where does this text go" logic to the functions here. Splitting the layers
this way means the ledger-format logic -- the highest-stakes code in
local-mcp.py, since it edits documents the architect and the Auto Mode
permission classifier both treat as canonical -- can be unit-tested without a
tempfile or a FastMCP server (see tests/test_ledger_io.py).
"""

import re

# ---------------------------------------------------------------------------
# OQ ledger (architect-open-questions.md)
# ---------------------------------------------------------------------------

_OQ_ROW_START_RE = re.compile(r"^\|\s*OQ-(\d+)\s*\|", re.MULTILINE)
_OQ_TABLE_SEP_RE = re.compile(r"^\|\s*-{2,}")
_OQ_TRAILING_DATE_RE = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*$")
_OQ_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_HEADING_RE = re.compile(r"^#{1,6}\s")


def next_oq_id(oq_doc_text: str) -> int:
    """Pick the next free OQ id. The live sequence the architect works through
    is contiguous in the low hundreds (currently topping out at OQ-258);
    OQ-900 is a one-off from a different numbering context (a geometry/zone-
    classification question raised 2026-05-09, well BEFORE OQ-258's 2026-05-28
    -- ids here are not chronological). Minting OQ-901 next to that one-off
    would start a second sequence; continuing the live one (OQ-259) is what an
    architect skimming the table top-to-bottom would expect."""
    ids = [int(m) for m in re.findall(r"^\|\s*OQ-(\d+)\s*\|", oq_doc_text, re.MULTILINE)]
    live_sequence = [i for i in ids if i < 500]
    return (max(live_sequence) if live_sequence else max(ids, default=0)) + 1


def format_oq_row(oq_id: int, question: str, context: str, unblocks: str, date: str) -> str:
    return f"| OQ-{oq_id} | {question} | {context} | {unblocks} | {date} |\n"


def insert_oq_row(doc_text: str, row: str) -> "tuple[str, bool]":
    """Insert a freshly-formatted OQ row directly below the Open Questions
    table's header separator -- the file's existing convention is newest-first
    (OQ-258 sits above OQ-257, etc.), so a fresh row belongs at the top of the
    table body, not the bottom. Returns (doc_text, False) unchanged if no
    '|---' separator line is found -- the caller must not silently lose an OQ
    it believes it raised."""
    lines = doc_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if _OQ_TABLE_SEP_RE.match(line.lstrip()):
            lines.insert(i + 1, row)
            return "".join(lines), True
    return doc_text, False


def _oq_block_bounds(doc_text: str, oq_id: int) -> "tuple[int, int] | None":
    """Return (start, end) character offsets of the OQ-<oq_id> row's full
    block -- the header line plus any continuation lines up to (but not
    including) the next '| OQ-<N> |' row, the next heading, or end of text.
    Many OQ rows (e.g. orchestrator-raised ambiguity OQs) span multiple
    physical lines via literal newlines inside the Question cell, so a block
    is not always a single line. Returns None if OQ-<oq_id> isn't found."""
    lines = doc_text.splitlines(keepends=True)
    starts: list[tuple[int, int, int]] = []  # (oq_id, line_index, char_offset)
    offset = 0
    for idx, line in enumerate(lines):
        m = _OQ_ROW_START_RE.match(line)
        if m:
            starts.append((int(m.group(1)), idx, offset))
        offset += len(line)

    target = next((s for s in starts if s[0] == oq_id), None)
    if target is None:
        return None
    _, start_idx, start_offset = target
    later_starts = [s[1] for s in starts if s[1] > start_idx]
    end_idx = min(later_starts) if later_starts else len(lines)
    # Stop early if a heading line appears before the next OQ row.
    for idx in range(start_idx + 1, end_idx):
        if _HEADING_RE.match(lines[idx]):
            end_idx = idx
            break
    end_offset = sum(len(l) for l in lines[:end_idx])
    return start_offset, end_offset


def get_oq_block(doc_text: str, oq_id: int) -> "str | None":
    """Return the full multi-line block for OQ-<oq_id> (the row plus any
    continuation lines), or None if not found."""
    bounds = _oq_block_bounds(doc_text, oq_id)
    if bounds is None:
        return None
    start, end = bounds
    return doc_text[start:end]


def remove_oq_block(doc_text: str, oq_id: int) -> "tuple[str, str | None]":
    """Remove OQ-<oq_id>'s full block from the Open Questions table. Returns
    (new_doc_text, removed_block) on success, or (doc_text, None) if
    OQ-<oq_id> isn't found -- the caller must not silently report success for
    an id that was never removed.

    This is deliberately the ONLY thing this function does: it does not write
    a "Last updated" changelog entry summarizing the resolution. Composing
    that narrative requires the architect's actual decision and an agent's
    judgment about how to phrase it -- that is a first-class step of its own,
    not a "fallback" this function skips. Callers (e.g.
    local-mcp.py's resolve_open_question tool) return the removed block text
    so the caller can compose and write that entry separately."""
    bounds = _oq_block_bounds(doc_text, oq_id)
    if bounds is None:
        return doc_text, None
    start, end = bounds
    removed = doc_text[start:end]
    new_text = doc_text[:start] + doc_text[end:]
    return new_text, removed


def _oq_summary(block: str) -> str:
    """Pull a short human-readable summary out of an OQ block's Question
    cell: the first bolded span if present (the convention is to bold the
    one-line question title), else the first ~160 chars of the cell."""
    first_line = block.splitlines()[0]
    # Strip the leading "| OQ-<N> |" cell.
    cell = re.sub(r"^\|\s*OQ-\d+\s*\|\s*", "", first_line)
    bold = _OQ_BOLD_RE.search(cell)
    if bold:
        summary = bold.group(1)
    else:
        summary = cell
    summary = summary.strip()
    if len(summary) > 160:
        summary = summary[:157].rstrip() + "..."
    return summary


def parse_oq_summaries(doc_text: str) -> "list[dict]":
    """Return [{"id": int, "summary": str, "date": str | None}, ...] for every
    OQ row in the Open Questions table, in document order (the ledger's
    convention is newest-first). `date` is the row's trailing "Date Added"
    cell (the last '| YYYY-MM-DD |' on the row's first line), or None if the
    row's first line doesn't end with one (e.g. a continuation-heavy
    orchestrator OQ whose first line is mid-sentence)."""
    results = []
    for line in doc_text.splitlines():
        m = _OQ_ROW_START_RE.match(line)
        if not m:
            continue
        oq_id = int(m.group(1))
        date_match = _OQ_TRAILING_DATE_RE.search(line)
        date = date_match.group(1) if date_match else None
        results.append({"id": oq_id, "summary": _oq_summary(line), "date": date})
    return results


# ---------------------------------------------------------------------------
# AT queue (ai-task-queue.md)
# ---------------------------------------------------------------------------

_AT_READY_POOL_HEADING_PREFIX = "## Ready Pool"
_AT_INTAKE_HEADING = "### Newly Decomposed Tasks (Intake)"
_AT_INTAKE_INTRO = (
    "> New AT rows created via the `create_actionable_task` MCP tool (AT-1138) land here for "
    "triage -- review/add `Agent:`/`Model:` annotations and dependencies, then relocate each "
    "row into its appropriate lane.\n"
)
_AT_TABLE_HEADER = "| ID | Task | Spec / Issue | Exit Evidence | Effort | Depends On |\n"
_AT_TABLE_SEP = "|----|------|-------------|---------------|--------|------------|\n"


def next_at_id(queue_text: str) -> int:
    """Pick the next free AT id: the highest AT-<N> referenced anywhere in
    ai-task-queue.md, plus 1. `.N` subtask suffixes (e.g. AT-1146.2) are
    ignored -- the regex captures only the base number before any '.'."""
    ids = [int(m) for m in re.findall(r"AT-(\d+)", queue_text)]
    return (max(ids) if ids else 0) + 1


def format_at_row(at_id: int, description: str, spec_issue: str, dependencies: str,
                   exit_evidence: str, effort: str, state: str) -> str:
    task_cell = f"**{description}**"
    if state != "Ready":
        task_cell = f"**{state}** -- {task_cell}"
    return f"| AT-{at_id} | {task_cell} | {spec_issue} | {exit_evidence} | {effort} | {dependencies} |\n"


def insert_at_row(queue_text: str, row: str) -> "tuple[str, bool]":
    """Insert a freshly-formatted AT row into the `### Newly Decomposed Tasks
    (Intake)` subsection at the top of `## Ready Pool ...`, creating that
    subsection (with its own table) if it doesn't exist yet. New rows go
    directly below the subsection's table header separator (newest first,
    matching insert_oq_row's convention for the OQ ledger). Returns
    (queue_text, False) unchanged if neither the Intake subsection nor the
    Ready Pool heading can be found -- the caller must not silently lose an AT
    it believes it created."""
    lines = queue_text.splitlines(keepends=True)

    for i, line in enumerate(lines):
        if line.rstrip("\n") == _AT_INTAKE_HEADING:
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## ") or lines[j].startswith("### "):
                    return queue_text, False
                stripped = lines[j].lstrip()
                if stripped.startswith("|---") or stripped.startswith("|----") or stripped.startswith("| ---"):
                    lines.insert(j + 1, row)
                    return "".join(lines), True
            return queue_text, False

    for i, line in enumerate(lines):
        if line.startswith(_AT_READY_POOL_HEADING_PREFIX):
            lines[i + 1:i + 1] = [
                "\n",
                _AT_INTAKE_HEADING + "\n",
                "\n",
                _AT_INTAKE_INTRO,
                "\n",
                _AT_TABLE_HEADER,
                _AT_TABLE_SEP,
                row,
                "\n",
            ]
            return "".join(lines), True

    return queue_text, False
