# Cline CLI launcher with pre-flight checks.
# Usage: mcp-server/run-cline.ps1 -Task "your task here" [-Model "claude/sonnet-4"] [-TimeoutSec 600]
#
# Why this script exists:
#   - Cline defaults to its cloud provider when -P is omitted. The cloud JWT
#     expires hourly and causes silent hangs (0 bytes output, process never exits).
#   - The -k flag routes to Cline cloud auth, NOT the local LiteLLM proxy.
#   - If LiteLLM is not running, Cline fails with a connection error that is easy
#     to misread. The pre-flight check surfaces this immediately.

param(
    [Parameter(Mandatory=$true)]
    [string]$Task,

    [string]$Model = "claude/sonnet-4",

    [int]$TimeoutSec = 600,

    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

# ── Pre-flight 1: full toolchain diagnosis + auto-repair ─────────────────────
# Runs toolchain-doctor.ps1, which checks (and where safe, fixes) LiteLLM,
# local-mcp.py / CF proxy, the Cloudflare API token, and Cline's MCP connection
# to "local-devtools". See mcp-server/toolchain-doctor.ps1 for details.
Write-Host "[run-cline] Pre-flight: running toolchain-doctor.ps1 ..."
$diag = & (Join-Path $PSScriptRoot "toolchain-doctor.ps1")
if (-not $diag.LiteLlmOk) {
    Write-Error @"
[run-cline] FAIL: LiteLLM is not responding at http://localhost:4000/health
and toolchain-doctor.ps1 could not start it. See its output above for the
specific cause and fix.
"@
    exit 1
}
if (-not $diag.LocalMcpOk -or -not $diag.ClineMcpOk) {
    Write-Warning "[run-cline] local-mcp.py / Cline MCP connection still has issues -- see toolchain-doctor.ps1 output above. Continuing anyway (does not block claude/* models)."
}
if (-not $diag.CfTokenOk) {
    Write-Warning "[run-cline] Cloudflare API token check failed -- cf/* models will not work. See toolchain-doctor.ps1 output above. Continuing anyway."
}

# ── Pre-flight 2: provider config ────────────────────────────────────────────
$providersFile = Join-Path $env:USERPROFILE ".cline\data\settings\providers.json"
if (Test-Path $providersFile) {
    $cfg = Get-Content $providersFile -Raw | ConvertFrom-Json
    $last = $cfg.lastUsedProvider
    if ($last -and $last -ne "openai-compatible") {
        Write-Warning @"
[run-cline] WARN: providers.json lastUsedProvider = '$last'.
This script always passes -P openai-compatible, overriding the stored value.
If Cline ignores -P, re-run: npx cline auth openai-compatible --baseurl http://localhost:4000/v1
"@
    } else {
        Write-Host "[run-cline] Provider config OK (openai-compatible)"
    }
} else {
    Write-Warning "[run-cline] WARN: $providersFile not found -- provider API key may not be configured."
}

# ── Run Cline ────────────────────────────────────────────────────────────────
$approveFlag = if ($AutoApprove) { "--auto-approve true" } else { "" }
$startTime   = Get-Date
Write-Host ""
Write-Host "[run-cline] Starting task at $startTime"
Write-Host "[run-cline] Model:   $Model"
Write-Host "[run-cline] Timeout: ${TimeoutSec}s"
Write-Host "[run-cline] Task:    $Task"
Write-Host ""

# The task is piped to Cline via stdin rather than passed as a CLI argument.
# cmd.exe's command-line parsing truncates a multi-line / quote-containing
# argument at the first newline, silently dropping everything after the first
# sentence -- Cline never saw the rest of the task. Cline's CLI reads the full
# prompt from stdin when no TTY is attached and stdin is piped (apps/cli
# main.ts). See foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-
# budget-roadmap.md, 2026-06-11 entry.
$taskFile = [System.IO.Path]::GetTempFileName()
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($taskFile, $Task, $utf8NoBom)

# -P openai-compatible is mandatory -- never rely on the stored lastUsedProvider.
# -k is intentionally omitted: that flag goes to Cline cloud auth, not LiteLLM.
#
# CB-13 (2026-06-12): Start-Process without -WorkingDirectory inherits the
# CALLING process's current location, not this script's own directory. If
# run-cline.ps1 (or a wrapper like resume-orchestrator-run.ps1) is invoked
# from a shell whose cwd is $env:USERPROFILE, the spawned `cline` process's
# process.cwd() is $env:USERPROFILE too, and Cline resolves the task's
# relative file paths (e.g. "foundation/SR-1.4-ai-guidance/docs/...") against
# that -- writing to C:\Users\<user>\foundation\... instead of the repo. Pin
# the working directory to this script's repo root so cline's relative paths
# always resolve against the repo regardless of the caller's cwd.
$repoRoot = Split-Path -Parent $PSScriptRoot
$proc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npx cline -P openai-compatible -m `"$Model`" $approveFlag" `
    -RedirectStandardInput $taskFile `
    -WorkingDirectory $repoRoot `
    -NoNewWindow -PassThru

$finished = $proc.WaitForExit($TimeoutSec * 1000)
$elapsed  = [math]::Round(((Get-Date) - $startTime).TotalSeconds, 1)
Remove-Item $taskFile -ErrorAction SilentlyContinue

if (-not $finished) {
    Write-Warning "[run-cline] TIMEOUT after ${TimeoutSec}s -- killing Cline process (pid $($proc.Id))"
    $proc.Kill()
    Write-Warning "[run-cline] The task was NOT completed. Consider splitting it into smaller steps."
    exit 124
}

$exit = $proc.ExitCode
if ($exit -eq 0) {
    Write-Host "[run-cline] Completed in ${elapsed}s (exit 0)"
} else {
    Write-Warning "[run-cline] Exited with code $exit after ${elapsed}s -- check output above for errors"
}
exit $exit
