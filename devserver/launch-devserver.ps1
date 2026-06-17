#Requires -Version 5.1
# =============================================================================
# launch-devserver.ps1
# Opens VS Code connected to the Vast.ai development server with the repo open.
#
# Usage:
#   Run this script (or use the "Open Dev Server" VS Code task).
#   No manual configuration needed -- IP and port are read live from Vast.ai.
#
# One-time prerequisite:
#   pip install vastai
#   vastai set api-key <your-api-key>   # from https://vast.ai/account/api-keys
#
# What this script does:
#   - Queries the Vast.ai CLI for your running instance IP and port
#   - Loads static config (SSH key, repo path) from devserver.config.ps1
#   - Updates ~/.ssh/config with the current instance IP/port
#   - Tests SSH connectivity
#   - Launches VS Code with the remote repo open via Remote-SSH
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Load static config (key path + repo path only) ---
$configPath = Join-Path $PSScriptRoot "devserver.config.ps1"
if (-not (Test-Path $configPath)) {
    Write-Error "Config file not found: $configPath"
    exit 1
}
. $configPath

if (-not (Test-Path $DevServerKey)) {
    Write-Error @"
SSH key not found: $DevServerKey
Run: ssh-keygen -t ed25519 -f `"`$env:USERPROFILE\.ssh\vast_key`" -C vast-devserver
"@
    exit 1
}

# --- Resolve vastai executable ---
$vastaiExe = Get-Command vastai -ErrorAction SilentlyContinue
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) {
        $vastaiExe = $fallback
    } else {
        Write-Error "vastai not found. Install it: pip install vastai"
        exit 1
    }
} else {
    $vastaiExe = $vastaiExe.Source
}

# --- Auto-detect running instance via Vast.ai CLI ---
Write-Host "Querying Vast.ai for running instances..." -ForegroundColor Cyan

$rawJson = (& $vastaiExe show instances-v1 --raw 2>&1) | Out-String
if ($rawJson -match '401.*Authorization|requires.*2FA|Two Factor') {
    Write-Error @"
Vast.ai requires 2FA authentication. Run one of:
  vastai tfa login --method-type totp   -c <6-digit-code>
  vastai tfa send-sms  then: vastai tfa login --method-type sms   --secret <SECRET> -c <CODE>
  vastai tfa send-email then: vastai tfa login --method-type email --secret <SECRET> -c <CODE>
Then re-run this script.
"@
    exit 1
}
try {
    # -AsHashTable is required: live API response contains "label_counts":{"":1}
    # (empty-string key) which ConvertFrom-Json cannot map to a PSCustomObject.
    $parsed = $rawJson | ConvertFrom-Json -AsHashTable
    $instances = if ($parsed -is [hashtable] -and $parsed.ContainsKey('instances')) { $parsed['instances'] } else { $parsed }
} catch {
    Write-Error "vastai show instances-v1 returned unexpected output:`n$rawJson"
    exit 1
}

$running = @($instances | Where-Object { $_.actual_status -eq 'running' })

if ($running.Count -eq 0) {
    Write-Error "No running Vast.ai instances found. Start your instance at https://vast.ai/console/instances"
    exit 1
}

if ($running.Count -gt 1) {
    Write-Host "Multiple running instances found:" -ForegroundColor Yellow
    $running | ForEach-Object { $i = 0 } { Write-Host "  [$i] ID $($_.id)  $($_.public_ipaddr):$($_.ports.'22/tcp'[0].HostPort)" -ForegroundColor Yellow; $i++ }
    $choice = Read-Host "Enter index to use [0]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = 0 }
    $inst = $running[[int]$choice]
} else {
    $inst = $running[0]
}

$DevServerIP   = $inst.public_ipaddr
$DevServerPort = [int]($inst.ports.'22/tcp'[0].HostPort)
$DevServerUser = "root"

Write-Host "Instance ID $($inst.id): $DevServerIP`:$DevServerPort" -ForegroundColor Green

Write-Host "Dev server: $DevServerUser@$DevServerIP port $DevServerPort" -ForegroundColor Cyan
Write-Host "SSH key:    $DevServerKey" -ForegroundColor Cyan
Write-Host "Repo path:  $DevServerRepo" -ForegroundColor Cyan
Write-Host ""

# --- Update ~/.ssh/config ---
$sshDir        = Join-Path $env:USERPROFILE ".ssh"
$sshConfigPath = Join-Path $sshDir "config"

if (-not (Test-Path $sshDir)) {
    New-Item -ItemType Directory -Path $sshDir | Out-Null
}

