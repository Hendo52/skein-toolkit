#Requires -Version 5.1
# =============================================================================
# DevServer.psm1
# Shared business logic for Vast.ai dev server management.
#
# Testability model:
#   Pure functions (no side effects -- test without mocks):
#     ConvertFrom-VastaiInstances, Select-VastaiOffer, Test-WatcherShouldStop
#
#   Impure functions with injectable seams (mock Invoke-VastaiCli in tests):
#     Get-DevServerInstances, Wait-ForRunning
#
#   Impure functions (mock Invoke-RestMethod via Pester):
#     Get-OllamaStatus
# =============================================================================

Set-StrictMode -Version Latest

# =============================================================================
# CLI resolution
# =============================================================================

function Resolve-VastaiExe {
    <#
    .SYNOPSIS Returns full path to vastai.exe. Throws if not found.
    #>
    $found = Get-Command vastai -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "vastai not found. Install with: pip install vastai"
}

# =============================================================================
# CLI wrapper -- the primary mockable seam for all external CLI calls
# =============================================================================

function Invoke-VastaiCli {
    <#
    .SYNOPSIS
    Invokes the vastai CLI and returns stdout+stderr as a single string.
    This is the mockable seam for all tests that exercise CLI-dependent logic.
    #>
    param([Parameter(Mandatory)][string[]]$Argv)
    $exe = Resolve-VastaiExe
    return (& $exe @Argv 2>&1) | Out-String
}

# =============================================================================
# Pure: Parse raw vastai instances JSON
# =============================================================================

function ConvertFrom-VastaiInstances {
    <#
    .SYNOPSIS
    Parses raw JSON from 'vastai show instances-v1 --raw' into a structured result.

    vastai returns either:
      - Wrapped format: {"instances":[...]}
      - Bare array:     [{...},{...}]

    Returns a PSCustomObject with .Running, .Loading, .Stopped, .All arrays.
    Returns $null on parse failure (caller is responsible for error handling).
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$RawJson)

    if ([string]::IsNullOrWhiteSpace($RawJson)) { return $null }

    $list = @()   # pre-initialize; overwritten inside try on success
    try {
        # -AsHashTable is required: the live API response includes "label_counts":{"":1}
        # which has an empty-string key that ConvertFrom-Json cannot map to a PSCustomObject.
        $parsed = $RawJson | ConvertFrom-Json -AsHashTable
        # Handle wrapped {"instances":[...]} vs bare [{...}] format
        $rawList = if ($parsed -is [hashtable] -and $parsed.ContainsKey('instances')) {
            $parsed['instances']
        } else {
            $parsed
        }
        # Normalize to a typed array.
        # IMPORTANT: do NOT use @() or conditional expressions here -- in PS7,
        # @() inside an if-expression is pipeline-unrolled to no-output, so the
        # assignment becomes $null.  The $list = @() pre-init above handles the
        # null/empty case; this branch only runs when rawList is actually populated.
        if ($null -ne $rawList) {
            $list = [object[]]$rawList
        }
    } catch {
        return $null
    }

    # Partition into typed buckets using explicit @() initialization so the
    # properties are always non-null empty arrays (not $null) in strict mode.
    $running = @()
    $loading = @()
    $stopped = @()
    foreach ($inst in $list) {
        if ($null -eq $inst) { continue }
        switch ($inst.actual_status) {
            'running' { $running += $inst }
            'loading' { $loading += $inst }
            'stopped' { $stopped += $inst }
        }
    }

    return [pscustomobject]@{
        Running = $running
        Loading = $loading
        Stopped = $stopped
        All     = $list
    }
}

# =============================================================================
# Pure: Select cheapest qualifying offer
# =============================================================================

function Select-VastaiOffer {
    <#
    .SYNOPSIS
    Filters offers by VRAM minimum, price ceiling, and country blocklist,
    then returns the cheapest qualifying offer (or $null if none qualify).

    The geolocation field is expected to be "City, CC" where CC is an ISO-3166
    two-letter country code. Offers with no geolocation field pass the country check.
    #>
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][array]$Offers,
        [Parameter(Mandatory)][int]$MinVramGb,
        [Parameter(Mandatory)][double]$MaxCostHr,
        [string[]]$BlockedCountryCodes = @('CN','RU','BY','IR','KP','SY','CU','VE')
    )

    if (-not $Offers -or $Offers.Count -eq 0) { return $null }

    $qualified = $Offers | Where-Object {
        $o = $_
        # VRAM check
        if ($o.gpu_ram -lt $MinVramGb) { return $false }
        # Price check
        if ($o.dph_total -gt $MaxCostHr) { return $false }
        # Country check -- parse "City, CC" geolocation
        if ($o.PSObject.Properties['geolocation'] -and $o.geolocation) {
            $cc = if ($o.geolocation -match ',\s*([A-Z]{2})$') { $Matches[1] } else { '' }
            if ($cc -ne '' -and $BlockedCountryCodes -contains $cc) { return $false }
        }
        return $true
    }

    return $qualified | Sort-Object dph_total | Select-Object -First 1
}

# =============================================================================
# Pure: Watcher auto-stop decision
# =============================================================================

