#Requires -Version 5.1
# =============================================================================
# stop-devserver.ps1
# Manually stops the running Vast.ai dev instance (disk preserved, no GPU charges).
#
# Usage:
#   scripts\stop-devserver.ps1           # stops the first running instance
#   scripts\stop-devserver.ps1 -Destroy  # PERMANENTLY destroys (loses disk contents)
# =============================================================================

param(
    # Destroy the instance rather than stopping it (ALL DATA LOST).
    [switch]$Destroy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Resolve vastai executable ---
$vastaiExe = Get-Command vastai -ErrorAction SilentlyContinue
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { $vastaiExe = $fallback } else {
        Write-Error "vastai not found. Install it: pip install vastai"
        exit 1
    }
} else { $vastaiExe = $vastaiExe.Source }

# --- Find running instances ---
$rawJson = (& $vastaiExe show instances-v1 --raw 2>&1) | Out-String
try {
    # -AsHashTable is required: live API response contains "label_counts":{"":1}
    # (empty-string key) which ConvertFrom-Json cannot map to a PSCustomObject.
    $parsed    = $rawJson | ConvertFrom-Json -AsHashTable
    $instances = if ($parsed -is [hashtable] -and $parsed.ContainsKey('instances')) { $parsed['instances'] } else { $parsed }
} catch {
    Write-Error "Could not parse Vast.ai instance list. Output:`n$rawJson"
    exit 1
}

$running = @($instances | Where-Object { $_.actual_status -in 'running', 'loading' })

if ($running.Count -eq 0) {
    Write-Host "No running or loading instances found." -ForegroundColor Yellow
    $stopped = @($instances | Where-Object { $_.actual_status -eq 'stopped' })
    if ($stopped.Count -gt 0) {
        Write-Host "Stopped instances (disk still billed):" -ForegroundColor Yellow
        foreach ($s in $stopped) {
            Write-Host "  ID $($s.id): $($s.gpu_name) ($($s.geolocation))" -ForegroundColor Yellow
        }
        $destroyStopped = Read-Host "Destroy a stopped instance to stop disk billing? Enter ID or press Enter to skip"
        if ($destroyStopped -match '^\d+$') {
            Write-Host "Destroying stopped instance $destroyStopped..." -ForegroundColor Red
            & $vastaiExe destroy instance $destroyStopped 2>&1 | ForEach-Object { Write-Host $_ }
        }
    }
    exit 0
}

# --- Pick instance if multiple ---
$inst = $null
if ($running.Count -eq 1) {
    $inst = $running[0]
} else {
    Write-Host "Multiple active instances:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $running.Count; $i++) {
        $r = $running[$i]
        Write-Host "  [$i] ID $($r.id): $($r.gpu_name) -- `$$($r.dph_total)/hr  ($($r.geolocation))" -ForegroundColor Yellow
    }
    $idx = Read-Host "Enter index to stop [0]"
    if ([string]::IsNullOrWhiteSpace($idx)) { $idx = 0 }
    $inst = $running[[int]$idx]
}

$gpu   = if ($inst.gpu_name) { $inst.gpu_name } else { 'Unknown GPU' }
$rate  = $inst.dph_total

if ($Destroy) {
    Write-Host ""
    Write-Host "WARNING: -Destroy flag set. This will PERMANENTLY delete instance $($inst.id) and ALL disk contents." -ForegroundColor Red
    Write-Host "         There is no undo." -ForegroundColor Red
    $confirm = Read-Host "Type 'destroy' to confirm, or anything else to cancel"
    if ($confirm -ne 'destroy') {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit 0
    }
    Write-Host "Destroying instance $($inst.id) ($gpu)..." -ForegroundColor Red
    & $vastaiExe destroy instance $inst.id 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host "Instance $($inst.id) destroyed." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Stopping instance $($inst.id) ($gpu at `$$rate/hr)..." -ForegroundColor Cyan
    Write-Host "  Disk is preserved. GPU charges stop immediately." -ForegroundColor DarkGray
    Write-Host "  To restart: run 'Rent Dev Server' and select the stopped instance." -ForegroundColor DarkGray
    & $vastaiExe stop instance $inst.id 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host ""
    Write-Host "Instance $($inst.id) stopped. Restart via 'Rent Dev Server' when needed." -ForegroundColor Green
}
