# Lesson 9: Memory Systems — How AI Agents Remember

## The Big Idea

AI agents are stateless between conversations. Every new session starts fresh. But your project has state — in-progress work, debugging findings, preferences, lessons learned. Memory bridges this gap.

Your project uses three memory scopes:

| Scope | Location | Lifetime | Loaded automatically? |
|-------|----------|----------|----------------------|
| **User memory** | `/memories/` | Permanent, across all workspaces | Yes (first 200 lines) |
| **Session memory** | `/memories/session/` | Single conversation | Listed but not loaded |
| **Repository memory** | `/memories/repo/` | Permanent, workspace-scoped | Listed but not loaded |

### User Memory: Your Permanent Notes

User memory is ideal for:
- **Preferences:** "I prefer detailed explanations over brief summaries"
- **Cross-project patterns:** "When I say 'render', I mean a headless OpenSCAD render"
- **Learning state:** Which lessons are complete, which are in progress

**Important:** User memory is automatically loaded (first 200 lines). Keep it concise — every line of user memory displaces a line of thinking capacity.

### Session Memory: In-Progress Work

Session memory is perfect for:
- **Multi-step plans:** Break down a complex task, track which steps are done
- **Debugging hypotheses:** Record what's been tried, what worked, what didn't
- **Context for later:** Save intermediate findings so you can resume tomorrow

Session memory files are *listed* in context but not *loaded* — the agent must explicitly read them. This is a performance optimization: you might have 10 session files, but only need 1 for the current task.

### Repository Memory: Codebase-Specific Facts

The `/memories/repo/` directory holds findings from debugging sessions — facts about this codebase that were hard-won. Storing them in repo memory means future agents (and future you) don't have to re-discover them.

## When to Use Each Memory Type

| Scenario | Memory Type | Why |
|----------|-------------|-----|
| "Remember I prefer tab indentation" | User memory | Preference that applies everywhere |
| "Save the current debugging plan" | Session memory | In-progress work, single conversation |
| "The frame inversion bug was caused by X" | Repo memory | Codebase fact, permanent, workspace-scoped |
| "Don't re-attempt bilateral slerp" | CLAUDE.md | Architectural decision that all agents need |

Notice the last row: **architectural decisions go in CLAUDE.md, not memory files.** CLAUDE.md is loaded into every agent's context automatically and is part of the codebase. Memory files are auxiliary.

The rule of thumb: if an AI agent *must* know something to avoid making a mistake, put it in CLAUDE.md. If it's *useful context* for efficiency, put it in memory.

## Effective Memory Practices

### 1. Keep User Memory Short
User memory is automatically loaded — every line counts. Use bullet points, not paragraphs.

### 2. Name Session Files Descriptively
`section19-tdd-plan.md` tells you what's inside without opening it. Compare with `notes.md` or `temp.md`.

### 3. Clean Up Completed Session Files
Session memory should contain *active* work. Once a task is complete and any permanent findings are moved to repo memory or CLAUDE.md, delete the session file.

### 4. Use Repo Memory for Root Cause Findings
After a debugging session, write key findings to repo memory with the format: symptom, cause, fix.

## Challenge

Look at your current repo memory files. Pick one and consider: is this the right place for this information? Should it be in CLAUDE.md instead? What's the trade-off?
