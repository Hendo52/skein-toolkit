# Supervisor (Tier C) Cost Model and Candidate High-Tier Activities -- 2026-06-14

**Type:** Research note (Tier C / Claude Code supervisor contribution)
**Status:** Input to AT-1159
**Author:** Claude Code (Sonnet), supervising a live Cline session

## 1. Why this note exists

During a live supervision session (watching Cline execute AT-1142/1156/1157
via the CF proxy), the architect observed that supervision and high-level
guidance -- periodic check-ins, steering corrections, writing follow-up AT
tasks when work fails or partially succeeds, and raising OQs -- might
themselves be a cost-effective use of a frontier/Tier-C model, *if* the
per-activity cost is well understood. This note provides the Tier-C cost
model and a first cut at candidate activity types, as input to AT-1159's
cost-allocation framework.

## 2. The Tier-C cost model: prompt caching dominates

Tier-C (Claude Sonnet) billing is governed by Anthropic's prompt cache:
cache-read tokens cost roughly 10-12x less than cache-write/fresh-processing
tokens, and the cache has a ~5 minute TTL.

- A supervisor check that lands within 5 minutes of the previous one is
  almost free: only the *new* tokens (a `grep -c`, a small `tail`) are billed
  at the expensive rate; the accumulated conversation history is billed at the
  cheap cache-read rate.
- A check beyond 5 minutes is a cache miss: the *entire* accumulated
  conversation is reprocessed at the expensive rate, and that base grows over
  the session.

**Practical consequence:** the cost of a supervision activity is not primarily
a function of "how smart the model needs to be" -- it's a function of (a) how
much context the supervisor has already accumulated, and (b) how much new
context each activity adds. A judgment-heavy but textually small activity
(e.g. "does this commit satisfy AC-4? yes/no, here's why") is cheap. A
judgment-heavy activity that requires reading a large new artifact (a full
log, a large diff, a long design doc) is expensive regardless of how "smart"
the judgment itself is.

See `[[feedback_supervision_cost]]` (Claude Code memory, same date) for the
full mechanism writeup.

## 3. Tonight's rough cost data point

For calibration (order-of-magnitude, not precise -- no direct billing API was
available to the supervisor):

- ~2 hours of passive supervision (periodic ~15-20 min checks, each a
  `git log --oneline`, a small log `tail`, and a spend-file read) of Cline's
  AT-1142/1156/1157 run.
- Estimated Tier-C cost for this stretch: **roughly $1-2 USD**, dominated by
  the handful of >5-minute cache-miss wake-ups reprocessing a growing
  conversation base, plus thinking/output tokens per turn.
- Comparison: Cline's own CF-proxy spend over the same evening was
  **~$15-22 AUD** (Tier A, `cf/kimi-k2.6`), i.e. roughly an order of magnitude
  higher than the supervisor's cost for this stretch.

This single data point suggests passive supervision is *cheap relative to the
work being supervised* -- but one evening's anecdote is not a framework. AT-1159
should establish whether this ratio holds across task types, and what drives
the variance (context size accumulated before supervision starts is likely the
biggest factor).

## 4. Candidate Tier-C ("high") activity types

These are activity types that look like good candidates for a Tier-C
supervisor specifically *because* they are infrequent and judgment-heavy
relative to their textual footprint -- the opposite of routine execution,
which is frequent and high-footprint (lots of file edits, tool calls) but
comparatively low-judgment per step.

1. **Passive supervision / high-level steering.** Periodic minimal-footprint
   checks on a running Tier-A agent; intervene only when a clear, falsifiable
   problem appears (stalled progress, budget approaching cap, contradictory
   output). Cost driver: check frequency x per-check footprint, per §2-3
   above.

2. **Failure-driven AT authoring.** When a Tier-A agent's work fails or
   partially succeeds in an unexpected way, drafting the follow-up AT
   (root-causing what went wrong, scoping the fix, writing exit evidence) is a
   single judgment-heavy event, not a recurring cost. This is plausibly *more*
   reliable from Tier C than from Tier A, because the AT schema
   (`task-and-oq-authoring-standard.md`) requires synthesizing "what was
   attempted, what happened, what should happen next" -- exactly the kind of
   small-context, high-judgment task where Tier C's reliability advantage
   matters most and its cost (one-shot, not recurring) is smallest.

3. **OQ raising.** Similarly one-shot and judgment-heavy: the materiality
   filter and mandatory precedent search
   (`oq-authoring-and-precedent-search-policy.md`) require weighing whether a
   fork is genuinely architectural -- a task where Tier A's unreliability
   (per the architect's stated distrust) is most costly to get wrong (a bad OQ
   either blocks unnecessarily or lets an irreversible decision slide through
   unflagged).

## 5. What AT-1159 still needs

- **Tier-A reliability data.** AT-1157 (in progress as of this note) measures
  Tier A+Enabled vs Tier C+Bare pass rates on 5 Level-2 tasks. AT-1159 should
  cross-reference those results directly: low Tier-A reliability on a task
  type strengthens the case for routing that task type's *AT-authoring and
  OQ-raising* (not just execution) to Tier C.
- **A repeatable Tier-C cost measurement.** §3's number is a one-off estimate.
  AT-1159 should propose a lightweight, repeatable way to record Tier-C
  supervision cost per session (even if approximate) so the $1-2 USD vs
  $15-22 AUD ratio above can be tracked over time rather than re-estimated.
- **Concrete $ / activity-type routing rules.** A first-cut table: activity
  type -> recommended tier -> rough cost basis -> revisit trigger. If the data
  above is insufficient to propose thresholds with confidence, AT-1159 should
  raise an OQ per `oq-authoring-and-precedent-search-policy.md` rather than
  guess.
