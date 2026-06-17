# Start the LiteLLM unified proxy (port 4000).
# Reads credentials from mcp-server/litellm.env (gitignored, copy from litellm.env.example).
# Dashboard: http://localhost:4000/ui

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$EnvFile = Join-Path $ScriptDir "litellm.env"
$ConfigFile = Join-Path $ScriptDir "litellm_config.yaml"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Missing $EnvFile -- copy mcp-server/litellm.env.example and fill in values."
    exit 1
}

# Load env file into process environment
Get-Content $EnvFile | Where-Object { $_ -match '^\s*[A-Z_]+=.+' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}

# Cost log — one JSON record per request, persists across restarts
$LogDir = Join-Path $env:USERPROFILE ".litellm"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
$CostLog = Join-Path $LogDir "costs.jsonl"

Write-Host "Starting LiteLLM proxy on http://localhost:4000"
Write-Host "Dashboard:  http://localhost:4000/ui"
Write-Host "Spend API:  http://localhost:4000/spend/calculate"
Write-Host "Cost log:   $CostLog"
Write-Host "Config:     $ConfigFile"

# Force UTF-8 so LiteLLM's Unicode banner renders correctly in PS5.1 console
chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Start LiteLLM in a background job so we can health-check it before attaching.
Write-Host "Waiting for LiteLLM to bind on port 4000 ..."
$job = Start-Job -ScriptBlock {
    param($cfg, $log)
    $env:PYTHONIOENCODING = "utf-8"
    $ErrorActionPreference = "SilentlyContinue"  # suppress PS5.1 NativeCommandError on litellm stderr
    litellm --config $cfg --port 4000 2>&1 | Tee-Object -Append -FilePath $log
} -ArgumentList $ConfigFile, $CostLog

# Poll /health for up to 30 seconds.
$deadline = (Get-Date).AddSeconds(30)
$healthy  = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 1500
    Receive-Job $job -ErrorAction SilentlyContinue  # drain output so startup errors appear
    if ($job.State -eq "Failed" -or $job.State -eq "Completed") {
        Write-Error "[start-litellm] LiteLLM process exited unexpectedly. Check $CostLog for details."
        exit 1
    }
    try {
        # Use 127.0.0.1, not localhost: on this machine .NET's HttpClient tries
        # the IPv6 ::1 candidate for "localhost" first and stalls for ~2s before
        # falling back to IPv4, which spuriously trips the -TimeoutSec below and
        # throws TaskCanceledException instead of the expected 401 response.
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:4000/health" -TimeoutSec 3 -ErrorAction Stop
        $statusStr = 'ok'
        if ($null -ne $r.status) { $statusStr = $r.status }
        Write-Host "[start-litellm] LiteLLM is up (status: $statusStr)"
        $healthy = $true
        break
    } catch {
        # A 401 means auth is required -- the server IS running.
        if ($_ -match "401" -or $_ -match "Unauthorized" -or $_ -match "Authentication") {
            Write-Host "[start-litellm] LiteLLM is up (auth-protected)"
            $healthy = $true
            break
        } elseif ($_.Exception -is [System.Threading.Tasks.TaskCanceledException]) {
            Write-Host "[start-litellm] /health timed out -- not ready yet, retrying ..."
        } else {
            Write-Host "[start-litellm] /health check failed ($($_.Exception.GetType().Name): $($_.Exception.Message)) -- not ready yet, retrying ..."
        }
    }
}

if (-not $healthy) {
    Write-Error "[start-litellm] LiteLLM did not respond to /health within 30 seconds. Check $CostLog for startup errors."
    Stop-Job $job
    Remove-Job $job
    exit 1
}

Write-Host "Run  mcp-server\run-cline.ps1 -Task '...'  to launch Cline with pre-flight checks."

# Attach to the job and stream remaining output to the console.
Receive-Job $job -Wait -AutoRemoveJob
