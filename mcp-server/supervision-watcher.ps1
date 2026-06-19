#Requires -Version 5.1
# =============================================================================
# supervision-watcher.ps1
#
# AT-1168 / OQ-275 Option C (Option B half): a session-independent watcher
# that polls the AT task queue, the CF-proxy orchestrator's state files, and
# whether Cline is alive, and writes a structured status log
# (supervision-status.json). Built so a supervising Claude session's coverage
# survives session interruption (context auto-compaction, a budget/rate
# limit, or the conversation simply ending) -- a fresh session, or the
# architect, can read the log directly instead of needing live Claude
# supervision to know what state things were left in.
#
# This script does NOT replace Claude's judgment -- it only answers
# "what changed, and is anything stuck", cheaply and without re-deriving
# full context. See supervision-watcher-usage.md (alongside this script) for
# how a supervising Claude session should consume the log.
#
# Usage:
#   mcp-server\supervision-watcher.ps1                                  # loop forever, default settings
#   mcp-server\supervision-watcher.ps1 -RunOnce                         # single poll, then exit (used for testing)
#   mcp-server\supervision-watcher.ps1 -WatchedTaskIds 1162,1163,1164   # watch a specific AT set
#   mcp-server\supervision-watcher.ps1 -PollIntervalSeconds 30 -StuckThresholdSeconds 900
# =============================================================================

