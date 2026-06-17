# Draft-Spec Maturation Triage

Date: 2026-04-11  
Scope: classification only; no downstream freeze, implementation, or architect-decision packet work is performed here.

## Inventory Reconciliation

- `architecture-docs/specs/INDEX.md` currently contains 17 `Draft` rows.
- Two Draft specs are already adequately covered by active existing lanes and are excluded from the AT-590 maturation set:

| Spec | Why excluded from the AT-590 maturation set | Existing lane coverage |
|---|---|---|
| `profile-editor-gui.md` | Still intentionally Draft because the phased ISS-5.2K implementation lane is active; this is not a generic spec-maturation problem | ISS-5.2K umbrella, AT-557, AT-573 through AT-576 |
| `gltf-export.md` | Still intentionally Draft because the payload contract is implemented but the owning export issue is still in evidence closeout | AT-518, AT-519, ISS-5.3B |

- Remaining AT-590 triage set: 15 Draft specs.

## Classification

| Spec | Classification | Basis | Follow-on posture |
|---|---|---|---|
| `analytical-ray-tracing-research-framework.md` | Freeze-ready now | AT-524 is complete, OQ-73 through OQ-75 are answered, and the spec now reads as a stable research baseline rather than an open-ended placeholder | Later freeze task needed; not currently covered by AT-591 through AT-598 |
| `autonomous-execution-coordination.md` | Freeze-ready now | The coordination contract is already being used as live SR-1.12 authority; follow-on SR-1.12 docs elaborate under it rather than leaving the core contract unsettled | Later freeze task needed; not currently covered by AT-591 through AT-598 |
| `authority-packet-conformance-audit.md` | Freeze-ready now | AT-558 explicitly verified that the spec and runbook already satisfy the queued method contract with no further authoring required | Later freeze task needed; not currently covered by AT-591 through AT-598 |
| `profile-contract.md` | Freeze-ready now | The TypeScript profile runtime and validator surfaces are already live from AT-323 and subsequent SR-5.6 work; remaining editor follow-ons can be deferred explicitly instead of keeping the contract broadly Draft | Covered by AT-595 |
| `rca-evidence-pack-contract.md` | Freeze-ready now | `ForensicBundle` v2, `EvidenceCollector`, and the RCA handoff surfaces already exist; the remaining work is bounded reconciliation, not further invention | Covered by AT-594 |
| `shell-layout-acceptance-and-evidence.md` | Implementation-ready after existing queued work | The shell acceptance contract depends on the already-queued shell packet and related architect answers rather than on new spec invention | Covered by AT-591 after AT-584 and AT-585 |
| `resolution-auto-computation.md` | Implementation-ready after existing queued work | AT-539 plus OQ-77, OQ-79, OQ-85, OQ-86, and OQ-87 already fixed the architecture choices; the next step is implementation | Covered by AT-592 |
| `unified-observability.md` | Implementation-ready after existing queued work | AT-538 fixed the observability authority direction and ISS-5.15B now holds the bounded behavior-closeout work that must land before freeze | Covered by AT-593 after AT-585 |
| `repository-contributor-permissions-and-change-authorization.md` | Implementation-ready after existing queued work | The spec should freeze only after the already-queued SR-1.13 hardening packet, authority-tier audit, and horizon reconciliation land | Covered by AT-597 after AT-579 through AT-581 |
| `v2-control-node-inspector-panel.md` | Architect-decision-gated planning/spec work | OQ-95 is still required to decide whether v2 remains maintained or is superseded by the v3 inspector plus Layer 1 direction | Covered by AT-596 and OQ-95 |
| `browser-access-and-mobile-feasibility-planning.md` | Architect-decision-gated planning/spec work | OQ-96 is still required to decide whether this freezes now as a planning-only boundary or stays Draft pending a browser/mobile promotion decision | Covered by AT-598 and OQ-96 |
| `user-accounts-and-payments.md` | Architect-decision-gated planning/spec work | OQ-97 is still required before treating the commercialization spec as a frozen internal baseline instead of an exploratory Draft | Covered by AT-598 and OQ-97 |
| `brand-language-and-visual-identity.md` | Architect-decision-gated planning/spec work | OQ-97 is still required before treating the brand-strategy spec family as frozen internal baseline material | Covered by AT-598 and OQ-97 |
| `branding-art-assets.md` | Architect-decision-gated planning/spec work | OQ-97 is still required before treating the brand-strategy spec family as frozen internal baseline material | Covered by AT-598 and OQ-97 |
| `marketing-strategy.md` | Architect-decision-gated planning/spec work | OQ-97 is still required before treating the brand-strategy spec family as frozen internal baseline material | Covered by AT-598 and OQ-97 |

## Resulting Queue Reconciliation

- The queue's "live 15 Draft specs" phrasing is only correct after explicitly excluding `profile-editor-gui.md` and `gltf-export.md` from the generic maturation packet.
- Lane 42 already covers 10 of the 15 triaged specs through AT-591 through AT-598.
- Three freeze-ready-now Drafts are outside the current Lane 42 downstream packet and will need later freeze follow-on work if the repo wants the triage to fully drain Draft lifecycle debt:
  - `analytical-ray-tracing-research-framework.md`
  - `autonomous-execution-coordination.md`
  - `authority-packet-conformance-audit.md`
- No new architect open-question entry is required for AT-590. The current decision-gated set is fully explained by OQ-95, OQ-96, and OQ-97.