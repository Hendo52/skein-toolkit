#Requires -RunAsAdministrator
# =============================================================================
# register-cline-watcher-task.ps1
#
# One-time setup: registers a Windows Scheduled Task that runs
# cline-completion-watch.ps1 every hour.
#
# Must be run as Administrator because Register-ScheduledTask needs
# elevation to create the task -- but the task itself runs at standard
# user privilege (-RunLevel Limited), not elevated. BurntToast notifications
# need the interactive desktop session, not just any user-context token, so
# this uses -LogonType Interactive (runs only while the user is logged on --
# correct anyway, since there's no point notifying if no one's there to see
# it) rather than S4U (scheduled-git-push.ps1's choice, fine for a push,
# wrong for a toast notification that needs the visible desktop session).
#
# Usage:
#   mcp-server\register-cline-watcher-task.ps1
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "This script must be run as Administrator."
    exit 1
}

$ScriptPath = Join-Path $PSScriptRoot "cline-completion-watch.ps1"
$TaskName = "SkeinToolkit-ClineCompletionWatcher"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Watcher wrapper script not found: $ScriptPath"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing scheduled task '$TaskName' ..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NoProfile -NonInteractive -File `"$ScriptPath`""

# Every hour, starting now, indefinitely. [timeSpan]::maxvalue (10,675,199
# days plus a fractional remainder of hours/minutes/seconds) serializes to
# an invalid duration XML for Task Scheduler's own schema -- confirmed live:
# Register-ScheduledTask failed with "task XML contains a value which is
# incorrectly formatted or out of range (10,42):Duration:P99999999DT23H59M59S".
# A round day count with no fractional remainder (the standard community
# workaround for "repeat forever") is what Task Scheduler's schema accepts.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 9999)

# Interactive logon (not S4U/Password) -- required for BurntToast's
# notifications to actually reach the visible desktop session, confirmed
# necessary by direct research into known BurntToast + Task Scheduler
# interactions, not assumed. Limited run level -- this task needs no
# elevation; BurntToast and the watcher's own checks were verified to work
# fine at standard user privilege.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Write-Host "Registering scheduled task '$TaskName' ..." -ForegroundColor Cyan
Write-Host "  Script:  $ScriptPath" -ForegroundColor Gray
Write-Host "  Trigger: every hour" -ForegroundColor Gray
Write-Host "  Logon:   Interactive (required for toast notifications)" -ForegroundColor Gray
Write-Host "  User:    $env:USERNAME" -ForegroundColor Gray

$task = Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "SR-1.14 VERIFY-4 / OQ-300: hourly check for newly-completed interactive Cline sessions, verified via real execution (test suites + launcher smoke tests), with a Windows toast notification on real failures only." `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force

Write-Host ""
Write-Host "Done. Task '$TaskName' is registered." -ForegroundColor Green
Write-Host ""
Write-Host "To verify:   Get-ScheduledTask -TaskName '$TaskName' | Format-List" -ForegroundColor Cyan
Write-Host "To run now:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Cyan
Write-Host "To remove:   Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Cyan
Write-Host "Run log:     `$env:USERPROFILE\.cline_completion_watcher_run.log" -ForegroundColor Cyan
