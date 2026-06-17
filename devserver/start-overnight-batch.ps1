#Requires -Version 5.1
# =============================================================================
# start-overnight-batch.ps1
# Zero-touch overnight batch launcher: reads the ACTIVE tik/tok batch file,
# derives the minimum GPU tier needed, estimates session cost, asks for approval,
# then rents the right instance and starts the safety watcher.
#
# Usage:
#   scripts\start-overnight-batch.ps1                # uses $BatchFilePath from config
#   scripts\start-overnight-batch.ps1 -BatchFile architecture-docs\global\ai-task-tok.md
#   scripts\start-overnight-batch.ps1 -DryRun        # show plan, don't rent
# =============================================================================

param(
    # Override batch file (default: $BatchFilePath from devserver.config.ps1)
    [string]$BatchFile = '',

    # Show plan and cost estimate but do not rent anything.
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Load config ---
$configPath = Join-Path $PSScriptRoot 'devserver.config.ps1'
if (-not (Test-Path $configPath)) { Write-Error "Config not found: $configPath"; exit 1 }
. $configPath

# Load batch state helper
$checkQueueScript = Join-Path $PSScriptRoot 'check-queue-batch-state.ps1'
if (-not (Test-Path $checkQueueScript)) { Write-Error "check-queue-batch-state.ps1 not found"; exit 1 }
. $checkQueueScript

# Resolve batch file
if ($BatchFile -ne '') { $resolvedBatch = $BatchFile }
elseif ($BatchFilePath -ne '') { $resolvedBatch = $BatchFilePath }
else { Write-Error "No batch file configured. Set `$BatchFilePath in devserver.config.ps1 or pass -BatchFile."; exit 1 }

if (-not (Test-Path $resolvedBatch)) { Write-Error "Batch file not found: $resolvedBatch"; exit 1 }

# Resolve vastai executable
$vastaiExe = Get-Command vastai -ErrorAction SilentlyContinue
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { $vastaiExe = $fallback }
    else { Write-Error "vastai not found. Install it: pip install vastai"; exit 1 }
} else { $vastaiExe = $vastaiExe.Source }

function Invoke-VastaiRaw { param([string[]]$Argv); return & $vastaiExe @Argv 2>&1 }

# =============================================================================
# Step 1: Read batch file and parse task tiers
# =============================================================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Overnight Batch Pre-flight" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Batch file: $resolvedBatch" -ForegroundColor Cyan
Write-Host ""

$batchState = Get-BatchFileState -FilePath $resolvedBatch

# Guard: must be READY or ACTIVE (not DONE, STAGING, HOLD)
if ($batchState.Status -notin 'READY', 'ACTIVE') {
    Write-Error "Batch status is '$($batchState.Status)' -- must be READY or ACTIVE to start. Stage a batch first."
    exit 1
}

# Guard: already running elsewhere
$inProgress = @($batchState.TaskStatusMap.Keys | Where-Object { $batchState.TaskStatusMap[$_] -contains 'In Progress' }).Count
if ($inProgress -gt 0) {
    Write-Host "WARNING: $inProgress task(s) are already In Progress in this batch." -ForegroundColor Yellow
    Write-Host "  This may mean a batch is already running on another instance." -ForegroundColor Yellow
    $cont = Read-Host "Continue anyway? (y/N)"
    if ($cont -notmatch '^[yY]') { Write-Host "Cancelled."; exit 0 }
}

if ($batchState.ReadyTaskCount -eq 0) {
    Write-Host "No Ready tasks in batch. Nothing to do." -ForegroundColor Yellow
    exit 0
}

# Parse Model: Tier-X annotations from the batch file raw content
$raw = Get-Content $resolvedBatch -Raw
$tierMatches = [regex]::Matches($raw, 'Model:\s*Tier-([RCM])')
$tiers = $tierMatches | ForEach-Object { $_.Groups[1].Value }

# Determine highest tier present (M > C > R)
$maxTier = if ($tiers -contains 'M') { 'M' }
           elseif ($tiers -contains 'C') { 'C' }
           elseif ($tiers -contains 'R') { 'R' }
           else { 'R' }   # no annotations -- assume cheapest

# Tier -> use-case routing table (mirrors the $useCases table in rent-devserver.ps1)
$useCase = switch ($maxTier) {
    'M' { 'batch' }       # 20+ GB VRAM, spot pricing
    'C' { 'completions' } # cloud tasks don't need local GPU -- use cheap local for tool calls
    'R' { 'completions' } # small local model sufficient
}

$tierCounts = @{ R = 0; C = 0; M = 0 }
foreach ($t in $tiers) { $tierCounts[$t]++ }

Write-Host " Tasks ready  : $($batchState.ReadyTaskCount)" -ForegroundColor White
Write-Host " Tier breakdown: Tier-R=$($tierCounts.R)  Tier-C=$($tierCounts.C)  Tier-M=$($tierCounts.M)  (unannotated=$(($batchState.ReadyTaskCount - $tiers.Count)))" -ForegroundColor White
Write-Host " Max tier     : Tier-$maxTier  ->  use-case: $useCase" -ForegroundColor White
Write-Host ""

