#Requires -Version 5.1
# =============================================================================
# chat-devserver.ps1
# Opens a local VS Code window with Continue.dev wired to the Ollama service
# running on the Vast.ai dev server.
#
# Usage:
#   Run this script (or use the "Chat Dev Server" VS Code task).
#   The dev server instance must already be running (use "Rent Dev Server" first).
#
# How it works:
#   - Queries the running Vast.ai instance for the SSH host alias
#   - Opens an SSH tunnel: localhost:11434 -> remote:11434
#     (Continue.dev config already points to localhost:11434 -- no config changes needed)
#   - Opens a local VS Code window so Continue.dev chat is available
#   - Keeps the tunnel alive; Ctrl+C or closing the terminal tears it down
#
# One-time prerequisite:
#   Run "Open Dev Server" at least once first -- that step writes the
#   vast-devserver entry in ~/.ssh/config which this script reuses.
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Load static config ---
$configPath = Join-Path $PSScriptRoot "devserver.config.ps1"
if (-not (Test-Path $configPath)) {
    Write-Error "Config file not found: $configPath"
    exit 1
}
. $configPath

if (-not (Test-Path $DevServerKey)) {
    Write-Error "SSH key not found: $DevServerKey`nRun 'Open Dev Server' first to provision the key."
    exit 1
}

# --- Resolve vastai executable ---
$vastaiExe = Get-Command vastai -ErrorAction SilentlyContinue
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { $vastaiExe = $fallback }
    else {
        Write-Error "vastai not found. Install it: pip install vastai"
        exit 1
    }
} else { $vastaiExe = $vastaiExe.Source }

# --- Find running instance ---
Write-Host "Querying Vast.ai for running instances..." -ForegroundColor Cyan

$rawJson = (& $vastaiExe show instances-v1 --raw 2>&1) | Out-String
if ($rawJson -match '401.*Authorization|requires.*2FA|Two Factor') {
    Write-Error "Vast.ai requires 2FA. Run: vastai tfa login --method-type totp -c <code>"
    exit 1
}

try {
    $parsed    = $rawJson | ConvertFrom-Json -AsHashTable
    $instances = if ($parsed -is [hashtable] -and $parsed.ContainsKey('instances')) { $parsed['instances'] } else { $parsed }
} catch {
    Write-Error "Could not parse Vast.ai instance list: $_"
    exit 1
}

$running = @($instances | Where-Object { $_.actual_status -eq 'running' })

if ($running.Count -eq 0) {
    Write-Error @"
No running Vast.ai instances found.
Start one first via the 'Rent Dev Server' task, then run this script again.
"@
    exit 1
}

if ($running.Count -gt 1) {
    Write-Host "Multiple running instances found:" -ForegroundColor Yellow
    for ($i = 0; $i -lt $running.Count; $i++) {
        Write-Host "  [$i] ID $($running[$i].id)  $($running[$i].gpu_name)  $($running[$i].geolocation)" -ForegroundColor Yellow
    }
    $choice = Read-Host "Enter index to use [0]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = 0 }
    $inst = $running[[int]$choice]
} else {
    $inst = $running[0]
}

$sshPort = [int]($inst.ports.'22/tcp'[0].HostPort)
$instIp  = $inst.public_ipaddr
$instId  = $inst.id

Write-Host "Instance ID $instId : $instIp port $sshPort  ($($inst.gpu_name), $($inst.geolocation))" -ForegroundColor Green

# --- Ensure vast-devserver is in ~/.ssh/config ---
# (Reuses the same entry written by launch-devserver.ps1)
$sshDir        = Join-Path $env:USERPROFILE ".ssh"
$sshConfigPath = Join-Path $sshDir "config"

if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }

$marker      = "# vast-devserver-start"
$markerEnd   = "# vast-devserver-end"
$sshEntry    = @"
$marker
Host vast-devserver
    HostName $instIp
    Port $sshPort
    User root
    IdentityFile $DevServerKey
    StrictHostKeyChecking no
    UserKnownHostsFile NUL
$markerEnd
"@

if (Test-Path $sshConfigPath) {
    $existing = Get-Content $sshConfigPath -Raw
    if ($existing -match [regex]::Escape($marker)) {
        # Replace the existing block
        $existing = $existing -replace "(?s)$([regex]::Escape($marker)).*?$([regex]::Escape($markerEnd))", $sshEntry.Trim()
        Set-Content $sshConfigPath $existing -NoNewline
    } else {
        Add-Content $sshConfigPath "`n$sshEntry"
    }
} else {
    Set-Content $sshConfigPath $sshEntry
}

Write-Host "Updated ~/.ssh/config: vast-devserver -> ${instIp}:${sshPort}" -ForegroundColor Cyan

# --- Check Ollama is reachable via SSH ---
Write-Host "Checking Ollama is reachable on the instance..." -ForegroundColor Cyan
$ollamaTags = ssh -i $DevServerKey `
    -o StrictHostKeyChecking=no `
    -o UserKnownHostsFile=NUL `
    -p $sshPort root@$instIp `
    "curl -s --max-time 5 http://localhost:11434/api/tags 2>/dev/null || echo UNREACHABLE" 2>$null

if ($ollamaTags -match 'UNREACHABLE' -or [string]::IsNullOrWhiteSpace($ollamaTags)) {
    Write-Warning "Ollama did not respond on the instance. It may still be starting up."
    Write-Warning "The tunnel will open anyway -- models will appear once Ollama is ready."
} else {
    try {
        $tags = $ollamaTags | ConvertFrom-Json -AsHashTable
        $models = @($tags['models'] | ForEach-Object { $_['name'] })
        if ($models.Count -gt 0) {
            Write-Host "Available models on this instance:" -ForegroundColor Green
            $models | ForEach-Object { Write-Host "  - $_" -ForegroundColor Green }
        } else {
            Write-Warning "Ollama is running but no models are loaded yet."
            Write-Warning "Pull a model on the instance: ssh vast-devserver 'ollama pull llama3.3:70b'"
        }
    } catch {
        Write-Warning "Could not parse model list (Ollama may be starting up)."
    }
}

# --- Open local VS Code window ---
Write-Host ""
Write-Host "Opening local VS Code window..." -ForegroundColor Cyan
$codeExe = Get-Command code -ErrorAction SilentlyContinue
if (-not $codeExe) {
    Write-Warning "VS Code 'code' command not found in PATH. Open VS Code manually."
} else {
    # Open in a new local window at the repo root so Continue.dev is available
    & code --new-window (Split-Path $PSScriptRoot -Parent) 2>$null
    Write-Host "VS Code opened. Use the Continue.dev sidebar (Ctrl+Shift+I) to chat." -ForegroundColor Green
}

# --- Start SSH tunnel: localhost:11434 -> remote:11434 ---
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Ollama SSH Tunnel" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Forwarding : localhost:11434 -> vast-devserver:11434" -ForegroundColor Cyan
Write-Host " Continue.dev config already points to localhost:11434" -ForegroundColor Cyan
Write-Host " Press Ctrl+C to close the tunnel and disconnect." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

try {
    # -N: no remote command (tunnel only)
    # -L: local port forward
    # ServerAliveInterval keeps the tunnel alive during long conversations
    ssh -N `
        -L 11434:localhost:11434 `
        -i $DevServerKey `
        -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL `
        -o ServerAliveInterval=30 `
        -o ServerAliveCountMax=6 `
        -p $sshPort `
        root@$instIp
} finally {
    Write-Host ""
    Write-Host "Tunnel closed." -ForegroundColor Yellow
}
