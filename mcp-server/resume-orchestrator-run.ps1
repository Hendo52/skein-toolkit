# Resume a paused_for_oq orchestrator run in a FRESH cline session.
# Usage: mcp-server/resume-orchestrator-run.ps1 -Key <orchestrator-key> [-Model <litellm-model-name>] [-TimeoutSec 600] [-AutoApprove]
#
# CB-9 / OQ-262 Option C:
#   When an orchestrated run pauses on a step-ambiguity OQ (status
#   "paused_for_oq" in ~/.cf_proxy_orchestrator/<key>.json), the architect's
#   "continue" reply normally has to land in the SAME Cline session that
#   raised the OQ -- but that session can be huge (the whole multi-step run's
#   history) and replaying it via `cline --id` is exactly the kind of
#   context-budget blowup CB-9 exists to avoid.
#
#   This script instead asks local-mcp.py to print a short resume prompt
#   (--print-resume-prompt) that embeds an `[orchestrator-key: ...]` marker,
#   and feeds that prompt to a brand-new, non-`--id` run-cline.ps1 session.
#   _orchestrator_key() recognizes the marker and re-derives the SAME run
#   identity, and _handle_orchestrated_request's resume branch treats the
#   marker-bearing fresh session as the architect's "continue" verdict for
#   the paused step, then dispatches the next step as usual.

param(
    [Parameter(Mandatory=$true)]
    [string]$Key,

    [string]$Model,

    [int]$TimeoutSec = 600,

    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = "python"
}

# Reverse of the cf/* entries in mcp-server/litellm_config.yaml -- maps the raw
# "@cf/<vendor>/<name>" string local-mcp.py stores in orchestrator state
# (state["model"], from the proxied request body's "model" field) back to the
# litellm_config.yaml model_name that run-cline.ps1's -Model expects. Keep in
# sync with the cf/* block of mcp-server/litellm_config.yaml.
$cfModelReverseMap = @{
    "@cf/openai/gpt-oss-120b"                  = "cf/gpt-oss-120b"
    "@cf/openai/gpt-oss-20b"                   = "cf/gpt-oss-20b"
    "@cf/qwen/qwen2.5-coder-32b-instruct"      = "cf/qwen2.5-coder:32b"
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast" = "cf/llama3.3:70b"
    "@cf/moonshotai/kimi-k2.6"                 = "cf/kimi-k2.6"
    "@cf/google/gemma-4-26b-a4b-it"            = "cf/gemma-4-26b"
}

$statePath = Join-Path $env:USERPROFILE ".cf_proxy_orchestrator\$Key.json"
if (-not (Test-Path $statePath)) {
    Write-Error "[resume-orchestrator-run] No state file at $statePath"
    exit 1
}
$state = Get-Content $statePath -Raw | ConvertFrom-Json

if (-not $Model) {
    $storedModel = $state.model
    if ($storedModel -and $cfModelReverseMap.ContainsKey($storedModel)) {
        $Model = $cfModelReverseMap[$storedModel]
        Write-Host "[resume-orchestrator-run] Resuming with model '$Model' (from state['model']='$storedModel')"
    } elseif ($storedModel) {
        Write-Error @"
[resume-orchestrator-run] State['model'] = '$storedModel' has no entry in
`$cfModelReverseMap -- pass -Model explicitly with the matching
litellm_config.yaml model_name (e.g. -Model cf/kimi-k2.6).
"@
        exit 1
    } else {
        Write-Error @"
[resume-orchestrator-run] State file $statePath has no 'model' field (it
predates CB-9 resume support) -- pass -Model explicitly, e.g. -Model cf/kimi-k2.6.
"@
        exit 1
    }
}

Write-Host "[resume-orchestrator-run] Run: $Key"
Write-Host "[resume-orchestrator-run] Status: $($state.status)  Step: $($state.current)/$($state.steps.Count)"

$prompt = & $VenvPython (Join-Path $PSScriptRoot "local-mcp.py") --print-resume-prompt $Key
if ($LASTEXITCODE -ne 0) {
    Write-Error "[resume-orchestrator-run] --print-resume-prompt failed (exit $LASTEXITCODE) -- see output above"
    exit $LASTEXITCODE
}

Write-Host "[resume-orchestrator-run] Resume prompt:"
Write-Host "  $prompt"
Write-Host ""

& (Join-Path $PSScriptRoot "run-cline.ps1") -Task $prompt -Model $Model -TimeoutSec $TimeoutSec -AutoApprove:$AutoApprove
exit $LASTEXITCODE
