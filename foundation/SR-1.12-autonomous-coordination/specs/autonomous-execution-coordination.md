# Spec: Autonomous Execution Coordination

**Date:** 2026-04-11
**Status:** Frozen
**Type:** Governance / Coordination Operations

---

## 1. Design-Goal Linkage

- Primary system requirement: [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md) SR-1.12 (Autonomous execution governance and coordination tooling)
- Adjacent governance references: SR-1.2, SR-1.5, SR-1.6, and SR-1.9 in [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md)

This spec defines the operating contract for how autonomous work is coordinated across shared planning surfaces, isolated execution lanes, and serial reintegration gates during the next 30 days of repo operation.

---

## 2. Problem Statement

The repository already has multiple live coordination surfaces for assigning work, tracking blockers, and escalating decisions, but those surfaces do not yet have a single governing contract that explains which ones are operationally authoritative, how active work should be isolated, or what conditions must be satisfied before concurrent work is reintegrated.

Without a dedicated coordination spec, the repo remains vulnerable to predictable multi-agent failure modes: conflicting edits to shared planning files, ambiguous source of truth for active work, unbounded queue accumulation, stale blocker state, and lane reintegration that happens before evidence or workspace hygiene is checked.

---

## 3. Scope

In scope:

- Coordination-surface temperature model for hot, warm, and cold operational docs
- Active-vs-archive boundary for queue, dashboard, and architect-question surfaces
- Agent lane isolation contract using a linked-worktree policy model or an equivalent isolation mechanism with the same invariants
- Reintegration gate contract for merging lane output back into the primary branch
- Coordination health signals that can be automated later without changing this contract

Out of scope:

- Specification lifecycle ownership, test-to-spec mapping, and defect classification mechanics
- Agent definition YAML, tool permissions, and delegation trigger wording
- Instruction-pack or skill-manifest content rules
- Generic repository retention taxonomy outside coordination-authority surfaces
- Shell scripts, git hooks, worktree provisioning commands, or CI implementation

---

## 4. Coordination Model

### 4.1 Coordination Surface Temperature Model

All coordination surfaces that can influence active execution must be classified as exactly one of the following:

1. **Hot surface:** authoritative for immediate execution decisions. A hot surface may create, re-order, block, unblock, or close active work.
2. **Warm surface:** recent context that informs execution decisions but is not independently authoritative for claiming new work.
3. **Cold surface:** historical or archival context with zero authority over current execution until explicitly promoted back to a hot or warm surface.

Initial surface classification for the next 30 days:

| Surface | Temperature | Operational authority |
|---|---|---|
| [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md) | Hot | Current active issues, blockers, and close-out state |
| [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md) active and ready sections | Hot | Work intake and promotion candidate list |
| [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md) unresolved questions | Hot | Decision blockers awaiting architect input |
| [architecture-docs/global/tik-tok-queue-system.md](../../../architecture-docs/global/tik-tok-queue-system.md) active operating guidance | Warm | Batch-shaping and dispatch context |
| Recently closed dashboard items, recently resolved architect questions, and recently completed queue items retained in place | Warm | Near-term execution context and handoff reference |
| Historical queue history, superseded operating notes, and resolved questions beyond the recent-context window | Cold | Archive only |

Only hot surfaces may authorize new active work claims or change the authoritative blocker state of an in-flight item.

### 4.1.1 Practice-Uplift Priority Arbitration

The SR-tier overlay is intentionally softened by a bounded practice-uplift rule.

Contracts:

1. **Architect override remains strongest:** an explicit architect priority override outranks the default SR-tier overlay and any local arbitration heuristic.
2. **Blocker-first remains primary inside the overlay:** direct blocker-removal work for a top-tier SR outranks non-blocking uplift work for that same SR unless an architect override states otherwise.
3. **Practice-uplift eligibility:** validation improvements, test-reliability work, dev-tooling, observability, state or data-model hardening, and refactors that materially reduce delivery risk may float upward when they directly improve the delivery loop of a currently top-tier SR.
4. **Materiality test:** a practice-uplift task is eligible only when its effect is concrete and near-term, such as improving confidence, shortening feedback time, increasing unblock velocity, or making execution of top-tier SR work safer.
5. **Bounded rule:** practice-uplift work does not become high priority merely by being generally good engineering hygiene. The claiming surface must be able to name the top-tier SR helped and the concrete delivery-loop improvement expected.

### 4.2 Active-vs-Archive Retention Boundary

The queue, dashboard, and architect-question surfaces must maintain a visible boundary between operationally active content and archival content.

Contracts:

1. **Active section contract:** active, ready, blocked, and awaiting-decision entries remain on hot surfaces until the associated work is either completed, explicitly deferred, or superseded.
2. **Warm retention contract:** recently closed or recently resolved entries remain visible on the live surface only for the recent-context window defined in Section 4.5.
3. **Archive contract:** entries older than the recent-context window, with no active execution authority, must be moved to or treated as archive/history content. Archived entries retain reference value but cannot act as current assignment authority.
4. **No silent authority leakage:** if an archived note still needs to affect current work, that note must be re-stated or linked from a hot surface rather than relied on implicitly.

This contract is intentionally narrower than repository-wide retention policy. It governs operational authority boundaries on coordination surfaces only.

### 4.3 Agent Lane Isolation Contract

Concurrent execution must occur in isolated lanes.

Policy model:

1. Each active lane owns one primary work item at a time.
2. Each active lane operates in a linked-worktree model, or an equivalent isolation mechanism that provides the same guarantees:
   - independent dirty-tree detection
   - independent branch or branch-equivalent state
   - clear mapping from lane to work item
   - no hidden cross-lane filesystem coupling beyond explicitly shared coordination docs
