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
_OQ_HIGH_WATER_MARK_RE = re.compile(r"\*\*Highest OQ ID ever minted[^:]*:\*\*\s*(\d+)")


def next_oq_id(oq_doc_text: str) -> int:
    """Pick the next free OQ id. The live sequence the architect works through
    is contiguous in the low hundreds; OQ-900 is a one-off from a different
    numbering context (a geometry/zone-classification question raised
    2026-05-09 -- ids here are not chronological). Minting OQ-901 next to that
    one-off would start a second sequence; continuing the live one is what an
    architect skimming the table top-to-bottom would expect.

    CB-18 fix: a resolved OQ's row is meant to be deleted from the table (see
    remove_oq_block), not left in place with an inline decision note -- but
    that means a naive row-scan can no longer see the true historical max
    once old rows are cleaned up, and would start re-minting already-used IDs.
    The doc's '**Highest OQ ID ever minted...:** N' marker line is the
    persistent source of truth that survives row deletion; live-table rows
    are still scanned too (belt-and-suspenders for a doc where the marker
    line was edited by hand and drifted) and the higher of the two wins."""
    ids = [int(m) for m in re.findall(r"^\|\s*OQ-(\d+)\s*\|", oq_doc_text, re.MULTILINE)]
    live_sequence = [i for i in ids if i < 500]
    row_max = max(live_sequence) if live_sequence else max(ids, default=0)
    marker_match = _OQ_HIGH_WATER_MARK_RE.search(oq_doc_text)
    marker_max = int(marker_match.group(1)) if marker_match else 0
    return max(row_max, marker_max) + 1


def bump_oq_high_water_mark(doc_text: str, oq_id: int) -> "tuple[str, bool]":
    """Raise the doc's '**Highest OQ ID ever minted...:** N' marker to oq_id
    if oq_id is higher than the current marker value. Returns (doc_text,
    False) unchanged if no marker line is found, or if oq_id does not exceed
    the current value -- the caller must not silently lose the marker."""
    match = _OQ_HIGH_WATER_MARK_RE.search(doc_text)
    if match is None:
        return doc_text, False
    current = int(match.group(1))
    if oq_id <= current:
        return doc_text, False
    start, end = match.span(1)
    new_text = doc_text[:start] + str(oq_id) + doc_text[end:]
    return new_text, True


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


_AT_HIGH_WATER_MARK_RE = re.compile(r"\*\*Highest AT ID ever minted[^:]*:\*\*\s*(\d+)")


def next_at_id(queue_text: str) -> int:
    """Pick the next free AT id: the highest AT-<N> referenced anywhere in
    ai-task-queue.md, plus 1. `.N` subtask suffixes (e.g. AT-1146.2) are
    ignored -- the regex captures only the base number before any '.'.

    CB-26 fix (2026-06-19, the same class of bug as CB-18's OQ-id fix):
    found when ai-task-queue.md grew to ~232K tokens -- large enough to
    exceed a real model's context window and break Cline mid-task -- and
    the fix (archiving struck-through/Done rows to a separate file, mirroring
    the OQ ledger's resolved-row policy) would have silently re-minted
    already-used AT ids once their rows left the live document, exactly
    like CB-18 before the OQ marker line existed. The doc's '**Highest AT ID
    ever minted...:** N' marker line is the persistent source of truth that
    survives row archival; live-table rows are still scanned too (belt-and-
    suspenders for a doc where the marker line was edited by hand and
    drifted) and the higher of the two wins."""
    ids = [int(m) for m in re.findall(r"AT-(\d+)", queue_text)]
    row_max = max(ids) if ids else 0
    marker_match = _AT_HIGH_WATER_MARK_RE.search(queue_text)
    marker_max = int(marker_match.group(1)) if marker_match else 0
    return max(row_max, marker_max) + 1


def bump_at_high_water_mark(doc_text: str, at_id: int) -> "tuple[str, bool]":
    """Raise the doc's '**Highest AT ID ever minted...:** N' marker to at_id
    if at_id is higher than the current marker value. Returns (doc_text,
    False) unchanged if no marker line is found, or if at_id does not exceed
    the current value -- the caller must not silently lose the marker."""
    match = _AT_HIGH_WATER_MARK_RE.search(doc_text)
    if match is None:
        return doc_text, False
    current = int(match.group(1))
    if at_id <= current:
        return doc_text, False
    start, end = match.span(1)
    new_text = doc_text[:start] + str(at_id) + doc_text[end:]
    return new_text, True


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


