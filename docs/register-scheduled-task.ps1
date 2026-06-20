#Requires -RunAsAdministrator
# =============================================================================
# register-scheduled-task.ps1
#
# One-time setup: registers a Windows Scheduled Task that runs
# docs\scheduled-git-push.ps1 every 4 hours.
#
# Must be run as Administrator because schtasks.exe /create needs elevation.
# The task runs whether the user is logged on or not, using the current
# user's credentials.
#
# Usage:
#   docs\register-scheduled-task.ps1
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "This script must be run as Administrator."
    exit 1
}

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$ScriptPath  = Join-Path $RepoRoot "docs\scheduled-git-push.ps1"
$TaskName    = "SkeinToolkit-ScheduledGitPush"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Push script not found: $ScriptPath"
    exit 1
}

# Unregister any previous incarnation of this task
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing scheduled task '$TaskName' ..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build the action: PowerShell -ExecutionPolicy Bypass -File <script>
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -File `"$ScriptPath`""

# Every 4 hours, starting now
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 4) -RepetitionDuration ([timeSpan]::maxvalue)

# Run with highest privileges; stop if the task runs longer than 10 minutes
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Write-Host "Registering scheduled task '$TaskName' ..." -ForegroundColor Cyan
Write-Host "  Script:  $ScriptPath" -ForegroundColor Gray
Write-Host "  Trigger: every 4 hours" -ForegroundColor Gray
Write-Host "  User:    $env:USERNAME" -ForegroundColor Gray

$task = Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "AT-1247: scheduled git push across Electron-Splines, skein-toolkit, and odysseus repos every 4 hours." `
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

