#Requires -Version 5.1
# =============================================================================
# watch-devserver.ps1
# Safety watcher for a running Vast.ai dev instance.
#
# Stops the instance automatically when ANY of these conditions are met:
#   1. Ollama has been idle (no model loaded) for $IdleMinutes
#   2. The session has run for $MaxSessionHours hours (hard cap)
#   3. Estimated session spend exceeds $MaxSpendUsd
#
# Vast.ai auto-tops-up credit without confirmation. This watcher is the
# circuit breaker that prevents runaway overnight charges.
#
# Typical usage (called automatically by launch-devserver.ps1):
#   Start-Job -FilePath scripts\watch-devserver.ps1 -ArgumentList $instanceId, $hourlyRate
#
# Can also be run manually in a terminal for visibility:
#   scripts\watch-devserver.ps1 -InstanceId 12345678 -HourlyRate 0.24
#
# The watcher checks Ollama via the SSH tunnel forwarded to localhost:11434.
# Ensure launch-devserver.ps1 has already opened the SSH connection before
# starting this watcher.
# =============================================================================

param(
    [Parameter(Mandatory)]
    [int]$InstanceId,

    [Parameter(Mandatory)]
    [double]$HourlyRate,

    # Stop if Ollama reports no loaded models for this many consecutive minutes.
    [int]$IdleMinutes = 30,

    # Hard session cap in hours. Instance is stopped regardless of activity.
    [double]$MaxSessionHours = 8,

    # Hard spend cap for this session in USD.
    [double]$MaxSpendUsd = 10.00,

    # Poll interval in seconds.
    [int]$PollSeconds = 60,

    # Warn N minutes before a hard cap triggers.
    [int]$WarnMinutes = 10,

    # Optional: path to the active tik/tok batch file.
    # When set, the watcher also stops the instance when the batch reports Status: DONE
    # and suppresses idle-teardown while tasks are In Progress.
    [string]$BatchFilePath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'   # watcher must not crash on transient errors

# --- Resolve vastai executable ---
$vastaiExe = Get-Command vastai -ErrorAction SilentlyContinue
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { $vastaiExe = $fallback } else { Write-Error "vastai not found."; exit 1 }
} else { $vastaiExe = $vastaiExe.Source }

# Load batch-state helper if a batch file was provided
$checkQueueScript = Join-Path $PSScriptRoot 'check-queue-batch-state.ps1'
$batchAware = $BatchFilePath -ne '' -and (Test-Path $BatchFilePath) -and (Test-Path $checkQueueScript)
if ($batchAware) {
    . $checkQueueScript
    Write-Host " Batch file      : $BatchFilePath" -ForegroundColor Cyan
} else {
    Write-Host " Batch file      : (not set -- idle-only stop)" -ForegroundColor DarkGray
}

function Stop-Instance {
    param([string]$Reason)
    Write-Host ""
    Write-Host "=== AUTO-STOP TRIGGERED ===" -ForegroundColor Red
    Write-Host "Reason : $Reason" -ForegroundColor Red
    Write-Host "Action : vastai stop instance $InstanceId (disk preserved)" -ForegroundColor Yellow
    Write-Host ""
    & $vastaiExe stop instance $InstanceId 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host ""
    Write-Host "Instance $InstanceId stopped. Restart it via 'Rent Dev Server' when needed." -ForegroundColor Cyan
}

