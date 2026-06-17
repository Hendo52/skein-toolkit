#Requires -Version 5.1
# =============================================================================
# check-devserver.ps1
# Verifies that the dev server SSH tunnels are alive and Ollama is responding.
#
# Run this after rent-devserver.ps1 opens VS Code to confirm the inference
# tunnel is working before starting a session.
#
# Usage:
#   scripts\check-devserver.ps1
#   Or: VS Code task "Check Dev Server Health"
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$configPath = Join-Path $PSScriptRoot 'devserver.config.ps1'
if (Test-Path $configPath) { . $configPath }

# rent-devserver.ps1 tunnels Ollama to 11435 (not 11434) to avoid conflicting
# with any local Ollama install that may be running on the standard port.
$OllamaUrl = "http://localhost:11435"
$McpUrl    = "http://localhost:$DevServerMcpTunnelPort/sse"
$ok = $true

Write-Host ""
Write-Host "Dev Server Health Check" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan

# --- Check 1: Ollama API reachable via tunnel ---
Write-Host ""
Write-Host "[1/3] Checking Ollama tunnel (localhost:11435)..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 5 -ErrorAction Stop
    $modelCount = $response.models.Count
    Write-Host "  Ollama is reachable. Version: $($(Invoke-RestMethod -Uri "$OllamaUrl/api/version" -TimeoutSec 5 -ErrorAction SilentlyContinue).version)" -ForegroundColor Green
    Write-Host "  Models available: $modelCount" -ForegroundColor Green
    if ($modelCount -gt 0) {
        foreach ($m in $response.models) {
            $sizeGb = [math]::Round($m.size / 1GB, 1)
            Write-Host "    - $($m.name)  ($sizeGb GB)" -ForegroundColor Gray
        }
    } else {
        Write-Host "  WARNING: No models pulled yet on the remote." -ForegroundColor Yellow
        Write-Host "  SSH in and pull a model:" -ForegroundColor Yellow
        Write-Host "    ssh vast-devserver 'ollama pull qwen2.5-coder:7b'" -ForegroundColor Yellow
        $ok = $false
    }
} catch {
    Write-Host "  FAILED: Cannot reach localhost:11435" -ForegroundColor Red
    Write-Host "  Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Most likely causes:" -ForegroundColor Yellow
    Write-Host "    1. The SSH tunnel process was closed." -ForegroundColor Yellow
    Write-Host "       Fix: re-run rent-devserver.ps1 (already running instance) or restart tunnels manually:" -ForegroundColor Yellow
    Write-Host "         Start-Process ssh -ArgumentList '-N','-L','11435:localhost:11434','vast-devserver' -WindowStyle Hidden" -ForegroundColor Gray
    Write-Host "    2. Ollama is not running on the remote." -ForegroundColor Yellow
    Write-Host "       Fix: ssh vast-devserver 'OLLAMA_KEEP_ALIVE=-1 nohup ollama serve > /tmp/ollama.log 2>&1 &'" -ForegroundColor Yellow
    $ok = $false
}

# --- Check 2: MCP server reachable ---
Write-Host ""
Write-Host "[2/3] Checking MCP server tunnel (localhost:$DevServerMcpTunnelPort)..." -ForegroundColor Yellow
try {
    # SSE endpoint returns a stream; just verify it accepts the connection (200/non-error)
    $mcpResp = Invoke-WebRequest -Uri $McpUrl -TimeoutSec 3 -ErrorAction Stop -Method Get
    Write-Host "  MCP server reachable (HTTP $($mcpResp.StatusCode))." -ForegroundColor Green
} catch {
    $code = $_.Exception.Response?.StatusCode.value__
    if ($code -and $code -lt 500) {
        Write-Host "  MCP server reachable (HTTP $code)." -ForegroundColor Green
    } else {
        Write-Host "  WARNING: MCP server unreachable on localhost:$DevServerMcpTunnelPort." -ForegroundColor Yellow
        Write-Host "  Coding agent tools (create_test, run_shell, etc.) will not work." -ForegroundColor Yellow
        Write-Host "  Fix: check tunnel and MCP process on remote:" -ForegroundColor Yellow
        Write-Host "    ssh vast-devserver 'ss -tlnp | grep 3100'" -ForegroundColor Gray
        Write-Host "    Start-Process ssh -ArgumentList '-N','-L','${DevServerMcpTunnelPort}:localhost:3100','vast-devserver' -WindowStyle Hidden" -ForegroundColor Gray
        $ok = $false
    }
}

# --- Check 3: SSH direct check of Ollama process on remote ---
Write-Host ""
Write-Host "[3/3] Checking Ollama process on remote via SSH..." -ForegroundColor Yellow
try {
    $sshResult = & ssh -o ConnectTimeout=8 -o BatchMode=yes vast-devserver `
        "pgrep -a ollama | grep 'ollama serve' | head -1; free -h | grep Mem" 2>&1 | Out-String
    if ($sshResult -match 'ollama') {
        Write-Host "  SSH OK. Ollama process running." -ForegroundColor Green
        $memLine = ($sshResult -split '\r?\n' | Where-Object { $_ -match '^Mem:' } | Select-Object -First 1)
        if ($memLine) { Write-Host "  Memory: $memLine" -ForegroundColor Gray }
    } else {
        Write-Host "  SSH OK but Ollama process not found." -ForegroundColor Red
        Write-Host "  Fix: ssh vast-devserver 'OLLAMA_KEEP_ALIVE=-1 nohup ollama serve > /tmp/ollama.log 2>&1 &'" -ForegroundColor Yellow
        $ok = $false
    }
} catch {
    Write-Host "  SSH check failed: $_" -ForegroundColor Red
    Write-Host "  (Make sure 'vast-devserver' is in ~/.ssh/config -- run rent-devserver.ps1 first.)" -ForegroundColor Gray
}

# --- Summary ---
Write-Host ""
if ($ok) {
    Write-Host "All checks passed. Inference tunnel is ready." -ForegroundColor Green
} else {
    Write-Host "One or more checks failed. See details above." -ForegroundColor Red
}
Write-Host ""