# AT-1228: AT rows had no get_oq_block-style accessor before this -- every
# prior AT-row lookup in this codebase was done by an agent grepping/reading
# the file directly. dispatch_coding_task needs to resolve a row
# programmatically, so this mirrors the OQ block functions above rather than
# inventing a separate convention.
_AT_ROW_START_RE = re.compile(r"^\|\s*AT-(\d+)\s*\|", re.MULTILINE)
# Tolerates the inconsistent formatting actually used across existing rows:
# "Model: Tier-R", "Model: Tier-C.", "Model: `Tier-C`.", etc.
_AT_MODEL_TIER_RE = re.compile(r"Model:\s*`?(Tier-[RCM])`?\.?")


def _at_block_bounds(doc_text: str, at_id: int) -> "tuple[int, int] | None":
    """Same shape as _oq_block_bounds, for AT-<at_id>. AT rows are single-line
    in every row this codebase has produced so far (format_at_row always
    emits one line), but this still scans to the next row/heading rather than
    assuming exactly one line, for the same reason _oq_block_bounds does:
    a future row format change shouldn't silently break this."""
    lines = doc_text.splitlines(keepends=True)
    starts: list[tuple[int, int, int]] = []
    offset = 0
    for idx, line in enumerate(lines):
        m = _AT_ROW_START_RE.match(line)
        if m:
            starts.append((int(m.group(1)), idx, offset))
        offset += len(line)

    target = next((s for s in starts if s[0] == at_id), None)
    if target is None:
        return None
    _, start_idx, start_offset = target
    later_starts = [s[1] for s in starts if s[1] > start_idx]
    end_idx = min(later_starts) if later_starts else len(lines)
    for idx in range(start_idx + 1, end_idx):
        if _HEADING_RE.match(lines[idx]):
            end_idx = idx
            break
    end_offset = sum(len(l) for l in lines[:end_idx])
    return start_offset, end_offset


def get_at_block(doc_text: str, at_id: int) -> "str | None":
    """Return AT-<at_id>'s full row text, or None if not found. Returns the
    FIRST occurrence in document order -- ai-task-queue.md is known to
    contain duplicate/historical re-mentions of some AT ids in separate
    closeout-log tables further down the file (found 2026-06-18, AT-1239's
    motivating example); the live Intake-table row is always the first one
    encountered top-to-bottom."""
    bounds = _at_block_bounds(doc_text, at_id)
    if bounds is None:
        return None
    start, end = bounds
    return doc_text[start:end]


def parse_at_row(doc_text: str, at_id: int) -> "dict | None":
    """Parse AT-<at_id>'s row into its table columns plus an extracted
    model_tier. Returns None if the row isn't found. Returns
    {"id", "raw", "description", "spec_issue", "exit_evidence", "effort",
    "depends_on", "model_tier"} -- model_tier is None if no "Model: Tier-X"
    annotation is found (grandfathered pre-policy rows, per
    ai-model-selection-policy.md S11.2 -- the caller must decide what to do
    about a missing tier, this function does not guess one)."""
    block = get_at_block(doc_text, at_id)
    if block is None:
        return None
    # Split on " | " at the top level of the markdown table row. AT
    # descriptions can themselves contain pipe-adjacent characters in code
    # spans, but every row produced by format_at_row uses literal " | "
    # (space-pipe-space) only as the column separator, never inside a cell --
    # splitting on that exact substring is safe for this codebase's rows.
    body = block.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cols = [c.strip() for c in body.split(" | ")]
    if len(cols) < 6:
        return None
    _id_col, description, spec_issue, exit_evidence, effort, depends_on = cols[:6]
    tier_match = _AT_MODEL_TIER_RE.search(description)
    return {
        "id": at_id,
        "raw": block,
        "description": description,
        "spec_issue": spec_issue,
        "exit_evidence": exit_evidence,
        "effort": effort,
        "depends_on": depends_on,
        "model_tier": tier_match.group(1) if tier_match else None,
    }
