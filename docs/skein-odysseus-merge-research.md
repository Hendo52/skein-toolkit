# Research: Skein-Toolkit <-> Odysseus Integration Depth (AT-1217)

**Date:** 2026-06-19
**Scope:** Research only, per this AT's own constraint -- this does not
decide to merge; it produces the evidence base for a future OQ, and
recommends whether that OQ is ripe yet.

## 1. What "merge" would concretely mean -- two very different depths

**Depth A -- codebase merge.** Skein MCP's tools (`dispatch_coding_task`,
`create_actionable_task`, `ledger_io.py`, etc.) become native Odysseus
Python code, no separate MCP server process. Odysseus's own codebase
absorbs the AT/OQ ledger tooling directly.

**Depth B -- MCP-client integration (today's actual, working depth).**
Odysseus and skein-toolkit remain separate repos/processes; Odysseus
connects to Skein MCP as an external server (already true today --
`feat: auto-register skein-toolkit MCP server as built-in SSE provider`,
odysseus commit `bef0108`). Tools are called remotely over the documented
MCP protocol, not imported as Python modules.

These are not a spectrum with a "best" middle point -- they're qualitatively
different architectures with different tradeoffs, which is why this
section leads with naming them rather than assuming "merge" means one
obvious thing.

## 2. New evidence since AT-1217 was written (2026-06-18 -> today)

The entire dispatch architecture built and validated for real today
(`dispatch_coding_task`/`get_coding_task_status`/`promote_coding_task`,
`supervisor_triage.py`, `supervision-watcher.ps1`'s extension) lives
**entirely within skein-toolkit**, at Depth B. Odysseus's dashboard
(AT-1220..1226, designed in AT-1234 but not yet built) would consume this
purely as an MCP client -- reading job-state JSON, calling tools remotely.
Nothing built or designed today required Depth A. This is concrete,
load-bearing evidence that didn't exist when this AT was originally
queued: a real, working, multi-tool system was just built and proven at
Depth B, with no friction that argued for Depth A.

## 3. Does merge change Odysseus's upstream-contribution posture?

Yes, and a separate piece of today's work makes this concrete rather than
abstract. Resolving OQ-290 (2026-06-19, the aider-evaluation OQ), the
architect stated explicitly: the Odysseus fork exists "for convenience
during development," with intent to contribute back to the main Odysseus
project eventually -- not to permanently diverge -- and any fork
modifications must stay "cleanly labelled/separated from upstream
Odysseus code."

Depth A (codebase merge) actively works against this: once skein-toolkit's
AT/OQ ledger tooling is woven into Odysseus's own files, it can't be
cleanly extracted back out for an upstream contribution -- the fork would
permanently carry fork-specific tooling baked into its core. Depth B
preserves the posture by construction: Skein MCP is an entirely separate,
optional, pluggable server. Odysseus's *own* code (the fork-specific parts
flagged in AT-1191's design requirement -- the `# fork-specific:` marker
convention already partially in use in `builtin_endpoints.py`) stays
small and isolable; the bulk of the AT/OQ tooling lives somewhere that
was never part of upstream Odysseus to begin with, so there's nothing to
extract.

**Finding: staying at Depth B is not a compromise pending a future Depth A
-- it is the architecture that actually serves the stated contribution
goal.**

## 4. Should the AT/OQ tooling become Odysseus's "native" project-management layer?

Already effectively true in the sense that matters, without requiring
Depth A. `create_actionable_task`/`create_open_question`/
`resolve_open_question` are generic capabilities any properly-configured
consuming repo can use -- they resolve paths via `WORKSPACE_ROOT`, not via
being physically part of any particular codebase. (A real bug in exactly
this resolution was found and fixed today, AT-1228's smoke test: neither
`start-skein.ps1` nor `toolchain-doctor.ps1`'s restart path ever set
`WORKSPACE_ROOT`, so the live server had been silently misconfigured. Fixed
in skein-toolkit commit `0b883c1`.) AT-1234's dashboard CRUD design
(today) already treats this as Depth B's natural shape: the dashboard
calls Skein MCP's tools remotely for AT/OQ/job display and actions, no
Odysseus-side reimplementation of ledger logic needed.

## 5. Recommendation on OQ readiness

**Not ripe for a "should we merge" OQ right now -- and the reason is not
"insufficient evidence," it's that the evidence increasingly points one
way.** OQ-278's original framing (2026-06-17) was that the contribution
target would become clearer once skein-toolkit's own evaluations
(AT-1194..1200) were done. Today's evidence arrived from a different,
more concrete source than those evaluations -- a real production system
built and proven at Depth B, plus a real architect statement (OQ-290)
about contribution intent that directly bears on the merge question. That
evidence doesn't make this a closer call; it makes "stay at Depth B"
the evidence-backed default, not a 50/50 decision needing the architect's
tie-breaking judgment.

**When to revisit:** if a concrete capability turns out to be impossible
or seriously degraded at arm's length (e.g. a latency or reliability
requirement Depth B's remote-MCP-call model can't meet, discovered through
real use of the dashboard once AT-1220..1226 are built), that's the trigger
for a real OQ -- a specific, named friction, not a recurring "should we
merge" check-in with no new information.
