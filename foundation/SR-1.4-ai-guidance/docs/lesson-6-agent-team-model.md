# Lesson 6: How Agent Teams Work — The Mental Model

## The Big Idea

A single AI agent is like a single developer — good at many things, but limited by context. When your project spans multiple languages, tools, and concerns (TypeScript, OpenSCAD, mesh analysis, documentation, architecture), a single agent drowns in instructions and context. The solution is **specialization**: split the work into focused roles, each with just the context they need.

Your project already does this. Look at the team roster in `.github/agents/teamlead.agent.md`:

| Agent | Specialty |
|-------|-----------|
| **teamlead** | Coordination, delegation, progress tracking |
| **openscad** | `.scad` file editing, headless renders, geometry debugging |
| **typescript** | Electron app, Three.js, serialization, UI |
| **meshqa** | STL analysis, mesh quality validation |
| **teacher** | Concept explanation with codebase examples |
| **docs** | Documentation maintenance |
| **priorwork** | Internet research on prior art |
| **rnd** | Evaluate research applicability |
| **spec** | Write specifications from design goals |
| **unittest** | Write tests from specifications |
| **tdd** | Test-driven development coordinator |
| **rca** | Root cause analysis — systematic bug diagnosis |
| **hr** | Agent definition improvement |

This mirrors how real software teams work: you don't ask the QA engineer to write architecture docs, and you don't ask the researcher to fix bugs.

## The Stateless Subagent Model

Here's the critical mental model: **every agent invocation is stateless**. When the teamlead delegates to the openscad agent, that agent:

1. Gets a fresh context — it reads the system prompt, project instructions, and the specific task
2. Does the work (reads files, edits code, runs commands)
3. Returns results to the teamlead
4. **Forgets everything**

This means:
- **Agents don't remember previous conversations.** If you talked to the openscad agent yesterday about bisector clip v8, it doesn't know that today.
- **Context must be self-contained.** Every delegation must include enough information for the agent to act independently.
- **The teamlead is the memory.** It maintains continuity across delegations.

Think of it like writing a work ticket: if the ticket says "fix that bug from this morning," it's useless. If it says "fix the off-surface vertex issue in `_bisector_clip_ring_clip()` at line 142 of `5_bisector_clip.scad` where clipped vertices project perpendicular to the bisector plane instead of along the skin edge," the assignee can act immediately.

## The Delegation Pipeline

Your project defines a standard pipeline for features:

```
priorwork -> rnd -> spec -> unittest -> openscad/typescript -> meshqa -> docs
(research)  (filter) (specify) (test-first) (implement)        (validate) (document)
```

Not every task needs every stage. The teamlead's judgment determines which stages to use:

| Task Type | Pipeline |
|-----------|----------|
| **Bug fix** | openscad/typescript -> meshqa -> docs |
| **New feature** | spec -> unittest -> openscad/typescript -> meshqa -> docs |
| **Exploration** | priorwork -> rnd -> report back |
| **Learning** | teacher (no pipeline) |
| **Agent improvement** | hr (no pipeline) |

This pipeline exists because the team learned through experience that skipping stages causes problems. Implementing without a spec leads to rework. Skipping mesh QA after geometry changes leads to silent regressions.

## Challenge

Look at the pipeline defined in `.github/agents/teamlead.agent.md`. If you wanted to add a new twist correction algorithm to the Long Bezier pipeline, which agents would be involved and in what order? What would change if you were merely *exploring* whether a new algorithm is worth implementing?
