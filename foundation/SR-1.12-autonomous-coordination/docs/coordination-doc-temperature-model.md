# Coordination Doc Temperature Model

> **Owner:** SR-1.12 (Autonomous Coordination)
> **Task:** AT-542
> **Status:** Active policy

## Purpose

Defines recency/retention tiers for the three main coordination docs so they remain within AI context-window limits (~60KB) while preserving full history in linked archives.

## Temperature Tiers

| Tier | Definition | Retention |
|------|-----------|-----------|
| **Hot** | Actively consulted every session. Must fit within AI context window. Contains active policy, ready/blocked/in-progress items, and a bounded recent-completions window. | Always in the hot doc |
| **Warm** | Referenced occasionally for historical context. Linked from the hot doc. | Last 90 days of completed work |
| **Cold** | Preserved in git history only. Not actively linked. | Completed work older than 90 days |

## Per-Document Rules

| Document | Hot content | Archive target | Rollover trigger |
|----------|-----------|----------------|-----------------|
| `ai-task-queue.md` | Operating policy, Ready Pool, Blocked, In Progress, last 50 Done items | `ai-task-queue-done-archive.md` | Done table exceeds 50 rows |
| `current-dashboard.md` | Active issues (Not Started, In Progress, Blocked), last 30 days of completed items | `dashboard-completed-archive.md` | Completed section exceeds 40 items |
| `architect-open-questions.md` | Open questions, last 30 days of answered questions | `architect-open-questions-answered-archive.md` | Answered section exceeds 30 items |

All archive target files live in `architecture-docs/global/` alongside their hot counterparts.

## Rollover Process

1. Count items in the retention-bounded section of the hot doc.
2. If the count exceeds the rollover trigger, identify items beyond the retention window (oldest first).
3. Move those items to the archive target file, preserving their original formatting.
4. The archive file header links back to the hot doc: `> Active doc: [ai-task-queue.md](ai-task-queue.md)`
5. The hot doc contains a standing note: `> See [archive](archive-file.md) for older history.`
6. Rollover is idempotent — running it when under the threshold is a no-op.

## Ownership Rules

- **Hot docs** are the single source of truth for active work. All reads and writes target the hot doc.
- **Archive docs** are append-only. Do not edit, reorder, or delete archived entries.
- **Only the teamlead or docs agent** may execute rollovers. Other agents must not move items between hot and archive docs.
- **Git history** is the cold tier. No explicit cold archive files are maintained — `git log` provides access to removed content.

## Cross-References

- Hot docs: [`ai-task-queue.md`](../../../architecture-docs/global/ai-task-queue.md), [`current-dashboard.md`](../../../architecture-docs/global/current-dashboard.md), [`architect-open-questions.md`](../../../architecture-docs/global/architect-open-questions.md)
- Archive creation: AT-543 (ai-task-queue), AT-544 (dashboard + OQ)
- Rollover automation: deferred — manual rollover per process above until automation is warranted
