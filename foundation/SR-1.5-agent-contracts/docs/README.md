# SR-1.5 — Agent Definition and Delegation Contracts

## Purpose

The project shall maintain a team of specialist agent definitions (`.github/agents/*.agent.md`) with YAML frontmatter that defines description trigger keywords, tool access boundaries, and delegation authority. The orchestrator-workers pattern (teamlead → specialists) is the primary coordination architecture.

## Specs

- [agentic-coding-governance.md](../../SR-1.4-ai-guidance/specs/agentic-coding-governance.md) — Governance of agent definitions, instruction packs, skill manifests, and root AI guidance synchronization (Lifecycle: Frozen)

## Related SRs

- SR-1.4 — Root AI guidance synchronization (shared ownership of `agentic-coding-governance.md`)
- SR-1.6 — Instruction and skill governance (shared ownership of `agentic-coding-governance.md`; skills/instructions that agents invoke)