function Test-WatcherShouldStop {
    <#
    .SYNOPSIS
    Evaluates whether the safety watcher should stop the instance.

    All state is passed as parameters; this function has no side effects and
    requires no mocks to test.

    Return value:
      $null          -- no stop warranted
      @{Stop=$true; Reason='...'}  -- stop should be triggered

    Batch-aware rules:
      - Session and spend caps are NEVER suppressed (they fire regardless of batch state).
      - Idle teardown IS suppressed when BatchReadyCount > 0 or BatchInProgressCount > 0.
      - BatchDone=$true with both counts = 0 triggers a hard stop.
      - When BatchReadyCount/BatchInProgressCount = -1, batch awareness is disabled.
    #>
    param(
        [Parameter(Mandatory)][double]$ElapsedSeconds,
        [Parameter(Mandatory)][double]$SpentUsd,
        [Parameter(Mandatory)][double]$IdleSeconds,
        [Parameter(Mandatory)][double]$IdleThresholdSeconds,
        [Parameter(Mandatory)][double]$MaxSessionSeconds,
        [Parameter(Mandatory)][double]$MaxSpendUsd,
        [bool]$BatchDone            = $false,
        [int]$BatchReadyCount       = -1,   # -1 = not batch-aware
        [int]$BatchInProgressCount  = -1    # -1 = not batch-aware
    )

    # Batch DONE + nothing pending = hard stop (checked before idle, before caps)
    $batchAware = $BatchReadyCount -ge 0 -and $BatchInProgressCount -ge 0
    if ($batchAware -and $BatchDone -and $BatchReadyCount -eq 0 -and $BatchInProgressCount -eq 0) {
        return @{ Stop = $true; Reason = "Batch DONE: all tasks complete" }
    }

    # Session hard cap (never suppressed -- even with pending batch work)
    if ($ElapsedSeconds -ge $MaxSessionSeconds) {
        return @{ Stop = $true; Reason = "Session cap: $([int]($ElapsedSeconds/3600))h >= $([int]($MaxSessionSeconds/3600))h limit" }
    }

    # Spend hard cap (never suppressed)
    if ($SpentUsd -ge $MaxSpendUsd) {
        return @{ Stop = $true; Reason = "Spend cap: `$$SpentUsd >= `$$MaxSpendUsd limit" }
    }

    # Idle stop -- suppressed when batch has pending work
    $batchHasPending = $batchAware -and ($BatchReadyCount -gt 0 -or $BatchInProgressCount -gt 0)
    if ($IdleSeconds -ge $IdleThresholdSeconds -and -not $batchHasPending) {
        return @{ Stop = $true; Reason = "Idle: $([int]($IdleSeconds/60)) min >= $([int]($IdleThresholdSeconds/60)) min threshold" }
    }

    return $null
}

# =============================================================================
# Impure: Fetch current instance list
# =============================================================================

function Get-DevServerInstances {
    <#
    .SYNOPSIS
    Fetches and parses the current Vast.ai instance list.
    Returns a structured result (@{Running;Loading;Stopped;All}) or $null on failure.
    #>
    $raw = Invoke-VastaiCli @('show', 'instances-v1', '--raw')
    return ConvertFrom-VastaiInstances -RawJson $raw
}

# =============================================================================
# Impure: Wait for instance to reach 'running' state
# =============================================================================

function Wait-ForRunning {
    <#
    .SYNOPSIS
    Polls until the specified instance reaches 'running' status or timeout elapses.

    The $Sleeper parameter accepts a scriptblock so tests can inject a no-op
    to avoid real delays:
        Wait-ForRunning -InstanceId 123 -Sleeper { }
    #>
    param(
        [Parameter(Mandatory)][int]$InstanceId,
        [int]$TimeoutMinutes = 15,
        [int]$PollSeconds    = 10,
        [scriptblock]$Sleeper = { param($s) Start-Sleep -Seconds $s }
    )

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)

    while ((Get-Date) -lt $deadline) {
        & $Sleeper $PollSeconds
        $state = Get-DevServerInstances
        if ($state) {
            $inst = $state.All | Where-Object { $_.id -eq $InstanceId } | Select-Object -First 1
            if ($inst -and $inst.actual_status -eq 'running') { return $inst }
        }
    }

    return $null
}

# =============================================================================
# Impure: Ollama model activity check (via SSH tunnel)
# =============================================================================

function Get-OllamaStatus {
    <#
    .SYNOPSIS
    Queries the local Ollama API (port-forwarded via SSH tunnel to the dev instance).
    Returns 'idle', 'busy:modelname', or 'unreachable'.

    'unreachable' means the tunnel is down or Ollama has not started yet.
    It does NOT mean the instance is idle -- treat 'unreachable' as unknown, not idle.
    #>
    try {
        $resp = Invoke-RestMethod -Uri 'http://localhost:11434/api/ps' `
            -Method Get -TimeoutSec 5 -ErrorAction Stop
        if (-not $resp.models -or $resp.models.Count -eq 0) { return 'idle' }
        $names = ($resp.models | ForEach-Object { $_.name }) -join ', '
        return "busy:$names"
    } catch {
        return 'unreachable'
    }
}

# =============================================================================
# Module exports
# =============================================================================

Export-ModuleMember -Function @(
    'Resolve-VastaiExe',
    'Invoke-VastaiCli',
    'ConvertFrom-VastaiInstances',
    'Select-VastaiOffer',
    'Test-WatcherShouldStop',
    'Get-DevServerInstances',
    'Wait-ForRunning',
    'Get-OllamaStatus'
)
