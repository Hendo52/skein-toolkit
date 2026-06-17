# Authority-Packet Conformance Audit — SR-1.12

| Field | Value |
|-------|-------|
| **Lifecycle** | Frozen |
| **System Req (primary)** | SR-1.12 |
| **System Req (secondary)** | SR-1.2 |
| **Issue** | AT-558 |
| **Owning files** | `architecture-docs/specs/INDEX.md`, `architecture-docs/global/current-dashboard.md`, `architecture-docs/global/ai-task-queue.md`, `architecture-docs/global/architect-open-questions.md`, `foundation/SR-1.12-autonomous-coordination/docs/authority-packet-conformance-audit-runbook.md` |

---

## 1 — Purpose

The repository needs a repeatable way to decide whether the live coordination surfaces, landed artifacts, and recorded evidence for a work item still conform to the authority model already established by SR-1.12 and the traceability model owned by SR-1.2.

This spec defines the authority-packet conformance audit method. The method is used when an agent, reviewer, or coordinator needs to answer one question precisely: does the current repo state for a scoped work item match the governing requirements, current coordination state, and evidence model, or is there a governance mismatch that must be handed off?

The method is governance-specific and repo-specific. It is not a generic document review process.

---

## 2 — Design-Goal Linkage

- **Primary owner:** SR-1.12 in [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md)
- **Secondary linkage:** SR-1.2 in [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md)

SR-1.12 owns coordination authority, lane isolation, reintegration discipline, and hot-surface operating rules. SR-1.2 owns lifecycle, traceability, test ownership, and defect ownership. This audit method lives under SR-1.12 because it evaluates whether the active coordination packet is coherent, but it explicitly depends on SR-1.2 because lifecycle and verification claims inside the packet must be judged against the traceability model rather than against coordination heuristics.

---

## 3 — Audit Scope

An authority-packet conformance audit is scoped to exactly one of the following:

1. One specification and its currently active implementation or verification workstream.
2. One dashboard issue or AT/ISS work item being coordinated across repo surfaces.
3. One reintegration candidate whose coordination state, implementation evidence, and verification evidence must be checked before close-out.

The audit answers whether the scoped work item presents one coherent authority packet.

### 3.1 — Authority Packet Definition

The **authority packet** is the minimum scoped set of repo artifacts that together establish what the work item means, what state it is in, what has been implemented, and what has been verified.

Every audit packet must contain the required components below, plus any conditional components that exist and are relevant to the audited claim.

Required packet components:

1. **Spec authority:** the governing spec text and owning SR entry in [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md).
2. **Dashboard authority:** the active or recently closed state recorded in [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md) when the audited item is tracked on the dashboard.
3. **Implementation evidence:** the concrete landed artifacts that claim to satisfy the work item, such as owned docs, source changes, bug updates, or other repo artifacts explicitly linked by the governing spec or dashboard issue.
4. **Verification evidence:** the tests, QA artifacts, audit reports, render evidence, lifecycle updates, and bug status needed to justify any claim that the work is implemented, verified, or done.

Conditional packet components:

1. **Answered OQ authority:** any resolved entry in [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md) that explicitly clarifies, narrows, or overrides the disputed interpretation for the audited item.
2. **Queue authority:** the intake, promotion, or backlog state recorded in [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md), and the active dispatch context in [architecture-docs/global/tik-tok-queue-system.md](../../../architecture-docs/global/tik-tok-queue-system.md) when those artifacts exist and were used to shape execution for the audited item.

Absence of a non-applicable conditional component does not by itself make the packet ambiguous. Ambiguous authority arises only when the available packet does not support a deterministic precedence decision, including unresolved conflicts between available sources or missing required authority for the scoped claim.

### 3.2 — Packet Assembly Rules

Contracts:

- **PRE:** The packet must be frozen to a named work item before the audit begins. Do not mix multiple issues, specs, or reintegration candidates into one packet.
- **PRE:** Each packet source must be cited by exact file and local section, row, or entry label.
- **INV:** The packet may describe current state only from repo surfaces that exist in the workspace.
- **INV:** Unrecorded memory, chat context, or verbal recollection is not authority unless it has been deposited into a governed repo surface.

---

