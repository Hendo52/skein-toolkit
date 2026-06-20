#Requires -Version 5.1
# =============================================================================
# cline-completion-watch.ps1
#
# Scheduled-Task wrapper for cline_completion_watcher.py (OQ-300, AT pending).
#
# Runs the Python watcher in --json mode, and sends a real Windows toast
# notification (BurntToast) only when a newly-completed interactive Cline
# session actually failed verification -- never for a routine all-clear.
#
# Background: SR-1.14 VERIFY-4 (verification-loop-reliability.md). This
# exists because a real Cline session declared "Done" and committed before
# ever running what it had written, which then crashed immediately on first
# real use. dispatch_coding_task already has automatic, real verification
# (checks actual git state); interactive Cline sessions had none. Cline's
# own mechanisms can't fill this gap on Windows (hooks have no completion-
# blocking event and are macOS/Linux-only; "Double-Check Completion" is
# text-only self-critique, confirmed by reading its actual checklist text).
#
# Invocation history: originally built against CronCreate (Claude Code's
# own scheduler), but CronCreate's "durable" flag was found not to actually
# persist jobs across sessions in this environment (confirmed via direct
# testing, contrary to its own documented description) -- a true background
# process was needed instead. This script + register-cline-watcher-task.ps1
# is that background process.
#
# Usage:
#   mcp-server\cline-completion-watch.ps1
# =============================================================================

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$WatcherScript = Join-Path $PSScriptRoot "cline_completion_watcher.py"
$LogPath = Join-Path $env:USERPROFILE ".cline_completion_watcher_run.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $LogPath -Value $line
}

Write-Log "Run starting"

if (-not (Test-Path $WatcherScript)) {
    Write-Log "ERROR: watcher script not found at $WatcherScript"
    exit 1
}

try {
    $jsonOutput = & python $WatcherScript --json 2>&1
} catch {
    Write-Log "ERROR: failed to run watcher script -- $($_.Exception.Message)"
    exit 1
}

try {
    $reports = $jsonOutput | ConvertFrom-Json
} catch {
    Write-Log "ERROR: watcher output was not valid JSON -- $jsonOutput"
    exit 1
}

if (-not $reports -or $reports.Count -eq 0) {
    Write-Log "No new Cline completions -- nothing to report."
    exit 0
}

Write-Log "Found $($reports.Count) new completion(s)."

$anyFailures = $false
foreach ($report in $reports) {
    $reposTouched = ($report.repos_touched -join ", ")
    if ($report.any_failures) {
        $anyFailures = $true
        Write-Log "FAILURE in task $($report.task_id) -- repos: $reposTouched"

        # Compose a specific, actionable message -- name the repo and what
        # failed, not just "something went wrong" (PushNotification's own
        # guidance applies here too: a notification someone can't act on
        # is worse than no notification).
        $failingTests = @($report.test_results.PSObject.Properties | Where-Object { $_.Value -and -not $_.Value.passed } | ForEach-Object { $_.Name })
        $failingSmoke = @($report.smoke_test_results | Where-Object { -not $_.passed } | ForEach-Object { $_.detail })

        $detailParts = @()
        if ($failingTests.Count -gt 0) { $detailParts += "tests failed: $($failingTests -join ', ')" }
        if ($failingSmoke.Count -gt 0) { $detailParts += "launcher crashed: $($failingSmoke -join '; ')" }
        $detail = if ($detailParts.Count -gt 0) { $detailParts -join " | " } else { "see log" }

        # BurntToast's XML template chokes on raw control characters --
        # found running this live: a smoke-test failure detail captured a
        # subprocess's colored log output verbatim, including a raw ANSI
        # escape byte (0x1B), which broke New-BurntToastNotification with
        # "hexadecimal value 0x1B, is an invalid character." Strip C0
        # control chars (keep nothing below 0x20 except none -- a toast is
        # single-line anyway) and cap length so a long traceback doesn't
        # produce an unreadable wall of text in a notification.
        $detail = -join ($detail.ToCharArray() | Where-Object { [int]$_ -ge 0x20 -or $_ -eq "`t" })
        if ($detail.Length -gt 200) { $detail = $detail.Substring(0, 200) + "..." }

        try {
            Import-Module BurntToast -ErrorAction Stop
            New-BurntToastNotification `
                -Text "Cline completion failed verification ($reposTouched)", $detail `
                -ErrorAction Stop
        } catch {
            Write-Log "ERROR: failed to send toast notification -- $($_.Exception.Message)"
        }
    } else {
        Write-Log "Task $($report.task_id) verified OK -- repos: $reposTouched"
    }
}

if (-not $anyFailures) {
    Write-Log "All new completions passed verification -- no notification sent."
}

exit 0
