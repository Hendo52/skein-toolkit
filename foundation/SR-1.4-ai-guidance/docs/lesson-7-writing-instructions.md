# Lesson 7: Writing Effective Project Instructions

## The Big Idea

The single most impactful thing you can do for AI agent effectiveness is write good instructions. Every AI agent reads your project's instruction files before doing anything. Bad instructions -> bad results, regardless of how clever your prompts are.

Your project has a three-layer instruction system:

| Layer | File | Scope | Who reads it |
|-------|------|-------|-------------|
| **Global** | `CLAUDE.md` | Entire project | All agents (Claude Code, Copilot, etc.) |
| **Copilot-specific** | `.github/copilot-instructions.md` | Copilot agent mode | Copilot agents only |
| **Per-agent** | `.github/agents/*.agent.md` | One specific agent | Only that agent |

**CLAUDE.md** is the ground truth. It's the canonical source for conventions, architecture, data contracts, and pitfalls.

## What Makes Good Instructions

### 1. Concrete, Not Abstract

Bad:
> "Follow good naming conventions."

Good (from your CLAUDE.md):
> "Functions: `_subsystem_verb_noun` (private) or `verb_noun` (public). Stage functions embed the stage number: `_assembly_stage3_payload_build`."

The agent doesn't need to *infer* what good naming means. You told it exactly.

### 2. Prohibitions Are as Important as Prescriptions

Your project is full of "don't do this" rules that save agents from common mistakes:

From CLAUDE.md:
> - "No trailing commas in `.scad` files — OpenSCAD's parser will reject them."
> - "No raw `echo()` outside `debug_pipeline/1_core.scad`."
> - "Never mix global and per-spline settings for the same parameter family."

Without these prohibitions, agents will innocently introduce bugs that are hard to diagnose (OpenSCAD fails silently!).

### 3. Data Contracts, Spelled Out

The most valuable section in your CLAUDE.md is the **Pipeline Data Contracts**:

```
payload[i] = [seg_idx, t, twist, outer_width, recession, gap, osc]
```

```
len(pts) == len(tangents) == len(payload)  // must always hold
```

This is the kind of detail that an AI agent *cannot* infer from reading code alone. It needs to be told: "this array has exactly this shape, and if you break it, geometry silently fails." Without this, an agent editing Stage 3 might reorder the payload tuple and everything would appear to work until Stage 7 produces garbage.

### 4. "Required Reading" Tables

Your CLAUDE.md has a brilliant pattern — a routing table that tells agents what to read *before* editing specific files:

| If editing... | Read first | Why |
|---|---|---|
| Pipeline assembly (`stages/`) | `stages/runtime-contract-snapshot.md` | Data contract shapes |
| Debug output or assertions | `ASSERT_ECHO_GOLD_STANDARD.md` | Centralized echo/assert policy |
| Joint/frame behavior | `design-goals.md` §3 | Approaches already tried |

This prevents agents from re-inventing solutions that have already been tried and confirmed insufficient.

### 5. Known Limitations: "Don't Re-Invent the Wheel"

The "Known Architectural Limitations" section in CLAUDE.md lists six approaches that were tried for the mohawk joint collision problem and found insufficient. This is *critical* context — without it, every new agent session might waste time suggesting bilateral slerp joint frame insertion (already tried, doesn't narrow profiles).

## The CLAUDE.md vs copilot-instructions.md Relationship

Your project keeps these ~90% in sync. CLAUDE.md is the canonical source; copilot-instructions.md is a subset tailored for Copilot's context window. The docs agent has explicit instructions to keep them synchronized.

**Key lesson:** If you maintain multiple instruction files, you need a synchronization policy and an agent responsible for enforcing it.

## Anatomy of CLAUDE.md Sections

Here's the structure that works:

1. **Project Identity** — what this is, languages, license
2. **Language-Specific Conventions** — style rules with concrete examples
3. **Architecture** — key classes, entry points, data flow
4. **Data Contracts** — exact shapes that cross boundaries
5. **Workflow Commands** — how to build, test, render
6. **Known Limitations** — what's been tried and failed
7. **Troubleshooting Triage** — symptom -> stage -> probe routing
8. **Required Reading Tables** — what to read before editing what
9. **Pitfalls** — common mistakes and how to avoid them
10. **Naming Enforcement** — the naming policy and how to handle violations

## Challenge

Pick one section of your CLAUDE.md and evaluate it against the five criteria above. Is it concrete? Does it include prohibitions? Are data contracts spelled out? Is there a "read before editing" route for the files it covers?
