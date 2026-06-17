# Spec: Agentic Coding Governance

**Date:** 2026-03-27
**Status:** Frozen
**Type:** Governance / Agentic Operations

---

## 1. Design-Goal Linkage

- Primary system requirement: [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md) SR-1.4 (AI toolchain governance — §1 Project Foundations; formerly SR-1.4, SR-1.5, SR-1.6; SR-1.5 and SR-1.6 consolidated into SR-1.4 on 2026-04-29)

This spec defines governance contracts for repository-hosted AI-agent operating documentation and configuration artifacts.

---

## 2. Problem Statement

The project relies heavily on AI agents for implementation, review, debugging, and documentation workflows. Prior ownership audits treated much of the `.github` agent/instruction/skill surface as out-of-scope, which left governance-critical behavior definitions outside explicit specification ownership.

Without a dedicated specification, agent behavior contracts can drift, instruction precedence can become ambiguous, and maintenance accountability for the AI operating surface is weakened.

---

## 3. Scope

In scope:

- Root AI governance docs and synchronization surfaces
- Agent definitions and role routing contracts
- Instruction-pack documents that constrain edits by path or subsystem
- Skill manifests that encode workflow expectations and trigger conditions
- Ownership matrix classification for these governance artifacts in index/audit documents

Out of scope:

- Runtime geometry/source-code behavior contracts
- CI/CD implementation details for agent execution
- Third-party extension-provided skills outside this repository

---

## 4. Contracts

### 4.1 Agentic Governance Ownership Contract

1. In-scope agentic governance artifacts must map to an explicit owning spec in [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md).
2. Governance ownership entries must be maintained in `INDEX.md` and in the live markdown-to-SR association surface `architecture-docs/global/markdown-by-system-requirement.md` in the same workstream.
3. Ownership counts must remain arithmetically consistent after any reclassification.

### 4.2 Root AI Guidance Synchronization Contract

1. `CLAUDE.md` is canonical for shared agent operating guidance.
2. `.github/copilot-instructions.md` must remain substantively synchronized with `CLAUDE.md` for shared sections.
3. Any governance change that affects shared policy must update both files or explicitly document why a change is canonical-only.

### 4.3 Agent Definition Contract

1. `.github/agents/*.agent.md` files must remain governed as a single agent-definition policy surface.
2. Agent definitions must preserve YAML frontmatter validity and routing semantics required by the repository instruction set.
3. Delegation and tool-boundary guidance in agent definitions must remain consistent with instruction-pack constraints.

### 4.4 Instruction and Skill Contract

1. `.github/instructions/*.instructions.md` files must define path-scoped editing rules that remain consistent with active architecture and governance docs.
2. `.github/skills/*/SKILL.md` files must describe reproducible workflows and should not conflict with higher-priority root policy docs.
3. When instruction or skill contracts change, ownership matrices and this spec's implementation artifact list must be reviewed for staleness.

---

## 5. Acceptance Criteria

This spec is considered Verified only when all criteria below are met:

- AC-1: [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md) contains an ISS-33.6 row for this spec with lifecycle state and owning files populated.
- AC-2: Ownership summaries in [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md) and `architecture-docs/global/markdown-by-system-requirement.md` include agentic governance assets with matching system-requirement routing.
- AC-3: `CLAUDE.md` and `.github/copilot-instructions.md` are categorized under this spec in both ownership matrices.
- AC-4: `.github/agents/*.agent.md`, `.github/instructions/*.instructions.md`, and `.github/skills/*/SKILL.md` are categorized under this spec in both ownership matrices.
- AC-5: The conservative uncategorized policy remains unchanged for non-agentic docs that still lack confident owner mapping.

---

## 6. Non-Goals

1. Defining behavior contracts for geometry algorithms or rendering pipelines.
2. Reclassifying all remaining uncategorized documentation in one wave.
3. Governing external marketplace/editor-extension agent assets stored outside this repository.
4. Replacing subsystem-specific specs with generic governance prose.

---

## 7. Initial Implementation Artifacts

- [CLAUDE.md](../../../CLAUDE.md)
- [.github/copilot-instructions.md](../../../.github/copilot-instructions.md)
- `.github/agents/*.agent.md`
- `.github/instructions/*.instructions.md`
- `.github/skills/*/SKILL.md`
- [architecture-docs/specs/INDEX.md](../../../architecture-docs/specs/INDEX.md)
- `architecture-docs/global/markdown-by-system-requirement.md`

These artifacts establish the initial governance ownership baseline for the repository's agentic coding operating surface.