function Get-OllamaStatus {
    # Ollama /api/ps returns {"models":[...]} -- empty list means nothing is loaded.
    # Requires the SSH tunnel (LocalForward 11434) to be active.
    try {
        $resp = Invoke-RestMethod -Uri 'http://localhost:11434/api/ps' `
            -Method Get -TimeoutSec 5 -ErrorAction Stop
        $models = $resp.models
        if ($null -eq $models -or $models.Count -eq 0) {
            return 'idle'
        }
        $names = ($models | ForEach-Object { $_.name }) -join ', '
        return "busy:$names"
    } catch {
        # Tunnel down or Ollama not started yet -- treat as unknown, not idle.
        return 'unreachable'
    }
}

function Format-TimeSpan {
    param([TimeSpan]$ts)
    return "{0:D2}h {1:D2}m" -f [int]$ts.TotalHours, $ts.Minutes
}

# --- Init ---
$sessionStart  = Get-Date
$idleStart     = $null   # when the current idle streak began
$warnedSession = $false
$warnedSpend   = $false

$maxSessionSec  = $MaxSessionHours * 3600
$warnSessionSec = ($MaxSessionHours * 3600) - ($WarnMinutes * 60)
$maxSpendWarn   = $MaxSpendUsd - ($HourlyRate * $WarnMinutes / 60)

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Dev Server Watcher  --  instance $InstanceId" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Idle auto-stop   : $IdleMinutes min of no Ollama activity" -ForegroundColor Cyan
Write-Host " Session hard cap : $MaxSessionHours hr ($($MaxSpendUsd.ToString('C')))" -ForegroundColor Cyan
Write-Host " Spend hard cap   : `$$MaxSpendUsd at `$$HourlyRate/hr" -ForegroundColor Cyan
Write-Host " Poll interval    : every $PollSeconds sec" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
Write-Host " To stop manually : vastai stop instance $InstanceId" -ForegroundColor DarkGray
Write-Host " To kill watcher  : Stop-Job (if running as background job)" -ForegroundColor DarkGray
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# --- Main loop ---
while ($true) {
    $elapsed      = (Get-Date) - $sessionStart
    $elapsedHours = $elapsed.TotalHours
    $spentSoFar   = [math]::Round($elapsedHours * $HourlyRate, 3)

    $ollamaStatus = Get-OllamaStatus

    # --- Track idle streak ---
    if ($ollamaStatus -eq 'idle') {
        if (-not $idleStart) { $idleStart = Get-Date }
        $idleSeconds = ((Get-Date) - $idleStart).TotalSeconds
        $idleDisplay = "{0:F0} min" -f ($idleSeconds / 60)
    } else {
        $idleStart   = $null
        $idleSeconds = 0
        $idleDisplay = "n/a"
    }

    # --- Status line ---
    $ts = Format-TimeSpan -ts $elapsed
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] elapsed=$ts  spent=`$$spentSoFar  ollama=$ollamaStatus  idle=$idleDisplay" -ForegroundColor DarkGray

    # --- Batch-aware checks ---
    if ($batchAware) {
        try {
            $batchState = Get-BatchFileState -FilePath $BatchFilePath
            $inProgress = @($batchState.TaskStatusMap.Keys | Where-Object { $batchState.TaskStatusMap[$_] -contains 'In Progress' }).Count

            # Hard stop: batch is fully done
            if ($batchState.Status -eq 'DONE' -and $batchState.ReadyTaskCount -eq 0 -and $inProgress -eq 0) {
                Stop-Instance -Reason "Batch DONE: all tasks complete in $([System.IO.Path]::GetFileName($BatchFilePath))"
                exit 0
            }

            # Suppress idle teardown while tasks are still running or queued
            if ($inProgress -gt 0 -or $batchState.ReadyTaskCount -gt 0) {
                if ($idleStart) {
                    Write-Host "  (idle suppressed: $($batchState.ReadyTaskCount) ready, $inProgress in-progress)" -ForegroundColor DarkGray
                }
                $idleStart = $null  # reset idle streak -- work is pending
            }
        } catch {
            Write-Host "  (batch state read failed: $_)" -ForegroundColor DarkGray
        }
    }

    # --- Warn: approaching session cap ---
    if (-not $warnedSession -and $elapsed.TotalSeconds -ge $warnSessionSec) {
        Write-Host ""
        Write-Host "WARNING: Session cap ($MaxSessionHours hr) in $WarnMinutes minutes. Instance will auto-stop unless you extend the session." -ForegroundColor Yellow
        Write-Host "  To extend: Restart this watcher with a higher -MaxSessionHours value." -ForegroundColor Yellow
        Write-Host ""
        $warnedSession = $true
    }

    # --- Warn: approaching spend cap ---
    if (-not $warnedSpend -and $spentSoFar -ge $maxSpendWarn) {
        Write-Host ""
        Write-Host "WARNING: Spend cap (`$$MaxSpendUsd) in ~$WarnMinutes minutes. Instance will auto-stop unless you extend the cap." -ForegroundColor Yellow
        Write-Host "  To extend: Restart this watcher with a higher -MaxSpendUsd value." -ForegroundColor Yellow
        Write-Host ""
        $warnedSpend = $true
    }

    # --- Hard stop: session cap ---
    if ($elapsed.TotalSeconds -ge $maxSessionSec) {
        Stop-Instance -Reason "Session hard cap reached: $(Format-TimeSpan -ts $elapsed) >= $MaxSessionHours hr"
        exit 0
    }

    # --- Hard stop: spend cap ---
    if ($spentSoFar -ge $MaxSpendUsd) {
        Stop-Instance -Reason "Spend cap reached: `$$spentSoFar >= `$$MaxSpendUsd"
        exit 0
    }

    # --- Hard stop: idle ---
    if ($idleSeconds -ge ($IdleMinutes * 60)) {
        Stop-Instance -Reason "Ollama idle for $([int]($idleSeconds/60)) min (threshold: $IdleMinutes min)"
        exit 0
    }

    Start-Sleep -Seconds $PollSeconds
}