[CmdletBinding()]
param(
    [int[]]$WatchedTaskIds = @(1164, 1168, 1170, 1171, 1173, 1174, 1176, 1177, 1201, 1202, 1211),
    [int]$PollIntervalSeconds = 60,
    [int]$StuckThresholdSeconds = 1800,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$OutFile = (Join-Path $env:USERPROFILE ".cf_proxy_orchestrator\supervision-status.json"),
    # AT-1232: dispatch_coding_task's job-state directory (CODING_TASK_STATE_DIR's
    # default in local-mcp.py/dispatch_io.py -- kept in sync manually since this
    # script has no Python dependency to import the constant from).
    [string]$CodingTaskStateDir = (Join-Path $env:USERPROFILE ".coding_task_dispatch"),
    # dispatch_coding_task's own DEFAULT_DISPATCH_TIMEOUT_SECONDS is 1200 (20 min);
    # run-cline.ps1 should self-terminate at that point. A job still reporting
    # status:running well past timeout+buffer, even with a live PID, means the
    # timeout enforcement itself failed -- worth flagging, not just PID death.
    [int]$CodingTaskTimeoutBufferSeconds = 1800,
    [switch]$RunOnce
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$QueueFile = Join-Path $RepoRoot "architecture-docs\global\ai-task-queue.md"
$OrchestratorStateDir = Join-Path $env:USERPROFILE ".cf_proxy_orchestrator"

# Matches a queue row's leading status cell, e.g.:
#   | AT-1182 | ~~**Ready**~~ -- **[Dashboard coverage] ...     (DONE -- this repo's convention
#                                                                 strikes through the ORIGINAL status
#                                                                 word rather than replacing it with
#                                                                 "Done"; the strikethrough itself is
#                                                                 the completion signal)
#   | AT-1201 | **Ready** -- **[skein-toolkit / foundation] ...  (still Ready, not done)
#   | AT-1176 | **Blocked on OQ-284** -- **[OQ-257, Option A] ...
# Capture group 1: leading ~~ (present if struck through). Group 2: AT number.
# Group 3: trailing ~~ after the number (rare but matches the same convention
# applied to the ID cell itself, e.g. ~~AT-1166~~). Group 4: the raw status
# word/phrase inside **...**. Group 5: ~~ immediately after the closing **
# (the actual "is this row done" signal -- this is what AT-1166/1167/etc
# strike through).
$RowStatusPattern = '^\|\s*(~~)?AT-(\d+)(~~)?\s*\|\s*(~~)?\*\*([^*]+)\*\*(~~)?\s*--'

function Get-QueueRowStatuses {
    param([int[]]$TaskIds)
    $result = @{}
    if (-not (Test-Path $QueueFile)) { return $result }
    $lines = Get-Content $QueueFile
    foreach ($id in $TaskIds) {
        $key = "AT-$id"
        $row = $lines | Where-Object { $_ -match "^\|\s*~{0,2}AT-$id~{0,2}\s*\|" } | Select-Object -First 1
        if ($row -and ($row -match $RowStatusPattern)) {
            $rawStatus = $Matches[5].Trim()
            $struckThrough = [bool]$Matches[4] -or [bool]$Matches[6]
            $result[$key] = if ($struckThrough) { "DONE (was: $rawStatus)" } else { $rawStatus }
        } else {
            $result[$key] = $null  # row not found in the queue at all
        }
    }
    return $result
}

function Get-OrchestratorStates {
    $states = @()
    if (-not (Test-Path $OrchestratorStateDir)) { return $states }
    $files = Get-ChildItem $OrchestratorStateDir -Filter "*.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "supervision-status.json" }
    foreach ($f in $files) {
        try {
            $state = Get-Content $f.FullName -Raw | ConvertFrom-Json
            $states += [PSCustomObject]@{
                key     = $f.BaseName
                status  = $state.status
                current = $state.current
                total   = if ($state.steps) { $state.steps.Count } else { $null }
                model   = $state.model
                lastLogTimestamp = if ($state.log -and $state.log.Count -gt 0) { $state.log[-1].ts } else { $null }
            }
        } catch {
            $states += [PSCustomObject]@{ key = $f.BaseName; status = "UNREADABLE"; current = $null; total = $null; model = $null; lastLogTimestamp = $null }
        }
    }
    return $states
}

function Test-ClineAlive {
    $proc = Get-Process -Name "cline" -ErrorAction SilentlyContinue
    return [bool]$proc
}

function Get-CodingTaskJobs {
    # AT-1232: mirrors dispatch_io.find_busy_job_for_repo's logic (PID-liveness
    # primary; a confirmed-dead PID means crashed, not busy) so this watcher and
    # dispatch_coding_task agree on what "stuck" means, rather than maintaining
    # two independent definitions that could silently drift apart.
    $jobs = @()
    if (-not (Test-Path $CodingTaskStateDir)) { return $jobs }
    $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $files = Get-ChildItem $CodingTaskStateDir -Filter "*.json" -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        try {
            $state = Get-Content $f.FullName -Raw | ConvertFrom-Json
        } catch {
            $jobs += [PSCustomObject]@{
                jobId = $f.BaseName; atId = $null; status = "UNREADABLE"; model = $null
                pid = $null; pidAlive = $false; secondsSinceStarted = $null; stuck = $true
            }
            continue
        }
        $pidAlive = $false
        if ($state.pid) {
            $proc = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
            $pidAlive = [bool]$proc
        }
        $secondsSinceStarted = $null
        if ($state.started_at) { $secondsSinceStarted = $nowEpoch - [int64]$state.started_at }

        $stuck = $false
        if ($state.status -eq "running") {
            if (-not $pidAlive) {
                $stuck = $true  # PID confirmed dead while status still says running -- crashed
            } elseif ($null -ne $secondsSinceStarted -and $secondsSinceStarted -gt $CodingTaskTimeoutBufferSeconds) {
                $stuck = $true  # alive but past dispatch_coding_task's own timeout+buffer -- timeout enforcement failed
            }
        }

        $jobs += [PSCustomObject]@{
            jobId               = $f.BaseName
            atId                = $state.at_id
            status              = $state.status
            model               = $state.model
            pid                 = $state.pid
            pidAlive            = $pidAlive
            secondsSinceStarted = $secondsSinceStarted
            stuck               = $stuck
        }
    }
    return $jobs
}

