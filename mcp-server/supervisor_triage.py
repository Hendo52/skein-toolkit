#!/usr/bin/env python3
"""
supervisor_triage.py -- AT-1233. Decision logic for the supervisor wake-loop's
four-item menu (retry / restart_dependency / revert / raise_oq), split out
the same way dispatch_io.py and ledger_io.py split out their own concerns:
the actual judgment-call logic should be unit-testable against canned
log/state inputs without needing a live wake cycle, a real LiteLLM call, or
a real stuck job to reproduce.

Design (odysseus-agentic-dispatch-architecture.md S3.5/S3.6, OQ-289):
the woken supervisor reads supervision-watcher.ps1's structured log
(supervision-status.json) and, for each stuck entry, needs one of four
actions recommended -- not guessed at fresh each time. recommend_action()
pattern-matches the job's log tail against signatures of failure modes
already seen for real this session (CF 429s, Anthropic credit exhaustion,
toolchain-down errors, execution-policy/interpreter mismatches) to recommend
retry or restart_dependency; falls back to raise_oq for anything that
doesn't clearly match a known, retryable/fixable signature -- consistent
with this architecture's conservative bias toward asking rather than
guessing on ambiguous cases (the same bias dispatch_coding_task's own
working-tree-precondition check uses).

revert is deliberately NOT pattern-matched here -- recognizing "this job's
output is a mess, discard it" requires judging the actual diff/commit
content, not just log text, which this module does not have access to and
should not guess at. A future caller with that context (e.g. a richer
supervisor that diffs the branch) can layer a revert recommendation on top;
this module's job is to handle what's mechanically decidable from the log
alone and raise_oq for everything else, including revert candidates.
"""

import re

# Each pattern is matched against the job's log tail (case-insensitive).
# Order matters: RESTART_DEPENDENCY_PATTERNS checked first, since several of
# these (e.g. "Connection error") could superficially overlap with a
# RETRY-worthy transient if checked in the wrong order -- a toolchain that's
# actually down needs fixing before any retry has a chance of succeeding,
# so misclassifying it as "just retry" would spin uselessly.
_RESTART_DEPENDENCY_PATTERNS = [
    # CB-15/CB-24-shaped: the toolchain itself (LiteLLM, local-mcp.py) isn't
    # reachable -- found for real this session via the AT-1228/1189 smoke
    # tests when both services had quietly stopped between sessions.
    re.compile(r"litellm is not responding", re.IGNORECASE),
    re.compile(r"nothing is listening on port", re.IGNORECASE),
    # Found for real this session (AT-1228 smoke test): a bare `powershell`
    # invocation hits the machine's execution policy.
    re.compile(r"running scripts is disabled on this system", re.IGNORECASE),
    # Found for real this session (AT-1228 smoke test): toolchain-doctor.ps1
    # uses PowerShell-7-only syntax invoked via the wrong interpreter.
    re.compile(r"unexpected token.*in expression or statement", re.IGNORECASE),
    re.compile(r"parseexception", re.IGNORECASE),
]

_RETRY_PATTERNS = [
    # Found for real this session (CB-23, and again during AT-1162's dispatch
    # run): Anthropic credit exhaustion and CF Workers AI capacity errors --
    # both transient in the sense that retrying later (or falling through to
    # the next model in the tier's candidate list) can succeed.
    re.compile(r"credit balance is too low", re.IGNORECASE),
    re.compile(r"\b429\b", re.IGNORECASE),
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"capacity", re.IGNORECASE),
    # Found for real this session (AT-1196, 2026-06-20): a long, otherwise-
    # successful dispatch lost all its work to a CF "Internal server error"
    # (status 500, code 8004) on what was likely the final tool-result round
    # trip -- the same class of transient CF-side hiccup as the 429s above,
    # just a different status code. local-mcp.py's own CF_TRANSIENT_RETRY_
    # STATUS_CODES now retries this at the proxy level; this signature lets
    # the supervisor recognize a job that still failed despite that (e.g.
    # the retry budget was exhausted too) as retryable rather than raising
    # an OQ for something a simple re-dispatch can resolve. Deliberately NOT
    # a bare \b500\b pattern -- that number appears too often in unrelated
    # contexts (line counts, file sizes, port numbers) for a safe match;
    # "internal server error" is CF's own specific phrase for this failure.
    re.compile(r"internal server error", re.IGNORECASE),
    # Found for real this session (AT-1194's aider evaluation): a degenerate
    # empty completion from a CF model under context pressure -- this
    # project's own already-tracked chronic problem (cf-proxy-cheap-model-
    # context-budget-roadmap.md). Retrying (possibly via a different model in
    # the candidate list) is the established mitigation, not a structural fix.
    re.compile(r"empty response received from llm", re.IGNORECASE),
    re.compile(r"connection error", re.IGNORECASE),
    re.compile(r"timed out|timeout", re.IGNORECASE),
]

_VALID_ACTIONS = ("retry", "restart_dependency", "raise_oq")


def recommend_action(log_tail: str) -> "tuple[str, str]":
    """Returns (action, reasoning). action is one of "retry",
    "restart_dependency", "raise_oq" -- never "revert" (see module
    docstring for why). Checks restart_dependency signatures before retry
    signatures, since a down toolchain needs fixing before retrying has any
    chance of working.

    Whitespace (including embedded newlines) is collapsed before matching:
    found via this AT's own real dry run against an actual captured log --
    PowerShell console output wraps at the terminal width, so a real log
    can contain "running scripts is \\ndisabled on this system" with the
    phrase split across a line break. A pattern with no DOTALL/whitespace
    tolerance silently misses this and falls through to raise_oq, which
    would have been a confidently-wrong "no known cause" on a failure this
    module's own pattern list already covers."""
    if not log_tail:
        return "raise_oq", "no log tail available to classify -- nothing to pattern-match against"

    normalized = re.sub(r"\s+", " ", log_tail)

    for pattern in _RESTART_DEPENDENCY_PATTERNS:
        m = pattern.search(normalized)
        if m:
            return "restart_dependency", f"log matches a known toolchain-down signature: {m.group(0)!r}"

    for pattern in _RETRY_PATTERNS:
        m = pattern.search(normalized)
        if m:
            return "retry", f"log matches a known transient-failure signature: {m.group(0)!r}"

    return "raise_oq", "log tail does not match any known retryable/fixable signature -- needs architect judgment (this includes any revert candidate, which this module never recommends on its own)"


def format_recommendation(job_id: str, at_id, action: str, reasoning: str) -> str:
    """Human-readable line for the woken supervisor's own report, not a log
    line for supervision-status.json (that's supervision-watcher.ps1's own
    schema, written in PowerShell -- this just formats the Python-side
    triage result for inclusion in the supervisor's response/report)."""
    assert action in _VALID_ACTIONS, f"format_recommendation got an action this module never returns: {action!r}"
    return f"job {job_id} (AT-{at_id}): recommend {action} -- {reasoning}"
