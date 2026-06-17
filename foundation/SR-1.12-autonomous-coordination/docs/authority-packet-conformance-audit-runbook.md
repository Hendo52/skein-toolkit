# Authority-Packet Conformance Audit Runbook

This runbook operationalizes [authority-packet-conformance-audit.md](../specs/authority-packet-conformance-audit.md). It is procedural guidance for humans and agents running the audit. The spec remains the normative source.

---

## 1 — When To Use This Runbook

Use this runbook when one of these conditions exists:

1. A dashboard item, queue item, or spec row appears out of sync with the actual repo state.
2. A reintegration candidate claims Done, Implemented, or Verified and you need to confirm the authority packet supports that claim.
3. Two coordination surfaces point to different next actions and you need a deterministic handoff.
4. An answered architect question appears to have changed practice, but the governing spec or lifecycle state has not been updated.

---

## 2 — Inputs To Collect First

Collect the packet in this order so the audit stays scoped and deterministic:

1. The governing spec file.
2. The owning row in [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md).
3. The current or recently closed dashboard entry in [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md), when the audited item is dashboard-tracked.
4. Any linked answered architect question in [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md), when one exists and is relevant to the disputed claim.
5. The queue entry in [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md), and any relevant shaping note in [architecture-docs/global/tik-tok-queue-system.md](../../../architecture-docs/global/tik-tok-queue-system.md), when queue or dispatch state is part of the audited scope.
6. The claimed implementation artifacts.
7. The claimed verification artifacts for any Implemented, Verified, or Done claim.

Stop if you cannot name the exact audited item. Split the work into separate audits instead of widening the packet.

---

## 3 — Checklist Order

Work the checklist in this order:

1. Name the audit scope.
2. Freeze the packet sources.
3. Extract the governing claim from the spec and index row.
4. Read dashboard state before queue state when the item is dashboard-tracked.
5. Check for answered OQs that narrow or override that claim when an answered OQ exists for the audited scope.
6. Compare implementation evidence against the governing claim.
7. Compare verification evidence against any Implemented, Verified, or Done claim.
8. Classify findings.
9. Route each finding to its governance destination.
10. Record the audit output in the same workstream.

---

## 4 — Practical Execution Steps

### Step 1 — Name The Scope

Write one line naming the audit target. Good examples:

- `AT-558 / authority-packet-conformance-audit.md / SR-1.12`
- `dashboard issue ISS-33.6 close-out packet`
- `reintegration candidate for SR-5.15 observability logger handoff`

Bad example:

- `coordination docs are messy`

### Step 2 — Build A Packet Table

Use a collection table like this:

| Packet component | Source | Exact entry used | Notes |
|---|---|---|---|
| Spec authority | `foundation/.../specs/...` | Section or AC | Governing contract |
| Index authority | `architecture-docs/specs/INDEX.md` | Row | Lifecycle and ownership |
| Answered OQ authority | `architecture-docs/global/architect-open-questions.md` | OQ id | Only if resolved and applicable |
| Dashboard authority | `architecture-docs/global/current-dashboard.md` | Issue row | Only when the item is dashboard-tracked |
| Queue authority | `architecture-docs/global/ai-task-queue.md` | Queue item id | Only when queue or dispatch state is in scope |
| Implementation evidence | repo artifacts | file list | Landed output |
| Verification evidence | tests, QA, bugs | artifact list | Required for Implemented, Verified, or Done claims |

### Step 3 — Extract The Claims Before You Compare

Write the claims in plain language before deciding anything. Example:

- `The spec requires a runbook and index registration.`
- `The dashboard says the item is in progress.`
- `The queue still lists the same work as ready.`
- `The repo contains the runbook file but no verification artifact.`

This prevents classification by vibe.

### Step 4 — Apply Precedence

Resolve claim conflicts using the precedence defined by the spec. In practice:

1. Let the governing spec decide requirement meaning.
2. Use a resolved OQ only when it directly addresses the disputed clause.
3. Let dashboard state beat queue state for active execution.
4. Require verification artifacts before accepting Verified or Done claims.
5. Treat implementation artifacts as existence proof, not as permission to rewrite the requirement.

