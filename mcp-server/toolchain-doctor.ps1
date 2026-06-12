#Requires -Version 5.1
# =============================================================================
# toolchain-doctor.ps1
#
# Diagnoses and (by default) repairs the AI agentic toolchain:
#
#   Cline (VS Code extension)
#     -> LiteLLM unified proxy            (port 4000)
#          -> local-mcp.py CF proxy       (port 3100, /cfproxy/...)
#               -> Cloudflare Workers AI  (cf/* models)
#     -> local-mcp.py MCP SSE server      (port 3100, /sse, "local-devtools")
#
# Each check reports: what's wrong, why, and the fix. With auto-fix enabled
# (the default), known-safe fixes are applied automatically:
#   - LiteLLM not running            -> start it (background, logs to ~/.litellm)
#   - local-mcp.py not running       -> start it (background, logs to cf_proxy_live.log)
#   - Cline stuck disconnected from "local-devtools" after a server restart
#     race -> nudge Cline's MCP config-file watcher to reconnect
#
# Fixes that require human action (new Cloudflare token, etc.) are reported
# with explicit step-by-step instructions, never guessed at.
#
# Usage:
#   mcp-server\toolchain-doctor.ps1                # diagnose + auto-fix
#   mcp-server\toolchain-doctor.ps1 -DiagnoseOnly  # report only, change nothing
# =============================================================================

[CmdletBinding()]
param(
    [switch]$DiagnoseOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Fix = -not $DiagnoseOnly

$RepoRoot       = Split-Path -Parent $PSScriptRoot
$EnvFile        = Join-Path $PSScriptRoot "litellm.env"
$ConfigFile     = Join-Path $PSScriptRoot "litellm_config.yaml"
$VenvPython     = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalMcpScript = Join-Path $PSScriptRoot "local-mcp.py"
$LiteLlmLogDir  = Join-Path $env:USERPROFILE ".litellm"
$ClineSettings  = Join-Path $env:APPDATA "Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json"

Write-Host ""
Write-Host "AI Toolchain Doctor" -ForegroundColor Cyan
Write-Host "===================" -ForegroundColor Cyan
if ($DiagnoseOnly) {
    Write-Host "(diagnose-only mode -- no changes will be made)" -ForegroundColor DarkGray
}

$litellmOk = $false
$mcpOk     = $false
$cfOk      = $false
$clineOk   = $false

function Test-LiteLlmHealth {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:4000/health" -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        if ($_ -match "401|Unauthorized|Authentication") { return $true }
        return $false
    }
}

