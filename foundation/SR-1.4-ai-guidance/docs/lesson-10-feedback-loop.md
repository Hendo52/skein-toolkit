# Lesson 10: The Feedback Loop — Working Effectively with Agent Teams

## The Big Idea

The difference between someone who gets mediocre results from AI agents and someone who gets excellent results isn't the AI — it's the **feedback loop**. Effective AI usage is iterative: prompt -> observe -> refine -> repeat.

## Prompt Crafting: The 80/20 Rule

80% of prompt quality is **context**. The remaining 20% is clarity and specificity.

### What to Include in a Task Delegation

When the teamlead delegates to a specialist agent, it should include:

1. **What to do** — the specific action, not the goal
2. **Where to do it** — file paths, function names, line numbers
3. **Why** — enough context that the agent can make judgment calls
4. **Constraints** — what NOT to do, what to preserve
5. **Success criteria** — how the agent knows it's done

**Bad delegation:**
> "Fix the bisector clip bug."

**Good delegation:**
> "In `stages/geometry_algorithms/5_bisector_clip.scad`, the `_bisector_clip_ring_clip()` function at line 142 projects clipped vertices perpendicular to the bisector plane. This creates off-surface vertices. Instead, project along the skin edge by interpolating between adjacent profile points. Preserve the existing `_ring_clip_vertex()` function signature. The fix is correct when `analyze_mesh.py` reports 0 non-manifold edges on the knight-v2 STL."

The second version can be acted on independently. The first requires a round trip.

### The Specificity Spectrum

| Level | Example | When to use |
|-------|---------|-------------|
| **Vague** | "Improve the joint handling" | Never — too ambiguous |
| **Goal-oriented** | "Make knight-v2 joints watertight" | When you trust the agent's domain expertise |
| **Tactical** | "Edit `_assembly_stage4_joint_frames_insert` to use bilateral slerp" | When you know the exact change needed |
| **Surgical** | "On line 287 of core.scad, change `frame_a` to `_math_slerp(frame_a, frame_b, 0.5)`" | When you've debugged to a specific line |

More specificity = fewer round trips = faster results. But over-specifying can also be wrong — if you prescribe the wrong line, the agent follows your instructions to a wrong result. **Specify the *what* and *why*; let the agent figure out the *where* and *how* when possible.**

## When to Use Which Agent: The Routing Decision

Your teamlead has a routing table, but the real skill is knowing when tasks are **cross-domain**. Some examples:

| Request | Obvious route | Actually needs |
|---------|--------------|----------------|
| "Add a new profile parameter" | openscad | spec -> openscad -> docs (touches data contracts!) |
| "Why does this joint look wrong?" | openscad | rca -> openscad (diagnose first, fix second) |
| "Is there a better algorithm for X?" | priorwork | priorwork -> rnd -> spec (research, evaluate, specify) |
| "The mesh has non-manifold edges" | meshqa | meshqa (diagnosis only) -> rca -> openscad (fix) |
| "Update the docs after this change" | docs | docs (but give it the diff, not just "update the docs") |

The most common mistake is **jumping to implementation without diagnosis**. When something looks wrong, the instinct is to delegate to the openscad agent to fix it. But if you don't understand *why* it's wrong, the fix is a guess. Route through RCA first.

## Teamlead vs Direct Invocation

You have two modes of interaction:

1. **Through the teamlead** — you describe a high-level goal, the teamlead breaks it down and delegates
2. **Direct invocation** — you switch to a specific agent mode (e.g., `@openscad` or `@teacher`) and talk to the specialist directly

| Scenario | Mode | Why |
|----------|------|-----|
| Multi-step feature | Teamlead | Needs coordination, memory across steps |
| Quick code edit | Direct to specialist | No coordination needed, faster |
| Learning question | Direct to teacher | No delegation overhead |
| Bug investigation | Teamlead | Might need RCA -> openscad -> meshqa chain |
| "Do everything" | Teamlead | That's literally its job |

## Common Pitfalls and Anti-Patterns

### 1. "Fix It" Without Context
**Anti-pattern:** "The mesh is broken, fix it."
**Fix:** "Knight-v2.scad produces 12 non-manifold edges at the mane-to-skull joint. Expected: 0 non-manifold edges, watertight mesh, Euler=2."

### 2. Over-Loading a Single Session
**Anti-pattern:** Working through a 15-step implementation plan in one conversation.
**Fix:** Use session memory to save checkpoints. Break long features into self-contained sub-tasks.

### 3. Not Validating After Changes
**Anti-pattern:** Making code changes and assuming they work because no errors were printed.
**Fix:** Always follow code changes with validation. OpenSCAD fails silently — a mesh that "renders" might have 50 non-manifold edges.

### 4. Not Reading the Output
**Anti-pattern:** Delegating to an agent and not reading its full output before continuing.
**Fix:** Read the full output. The agent might have flagged a concern, noted a naming violation, or identified a risk.

### 5. Re-Inventing the Wheel
**Anti-pattern:** Asking an agent to try an approach already documented as "confirmed insufficient" in CLAUDE.md.
**Fix:** The teamlead should check CLAUDE.md before delegating novel approaches.

### 6. Treating Agents as Infallible
**Anti-pattern:** Accepting the agent's first output without review.
**Fix:** Review code changes before committing. The agent is a powerful collaborator, but you're the System Architect — the buck stops with you.

## The Iteration Pattern

```
You:       (clear, specific task with context)
Agent:     (attempt, possibly incomplete)
You:       (feedback — "this part is right, but X is wrong because Y")
Agent:     (refined attempt)
You:       (validate — run tests, mesh QA, visual inspection)
Agent/You: (commit if good, iterate if not)
```

## Improving the Team Over Time

Your team has a meta-improvement loop via the hr agent. When an agent consistently underperforms:

1. **Identify the pattern** — is it missing keywords in descriptions? Lacking domain context? Exceeding its tool access?
2. **Delegate to HR** — "The meshqa agent keeps running renders when it should only analyze existing STL files"
3. **HR diagnoses and fixes** — updates the agent's `.agent.md` file
4. **Verify** — does the agent perform better with the new definition?

The agent definitions aren't static — they're living documents that evolve as you learn what works.

## Challenge

Think about the last time an AI agent gave you a result that wasn't quite right. What was missing from the prompt? What context would have prevented the misunderstanding? Could that context be added to CLAUDE.md so that *all future agents* benefit from it?

---

## Summary: Five Key Principles

1. **Specialize, don't generalize.** Each agent does one thing well, with just the context it needs.
2. **Instructions > prompts.** Invest in CLAUDE.md and agent definitions — they compound across every future interaction.
3. **Validate, don't trust.** Always run mesh QA, tests, or visual inspection after changes.
4. **Context is king.** The quality of an agent's output is directly proportional to the context you provide.
5. **Iterate and improve.** Both your prompts and your agent definitions should get better over time.