### Step 5 — Classify Each Finding Once

If more than one problem exists, create more than one finding. Do not stack multiple classes into one record.

Practical cues:

- If the repo changed and the spec did not keep up, classify `Spec stale`.
- If the spec is clear and the landed output disagrees, classify `Implementation non-conformant`.
- If the spec requires something absent, classify `Specified but not implemented`.
- If the work exists but the proof is missing, classify `Implemented but not verified`.
- If you still cannot choose a controlling source, classify `Ambiguous authority`.

### Step 6 — Choose The Governance Destination

Use the lightest surface that still preserves authority:

1. Queue item for non-blocking implementation or spec follow-up.
2. Dashboard update when the finding changes active status, blockers, or close-out.
3. Architect question when the packet lacks a controlling interpretation.
4. Index update only when lifecycle or owning-spec metadata is the thing being corrected.

### Step 7 — Deposit A Reusable Output

Make sure the next agent can act without replaying your audit. Include:

1. audited item
2. finding class
3. controlling source
4. exact mismatch
5. required next action

---

## 5 — Templates

### 5.1 — Finding Record Template

```md
Finding ID: AP-001
Audit scope: AT-558 / SR-1.12 authority packet
Finding class: Implemented but not verified
Primary SR: <audited SR or workstream>
Secondary SR links: SR-1.2
Authority sources checked:
- foundation/SR-1.12-autonomous-coordination/specs/authority-packet-conformance-audit.md
- architecture-docs/specs/INDEX.md
- architecture-docs/global/current-dashboard.md
Observed conflict or gap: The spec row claims Implemented, but no verification artifact or bug-closure evidence is linked.
Precedence decision: Verification evidence controls lifecycle advancement; implementation artifacts alone are insufficient.
Required handoff: Add verification task to queue and prevent Verified close-out.
Owner or target surface: architecture-docs/global/ai-task-queue.md
Status: Open
Audit date: 2026-04-11
```

`Primary SR` records the audited subject. SR-1.12 is the governing audit method unless the finding record explicitly states otherwise.

### 5.2 — Queue Handoff Template

```md
- [ ] AT-XXX Authority-packet follow-up — `Implemented but not verified` for <item>
  Control source: <spec or OQ>
  Gap: <missing verification artifact>
  Audit ref: <finding id>
```

### 5.3 — Dashboard Blocker Template

```md
Blocked: authority-packet audit found `Ambiguous authority` between <spec/OQ> and <dashboard/queue state>; see <finding id> and route to architect question before reintegration.
```

### 5.4 — Architect Question Seed Template

```md
OQ: Authority ambiguity for <item>
Conflict:
- <source A claim>
- <source B claim>
Why precedence failed: <missing controlling interpretation>
Decision needed: <exact clause that needs architect answer>
Audit ref: <finding id>
```

---

## 6 — Short Worked Examples

### Example A — Queue Still Says Ready, Dashboard Says In Progress

Outcome:

- Use dashboard state as controlling for active execution.
- Record no ambiguity if the dashboard entry is current.
- Create a queue cleanup handoff only if the stale queue state is likely to misroute new work.

### Example B — Answered OQ Changed Behavior, Spec Still Old

Outcome:

- Use the answered OQ for the specific disputed clause.
- Record `Spec stale`.
- Route a spec-sync task so the repo returns to one normative source.

### Example C — Files Landed, But No Verification Evidence

Outcome:

- Record `Implemented but not verified`.
- Do not allow Verified or Done language in the index row or dashboard close-out.
- Route a verification handoff with the exact missing proof named.

---

## 7 — Common Failure Modes

Watch for these mistakes while running the audit:

1. Treating queue order as stronger than dashboard state.
2. Treating code or doc existence as proof of verification.
3. Letting chat history stand in for a resolved OQ.
4. Combining multiple work items into one packet.
5. Closing a finding without depositing it onto a governed surface.

---

## 8 — Exit Condition

The runbook is complete when:

1. the packet table exists,
2. every mismatch is classified once,
3. each finding has a destination surface, and
4. the next actor can continue without rediscovering the packet.