## 4 — Authority Precedence Model

The audit must resolve contradictions by precedence, not by intuition.

### 4.1 — Precedence Order

Apply the following order when two packet components disagree:

1. **Spec text** governs required behavior, ownership, acceptance criteria, and lifecycle intent.
2. **Answered OQs** govern only where an included answered OQ explicitly resolves an ambiguity or directs a change not yet propagated into the spec. An answered OQ outranks the older spec text only for the exact question it resolves and creates a follow-up obligation to sync the spec.
3. **Dashboard state** governs active execution status, blocker state, close-out state, and whether the item is currently in flight when the audited item is dashboard-tracked.
4. **Queue state** governs intake, promotion readiness, and backlog placement only when queue artifacts are in scope, and only until the item is promoted into active dashboard execution.
5. **Verification evidence** governs whether claims of implemented, verified, or done are actually justified under SR-1.2 lifecycle rules.
6. **Implementation evidence** governs only the claim that work artifacts currently exist. It never overrides higher-authority requirement, decision, state, or verification sources.

### 4.2 — Precedence Interpretation Rules

The order above is applied by claim type:

| Claim under dispute | Controlling authority |
|---|---|
| What behavior is required? | Spec text, unless a linked answered OQ explicitly supersedes that clause |
| What is the current active state? | Dashboard state |
| Is the item merely queued or actually active? | Dashboard state over queue state |
| Has the work been implemented? | Implementation evidence, constrained by spec text |
| Can the item be called verified or done? | Verification evidence, constrained by spec text and SR-1.2 lifecycle rules |

### 4.3 — Non-Authority Sources

The following do not resolve contradictions on their own:

- commit recency by itself
- branch naming by itself
- unstated agent intent
- chat-only explanations that are not written into governed surfaces

If those are the only support for a claim, the packet is insufficient.

---

## 5 — Finding Classes

Every audit finding must be classified as exactly one of the following:

### 5.1 — Spec stale

The governing spec no longer reflects the currently answered architect decision, current coordination contract, or required repo behavior. Typical trigger: an answered OQ or repeated operational pattern has become controlling, but the spec still says something older or incomplete.

### 5.2 — Implementation non-conformant

The spec and authority packet are coherent, but the landed implementation artifacts or governance surfaces do not match that contract. Typical trigger: dashboard or runbook behavior claims something the governing spec does not permit.

### 5.3 — Specified but not implemented

The governing spec requires a capability, document, workflow output, or coordination behavior that has not yet been deposited into the repo. Typical trigger: the spec exists, the queue or dashboard says the work matters, but the claimed implementation artifact is absent.

### 5.4 — Implemented but not verified

Implementation artifacts exist, but the packet lacks the verification evidence required to justify the lifecycle or close-out claim. Typical trigger: a spec row or dashboard note implies done, while tests, QA, or defect closure evidence are missing.

### 5.5 — Ambiguous authority

The packet does not permit a deterministic precedence decision. Typical trigger: conflicting unresolved surfaces, a disputed claim that has never been resolved in spec text or an answered OQ, or missing required authority for the scoped claim.

---

## 6 — Minimum Finding Record

Each finding must be recorded with at least the following fields:

| Field | Required content |
|---|---|
| `finding_id` | Stable audit-local identifier |
| `audit_scope` | The exact spec, issue, or reintegration candidate audited |
| `finding_class` | One of the five classes in Section 5 |
| `primary_sr` | The audited SR or workstream that owns the subject of the finding |
| `secondary_sr_links` | Any linked SRs, explicitly including SR-1.2 when lifecycle or verification claims are involved |
| `authority_sources_checked` | Exact repo files and entries consulted |
| `observed_conflict_or_gap` | Plain-language description of the mismatch |
| `precedence_decision` | Which source controlled the decision and why |
| `required_handoff` | Queue, dashboard, architect-question, spec update, bug report, or verification follow-up |
| `owner_or_target_surface` | The surface or artifact that must receive the handoff |
| `status` | Open, queued, blocked, or resolved |
| `audit_date` | Date the finding was recorded |

SR-1.12 remains the governing method for this audit, but the `primary_sr` field records the audited subject rather than the method owner.