# Build the new Host block
$newBlock = @(
    "Host vast-devserver"
    "    HostName $DevServerIP"
    "    Port $DevServerPort"
    "    User $DevServerUser"
    "    IdentityFile $DevServerKey"
    "    StrictHostKeyChecking no"
    "    ServerAliveInterval 60"
    "    ServerAliveCountMax 3"
    "    LocalForward 11434 localhost:11434"
)

if (Test-Path $sshConfigPath) {
    # Read existing config, strip out any old vast-devserver block, append new one
    $lines       = Get-Content $sshConfigPath
    $kept        = [System.Collections.Generic.List[string]]::new()
    $inVastBlock = $false

    foreach ($line in $lines) {
        if ($line -match '^Host\s+vast-devserver\s*$') {
            $inVastBlock = $true
            continue
        }
        if ($inVastBlock -and $line -match '^Host\s+') {
            $inVastBlock = $false
        }
        if (-not $inVastBlock) {
            $kept.Add($line)
        }
    }

    # Remove trailing blank lines then append new block with separator
    while ($kept.Count -gt 0 -and $kept[$kept.Count - 1].Trim() -eq '') {
        $kept.RemoveAt($kept.Count - 1)
    }
    $allLines = @($kept) + @("") + $newBlock
    [System.IO.File]::WriteAllLines($sshConfigPath, $allLines)
    Write-Host "Updated ~/.ssh/config: vast-devserver -> $DevServerIP`:$DevServerPort" -ForegroundColor Green
} else {
    [System.IO.File]::WriteAllLines($sshConfigPath, $newBlock)
    Write-Host "Created ~/.ssh/config with vast-devserver entry" -ForegroundColor Green
}

# --- Test SSH connectivity ---
Write-Host ""
Write-Host "Testing SSH connectivity (timeout 10s)..." -ForegroundColor Yellow
try {
    $testOutput = & ssh -o ConnectTimeout=10 -o BatchMode=yes `
        -p $DevServerPort `
        -i $DevServerKey `
        "${DevServerUser}@${DevServerIP}" `
        "echo CONNECTED" 2>&1

    if ($testOutput -match "CONNECTED") {
        Write-Host "SSH connection OK" -ForegroundColor Green
    } else {
        Write-Warning "SSH test did not return expected output. Output: $testOutput"
        Write-Warning "Attempting to open VS Code anyway -- the Remote-SSH extension will prompt if needed."
    }
} catch {
    Write-Warning "SSH connectivity test failed: $_"
    Write-Warning "Attempting to open VS Code anyway -- the Remote-SSH extension will prompt if needed."
}

# --- Launch VS Code Remote-SSH ---
Write-Host ""
Write-Host "Opening VS Code -> vast-devserver:$DevServerRepo ..." -ForegroundColor Cyan

$remoteUri = "vscode-remote://ssh-remote+vast-devserver$DevServerRepo"
& code --folder-uri $remoteUri

if ($LASTEXITCODE -ne 0) {
    Write-Error "VS Code launch failed (exit code $LASTEXITCODE). Is 'code' in your PATH?"
}

Write-Host ""
Write-Host "VS Code is connecting. Once Remote-SSH is established, run:" -ForegroundColor Cyan
Write-Host "  Task: 'Check Dev Server Health'  (verifies the Ollama tunnel)" -ForegroundColor Cyan
Write-Host "  Or:   scripts\check-devserver.ps1" -ForegroundColor Cyan
Write-Host ""

# --- Start safety watcher in a new visible terminal ---
# The watcher polls Ollama idle status and stops the instance automatically
# when it has been idle, or when the session/spend hard caps are reached.
# Vast.ai auto-tops-up without confirmation, so this is the circuit breaker.
$watcherScript = Join-Path $PSScriptRoot 'watch-devserver.ps1'
$watcherArgs   = "-NoProfile -NoExit -File `"$watcherScript`"" +
                 " -InstanceId $($inst.id)" +
                 " -HourlyRate $($inst.dph_total)" +
                 " -IdleMinutes $WatchIdleMinutes" +
                 " -MaxSessionHours $WatchMaxSessionHours" +
                 " -MaxSpendUsd $WatchMaxSpendUsd" +
                 " -BatchFilePath `"$BatchFilePath`""

Write-Host "Starting safety watcher (idle: ${WatchIdleMinutes}min, cap: ${WatchMaxSessionHours}hr / `$$WatchMaxSpendUsd)..." -ForegroundColor Cyan
Start-Process pwsh -ArgumentList $watcherArgs -WindowStyle Normal
Write-Host "Watcher running in separate window. It will stop the instance when limits are reached." -ForegroundColor Green
