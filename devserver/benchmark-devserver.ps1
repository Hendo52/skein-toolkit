#Requires -Version 5.1
# =============================================================================
# benchmark-devserver.ps1
# Benchmarks Ollama performance on the dev server and checks/applies
# recommended agentic server settings.
#
# Usage:
#   scripts\benchmark-devserver.ps1                         # benchmark + show recommendations
#   scripts\benchmark-devserver.ps1 -ApplySettings          # also restart Ollama with optimal env
#   scripts\benchmark-devserver.ps1 -Model qwen2.5-coder:7b # bench specific model only
#   scripts\benchmark-devserver.ps1 -Quick                  # 1 prompt per model instead of 3
# =============================================================================

param(
    # Override SSH host (reads vast-devserver from ~/.ssh/config by default)
    [string]$SshHost    = '',
    [int]   $SshPort    = 0,
    [string]$SshKeyFile = '',
    # Benchmark a single model instead of all loaded models
    [string]$Model = '',
    # Restart Ollama with recommended agentic settings
    [switch]$ApplySettings,
    # Run 1 prompt per model instead of 3 (faster)
    [switch]$Quick
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Resolve SSH connection from ~/.ssh/config vast-devserver entry if not given
# ---------------------------------------------------------------------------
function Get-SshConfigEntry {
    param([string]$Alias)
    $sshConfigPath = Join-Path $env:USERPROFILE ".ssh\config"
    if (-not (Test-Path $sshConfigPath)) { return $null }
    $lines = Get-Content $sshConfigPath
    $inBlock = $false
    $entry = @{}
    foreach ($line in $lines) {
        if ($line -match "^\s*Host\s+$Alias\s*$") { $inBlock = $true; continue }
        if ($inBlock -and $line -match '^\s*Host\s+') { break }
        if ($inBlock -and $line -match '^\s*(\w+)\s+(.+)$') {
            $entry[$Matches[1].ToLower()] = $Matches[2].Trim()
        }
    }
    if ($entry.Count -gt 0) { return $entry } else { return $null }
}

if ([string]::IsNullOrEmpty($SshHost)) {
    $sshEntry = Get-SshConfigEntry 'vast-devserver'
    if ($sshEntry) {
        $SshHost    = $sshEntry['hostname'] ?? $sshEntry['host'] ?? ''
        $SshPort    = if ($sshEntry['port']) { [int]$sshEntry['port'] } else { 22 }
        $SshKeyFile = if ($sshEntry['identityfile']) { $sshEntry['identityfile'] } else { "$env:USERPROFILE\.ssh\vast_key" }
    }
}

if ([string]::IsNullOrEmpty($SshHost)) {
    Write-Error "No SSH host found. Run rent-devserver.ps1 first to populate ~/.ssh/config, or pass -SshHost/-SshPort."
    exit 1
}
if ($SshPort -le 0) { $SshPort = 22 }
if ([string]::IsNullOrEmpty($SshKeyFile)) { $SshKeyFile = "$env:USERPROFILE\.ssh\vast_key" }

$ssh = @('-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=15',
         '-o', 'UserKnownHostsFile=NUL', '-o', 'ControlMaster=no',
         '-p', "$SshPort", '-i', $SshKeyFile, "root@$SshHost")

function Invoke-Remote {
    param([string]$Cmd)
    return (& ssh @ssh $Cmd 2>$null | Out-String).Trim()
}

# ---------------------------------------------------------------------------
# Recommended agentic Ollama settings (source of truth for both benchmark
# reporting and the ApplySettings restart)
# ---------------------------------------------------------------------------
# These values are tuned for a 49GB VRAM card (Q RTX 8000) running two
# models simultaneously. Cards with less VRAM should reduce MAX_LOADED_MODELS
# and NUM_PARALLEL -- see VRAM_HEADROOM_CHECK below.
$recommended = [ordered]@{
    OLLAMA_MAX_LOADED_MODELS = '2'     # Keep both 32b + 7b resident; default is 1 for GPU
    OLLAMA_FLASH_ATTENTION   = '1'     # ~30% generation speedup with no quality loss
    OLLAMA_KV_CACHE_TYPE     = 'q8_0' # 50% smaller KV cache, negligible quality loss
    OLLAMA_KEEP_ALIVE        = '-1'    # Never evict models; agentic workflows re-use model mid-run
    OLLAMA_NUM_PARALLEL      = '2'     # 2 concurrent requests; increase for high-throughput pipelines
    OLLAMA_MAX_QUEUE         = '512'   # Large queue for agent bursts (default 512 already, explicit)
    OLLAMA_ORIGINS           = '*'     # CORS open -- required for browser-based agent UIs
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Dev Server Benchmark  --  ${SshHost}:${SshPort}" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. System snapshot
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[ SYSTEM ]" -ForegroundColor Yellow
$gpuInfo    = Invoke-Remote "nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu --format=csv,noheader 2>/dev/null || echo NO_GPU"
$cpuInfo    = Invoke-Remote "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs"
$ollamaVerRaw = Invoke-Remote "curl -s http://localhost:11434/api/version 2>/dev/null || echo unknown"
$ollamaVer    = try { ($ollamaVerRaw | ConvertFrom-Json).version } catch { $ollamaVerRaw }

if ($gpuInfo -notmatch 'NO_GPU') {
    $gpuFields = $gpuInfo -split ',\s*'
    Write-Host ("  GPU  : {0}" -f $gpuFields[0].Trim())
    Write-Host ("  VRAM : {0} total, {1} used, {2} free" -f $gpuFields[1].Trim(), $gpuFields[2].Trim(), $gpuFields[3].Trim())
    Write-Host ("  Temp : {0}  Util: {1}" -f $gpuFields[4].Trim(), $gpuFields[5].Trim())
} else {
    Write-Host "  GPU  : not detected (nvidia-smi unavailable)" -ForegroundColor Yellow
}
Write-Host ("  CPU  : {0}" -f $cpuInfo)
Write-Host ("  Ollama: v{0}" -f $ollamaVer)

# ---------------------------------------------------------------------------
# 2. Current Ollama env vars vs recommended
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[ OLLAMA CONFIGURATION ]" -ForegroundColor Yellow
$ollamaPid  = Invoke-Remote "ps aux | grep 'ollama serve' | grep -v grep | awk '{print `$2}' | head -1"
$actualEnv  = @{}
if ($ollamaPid -match '^\d+$') {
    $envLines = Invoke-Remote "cat /proc/$ollamaPid/environ 2>/dev/null | tr '\0' '\n' | grep '^OLLAMA_'"
    foreach ($line in ($envLines -split "`n")) {
        $line = $line.Trim()
        if ($line -match '^(OLLAMA_[^=]+)=(.*)$') {
            $actualEnv[$Matches[1]] = $Matches[2].Trim()
        }
    }
}

$allGood = $true
foreach ($k in $recommended.Keys) {
    $actual = if ($actualEnv.ContainsKey($k)) { $actualEnv[$k] } else { '(default)' }
    $want   = $recommended[$k]
    if ($actual -eq $want) {
        Write-Host ("  {0,-35} {1,-12} [OK]" -f $k, $actual) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-35} {1,-12} -> should be {2}" -f $k, $actual, $want) -ForegroundColor Red
        $allGood = $false
    }
}

if ($allGood) {
    Write-Host "  All recommended settings are active." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  Run with -ApplySettings to restart Ollama with all recommended settings." -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
# 3. Loaded models
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[ LOADED MODELS ]" -ForegroundColor Yellow
$tagsRaw = Invoke-Remote "curl -s http://localhost:11434/api/tags 2>/dev/null || echo UNREACHABLE"
if ($tagsRaw -match 'UNREACHABLE' -or [string]::IsNullOrWhiteSpace($tagsRaw)) {
    Write-Host "  Ollama is not responding. Cannot benchmark." -ForegroundColor Red
    exit 1
}
try {
    $tagsObj   = $tagsRaw | ConvertFrom-Json
    $modelNames = @($tagsObj.models | ForEach-Object { $_.name } | Where-Object { $_ })
} catch {
    $modelNames = @()
}
if ($modelNames.Count -eq 0) {
    Write-Host "  No models found. Pull a model first: ollama pull qwen2.5-coder:7b" -ForegroundColor Yellow
    exit 1
}
foreach ($m in $modelNames) { Write-Host "  $m" }

$targetModels = if ($Model) { @($Model) } else { $modelNames }

# ---------------------------------------------------------------------------
# 4. Benchmark prompts
# ---------------------------------------------------------------------------
$prompts = @(
    @{
        label  = 'hello-world'
        prompt = 'Write a Python function that returns the nth Fibonacci number using memoization.'
    }
    @{
        label  = 'ts-class'
        prompt = 'Write a TypeScript class for a generic LRU cache with get, set, and delete methods. Include proper typings.'
    }
    @{
        label  = 'code-review'
        prompt = 'Review this code and identify bugs: function mergeSort(arr) { if (arr.length <= 1) return arr; const mid = arr.length / 2; return merge(mergeSort(arr.slice(0,mid)), mergeSort(arr.slice(mid))); } function merge(l,r) { let res=[]; while(l.length&&r.length) res.push(l[0]<r[0]?l.shift():r.shift()); return res.concat(l,r); }'
    }
)

if ($Quick) { $prompts = @($prompts[0]) }

Write-Host ""
Write-Host "[ BENCHMARK ]" -ForegroundColor Yellow
Write-Host ("  Prompts per model: {0}" -f $prompts.Count)

$results = [System.Collections.Generic.List[hashtable]]::new()

foreach ($modelName in $targetModels) {
    Write-Host ""
    Write-Host "  -- Model: $modelName --" -ForegroundColor Cyan

    # Warmup: ensure model is loaded (first call includes load time)
    Write-Host "  Warming up (loading model into VRAM)..." -ForegroundColor DarkGray
    $warmupPayload = '{"model":"' + $modelName + '","prompt":"Hello","stream":false}'
    $warmupRaw = Invoke-Remote "curl -s -X POST http://localhost:11434/api/generate -H 'Content-Type: application/json' -d '$warmupPayload' 2>/dev/null"
    $loadTimeSec = 0
    try {
        $wu = $warmupRaw | ConvertFrom-Json
        # load_duration is in nanoseconds
        $loadTimeSec = [math]::Round($wu.load_duration / 1e9, 1)
    } catch {}
    if ($loadTimeSec -gt 0) {
        Write-Host ("  Model load time: {0}s" -f $loadTimeSec) -ForegroundColor DarkGray
    }

    foreach ($p in $prompts) {
        Write-Host ("    [{0}] running..." -f $p.label) -NoNewline
        $escaped = $p.prompt -replace "'", "'\'''"
        $payload  = '{"model":"' + $modelName + '","prompt":"' + ($p.prompt -replace '"', '\"') + '","stream":false}'
        $start    = Get-Date
        $raw      = Invoke-Remote "curl -s -X POST http://localhost:11434/api/generate -H 'Content-Type: application/json' -d '$payload' 2>/dev/null"
        $elapsed  = (Get-Date) - $start

        try {
            $resp = $raw | ConvertFrom-Json
            $genTokens      = [int]$resp.eval_count
            $genDurSec      = $resp.eval_duration / 1e9
            $promptTokens   = [int]$resp.prompt_eval_count
            $promptDurSec   = $resp.prompt_eval_duration / 1e9
            $genToksSec     = if ($genDurSec -gt 0) { [math]::Round($genTokens / $genDurSec, 1) } else { 0 }
            $prefillToksSec = if ($promptDurSec -gt 0) { [math]::Round($promptTokens / $promptDurSec, 1) } else { 0 }
            $ttftSec        = [math]::Round($promptDurSec, 2)

            Write-Host (" {0} tok/s gen | {1} tok/s prefill | TTFT {2}s | {3} gen tokens" -f $genToksSec, $prefillToksSec, $ttftSec, $genTokens) -ForegroundColor White

            $results.Add(@{
                model       = $modelName
                prompt      = $p.label
                gen_toks_s  = $genToksSec
                prefill_s   = $prefillToksSec
                ttft_s      = $ttftSec
                gen_tokens  = $genTokens
                total_s     = [math]::Round($elapsed.TotalSeconds, 1)
            })
        } catch {
            Write-Host " ERROR (raw: $($raw | Select-Object -First 120))" -ForegroundColor Red
        }
    }
}

# ---------------------------------------------------------------------------
# 5. Summary table
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[ SUMMARY ]" -ForegroundColor Yellow
Write-Host ("  {0,-28} {1,-22} {2,10} {3,12} {4,8}" -f 'Model', 'Prompt', 'Gen tok/s', 'TTFT (s)', 'Tokens')
Write-Host ("  {0}" -f ('-' * 82))
foreach ($r in $results) {
    $modelShort = $r.model -replace ':latest$', ''
    if ($modelShort.Length -gt 27) { $modelShort = $modelShort.Substring(0, 24) + '...' }
    Write-Host ("  {0,-28} {1,-22} {2,10} {3,12} {4,8}" -f $modelShort, $r.prompt, $r.gen_toks_s, $r.ttft_s, $r.gen_tokens)
}

# Compute averages per model
$byModel = $results | Group-Object { $_['model'] }
Write-Host ""
Write-Host "  Averages:"
foreach ($grp in $byModel) {
    $avg = [math]::Round(($grp.Group | Measure-Object { $_['gen_toks_s'] } -Average).Average, 1)
    Write-Host ("    {0,-30} avg {1} tok/s generation" -f ($grp.Name -replace ':latest$', ''), $avg)
}

# ---------------------------------------------------------------------------
# 6. Reference targets for Q RTX 8000
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[ REFERENCE TARGETS  (Q RTX 8000, 49GB, agentic settings) ]" -ForegroundColor DarkGray
Write-Host "  qwen2.5-coder:32b  : 22-28 tok/s gen  (Q4_K_M, flash_attn, num_ctx=32768)" -ForegroundColor DarkGray
Write-Host "  qwen2.5-coder:7b   : 90-110 tok/s gen (Q4_K_M, flash_attn, num_ctx=32768)" -ForegroundColor DarkGray
Write-Host "  TTFT 32b / 32K ctx : ~2-4s prefill at 32K context" -ForegroundColor DarkGray
Write-Host "  If numbers are much lower, settings likely need applying (-ApplySettings)." -ForegroundColor DarkGray

# ---------------------------------------------------------------------------
# 7. Apply recommended settings (optional)
# ---------------------------------------------------------------------------
if ($ApplySettings) {
    Write-Host ""
    Write-Host "[ APPLYING SETTINGS ]" -ForegroundColor Yellow

    # Detect VRAM and scale back if needed
    $vramMib = 0
    if ($gpuInfo -notmatch 'NO_GPU') {
        if ($gpuInfo -match '(\d+)\s*MiB') { $vramMib = [int]$Matches[1] }
    }

    $envToApply = [ordered]@{} + $recommended
    if ($vramMib -gt 0 -and $vramMib -lt 32768) {
        Write-Host ("  VRAM is {0}MB (<32GB): reducing MAX_LOADED_MODELS=1 and NUM_PARALLEL=1" -f $vramMib) -ForegroundColor Yellow
        $envToApply['OLLAMA_MAX_LOADED_MODELS'] = '1'
        $envToApply['OLLAMA_NUM_PARALLEL']      = '1'
    }

    $envExports = ($envToApply.GetEnumerator() | ForEach-Object { "export $($_.Key)=$($_.Value)" }) -join '; '

    Write-Host "  Stopping current ollama serve..." -ForegroundColor DarkGray
    Invoke-Remote "pkill -f 'ollama serve' 2>/dev/null; sleep 2; pkill -9 -f 'ollama serve' 2>/dev/null; sleep 1; echo KILLED" | Out-Null

    Write-Host "  Starting ollama serve with agentic settings..." -ForegroundColor DarkGray
    $startCmd = "$envExports; nohup ollama serve > /tmp/ollama.log 2>&1 &"
    Invoke-Remote $startCmd | Out-Null

    # Wait for Ollama to come up
    $deadline = (Get-Date).AddSeconds(60)
    $up = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $check = Invoke-Remote "curl -s --max-time 3 http://localhost:11434/api/version 2>/dev/null || echo DOWN"
        if ($check -notmatch 'DOWN' -and -not [string]::IsNullOrWhiteSpace($check)) { $up = $true; break }
        Write-Host "  Waiting for Ollama..." -ForegroundColor DarkGray
    }

    if ($up) {
        Write-Host "  Ollama restarted with agentic settings." -ForegroundColor Green
        Write-Host "  Settings will persist until the instance is rebooted." -ForegroundColor DarkGray
        Write-Host "  To persist across reboots, rent-devserver.ps1 now sets these automatically." -ForegroundColor DarkGray

        # Verify env vars are visible in new process
        $newPid = Invoke-Remote "ps aux | grep 'ollama serve' | grep -v grep | awk '{print `$2}' | head -1"
        if ($newPid -match '^\d+$') {
            $newEnvCheck = Invoke-Remote "cat /proc/$newPid/environ 2>/dev/null | tr '\0' '\n' | grep '^OLLAMA_' | sort"
            Write-Host ""
            Write-Host "  Active env vars in new process:" -ForegroundColor DarkGray
            foreach ($line in ($newEnvCheck -split "`n")) {
                if ($line.Trim()) { Write-Host "    $line" -ForegroundColor DarkGray }
            }
        }
    } else {
        Write-Host "  Ollama did not start within 60s. Check /tmp/ollama.log on the instance." -ForegroundColor Red
    }
}

Write-Host ""