Optional fields such as severity, proposed fix, or linked commit may be added, but the fields above are the irreducible minimum.

---

## 7 — Governance Outputs And Handoff Rules

An audit is incomplete until each finding has a governance destination.

### 7.1 — Output Routing

| Finding class | Required governance output |
|---|---|
| Spec stale | Create or update a queue item for spec sync, or promote directly to dashboard if it blocks active work |
| Implementation non-conformant | Create an implementation or defect handoff tied to the governing spec |
| Specified but not implemented | Create or refresh a queue item with the governing spec and missing artifact named explicitly |
| Implemented but not verified | Create a verification handoff and prevent any Verified or Done claim until evidence exists |
| Ambiguous authority | Open or refresh an architect question, or mark the dashboard item Blocked when active work cannot proceed safely |

### 7.2 — Handoff Contracts

Contracts:

- **INV:** A finding must never be closed by editing only a lower-authority surface.
- **INV:** Queue or dashboard handoff text must include the finding class, audited item, controlling authority source, and the exact missing or conflicting artifact.
- **INV:** A lifecycle claim in [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md) must not be advanced on the strength of implementation evidence alone.
- **INV:** If the audit discovers a requirement conflict that needs architect resolution, the output must land in [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md) before any dashboard close-out.
- **POST:** The receiving governance surface must carry enough detail that another agent can act without reconstructing the audit from scratch.

### 7.3 — Close-Out Rule

The audit itself may be marked complete when all findings are either:

1. deposited onto the correct governance surface with a stable identifier, or
2. resolved immediately by synchronizing the higher-authority surface in the same workstream.

---

## 8 — Boundaries Against Adjacent SRs

### 8.1 — Boundary with SR-1.2

SR-1.2 owns traceability, lifecycle states, test ownership, and defect ownership. This spec does not redefine those rules. It only defines how an SR-1.12 audit collects the packet and decides whether current coordination claims conform to the SR-1.2 model already in force.

### 8.2 — Boundary with SR-1.5

SR-1.5 owns agent identity, delegation contracts, trigger wording, and tool boundaries. This spec does not define who performs the audit or which agent is allowed to do it. It defines only the audit method and output routing once an audit is performed.

### 8.3 — Boundary with SR-1.6

SR-1.6 owns instruction packs, skills, memory procedures, and related operator guidance. This spec may reference those materials as packet evidence, but it does not govern how those instructions are written or maintained.

### 8.4 — Boundary with SR-1.9

SR-1.9 owns repository-wide file placement, retention, and archive policy. This spec does not redefine where files belong. It only governs which existing coordination and evidence surfaces are authoritative during an authority-packet audit.

---

## 9 — Acceptance Criteria

This spec is satisfied only when all of the following are true:

- AC-1: The spec defines the minimum authority packet contents using repo surfaces that already exist in this workspace.
- AC-2: The spec defines explicit precedence between spec text, answered OQs, dashboard state, queue state, implementation evidence, and verification evidence.
- AC-3: The spec defines exactly five finding classes: Spec stale, Implementation non-conformant, Specified but not implemented, Implemented but not verified, and Ambiguous authority.
- AC-4: The spec defines a minimum finding record with required fields sufficient for queue, dashboard, architect-question, or verification handoff.
- AC-5: The spec defines governance output routing and prohibits lifecycle advancement based only on implementation evidence.
- AC-6: The spec states explicit boundaries against SR-1.2, SR-1.5, SR-1.6, and SR-1.9.

---

## 10 — Initial Implementation Artifacts

- [foundation/SR-1.12-autonomous-coordination/specs/autonomous-execution-coordination.md](autonomous-execution-coordination.md)
- [foundation/SR-1.12-autonomous-coordination/docs/authority-packet-conformance-audit-runbook.md](../docs/authority-packet-conformance-audit-runbook.md)
- [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md)
- [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md)
- [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md)
- [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md)
- [architecture-docs/global/tik-tok-queue-system.md](../../../architecture-docs/global/tik-tok-queue-system.md)

These artifacts are sufficient to run the audit method manually. Future automation may assemble or diff packets automatically, but any automation must preserve the packet contents, precedence model, finding classes, and governance-output rules defined here.