3. A lane must declare the coordination item it is executing and the files or document surfaces it expects to touch.
4. A lane must not directly edit files actively claimed by another lane, except for shared hot coordination surfaces edited during a serialized reintegration step.
5. Shared hot surfaces are coordinator-owned during reintegration even when the implementation work occurred elsewhere.

This spec does not require a specific shell script, task runner, or git wrapper. It requires the isolation invariants above.

### 4.4 Reintegration Gate Contract

Lane output may be reintegrated only through a serialized gate.

Gate requirements:

1. **Clean lane:** the lane contains only intentional changes for its claimed work item, with no unresolved conflicts and no unrelated modified or untracked files relied upon for successful handoff.
2. **Evidence attached:** the reintegration request includes the governing SR/spec reference, a concise validation summary, and any required artifacts or doc links needed to justify the change.
3. **Shared-surface refresh:** any impacted hot coordination surfaces are refreshed in the same reintegration workstream so status, blockers, and ownership remain synchronized.
4. **Serial integration:** only one lane at a time may update shared hot coordination surfaces and land to the primary branch. Other lanes must rebase or refresh against the new head before their own reintegration.
5. **No silent merge of unhealthy work:** a lane that fails a coordination health signal in Section 4.5 must be corrected or explicitly escalated before reintegration.

### 4.5 Coordination Health Signals

The following signals define minimum coordination health. They may be checked manually now and automated later without changing this spec.

1. **Dirty-tree signal:** unhealthy when an active lane contains unrelated edits, unresolved conflicts, or ambiguous untracked files beyond the lane's declared scope.
2. **Stale-surface signal:** unhealthy when a hot surface fails to reflect a claim, blocker, unblock, defer, or completion event by the end of the same workstream, or when an item remains marked active without a meaningful update for 7 calendar days.
3. **Recent-context window signal:** warm retention on live coordination surfaces is limited to the shorter operational slice needed for safe handoff review. For the next 30 days, the default window is the last 14 calendar days or the most recent 10 closed or resolved entries on a surface, whichever preserves more context.
4. **Lane-to-item mapping signal:** unhealthy when a lane cannot be traced back to one active coordination item and one governing spec or issue reference.
5. **Reintegration backlog signal:** unhealthy when completed lanes accumulate without serial landing and shared-surface refresh, because that increases conflict probability on hot surfaces.

### 4.6 Scope Boundaries Against Adjacent Foundation SRs

This SR is intentionally narrow.

1. **Boundary with SR-1.2 (requirements traceability and lifecycle):** SR-1.2 owns spec lifecycle states, test pairing, and defect ownership. SR-1.12 owns how active work is coordinated and reintegrated before and during implementation, not how resulting artifacts are lifecycle-tracked.
2. **Boundary with SR-1.5 (agent definition and delegation contracts):** SR-1.5 owns who agents are, how they route, and which tools they can access. SR-1.12 owns how concurrently running lanes are isolated and reintegrated once work has been delegated.
3. **Boundary with SR-1.6 (instruction and skill governance):** SR-1.6 owns the content and maintenance of instruction packs, skills, and memory guidance. SR-1.12 owns the operational health signals and coordination-surface contracts those workflows must respect.
4. **Boundary with SR-1.9 (file governance and retention):** SR-1.9 owns repository-wide taxonomy, placement, and retention policy. SR-1.12 owns only the active-versus-archive authority boundary for queue, dashboard, and architect-question surfaces.

---

## 5. Acceptance Criteria

This spec is considered Verified only when all criteria below are met:

- AC-1: [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md) defines SR-1.12 as a distinct foundation requirement with scope boundaries against SR-1.2, SR-1.5, SR-1.6, and SR-1.9.
- AC-2: [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md) contains a row for this spec under SR-1.12 with lifecycle state and owning coordination surfaces populated.
- AC-3: The coordination model defines hot, warm, and cold surfaces and states that only hot surfaces can authorize active work claims or blocker-state changes.
- AC-4: The coordination model defines a bounded practice-uplift rule stating that validation, dev-tooling, observability, hardening, and similar quality work may rise when it materially improves the delivery loop of a top-tier SR, while preserving architect override and blocker-first behavior.
- AC-5: The spec defines an active-versus-archive boundary for [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md), [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md), and [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md).
- AC-6: The lane isolation contract requires one primary work item per lane, linked-worktree-equivalent isolation invariants, and a prohibition on cross-lane edits outside serialized shared-surface updates.
- AC-7: The reintegration gate contract requires a clean lane, attached evidence, and serial integration for shared hot surfaces.
- AC-8: The coordination health section defines at least dirty-tree, stale-surface, and recent-context-window signals with concrete default thresholds suitable for the next 30 days.

---

## 6. Non-Goals

1. Implementing linked-worktree provisioning scripts, queue bots, or automatic stale-entry movers.
2. Replacing the dashboard, queue, or architect-open-question documents with a new platform.
3. Governing generic documentation style, naming, or lifecycle metadata outside coordination behavior.
4. Defining agent-specific prompt wording or team topology.

---

## 7. Initial Implementation Artifacts

- [architecture-docs/global/current-dashboard.md](../../../architecture-docs/global/current-dashboard.md)
- [architecture-docs/global/ai-task-queue.md](../../../architecture-docs/global/ai-task-queue.md)
- [architecture-docs/global/tik-tok-queue-system.md](../../../architecture-docs/global/tik-tok-queue-system.md)
- [architecture-docs/global/architect-open-questions.md](../../../architecture-docs/global/architect-open-questions.md)
- [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md)
- [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md)

These artifacts define the current coordination authority surfaces. Future tooling may automate parts of this model, but any automation must preserve the contracts in Sections 4.1 through 4.5.
