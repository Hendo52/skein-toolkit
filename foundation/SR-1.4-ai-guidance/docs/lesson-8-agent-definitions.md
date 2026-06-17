# Lesson 8: Crafting Agent Definitions

## The Big Idea

Each `.agent.md` file in `.github/agents/` defines a specialist. The file has three parts:

1. **YAML frontmatter** — metadata that the system uses for routing
2. **Role description** — what the agent does and how it approaches problems
3. **Constraints** — what it must NOT do

## The Frontmatter: How Agents Get Routed

From `openscad.agent.md`:

```yaml
---
description: "Use when editing or debugging OpenSCAD .scad files, the Long Bezier pipeline, sweep geometry, profiles, or running headless OpenSCAD renders"
tools: [read, search, edit, execute]
---
```

Three critical fields:

### `description`
This is the **routing trigger**. When the teamlead decides which agent to use, it matches the task against each agent's description. The description must contain the keywords that tasks will naturally use.

Compare two descriptions:
- **Vague:** "Use for OpenSCAD work" — misses when someone says "edit the sweep geometry" or "debug the pipeline"
- **Specific:** "Use when editing or debugging OpenSCAD .scad files, the Long Bezier pipeline, sweep geometry, profiles, or running headless OpenSCAD renders" — catches all those variants

### `tools`
Controls what the agent can *do*. This is a security boundary:

| Tool set | Capability | Example agents |
|----------|-----------|----------------|
| `[read, search]` | Read-only exploration | — |
| `[read, search, web]` | Read-only + internet research | teacher, priorwork |
| `[read, search, edit]` | Can modify files | docs, hr, spec, rnd |
| `[read, search, edit, execute]` | Full power: edit + run commands | openscad, typescript, meshqa, rca, tdd |
| `[read, search, edit, execute, agent, todo]` | Orchestrator: can delegate + track work | teamlead |

The teacher agent has `[read, search, web]` — it can read the codebase and search the internet for explanations, but it **cannot edit files or run commands**. This prevents it from accidentally modifying code while explaining something.

### `agents`
Only relevant for agents that delegate to others:
- **teamlead** has an agents list covering all specialists
- **rnd** can delegate to priorwork for deeper research

Most agents have no `agents:` field — they're leaf nodes in the delegation tree.

## The Body: Shaping Agent Behavior

A good agent body has four sections:

### 1. Role Statement
One paragraph that captures the essence. From the rca agent:

> "You systematically diagnose bugs through measurement and evidence, never through guessing."

This shapes how the agent approaches problems. The "never through guessing" part means the RCA agent will always instrument code and measure before forming hypotheses.

### 2. Key Context
The minimal domain knowledge the agent needs. From the openscad agent:

> - "The Long Bezier pipeline lives in `engine/pipeline/`"
> - "All angles are in degrees, vectors are `[x, y, z]`"
> - "No trailing commas in `.scad` — the parser rejects them"

This is the 20% of CLAUDE.md that this specific agent needs 80% of the time.

### 3. Process/Workflow
Concrete steps the agent follows. From the rca agent:

```
Step 1: Reproduce and Measure
Step 2: Hypothesize
Step 3: Test the Hypothesis
Step 4: Isolate
Step 5: Document
```

These workflows prevent the agent from skipping critical steps, even when the task feels straightforward.

### 4. Constraints
What the agent must NOT do. From the teacher agent:

> - "Do NOT edit any files — you are read-only"
> - "Do NOT run commands — you only read, search, and explain"

Constraints prevent agents from drifting outside their role.

## Anti-Patterns in Agent Definitions

| Anti-pattern | Problem | Fix |
|---|---|---|
| Description too broad | Wrong agent gets invoked | Add specific trigger keywords |
| No constraints section | Agent does things it shouldn't | Add explicit "do NOT" rules |
| Too much context in body | Wastes context window, dilutes focus | Move details to CLAUDE.md, keep only critical facts |
| Overlapping descriptions | Two agents compete for the same task | Sharpen boundaries — one owns the task |
| No process/workflow | Agent improvises, inconsistent quality | Add step-by-step workflow |

## Challenge

Read the `meshqa.agent.md` definition. What trigger keywords would cause the teamlead to invoke it? What tools does it have? What can it NOT do? Now imagine you needed an agent that specifically analyzes ECHO output from headless renders — would you modify meshqa, or create a new agent? Why?