# ── Check 1: LiteLLM proxy (port 4000) ───────────────────────────────────────
Write-Host ""
Write-Host "[1/5] LiteLLM unified proxy (port 4000) ..." -ForegroundColor Yellow
if (Test-LiteLlmHealth) {
    Write-Host "  OK - LiteLLM is responding." -ForegroundColor Green
    $litellmOk = $true
} else {
    Write-Host "  PROBLEM: LiteLLM is not responding on http://127.0.0.1:4000." -ForegroundColor Red
    Write-Host "  Cause:   the LiteLLM proxy process is not running." -ForegroundColor Yellow
    Write-Host "  Impact:  Cline (and any cf/local/claude/* model in litellm_config.yaml) cannot reach any model." -ForegroundColor Yellow
    if ($Fix) {
        Write-Host "  Fix: starting LiteLLM in the background ..." -ForegroundColor Cyan
        if (-not (Test-Path $EnvFile)) {
            Write-Host "  FIX FAILED: $EnvFile not found -- copy mcp-server\litellm.env.example and fill in values." -ForegroundColor Red
        } else {
            Get-Content $EnvFile | Where-Object { $_ -match '^\s*[A-Z_]+=.+' } | ForEach-Object {
                $k, $v = $_ -split '=', 2
                [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
            }
            if (-not (Test-Path $LiteLlmLogDir)) { New-Item -ItemType Directory -Force $LiteLlmLogDir | Out-Null }
            $outLog = Join-Path $LiteLlmLogDir "doctor-restart.out.log"
            $errLog = Join-Path $LiteLlmLogDir "doctor-restart.err.log"
            $env:PYTHONIOENCODING = "utf-8"
            Start-Process -FilePath "litellm" -ArgumentList "--config", "`"$ConfigFile`"", "--port", "4000" `
                -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-Date) -lt $deadline -and -not $litellmOk) {
                Start-Sleep -Seconds 2
                if (Test-LiteLlmHealth) { $litellmOk = $true }
            }
            if ($litellmOk) {
                Write-Host "  FIXED - LiteLLM is now up. Logs: $outLog / $errLog" -ForegroundColor Green
            } else {
                Write-Host "  FIX FAILED - LiteLLM still not responding after 30s." -ForegroundColor Red
                Write-Host "  Check: $errLog" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "  Fix: mcp-server\start-litellm.ps1" -ForegroundColor Cyan
    }
}

# ── Check 2: local-mcp.py / CF proxy + MCP SSE (port 3100) ───────────────────
Write-Host ""
Write-Host "[2/5] local-mcp.py -- CF proxy + MCP SSE server (port 3100) ..." -ForegroundColor Yellow

function Test-LocalMcpSse {
    $headers = & curl.exe -sS -D - -o NUL --max-time 3 "http://127.0.0.1:3100/sse" 2>$null
    return ($headers -match "(?i)content-type:\s*text/event-stream")
}

$listening = Get-NetTCPConnection -LocalPort 3100 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Write-Host "  PROBLEM: nothing is listening on port 3100." -ForegroundColor Red
    Write-Host "  Cause:   local-mcp.py is not running (the 'Local MCP Server' VS Code debug session is stopped, or was never started)." -ForegroundColor Yellow
    Write-Host "  Impact:  Cline's 'local-devtools' MCP tools AND all cf/* models (LiteLLM routes them through this proxy) will fail." -ForegroundColor Yellow
    if ($Fix) {
        if (-not (Test-Path $VenvPython)) {
            Write-Host "  FIX FAILED: $VenvPython not found." -ForegroundColor Red
        } else {
            Write-Host "  Fix: starting local-mcp.py as a background process ..." -ForegroundColor Cyan
            Write-Host "  Note: this is a plain background process, not the VS Code debugger -- code edits to" -ForegroundColor DarkGray
            Write-Host "        local-mcp.py still require restarting via the 'Local MCP Server' debug config." -ForegroundColor DarkGray
            $outLog = Join-Path $RepoRoot "cf_proxy_live.log"
            $errLog = Join-Path $RepoRoot "cf_proxy_live.err.log"
            Start-Process -FilePath $VenvPython -ArgumentList "`"$LocalMcpScript`"" -WorkingDirectory $RepoRoot `
                -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog

            $deadline = (Get-Date).AddSeconds(20)
            while ((Get-Date) -lt $deadline -and -not $mcpOk) {
                Start-Sleep -Seconds 2
                if ((Get-NetTCPConnection -LocalPort 3100 -State Listen -ErrorAction SilentlyContinue) -and (Test-LocalMcpSse)) {
                    $mcpOk = $true
                }
            }
            if ($mcpOk) {
                Write-Host "  FIXED - local-mcp.py is up and /sse responds. Logs: $outLog / $errLog" -ForegroundColor Green
            } else {
                Write-Host "  FIX FAILED - port 3100 still not serving /sse after 20s." -ForegroundColor Red
                Write-Host "  Check: $errLog" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "  Fix: in VS Code, Run and Debug -> 'Local MCP Server' (F5)" -ForegroundColor Cyan
        Write-Host "       or:  .venv\Scripts\python.exe mcp-server\local-mcp.py" -ForegroundColor Cyan
    }
} elseif (Test-LocalMcpSse) {
    Write-Host "  OK - local-mcp.py is up and /sse responds correctly." -ForegroundColor Green
    $mcpOk = $true
} else {
    $ownerPid = $listening[0].OwningProcess
    $procCmd  = (Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue).CommandLine
    Write-Host "  PROBLEM: port 3100 is in use by PID $ownerPid, but /sse did not return text/event-stream." -ForegroundColor Red
    Write-Host "  Process: $procCmd" -ForegroundColor Yellow
    Write-Host "  Cause:   a different or stuck process is holding port 3100, so local-mcp.py cannot bind to it." -ForegroundColor Yellow
    Write-Host "  Fix: Stop-Process -Id $ownerPid -Force, then restart 'Local MCP Server' in VS Code (F5)." -ForegroundColor Cyan
}

# ── Check 3: Cloudflare API token (cf/* models) ──────────────────────────────
Write-Host ""
Write-Host "[3/5] Cloudflare API token (cf/* models) ..." -ForegroundColor Yellow
if (-not (Test-Path $EnvFile)) {
    Write-Host "  SKIPPED: $EnvFile not found." -ForegroundColor Yellow
} else {
    $cfKeyLine = Get-Content $EnvFile | Where-Object { $_ -match '^CF_API_KEY=' } | Select-Object -First 1
    $cfKey = if ($cfKeyLine) { ($cfKeyLine -replace '^CF_API_KEY=', '').Trim() } else { "" }
    if (-not $cfKey) {
        Write-Host "  SKIPPED: CF_API_KEY is empty in $EnvFile." -ForegroundColor Yellow
    } else {
        try {
            $resp = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/user/tokens/verify" `
                -Headers @{ Authorization = "Bearer $cfKey" } -TimeoutSec 8 -ErrorAction Stop
            if ($resp.success -and $resp.result.status -eq "active") {
                Write-Host "  OK - Cloudflare API token is active." -ForegroundColor Green
                $cfOk = $true
            } else {
                Write-Host "  PROBLEM: Cloudflare token verify returned status '$($resp.result.status)'." -ForegroundColor Red
                Write-Host "  Fix: create a new token at https://dash.cloudflare.com/profile/api-tokens and update CF_API_KEY in $EnvFile." -ForegroundColor Cyan
            }
        } catch {
            $code = $_.Exception.Response?.StatusCode.value__
            Write-Host "  PROBLEM: Cloudflare token verification failed (HTTP $code)." -ForegroundColor Red
            Write-Host "  Cause:   the token is invalid/revoked, OR its 'Client IP Address Filtering' is blocking your current IP." -ForegroundColor Yellow
            try {
                $myIp = (Invoke-RestMethod -Uri "https://api.ipify.org?format=json" -TimeoutSec 5 -ErrorAction Stop).ip
                Write-Host "  Your current public IP: $myIp (check this against the token's IP filter rules)" -ForegroundColor Yellow
            } catch {
                Write-Host "  (Could not determine your current public IP.)" -ForegroundColor DarkGray
            }
            Write-Host "  Fix (requires Cloudflare dashboard -- no safe auto-fix):" -ForegroundColor Cyan
            Write-Host "    1. https://dash.cloudflare.com/profile/api-tokens" -ForegroundColor Cyan
            Write-Host "    2. Create a new token with NO IP filter (CF rejects 0.0.0.0/0 as a no-op CIDR)." -ForegroundColor Cyan
            Write-Host "    3. Update CF_API_KEY in $EnvFile, then re-run this script to restart LiteLLM." -ForegroundColor Cyan
        }
    }
}

# ── Check 4: Cline <-> "local-devtools" MCP connection ───────────────────────
Write-Host ""
Write-Host "[4/5] Cline <-> 'local-devtools' MCP connection ..." -ForegroundColor Yellow

$logsRoot = Join-Path $env:APPDATA "Code\logs"
$clineLog = $null
if (Test-Path $logsRoot) {
    $recentLogDirs = Get-ChildItem $logsRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 3
    $clineLog = $recentLogDirs |
        ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter "*-Cline.log" -ErrorAction SilentlyContinue } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

if (-not $clineLog) {
    Write-Host "  SKIPPED: no Cline extension log found (Cline may not have run in this VS Code session yet)." -ForegroundColor Yellow
} elseif (-not $mcpOk) {
    Write-Host "  SKIPPED: local-mcp.py is not healthy (see check 2 above) -- fix that first, then re-run this script." -ForegroundColor Yellow
} else {
    $lines = Get-Content $clineLog.FullName
    $lastEvent = $lines | Select-String "local-devtools" | Select-Object -Last 1
    $failuresBefore = ($lines | Select-String 'Failed to connect to new MCP server local-devtools|Transport error for "local-devtools"').Count

    if (-not $lastEvent) {
        Write-Host "  UNKNOWN: no 'local-devtools' activity found in the current Cline log." -ForegroundColor Yellow
        Write-Host "  (This is normal if Cline hasn't loaded its MCP servers yet in this session.)" -ForegroundColor DarkGray
    } elseif ($lastEvent.Line -notmatch 'Failed to connect|Transport error') {
        Write-Host "  OK - last 'local-devtools' MCP event was a successful (re)connect." -ForegroundColor Green
        $clineOk = $true
    } else {
        Write-Host "  PROBLEM: Cline's last attempt to connect to 'local-devtools' failed, and Cline does not auto-retry." -ForegroundColor Red
        Write-Host "  Cause:   usually a startup race -- the VS Code window reloaded before local-mcp.py finished (re)starting." -ForegroundColor Yellow
        if ($Fix) {
            if (-not (Test-Path $ClineSettings)) {
                Write-Host "  FIX FAILED: $ClineSettings not found." -ForegroundColor Red
            } else {
                Write-Host "  Fix: nudging Cline to reconnect (toggling cline_mcp_settings.json) ..." -ForegroundColor Cyan
                $cfg = Get-Content $ClineSettings -Raw | ConvertFrom-Json
                $cfg.mcpServers.'local-devtools'.disabled = $true
                $cfg | ConvertTo-Json -Depth 10 | Set-Content $ClineSettings -Encoding utf8
                Start-Sleep -Seconds 1
                $cfg.mcpServers.'local-devtools'.disabled = $false
                $cfg | ConvertTo-Json -Depth 10 | Set-Content $ClineSettings -Encoding utf8
                Start-Sleep -Seconds 2

                $newLines = Get-Content $clineLog.FullName
                $failuresAfter = ($newLines | Select-String 'Failed to connect to new MCP server local-devtools|Transport error for "local-devtools"').Count
                $reconnected   = $newLines | Select-String 'Reconnected MCP server with updated config: local-devtools'

                if ($reconnected -and $failuresAfter -eq $failuresBefore) {
                    Write-Host "  FIXED - Cline reconnected to local-devtools (no new transport errors)." -ForegroundColor Green
                    $clineOk = $true
                } else {
                    Write-Host "  Reconnect attempted but could not be confirmed -- check Cline's MCP Servers panel." -ForegroundColor Yellow
                }
            }
        } else {
            Write-Host "  Fix: in Cline's MCP Servers panel, click restart on 'local-devtools' (server is healthy now -- a Reload Window would also work)." -ForegroundColor Cyan
        }
    }
}

# ── Check 5: Cline provider config ───────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Cline provider config ..." -ForegroundColor Yellow
$providersFile = Join-Path $env:USERPROFILE ".cline\data\settings\providers.json"
if (-not (Test-Path $providersFile)) {
    Write-Host "  SKIPPED: $providersFile not found." -ForegroundColor Yellow
} else {
    $cfg = Get-Content $providersFile -Raw | ConvertFrom-Json
    if ($cfg.lastUsedProvider -eq "openai-compatible") {
        Write-Host "  OK - lastUsedProvider = openai-compatible" -ForegroundColor Green
    } else {
        Write-Host "  NOTE: lastUsedProvider = '$($cfg.lastUsedProvider)' (Cline cloud -- hourly JWT expiry, silent hangs when expired)." -ForegroundColor Yellow
        Write-Host "  Fix: run-cline.ps1 always passes -P openai-compatible, overriding this. Only matters if invoking 'cline' directly without -P." -ForegroundColor Cyan
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "===================" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "  LiteLLM (4000):          $(if ($litellmOk) { 'OK' } else { 'PROBLEM' })" -ForegroundColor $(if ($litellmOk) { 'Green' } else { 'Red' })
Write-Host "  local-mcp.py (3100):     $(if ($mcpOk) { 'OK' } else { 'PROBLEM' })" -ForegroundColor $(if ($mcpOk) { 'Green' } else { 'Red' })
Write-Host "  Cloudflare token:        $(if ($cfOk) { 'OK' } else { 'PROBLEM' })" -ForegroundColor $(if ($cfOk) { 'Green' } else { 'Red' })
Write-Host "  Cline MCP connection:    $(if ($clineOk) { 'OK' } else { 'PROBLEM' })" -ForegroundColor $(if ($clineOk) { 'Green' } else { 'Red' })
Write-Host ""

# Emitted on the success stream so callers (e.g. run-cline.ps1) can inspect
# results via: $diag = & toolchain-doctor.ps1
[PSCustomObject]@{
    LiteLlmOk = $litellmOk
    LocalMcpOk = $mcpOk
    CfTokenOk = $cfOk
    ClineMcpOk = $clineOk
}