# =============================================================================
# Step 2: Query cheapest matching offer for cost estimate
# =============================================================================
$useCaseDefs = @{
    chat        = @{ min_vram_gb = 48; max_cost_hr = 0.90 }
    batch       = @{ min_vram_gb = 20; max_cost_hr = 0.60 }
    completions = @{ min_vram_gb = 12; max_cost_hr = 0.30 }
}
$ucDef = $useCaseDefs[$useCase]

Write-Host "Querying Vast.ai for cheapest $useCase offer..." -ForegroundColor Cyan
$blockedCC   = @('CN', 'RU', 'BY', 'IR', 'KP', 'SY', 'CU', 'VE')
$searchArgs  = @('search', 'offers', '--raw', '--limit', '50', '-o', 'dph_total')
if ($useCase -eq 'batch') { $searchArgs += '--type', 'bid' }
$searchArgs += "gpu_ram>=$($ucDef.min_vram_gb) dph_total<=$($ucDef.max_cost_hr) reliability>0.99"

try {
    $offersRaw = Invoke-VastaiRaw $searchArgs
    $allOffers = $offersRaw | ConvertFrom-Json
    $offers    = @($allOffers | Where-Object {
        $cc = if ($_.geolocation -match ',\s*([A-Z]{2})$') { $Matches[1] } else { '' }
        $blockedCC -notcontains $cc
    })
    $bestOffer = $offers | Select-Object -First 1
} catch {
    Write-Host "Could not query Vast.ai offers: $_" -ForegroundColor Yellow
    $bestOffer = $null
}

$estimatedCost = $null
if ($bestOffer) {
    $estimatedCost = [math]::Round($bestOffer.dph_total * $WatchMaxSessionHours, 2)
    $bidNote = if ($useCase -eq 'batch' -and $bestOffer.PSObject.Properties['min_bid'] -and $bestOffer.min_bid) {
        " (spot bid ~`$$([math]::Round($bestOffer.min_bid * 1.15, 4))/hr)"
    } else { '' }
    Write-Host " Best offer   : $($bestOffer.gpu_name) $($bestOffer.geolocation)" -ForegroundColor White
    Write-Host " Rate         : `$$($bestOffer.dph_total)/hr$bidNote" -ForegroundColor White
    Write-Host " Session cap  : $WatchMaxSessionHours hr / `$$WatchMaxSpendUsd spend cap" -ForegroundColor White
    Write-Host " Est. max cost: `$$estimatedCost  (at $WatchMaxSessionHours hr — actual cost likely less)" -ForegroundColor White
} else {
    Write-Host " Could not retrieve offer -- cost estimate unavailable." -ForegroundColor Yellow
    Write-Host " Idle cap: $WatchIdleMinutes min  |  Session cap: $WatchMaxSessionHours hr  |  Spend cap: `$$WatchMaxSpendUsd" -ForegroundColor White
}

Write-Host ""

# =============================================================================
# Step 3: Approval gate
# =============================================================================
if ($DryRun) {
    Write-Host "DRY RUN -- no instance will be rented. Remove -DryRun to proceed." -ForegroundColor Yellow
    exit 0
}

if ($estimatedCost -and $estimatedCost -gt $WatchMaxSpendUsd) {
    Write-Host "WARNING: Estimated cost `$$estimatedCost exceeds spend cap `$$WatchMaxSpendUsd." -ForegroundColor Yellow
    Write-Host "  Either raise `$WatchMaxSpendUsd in devserver.config.ps1 or choose a cheaper offer." -ForegroundColor Yellow
}

$approve = Read-Host "Approve overnight batch? [Y/n]"
if ($approve -match '^[nN]') {
    Write-Host "Cancelled." -ForegroundColor Yellow
    exit 0
}

# =============================================================================
# Step 4: Rent instance (non-interactive, auto-selects best offer)
# =============================================================================
Write-Host ""
Write-Host "Renting instance..." -ForegroundColor Cyan
$rentScript = Join-Path $PSScriptRoot 'rent-devserver.ps1'
& $rentScript -UseCase $useCase -NonInteractive

# rent-devserver.ps1 calls launch-devserver.ps1 internally, which spawns the watcher.
# The watcher is already configured to use $BatchFilePath from config.
# Nothing more to do here -- the batch will run and the watcher will stop the instance.
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Batch started. Safety watcher is running in a separate window." -ForegroundColor Green
Write-Host " Instance will auto-stop when:" -ForegroundColor Green
Write-Host "   - Batch file status becomes DONE, or" -ForegroundColor Green
Write-Host "   - Ollama idle >= $WatchIdleMinutes min, or" -ForegroundColor Green
Write-Host "   - Session >= $WatchMaxSessionHours hr, or" -ForegroundColor Green
Write-Host "   - Spend >= `$$WatchMaxSpendUsd" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