function Invoke-SupervisionPoll {
    # Canonical "now" is a Unix epoch second count (a plain number) -- never an
    # ISO date STRING. PowerShell's ConvertFrom-Json auto-detects and silently
    # converts ISO-looking strings back into [datetime] objects on read, and
    # that round-trip was observed to lose/shift the UTC offset (an integer
    # number of hours matching this machine's local UTC+9:30 offset), making
    # any later `Get-Date $stringValue` arithmetic against a freshly-generated
    # ISO string silently wrong by that offset. Epoch seconds have no timezone
    # to lose. A human-readable ISO string is still recorded alongside (for a
    # person reading the file), but no arithmetic ever touches it.
    $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $nowIso = [DateTimeOffset]::UtcNow.ToString("o")

    # Load the previous log (if any) so we can detect *changes*, not just
    # current state -- "last-change timestamp" and "stuck" both require
    # comparing against what we saw last poll.
    $previous = $null
    if (Test-Path $OutFile) {
        try { $previous = Get-Content $OutFile -Raw | ConvertFrom-Json } catch { $previous = $null }
    }
    $previousTasks = @{}
    if ($previous -and $previous.tasks) {
        foreach ($t in $previous.tasks) { $previousTasks[$t.id] = $t }
    }

    $currentStatuses = Get-QueueRowStatuses -TaskIds $WatchedTaskIds
    $tasks = @()
    foreach ($id in $WatchedTaskIds) {
        $key = "AT-$id"
        $status = $currentStatuses[$key]
        $prior = $previousTasks[$key]

        if ($prior -and $prior.status -eq $status -and $null -ne $prior.lastChangeEpoch) {
            $lastChangeEpoch = [int64]$prior.lastChangeEpoch
        } else {
            # Status differs from last poll (or this is the first poll ever) --
            # this IS the change, so the change timestamp is now.
            $lastChangeEpoch = $nowEpoch
        }

        $secondsSinceChange = $nowEpoch - $lastChangeEpoch
        $stuck = $secondsSinceChange -gt $StuckThresholdSeconds

        $tasks += [PSCustomObject]@{
            id                  = $key
            status              = $status
            lastChangeEpoch     = $lastChangeEpoch
            lastChangeIso       = [DateTimeOffset]::FromUnixTimeSeconds($lastChangeEpoch).ToString("o")
            secondsSinceChange  = $secondsSinceChange
            stuck               = $stuck
        }
    }

    $codingTaskJobs = Get-CodingTaskJobs
    $stuckCodingTaskJobCount = @($codingTaskJobs | Where-Object { $_.stuck }).Count

    $result = [PSCustomObject]@{
        pollTimestampEpoch = $nowEpoch
        pollTimestampIso   = $nowIso
        watchedTaskIds     = $WatchedTaskIds
        tasks              = $tasks
        orchestratorStates = Get-OrchestratorStates
        codingTaskJobs     = $codingTaskJobs
        clineAlive         = Test-ClineAlive
        # AT-1232: the total across both AT-row staleness AND coding-task-job
        # staleness -- AT-1233's wake-loop checks this single field to decide
        # whether anything needs attention at all, so it must cover both
        # detection mechanisms, not just the original AT-row one.
        stuckTaskCount           = @($tasks | Where-Object { $_.stuck }).Count + $stuckCodingTaskJobCount
        stuckCodingTaskJobCount  = $stuckCodingTaskJobCount
    }

    $outDir = Split-Path -Parent $OutFile
    if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force $outDir | Out-Null }
    $result | ConvertTo-Json -Depth 10 | Set-Content $OutFile -Encoding utf8

    return $result
}

# ── Main loop ─────────────────────────────────────────────────────────────
Write-Host "[supervision-watcher] watching $($WatchedTaskIds.Count) AT task(s): $($WatchedTaskIds -join ', ')" -ForegroundColor Cyan
Write-Host "[supervision-watcher] output: $OutFile" -ForegroundColor Cyan

if ($RunOnce) {
    $r = Invoke-SupervisionPoll
    Write-Host "[supervision-watcher] single poll complete -- $($r.stuckTaskCount) stuck task(s) [$($r.stuckCodingTaskJobCount) coding-task job(s)], cline alive: $($r.clineAlive)" -ForegroundColor $(if ($r.stuckTaskCount -gt 0) { 'Yellow' } else { 'Green' })
    exit 0
}

while ($true) {
    $r = Invoke-SupervisionPoll
    $color = if ($r.stuckTaskCount -gt 0) { 'Yellow' } else { 'Green' }
    Write-Host "[supervision-watcher] $($r.pollTimestampIso) -- $($r.stuckTaskCount) stuck task(s) [$($r.stuckCodingTaskJobCount) coding-task job(s)], cline alive: $($r.clineAlive)" -ForegroundColor $color
    Start-Sleep -Seconds $PollIntervalSeconds
}
