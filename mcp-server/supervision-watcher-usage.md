# supervision-watcher.ps1 -- usage and log format

AT-1168 / OQ-275 Option C. A standalone PowerShell script that polls the AT
task queue, the CF-proxy orchestrator's state files, and Cline's process
liveness on a fixed interval, independent of any Claude session. It writes
`~/.cf_proxy_orchestrator/supervision-status.json` so coverage survives a
Claude session ending (context auto-compaction, a budget/rate limit, or the
conversation simply being closed) -- a fresh session, or the architect
directly, can read the log instead of needing live Claude supervision to know
what state things were left in.

## Running it

```powershell
# Loop forever (default 60s poll interval), watching a sensible default AT set
mcp-server\supervision-watcher.ps1

# Single poll, then exit -- useful for a one-shot check or for testing
mcp-server\supervision-watcher.ps1 -RunOnce

# Watch a specific AT set (e.g. tonight's dispatched tasks)
mcp-server\supervision-watcher.ps1 -WatchedTaskIds 1162,1163,1164,1166,1167

# Tune the poll interval and stuck threshold
mcp-server\supervision-watcher.ps1 -PollIntervalSeconds 30 -StuckThresholdSeconds 900
```

It does not require Cline, Claude, or any MCP server to be running -- it only
reads `ai-task-queue.md` and `~/.cf_proxy_orchestrator/*.json`, both of which
exist independent of any live process.

## How a supervising Claude session should consume the log

**Read the latest entry instead of re-deriving full context each check-in.**
The whole point of this script is that a supervising session's periodic
check-in should be a single cheap file read, not a fresh `git log` /
`grep ai-task-queue.md` / orchestrator-state-directory walk every time (see
the `feedback_supervision_cost` memory note: keep periodic-check cost small).

```powershell
Get-Content "$env:USERPROFILE\.cf_proxy_orchestrator\supervision-status.json" -Raw | ConvertFrom-Json
```

Then look at, in order:

1. **`stuckTaskCount`** -- if 0, nothing needs attention; the rest of the log
   is for context, not action.
2. **`tasks[].stuck`** -- which specific AT(s) triggered it, and `status` to
   see what they're stuck *at* (e.g. still `Ready` after a long time means
   dispatch never happened or silently died; `Blocked on OQ-...` is not
   "stuck" in the worrying sense -- it's correctly waiting on a human
   decision, but a Claude session reviewing the log should still surface it).
3. **`orchestratorStates`** -- any entry with `status: "running"` and a
   `lastLogTimestamp` far in the past is a run that likely died without
   updating its own state file (the orchestrator only writes on each step
   transition, so a long gap usually means the dispatching process -- Cline,
   `run-cline.ps1` -- is no longer advancing it).
4. **`clineAlive`** -- `false` while AT rows show `Ready` (not yet dispatched)
   is expected and fine; `false` while an orchestrator state shows `running`
   is the strongest "something died" signal in the whole log.

## Log format

`supervision-status.json` (single object, overwritten each poll):

| Field | Meaning |
|---|---|
| `pollTimestampEpoch` / `pollTimestampIso` | When this poll ran. Epoch (Unix seconds) is canonical; the ISO string is for human readability only -- never parsed back for arithmetic (see the timezone note below). |
| `watchedTaskIds` | The AT numbers this poll was configured to watch. |
| `tasks[]` | One entry per watched AT: `id`, `status` (the raw text inside the queue row's leading `**...**`, or `"DONE (was: <original status>)"` if the row's status was struck through -- see below), `lastChangeEpoch`/`lastChangeIso` (when `status` last differed from the previous poll), `secondsSinceChange`, `stuck` (`secondsSinceChange > StuckThresholdSeconds`). |
| `orchestratorStates[]` | One entry per `~/.cf_proxy_orchestrator/*.json` file: `key` (filename without extension -- the orchestrator run key), `status`, `current`/`total` step, `model`, `lastLogTimestamp` (from the state file's own log, not this script's clock). |
| `clineAlive` | Whether a `cline.exe` process is currently running. |
| `stuckTaskCount` | Count of `tasks[]` with `stuck: true` -- the single field worth checking first. |

### The strikethrough convention

This repo's `ai-task-queue.md` marks a row done by striking through its
*original* status word rather than replacing it with a literal "Done", e.g.
`~~**Ready**~~` (see AT-1166/1167 and others). The watcher detects the `~~`
wrapper and reports `"DONE (was: Ready)"` rather than the misleading raw
`"Ready"`. Some rows use the other convention instead (a literal `**Done**`
with no strikethrough) -- those pass through unchanged since the raw text is
already unambiguous.

### Why epoch seconds, not ISO date strings, for the "last change" comparison

An earlier version of this script stored `lastChangeUtc` as an ISO-8601
string and computed `secondsSinceChange` via `(Get-Date $now) - (Get-Date
$lastChangeUtc)`. This produced a consistent ~9.5-hour error (matching this
machine's local UTC+9:30 offset) after a round-trip through `ConvertTo-Json`
/ `ConvertFrom-Json` -- PowerShell's JSON deserializer auto-detects
ISO-looking strings and silently converts them back into `[datetime]`
objects, and that conversion was observed to lose track of which values were
UTC and which were local. Epoch seconds (`[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()`)
have no timezone to lose, so all arithmetic in this script uses them; the ISO
string fields exist purely for a human reading the raw JSON.
