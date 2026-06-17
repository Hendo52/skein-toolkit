#Requires -Version 5.1
# =============================================================================
# rent-devserver.ps1
# Queries Vast.ai for suitable GPU offers and rents the best one.
#
# First-time users: run setup-devserver.ps1 first (or it runs automatically).
#
# Usage:
#   scripts\rent-devserver.ps1               # interactive mode (default: daily)
#   scripts\rent-devserver.ps1 -UseCase daily
#   scripts\rent-devserver.ps1 -UseCase heavy
#   scripts\rent-devserver.ps1 -UseCase batch
#   scripts\rent-devserver.ps1 -UseCase completions
# =============================================================================

param(
    [ValidateSet('daily', 'heavy', 'chat', 'batch', 'completions')]
    [string]$UseCase = '',

    # When set, skips all Read-Host prompts: auto-selects best offer, auto-approves volume
    # and instance creation. Used by start-overnight-batch.ps1.
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$secretRoot = Join-Path $env:LOCALAPPDATA 'Electron-Splines\devserver-secrets'
$vastaiSecretPath = Join-Path $secretRoot 'vastai-api-key.txt'
$gitHubSecretPath = Join-Path $secretRoot 'github-pat.txt'

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

function Invoke-VastaiRaw {
    param([string[]]$Argv)
    # Always pass --api-key explicitly. We keep the key in an encrypted DPAPI
    # secret file because the vastai CLI's automatic key-file lookup is brittle
    # on Windows and should not be the only source of truth.
    $apiKey = Read-SecretValue -SecretPath $vastaiSecretPath -LegacyPath "$HOME\.config\vastai\vast_api_key" -Label 'Vast.ai API key'
    # Coerce to a single plain string so callers can safely pipe to ConvertFrom-Json.
    return (& $vastaiExe --api-key $apiKey @Argv 2>&1 | Out-String).Trim()
}

function Read-SecretValue {
    param(
        [string]$SecretPath,
        [string]$LegacyPath,
        [string]$Label,
        [switch]$Optional
    )
    if (Test-Path $SecretPath) {
        try {
            $encrypted = (Get-Content $SecretPath -Raw).Trim()
            if ([string]::IsNullOrWhiteSpace($encrypted)) {
                Write-Error "$Label secret file is empty: $SecretPath"
                exit 1
            }
            $secure = ConvertTo-SecureString $encrypted
            return [System.Net.NetworkCredential]::new('', $secure).Password
        } catch {
            Write-Error "Could not read $Label from '$SecretPath'. Re-run setup-devserver.ps1 to recreate it. Details: $($_.Exception.Message)"
            exit 1
        }
    }

    if ($LegacyPath -and (Test-Path $LegacyPath)) {
        $value = (Get-Content $LegacyPath -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($value)) {
            Write-Error "$Label file is empty: $LegacyPath"
            exit 1
        }
        Write-Host "  WARNING: Using legacy plain-text $Label file. Re-run setup-devserver.ps1 to migrate it to secure storage." -ForegroundColor Yellow
        return $value
    }

    if ($Optional) { return '' }

    Write-Error "$Label not found. Run setup-devserver.ps1 to store it securely."
    exit 1
}

function Invoke-Vastai2FA {
    $secretCache = "$env:TEMP\vastai_tfa_secret.txt"
    Write-Host ""
    Write-Host "Vast.ai session expired -- 2FA re-authentication required." -ForegroundColor Yellow
    Write-Host "  (vastai tfa status requires an active session, so we ask directly)" -ForegroundColor DarkGray
    Write-Host "  Which 2FA method does your account use?" -ForegroundColor Yellow
    Write-Host "    [1] TOTP (Google Authenticator, Authy, etc.)  <-- most common" -ForegroundColor White
    Write-Host "    [2] Email code" -ForegroundColor White
    $choice = if ($NonInteractive) { '1' } else { (Read-Host "  Enter 1 or 2 [default: 1]").Trim() }
    $methodType = if ($choice -eq '2') { 'email' } else { 'totp' }

    if ($methodType -eq 'totp') {
        # TOTP: user enters code from authenticator app -- no email send step needed
        Write-Host "  Open your authenticator app and enter the 6-digit code." -ForegroundColor Cyan
        $code = if ($NonInteractive) {
            Write-Error "NonInteractive mode cannot complete TOTP 2FA interactively. Run the script once manually to refresh the session."
            exit 1
        } else {
            Read-Host "  Enter TOTP code"
        }
        $loginOut = (& $vastaiExe tfa login --method-type totp -c $code 2>&1 | Out-String).Trim()
        Write-Host $loginOut
        if ($loginOut -match '\[X\]|Error:|failed|invalid') {
            Write-Error "TOTP 2FA login failed. Make sure the code is current (codes expire every 30s)."
            exit 1
        }
    } else {
        # Email 2FA flow
        Write-Host "  Sending email code..." -ForegroundColor Yellow
        $sendOut = (& $vastaiExe tfa send-email 2>&1 | Out-String).Trim()

        if ($sendOut -match 'Secret token:\s*([a-f0-9]+)') {
            $secret = $Matches[1]
            # Cache the secret so it survives rate-limit retries.
            # Restrict file permissions to current user only.
            Set-Content -Path $secretCache -Value $secret -Encoding ASCII
            $acl = Get-Acl $secretCache
            $acl.SetAccessRuleProtection($true, $false)  # disable inheritance
            $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
                'Read,Write', 'Allow')
            $acl.AddAccessRule($rule)
            Set-Acl $secretCache $acl
            Write-Host "  Email sent. Check your inbox for the 6-digit code." -ForegroundColor Green
        } elseif ($sendOut -match 'already sent|already been sent') {
            Write-Host "  A code was already sent recently." -ForegroundColor Yellow
            if (Test-Path $secretCache) {
                $secret = (Get-Content $secretCache -Raw).Trim()
                Write-Host "  Reusing cached secret token from previous send." -ForegroundColor Cyan
            } else {
                Write-Host ""
                Write-Host "  No cached secret found. Run this in a terminal to get a new one:" -ForegroundColor Yellow
                Write-Host "    vastai tfa send-email" -ForegroundColor White
                Write-Host "  Then re-run this script." -ForegroundColor White
                exit 1
            }
        } else {
            Write-Host $sendOut
            Write-Error "Unexpected response from vastai tfa send-email."
            exit 1
        }

        $code = if ($NonInteractive) {
            Write-Error "NonInteractive mode requires a pre-authenticated vastai session. Run the script interactively once to complete 2FA, then retry."
            exit 1
        } else {
            Read-Host "  Enter the 6-digit code from your email"
        }
        $loginOut = (& $vastaiExe tfa login --method-type email --secret $secret -c $code 2>&1 | Out-String).Trim()
        Write-Host $loginOut
        if ($loginOut -match '\[X\]|Error:|failed|invalid') {
            Remove-Item -Path $secretCache -ErrorAction SilentlyContinue
            Write-Error "Email 2FA login failed. Check the code and try again."
            exit 1
        }
        Remove-Item -Path $secretCache -ErrorAction SilentlyContinue
    }

    Write-Host "2FA authentication successful." -ForegroundColor Green
    Write-Host ""
}

function Invoke-Vastai {
    param([string[]]$Argv)
    $out = Invoke-VastaiRaw $Argv
    # If the response still signals an auth failure despite passing --api-key,
    # the key itself is invalid. Print a clear message and exit.
    if ($out -match '"error":\s*true' -and $out -match 'Session expired|Authorization Error|Unauthorized') {
        Write-Host "Vast.ai API key is invalid or expired." -ForegroundColor Red
        Write-Host "Run: vastai set api-key <YOUR_KEY>  (get key from https://vast.ai/account)" -ForegroundColor Yellow
        exit 1
    }
    return $out
}

# --- Load static config early (needed by Open-DevServerAndChat) ---
$configPath = Join-Path $PSScriptRoot "devserver.config.ps1"
if (-not (Test-Path $configPath)) { Write-Error "Config not found: $configPath"; exit 1 }
. $configPath

# --- First-time setup gate ---
# Only trigger setup when the SSH key is actually missing.
# The user config (~/.devserver-config.ps1) is optional; defaults work without it.
if (-not (Test-Path $DevServerKey)) {
    Write-Host ""
    Write-Host "SSH key not found at: $DevServerKey" -ForegroundColor Yellow
    Write-Host "Running first-time setup wizard..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'setup-devserver.ps1')
    # Reload config after setup
    . $configPath
    if (-not (Test-Path $DevServerKey)) {
        Write-Error "Setup did not produce an SSH key at $DevServerKey. Re-run setup-devserver.ps1."
        exit 1
    }
}

# =============================================================================
# Open-DevServerAndChat
# After an instance is running: write SSH config, update ~/ssh/config,
# open a local VS Code window, start the Ollama SSH tunnel.
# All three scripts (rent/launch/chat) are unified here.
# =============================================================================
function Open-DevServerAndChat {
    param(
        [Parameter(Mandatory)][hashtable]$Inst,
        [string]$UseCase = 'chat'
    )

    $instId   = $Inst['id']
    # Use the Vast.ai proxy host/port (ssh_host / ssh_port) rather than the direct
    # public IP + container port. The proxy is always reachable; the direct IP path
    # depends on the host machine's firewall and is sometimes blocked.
    $instIp   = if ($Inst['ssh_host']) { $Inst['ssh_host'] } else { $Inst['public_ipaddr'] }
    $sshPort  = if ($Inst['ssh_port'] -and [int]$Inst['ssh_port'] -gt 0) { [int]$Inst['ssh_port'] } else { [int]($Inst['ports']['22/tcp'][0]['HostPort']) }
    $hourly   = $Inst['dph_total']

    Write-Host ""
    Write-Host "Instance ID ${instId}: ${instIp}:${sshPort}  ($($Inst['gpu_name']), $($Inst['geolocation']))" -ForegroundColor Green

    # --- Write ~/.ssh/config ---
    $sshDir        = Join-Path $env:USERPROFILE ".ssh"
    $sshConfigPath = Join-Path $sshDir "config"
    if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }

    $newBlock = @(
        "Host vast-devserver"
        "    HostName $instIp"
        "    Port $sshPort"
        "    User root"
        "    IdentityFile $DevServerKey"
        "    StrictHostKeyChecking no"
        "    ServerAliveInterval 60"
        "    ServerAliveCountMax 3"
    )

    if (Test-Path $sshConfigPath) {
        $lines       = Get-Content $sshConfigPath
        $kept        = [System.Collections.Generic.List[string]]::new()
        $inVastBlock = $false
        foreach ($line in $lines) {
            if ($line -match '^Host\s+vast-devserver\s*$') { $inVastBlock = $true; continue }
            if ($inVastBlock -and $line -match '^Host\s+') { $inVastBlock = $false }
            if (-not $inVastBlock) { $kept.Add($line) }
        }
        while ($kept.Count -gt 0 -and $kept[$kept.Count - 1].Trim() -eq '') { $kept.RemoveAt($kept.Count - 1) }
        $allLines = @($kept) + @("") + $newBlock
        [System.IO.File]::WriteAllLines($sshConfigPath, $allLines)
    } else {
        [System.IO.File]::WriteAllLines($sshConfigPath, $newBlock)
    }
    Write-Host "Updated ~/.ssh/config: vast-devserver -> ${instIp}:${sshPort}" -ForegroundColor Cyan

    # SSH base args with ControlMaster so all subsequent calls reuse one connection.
    # Forward slashes required -- Windows OpenSSH ControlMaster does not accept backslashes
    # in the socket path. Join-Path produces backslashes, so replace manually.
    $controlPath = ($env:TEMP + "\ssh-vast-$instId.ctl") -replace '\\', '/'
    $sshBase = @('-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=no',
                 '-o', 'UserKnownHostsFile=NUL', '-p', $sshPort, '-i', $DevServerKey,
                 '-o', "ControlMaster=auto", '-o', "ControlPath=$controlPath", '-o', 'ControlPersist=120',
                 "root@$instIp")
    # Clean up any stale ControlMaster socket from a previous run with the same instance ID.
    # A broken socket from a prior failed session causes all subsequent commands to fail instantly.
    if (Test-Path $controlPath) {
        ssh -O exit -o "ControlPath=$controlPath" -p $sshPort "root@$instIp" 2>&1 | Out-Null
        Remove-Item $controlPath -ErrorAction SilentlyContinue
    }

    # --- Define which models each use case requires (needed for remote config) ---
    $requiredModels = $useCases[$UseCase].models

    # --- Wait for SSH to accept connections (fresh instances need a few seconds) ---
    # All subsequent steps SSH in; if the daemon isn't ready yet the mkdir -p and
    # config writes fail silently (2>$null), leaving /root/repo absent and VS Code
    # erroring "Starting directory does not exist".
    Write-Host "Waiting for SSH..." -ForegroundColor Cyan
    # Probe args deliberately exclude ControlMaster -- a failed attempt with ControlMaster=auto
    # leaves a stale socket that causes all subsequent attempts to fail instantly (~0s each),
    # exhausting the 300s window on the first real failure rather than retrying.
    $sshProbeArgs = @('-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=no',
                      '-o', 'UserKnownHostsFile=NUL', '-o', 'ControlMaster=no',
                      '-p', $sshPort, '-i', $DevServerKey, "root@$instIp")
    $sshErrFile = Join-Path $env:TEMP "ssh-probe-err-$instId.txt"
    $sshDeadline = (Get-Date).AddSeconds(300)
    $sshReady = $false
    $probeCount = 0
    while ((Get-Date) -lt $sshDeadline) {
        $probeCount++
        $sshTest = & ssh @sshProbeArgs "echo SSH_OK" 2>$sshErrFile | Out-String
        if ($sshTest -match 'SSH_OK') { $sshReady = $true; break }
        # Show the SSH error on the first two attempts so the user can diagnose persistent failures
        if ($probeCount -le 2 -and (Test-Path $sshErrFile)) {
            $sshErr = (Get-Content $sshErrFile -Raw).Trim()
            if ($sshErr) { Write-Host "  SSH error: $sshErr" -ForegroundColor DarkYellow }
        }
        Write-Host "  SSH not ready yet..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 5
    }
    if (-not $sshReady) {
        Write-Error "SSH did not become ready within 5 minutes. Check the instance."
        return
    }
    Write-Host "  SSH ready." -ForegroundColor Green

    # --- Provision: clone repo onto fresh instance (now that SSH is confirmed ready) ---
    # Use $sshProbeArgs (direct, no ControlMaster) for all git operations.
    # A stale ControlMaster socket from a prior failed session causes $sshBase commands
    # to silently no-op on Windows, leaving the repo absent without any error message.
    if (-not [string]::IsNullOrWhiteSpace($DevServerRepoUrl)) {
        # For GitHub private repos, use an ephemeral tokenized URL only for clone/pull.
        # Never persist x-access-token identities in global git config (they show up in
        # VS Code account pickers and cause confusing identity selection prompts).
        & ssh @sshProbeArgs "git config --global --get-regexp 'url\\..*\\.insteadOf' 2>/dev/null | awk '{print `$1}' | while IFS= read -r k; do git config --global --unset-all `"`$k`" 2>/dev/null; done" 2>&1 | Out-Null
        $githubToken = Read-SecretValue -SecretPath $gitHubSecretPath -LegacyPath '' -Label 'GitHub personal access token' -Optional
        if ([string]::IsNullOrWhiteSpace($githubToken) -and -not [string]::IsNullOrWhiteSpace($DevServerGitHubToken)) {
            $githubToken = $DevServerGitHubToken
        }
        $authRepoUrl = $DevServerRepoUrl
        $usingEphemeralGitHubToken = $false
        if (-not [string]::IsNullOrWhiteSpace($githubToken) -and $DevServerRepoUrl -match '^https://github.com/') {
            $authRepoUrl = $DevServerRepoUrl -replace '^https://github.com/', "https://x-access-token:$githubToken@github.com/"
            $usingEphemeralGitHubToken = $true
        }
        Write-Host "Cloning $DevServerRepoUrl -> $DevServerRepo ..." -ForegroundColor Cyan
        if ([string]::IsNullOrWhiteSpace($githubToken)) {
            Write-Host "  No GitHub token is configured. Public repos will clone anonymously; private repos will fail here and the setup wizard should be re-run." -ForegroundColor DarkGray
        }
        $cloneOut = & ssh @sshProbeArgs "GIT_TERMINAL_PROMPT=0 git clone --depth=1 '$authRepoUrl' '$DevServerRepo' 2>&1 || echo CLONE_FAILED" 2>&1 | Out-String
        if ($cloneOut -match 'CLONE_FAILED') {
            # Clone failed -- directory likely exists. Check if the repo has commits.
            # If it has no commits (broken/interrupted partial clone), wipe and re-clone shallow.
            $hasCommits = & ssh @sshProbeArgs "git -C '$DevServerRepo' log -1 --oneline 2>/dev/null && echo HAS_COMMITS || echo NO_COMMITS" 2>&1 | Out-String
            if ($hasCommits -match 'NO_COMMITS') {
                Write-Host "  Directory exists but repo is empty/broken -- wiping and re-cloning shallow..." -ForegroundColor Yellow
                $cloneOut2 = & ssh @sshProbeArgs "rm -rf '$DevServerRepo'; GIT_TERMINAL_PROMPT=0 git clone --depth=1 '$authRepoUrl' '$DevServerRepo' 2>&1 && echo CLONE_OK || echo CLONE_FAILED" 2>&1 | Out-String
                if ($cloneOut2 -match 'CLONE_FAILED') {
                    Write-Host "  Re-clone also failed. Check the repo URL and GitHub token. Files will be absent on the remote." -ForegroundColor Red
                } else {
                    Write-Host "  Repo cloned (fresh shallow clone)." -ForegroundColor Green
                }
            } else {
                Write-Host "  Repo already present -- pulling latest..." -ForegroundColor DarkGray
                if ($usingEphemeralGitHubToken) {
                    $pullOut = & ssh @sshProbeArgs "GIT_TERMINAL_PROMPT=0 git -C '$DevServerRepo' pull '$authRepoUrl' 2>&1 || echo PULL_FAILED" 2>&1 | Out-String
                } else {
                    $pullOut = & ssh @sshProbeArgs "GIT_TERMINAL_PROMPT=0 git -C '$DevServerRepo' pull 2>&1 || echo PULL_FAILED" 2>&1 | Out-String
                }
                if ($pullOut -match 'PULL_FAILED') {
                    Write-Host "  Pull failed. Check the repo URL and GitHub token." -ForegroundColor Red
                } else {
                    Write-Host "  Repo updated via pull." -ForegroundColor Green
                }
            }
        } else {
            Write-Host "  Repo cloned." -ForegroundColor Green
        }
        if ($usingEphemeralGitHubToken) {
            & ssh @sshProbeArgs "git -C '$DevServerRepo' remote set-url origin '$DevServerRepoUrl' 2>/dev/null || true" 2>&1 | Out-Null
        }
    }
    # --- Configure git credential storage so plain-SSH terminals can git pull ---
    # VS Code's git credential socket (/tmp/vscode-git-*.sock) only exists while a
    # VS Code Remote window is connected. A plain SSH terminal gets ECONNREFUSED.
    # Fix: write the token into the git credential store and configure git to use it.
    # The credential store on Linux uses ~/.git-credentials (plaintext, chmod 600).
    # This is acceptable for a short-lived cloud instance where root is the only user.
    if (-not [string]::IsNullOrWhiteSpace($githubToken)) {
        $credsB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("https://x-access-token:${githubToken}@github.com"))
        # core.askPass='' prevents GIT_ASKPASS (injected by VS Code Remote into tmux sessions)
        # from taking priority over credential.helper when the VS Code socket is dead.
        & ssh @sshProbeArgs "echo '$credsB64' | base64 -d > ~/.git-credentials && chmod 600 ~/.git-credentials && git config --global credential.helper store && git config --global core.askPass '' && echo CREDS_STORED" 2>&1 | Out-Null
    }
    # --- Write git identity to remote ~/.gitconfig ---
    # Values come from the user's ~/.devserver-config.ps1 (never the repo).
    # Blank values are skipped so unset users get git's default (empty) behaviour.
    if (-not [string]::IsNullOrWhiteSpace($DevServerGitUserName)) {
        & ssh @sshProbeArgs "git config --global user.name '$DevServerGitUserName'" 2>&1 | Out-Null
    }
    if (-not [string]::IsNullOrWhiteSpace($DevServerGitUserEmail)) {
        & ssh @sshProbeArgs "git config --global user.email '$DevServerGitUserEmail'" 2>&1 | Out-Null
    }

    # --- Write /usr/local/bin/git wrapper to strip stale VS Code git env vars ---
    # GIT_ASKPASS is injected by VS Code Remote SSH into the tmux global environment.
    # It persists in all shells -- including already-running tmux windows -- after VS Code
    # disconnects. env var overrides git config, so core.askPass='' alone is not enough.
    # The wrapper at /usr/local/bin/git (which precedes /usr/bin/git in PATH) unsets them
    # unconditionally before every git call, making 'git pull' work in all shells.
    & ssh @sshProbeArgs @"
cat > /usr/local/bin/git << 'WRAPPER'
#!/bin/bash
# Strip stale VS Code git credential vars injected by Remote SSH into tmux sessions.
unset GIT_ASKPASS VSCODE_GIT_ASKPASS_NODE VSCODE_GIT_ASKPASS_MAIN VSCODE_GIT_ASKPASS_EXTRA_ARGS VSCODE_GIT_IPC_HANDLE
exec /usr/bin/git "`$@"
WRAPPER
chmod +x /usr/local/bin/git
"@ 2>&1 | Out-Null

    # --- Fix .bashrc: clean exit + unset stale VS Code git env vars ---
    # (1) VS Code Server spawns a login shell to read env vars; if .bashrc exits non-zero it
    #     logs "Unable to resolve your shell environment" warnings. 'true' at the end fixes this.
    # (2) VS Code Remote SSH writes GIT_ASKPASS and VSCODE_GIT_IPC_HANDLE into the tmux
    #     global environment when it connects. These persist after VS Code disconnects, so plain
    #     'git pull' in a tmux window tries the dead socket and fails with ECONNREFUSED.
    #     Unsetting them in .bashrc ensures new shells are clean. The tmux global env is also
    #     cleared below so the current session is fixed immediately.
    & ssh @sshProbeArgs @"
grep -qxF 'true  # vscode-remote-ssh-exit-0' ~/.bashrc || echo 'true  # vscode-remote-ssh-exit-0' >> ~/.bashrc
grep -qxF '# vscode-git-unset' ~/.bashrc || cat >> ~/.bashrc << 'BASHEOF'

# Unset VS Code git credential vars that persist in tmux after VS Code disconnects.
# vscode-git-unset
unset GIT_ASKPASS VSCODE_GIT_ASKPASS_NODE VSCODE_GIT_ASKPASS_MAIN VSCODE_GIT_ASKPASS_EXTRA_ARGS VSCODE_GIT_IPC_HANDLE
BASHEOF
tmux set-environment -g -u GIT_ASKPASS 2>/dev/null || true
tmux set-environment -g -u VSCODE_GIT_ASKPASS_NODE 2>/dev/null || true
tmux set-environment -g -u VSCODE_GIT_ASKPASS_MAIN 2>/dev/null || true
tmux set-environment -g -u VSCODE_GIT_IPC_HANDLE 2>/dev/null || true
"@ 2>&1 | Out-Null

    # --- Open VS Code Remote SSH window NOW so VS Code Server download runs in parallel ---
    # with Ollama startup and model checks below (saves ~30-60s on first connect).
    Write-Host "" 
    Write-Host "Opening VS Code Remote SSH window..." -ForegroundColor Cyan

    # Write Continue.dev config on the remote via base64 to avoid shell escaping issues with
    # newlines and special characters in the YAML content.
    # Use sshProbeArgs (ControlMaster=no): $sshBase requires an established ControlMaster socket
    # which does not yet exist at this point on Windows, causing the write to silently fail.
    $remoteConfigLines = @('name: Remote Ollama', 'version: 1.0.0', 'schema: v1', 'models:')
    foreach ($model in $requiredModels) {
        $title   = $model -replace ':latest$', ''
        $numCtx  = if ($DevServerModelNumCtx -and $DevServerModelNumCtx.ContainsKey($model))     { $DevServerModelNumCtx[$model] }
                   elseif ($DevServerModelNumCtx -and $DevServerModelNumCtx.ContainsKey($title)) { $DevServerModelNumCtx[$title] }
                   else { $DevServerDefaultNumCtx ?? 8192 }
        $timeout = if ($DevServerModelTimeout -and $DevServerModelTimeout.ContainsKey($model))     { $DevServerModelTimeout[$model] }
                   elseif ($DevServerModelTimeout -and $DevServerModelTimeout.ContainsKey($title)) { $DevServerModelTimeout[$title] }
                   else { $DevServerDefaultTimeout ?? 120 }
        $remoteConfigLines += "  - name: `"$title`""
        $remoteConfigLines += "    provider: ollama"
        $remoteConfigLines += "    model: $model"
        $remoteConfigLines += "    apiBase: `"http://localhost:11434`""
        $remoteConfigLines += "    contextLength: $numCtx"
        $remoteConfigLines += "    systemMessage: |"  # YAML block scalar -- content lines must be indented 6+ spaces
        $remoteConfigLines += "      You are an expert TypeScript/OpenSCAD coding assistant for the Electron-Splines project."
        $remoteConfigLines += "      Tests: app/test/*Test.ts. Imports: { expect } from 'chai'; import 'mocha'; then describe/it blocks."
        $remoteConfigLines += "      Run tests: yarn test. Source imports use relative path ../src/client/... from the test file."
        $remoteConfigLines += "      Write files with the write_file MCP tool, or output complete file content for the user to save."
    }
    # Embeddings provider -- enables @codebase semantic search (nomic-embed-text is 274MB, fast)
    $remoteConfigLines += 'embeddingsProvider:'
    $remoteConfigLines += '  provider: ollama'
    $remoteConfigLines += '  model: nomic-embed-text'
    $remoteConfigLines += '  apiBase: "http://localhost:11434"'
    # MCP server entry -- remote window connects directly to localhost:3100 (no tunnel needed)
    $remoteConfigLines += 'mcpServers:'
    $remoteConfigLines += '  - name: devserver'
    $remoteConfigLines += '    type: sse'
    $remoteConfigLines += '    url: "http://localhost:3100/sse"'
    $remoteConfigYaml = ($remoteConfigLines -join "`n") + "`n"
    $remoteConfigB64  = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteConfigYaml))
    $remoteConfigOut  = & ssh @sshProbeArgs "mkdir -p /root/.continue && echo '$remoteConfigB64' | base64 -d > /root/.continue/config.yaml && echo WRITTEN" 2>&1 | Out-String
    if ($remoteConfigOut -match 'WRITTEN') {
        Write-Host "  Updated /root/.continue/config.yaml on remote." -ForegroundColor Green
    } else {
        Write-Host "  Warning: could not write remote Continue.dev config. SSH error: $($remoteConfigOut.Trim())" -ForegroundColor Yellow
    }

    # Ensure the target directory exists (VS Code Remote errors if cwd is missing).
    # Use direct SSH (ControlMaster=no) for this critical step: a stale ControlMaster
    # socket from a prior session can silently fail all multiplexed commands on Windows,
    # leaving the directory absent and triggering "workspace does not exist" in VS Code.
    $mkdirOut = & ssh @sshProbeArgs "mkdir -p '$DevServerRepo' && echo MKDIR_OK" 2>&1 | Out-String
    if ($mkdirOut -notmatch 'MKDIR_OK') {
        Write-Host "  Warning: could not confirm remote workspace directory exists." -ForegroundColor Yellow
    }

    $codeExe = (Get-Command code -ErrorAction SilentlyContinue)?.Source
    if ($codeExe) {
        $savedNodeOptions     = $env:NODE_OPTIONS
        $savedVscodeInspector = $env:VSCODE_INSPECTOR_OPTIONS
        $env:NODE_OPTIONS             = $null
        $env:VSCODE_INSPECTOR_OPTIONS = $null
        try {
            # Use --folder-uri to bypass VS Code session-restore logic (avoids
            # "Workspace does not exist" when a previous remote session is cached).
            & $codeExe --folder-uri "vscode-remote://ssh-remote+vast-devserver$DevServerRepo"
        } finally {
            $env:NODE_OPTIONS             = $savedNodeOptions
            $env:VSCODE_INSPECTOR_OPTIONS = $savedVscodeInspector
        }
        Write-Host "  Remote window opening (first connect downloads VS Code Server, ~30s)." -ForegroundColor Green
        Write-Host "  Continue below -- Ollama check runs while VS Code connects." -ForegroundColor DarkGray
    } else {
        Write-Host "  'code' not in PATH. Open manually: code --remote ssh-remote+vast-devserver $DevServerRepo" -ForegroundColor Yellow
    }

    # --- Use a different local port to avoid conflict with any local Ollama install ---
    # The local Ollama service holds port 11434 and cannot be reliably stopped (SCM respawn).
    # Solution: bind the tunnel to localhost:11435 and patch the Continue.dev config to match.
    $localTunnelPort = 11435
    $tunnelBusy = Get-NetTCPConnection -LocalPort $localTunnelPort -State Listen -ErrorAction SilentlyContinue
    if ($tunnelBusy) {
        $oldTunnelPid = ($tunnelBusy | Select-Object -First 1).OwningProcess
        Write-Host "  Port $localTunnelPort held by PID $oldTunnelPid (stale tunnel) -- stopping it..." -ForegroundColor Yellow
        Stop-Process -Id $oldTunnelPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        $tunnelBusy = Get-NetTCPConnection -LocalPort $localTunnelPort -State Listen -ErrorAction SilentlyContinue
        if ($tunnelBusy) {
            Write-Error "Local port $localTunnelPort is still in use after kill attempt. Free it and re-run 'Dev Server'."
            return
        }
        Write-Host "  Old tunnel stopped." -ForegroundColor Green
    }
    # Write Continue.dev local config for this session -- generated from the selected
    # use case models only, so Continue does not advertise models that are not present
    # on the current instance (which surfaces as generic "Connection error").
    $continueConfigPath      = Join-Path $env:USERPROFILE ".continue\config.yaml"
    $continuePatchedPort     = $false
    $continueOriginalContent = $null
    $continueBaseContent     = $null
    if (Test-Path $continueConfigPath) {
        $continueOriginalContent = [System.IO.File]::ReadAllText($continueConfigPath)
    }
    # Use only the currently selected use-case models.
    $activeContinueModels = [System.Collections.Generic.List[string]]::new()
    foreach ($m in $requiredModels) {
        if (-not $activeContinueModels.Contains($m)) { [void]$activeContinueModels.Add($m) }
    }
    # Build base config (port 11434) and derive active config (tunnel port). Building both now
    # means the restore step has $continueBaseContent without needing to re-derive the model list.
    # Use native Ollama provider to avoid OpenAI-adapter fields that some Ollama versions reject
    # (for example boolean reasoning flags in /v1 chat payloads).
    $continueConfigLines = @('name: Local Ollama', 'version: 1.0.0', 'schema: v1', 'models:')
    # Prepend Claude BYOK models if an Anthropic key is configured.
    # These use provider:anthropic so they work without the GPU tunnel.
    if ($DevServerAnthropicKey -and $DevServerClaudeModels.Count -gt 0) {
        foreach ($cm in $DevServerClaudeModels) {
            $continueConfigLines += "  - name: `"$($cm.label)`""
            $continueConfigLines += "    provider: anthropic"
            $continueConfigLines += "    model: $($cm.name)"
            $continueConfigLines += "    apiKey: `"$DevServerAnthropicKey`""
        }
    }
    # Prepend Cloudflare Workers AI models if credentials are configured.
    # Uses provider:openai so Continue.dev injects MCP tools into requests.
    # (provider:cloudflare never sends tools -- no agentic capability)
    if ($DevServerCFAccountId -and $DevServerCFApiToken -and $DevServerCFModels.Count -gt 0) {
        $cfBase = "https://api.cloudflare.com/client/v4/accounts/$DevServerCFAccountId/ai/v1"
        foreach ($cm in $DevServerCFModels) {
            $cfCtx = if ($cm.numCtx) { $cm.numCtx } else { 32768 }
            $continueConfigLines += "  - name: `"$($cm.label)`""
            $continueConfigLines += "    provider: openai"
            $continueConfigLines += "    model: `"$($cm.name)`""
            $continueConfigLines += "    apiBase: `"$cfBase`""
            $continueConfigLines += "    apiKey: `"$DevServerCFApiToken`""
            $continueConfigLines += "    contextLength: $cfCtx"
            $continueConfigLines += "    capabilities:"
            $continueConfigLines += "      - tool_use"
            $continueConfigLines += "    chatOptions:"
            $continueConfigLines += "      baseSystemMessage: \"You are an expert TypeScript/OpenSCAD coding assistant for the Electron-Splines project. Tests: app/test/*Test.ts. Imports: { expect } from 'chai'; import 'mocha'; then describe/it blocks. Run tests: yarn test. Source imports use relative path ../src/client/... from the test file.\""
        }
    }
    foreach ($m in $activeContinueModels) {
        $title   = $m -replace ':latest$', ''
        $numCtx  = if ($DevServerModelNumCtx -and $DevServerModelNumCtx.ContainsKey($m))     { $DevServerModelNumCtx[$m] }
                   elseif ($DevServerModelNumCtx -and $DevServerModelNumCtx.ContainsKey($title)) { $DevServerModelNumCtx[$title] }
                   else { $DevServerDefaultNumCtx ?? 8192 }
        $timeout = if ($DevServerModelTimeout -and $DevServerModelTimeout.ContainsKey($m))     { $DevServerModelTimeout[$m] }
                   elseif ($DevServerModelTimeout -and $DevServerModelTimeout.ContainsKey($title)) { $DevServerModelTimeout[$title] }
                   else { $DevServerDefaultTimeout ?? 120 }
        $continueConfigLines += "  - name: `"$title`""
        $continueConfigLines += "    provider: ollama"
        $continueConfigLines += "    model: $m"
        $continueConfigLines += "    apiBase: `"http://localhost:11434`""
        $continueConfigLines += "    contextLength: $numCtx"
        $continueConfigLines += "    chatOptions:"
        $continueConfigLines += "      baseSystemMessage: \"You are an expert TypeScript/OpenSCAD coding assistant for the Electron-Splines project. Tests: app/test/*Test.ts. Imports: { expect } from 'chai'; import 'mocha'; then describe/it blocks. Run tests: yarn test. Source imports use relative path ../src/client/... from the test file.\""
    }
    # Embeddings provider -- enables @codebase semantic search via the Ollama tunnel port
    $continueConfigLines += 'embeddingsProvider:'
    $continueConfigLines += '  provider: ollama'
    $continueConfigLines += '  model: nomic-embed-text'
    $continueConfigLines += "  apiBase: `"http://localhost:11434`""  # patched to tunnel port below
    # MCP server entry -- local window uses the SSH-tunneled port
    $continueConfigLines += 'mcpServers:'
    $continueConfigLines += '  - name: devserver'
    $continueConfigLines += '    type: sse'
    $continueConfigLines += "    url: `"http://localhost:$DevServerMcpTunnelPort/sse`""
    $continueBaseContent   = ($continueConfigLines -join "`n") + "`n"
    $continueActiveContent = $continueBaseContent -replace 'localhost:11434', "localhost:$localTunnelPort"
    New-Item -ItemType Directory -Force -Path (Split-Path $continueConfigPath) | Out-Null
    [System.IO.File]::WriteAllText($continueConfigPath, $continueActiveContent)
    $continuePatchedPort = $true
    Write-Host "Continue.dev: set to localhost:$localTunnelPort" -ForegroundColor Cyan

    # Patch VS Code Copilot Ollama endpoint to the tunnel port so the model picker works.
    # The default setting points at localhost:11434 which conflicts with any local Ollama;
    # tunnel port 11435 is always the remote instance.
    $vscodeSettingsPath   = Join-Path $env:APPDATA "Code\User\settings.json"
    $vscodePatchedOllama  = $false
    $vscodeOriginalContent = $null
    if (Test-Path $vscodeSettingsPath) {
        $vscodeOriginalContent = [System.IO.File]::ReadAllText($vscodeSettingsPath)
        if ($vscodeOriginalContent -match '"github\.copilot\.chat\.byok\.ollamaEndpoint"') {
            $ollamaPattern        = '"github\.copilot\.chat\.byok\.ollamaEndpoint"\s*:\s*"[^"]*"'
            $ollamaReplacement    = '"github.copilot.chat.byok.ollamaEndpoint": "http://localhost:' + $localTunnelPort + '"'
            $vscodePatchedContent = $vscodeOriginalContent -replace $ollamaPattern, $ollamaReplacement
            [System.IO.File]::WriteAllText($vscodeSettingsPath, $vscodePatchedContent)
            $vscodePatchedOllama = $true
            Write-Host "Copilot: Ollama endpoint set to localhost:$localTunnelPort" -ForegroundColor Cyan
        }
    }

    # --- Start safety watcher in a separate window ---
    # Chat mode: omit -BatchFilePath so the watcher does NOT stop on DONE batch state.
    # Batch mode: pass the batch file so the watcher auto-stops when all tasks complete.
    $watcherScript = Join-Path $PSScriptRoot 'watch-devserver.ps1'
    $watcherArgs   = "-NoProfile -NoExit -File `"$watcherScript`"" +
                     " -InstanceId $instId" +
                     " -HourlyRate $hourly" +
                     " -IdleMinutes $WatchIdleMinutes" +
                     " -MaxSessionHours $WatchMaxSessionHours" +
                     " -MaxSpendUsd $WatchMaxSpendUsd"
    if ($UseCase -eq 'batch') {
        $watcherArgs += " -BatchFilePath `"$BatchFilePath`""
    }
    Write-Host "Starting safety watcher (idle: ${WatchIdleMinutes}min, cap: ${WatchMaxSessionHours}hr / `$$WatchMaxSpendUsd)..." -ForegroundColor Cyan
    Start-Process pwsh -ArgumentList $watcherArgs -WindowStyle Normal
    Write-Host "Watcher running in a separate window." -ForegroundColor Green

        # --- Ensure Ollama 0.5.4 is installed on the instance ---
    # Version is pinned to 0.5.4 because:
    #   - 0.5.4+ supports tool_calls in the API response (required for Continue.dev MCP execution)
    #   - 0.5.4 ships CUDA 11 + CUDA 12.4 runners; we remove the CUDA 12.4 runner after install
    #     because CUDA 12.4 requires driver >= 550 and Vast.ai containers often have driver 535
    #   - The CUDA 11 runner works with any driver >= 450, which covers all common Vast.ai images
    # pciutils (lspci) is required by the Ollama install script to detect the NVIDIA GPU;
    # without it, install.sh prints "Unable to detect NVIDIA/AMD GPU" and skips GPU libs.
    $OLLAMA_TARGET_VERSION = '0.5.4'
    Write-Host ""
    Write-Host "Checking Ollama on instance..." -ForegroundColor Cyan
    # $sshBase and $requiredModels already defined above.
    $ollamaVersionRaw = & ssh @sshProbeArgs "ollama --version 2>/dev/null | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo MISSING" 2>&1 | Out-String
    $ollamaVersionInstalled = ($ollamaVersionRaw -split '\r?\n' | Where-Object { $_ -match '^\d+\.\d+\.\d+$' } | Select-Object -First 1)?.Trim()
    $needsOllamaInstall = [string]::IsNullOrWhiteSpace($ollamaVersionInstalled) -or $ollamaVersionInstalled -ne $OLLAMA_TARGET_VERSION

    if ($needsOllamaInstall) {
        if ([string]::IsNullOrWhiteSpace($ollamaVersionInstalled)) {
            Write-Host "  Ollama not found. Installing v$OLLAMA_TARGET_VERSION..." -ForegroundColor Yellow
        } else {
            Write-Host "  Ollama v$ollamaVersionInstalled installed; upgrading/downgrading to v$OLLAMA_TARGET_VERSION..." -ForegroundColor Yellow
        }
        # Install pciutils so Ollama's install.sh detects the NVIDIA GPU
        & ssh @sshProbeArgs "command -v lspci >/dev/null 2>&1 || apt-get install -y pciutils 2>/dev/null" 2>&1 | Out-Null
        # Download and extract Ollama 0.5.4 tarball
        $installCmd = @"
set -e
TGZPATH=/tmp/ollama_${OLLAMA_TARGET_VERSION}.tgz
EXTRACTDIR=/tmp/ollama_${OLLAMA_TARGET_VERSION}_extract
curl -L "https://github.com/ollama/ollama/releases/download/v${OLLAMA_TARGET_VERSION}/ollama-linux-amd64.tgz" -o `$TGZPATH
mkdir -p `$EXTRACTDIR
tar -xzf `$TGZPATH -C `$EXTRACTDIR
pkill -f "ollama serve" 2>/dev/null; sleep 1
cp `$EXTRACTDIR/bin/ollama /usr/local/bin/ollama
rsync -a `$EXTRACTDIR/lib/ /usr/local/lib/ 2>/dev/null || cp -r `$EXTRACTDIR/lib/. /usr/local/lib/
rm -rf `$TGZPATH `$EXTRACTDIR
echo OLLAMA_INSTALLED
"@
        $installOut = & ssh @sshProbeArgs $installCmd 2>&1 | Out-String
        if ($installOut -notmatch 'OLLAMA_INSTALLED') {
            Write-Host "  Ollama install failed. Output:" -ForegroundColor Red
            Write-Host $installOut -ForegroundColor DarkYellow
            throw "Cannot continue: Ollama v$OLLAMA_TARGET_VERSION install failed."
        }
        Write-Host "  Ollama v$OLLAMA_TARGET_VERSION installed." -ForegroundColor Green
    } else {
        Write-Host "  Ollama v$ollamaVersionInstalled present (correct version)." -ForegroundColor Green
    }
    # Always remove the cuda_v12_avx runner after any install/re-install.
    # Reason: CUDA 12.4 runner requires driver >= 550; most Vast.ai containers ship driver 535.
    # Without removal, Ollama selects cuda_v12_avx (preferred) and fails at model load time
    # with "CUDA error: device kernel image is invalid". CUDA 11 works with driver >= 450.
    & ssh @sshProbeArgs "rm -rf /usr/local/lib/ollama/runners/cuda_v12_avx /usr/local/lib/ollama/cuda_v12 /usr/local/lib/ollama/cuda_v13 2>/dev/null; echo CUDA_V11_ONLY" 2>&1 | Out-Null

    # --- Build the agentic Ollama environment string ---
    # These settings are essential for an agentic coding server. Without them:
    #   - MAX_LOADED_MODELS defaults to 1 (GPU), causing 30-60s model reload on every switch
    #   - FLASH_ATTENTION is off (~30% slower generation)
    #   - KV_CACHE_TYPE is float16 (2x larger than q8_0, wastes VRAM)
    #   - KEEP_ALIVE is 5m (models evict mid-session)
    # VRAM budget check: if the GPU has <32GB, back off to 1 loaded model and 1 parallel slot.
    # Use --nounits so nvidia-smi emits a bare integer with no unit suffix.
    # Parse strictly: only accept a line that is purely digits so that SSH banners,
    # connection warnings, and any other prefix text do not contaminate the value.
    $gpuVramRaw = (& ssh @sshProbeArgs "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | tail -1" 2>&1 | Out-String).Trim()
    $gpuVramLine = $gpuVramRaw -split '\r?\n' | Where-Object { $_ -match '^\s*\d+\s*$' } | Select-Object -Last 1
    $gpuVramMib  = if ($gpuVramLine) { [long]$gpuVramLine.Trim() } else { 0 }
    $maxLoadedModels = if ($gpuVramMib -gt 0 -and $gpuVramMib -lt 32768) { '1' } else { '2' }
    $numParallel     = if ($gpuVramMib -gt 0 -and $gpuVramMib -lt 32768) { '1' } else { '2' }
    $ollamaEnvExports = @(
        "export OLLAMA_MAX_LOADED_MODELS=$maxLoadedModels",  # keep both models resident (not just 1)
        "export OLLAMA_FLASH_ATTENTION=1",                    # ~30% faster generation
        "export OLLAMA_KV_CACHE_TYPE=q8_0",                  # 50% smaller KV cache
        "export OLLAMA_KEEP_ALIVE=-1",                        # never evict models
        "export OLLAMA_NUM_PARALLEL=$numParallel",            # concurrent request slots
        "export OLLAMA_MAX_QUEUE=512",                        # large queue for agent bursts
        "export OLLAMA_ORIGINS=*"                             # CORS open for browser-based UIs
    ) -join '; '

    # Check if Ollama is running and whether it already has the required settings.
    # If it's running without the agentic env vars, restart it -- the settings cannot
    # be applied to a live process.
    $tagsRaw = & ssh @sshProbeArgs "curl -s --max-time 3 http://localhost:11434/api/tags 2>/dev/null || echo UNREACHABLE" 2>&1
    $ollamaRunning = $tagsRaw -notmatch 'UNREACHABLE' -and -not [string]::IsNullOrWhiteSpace($tagsRaw)

    $needsRestart = $false
    if ($ollamaRunning) {
        $ollamaPid = (& ssh @sshProbeArgs "pgrep -f 'ollama serve' | head -1" 2>&1 | Out-String).Trim()
        if ($ollamaPid -match '^\d+$') {
            $activeEnv = & ssh @sshProbeArgs "cat /proc/$ollamaPid/environ 2>/dev/null | tr '\0' '\n' | grep '^OLLAMA_FLASH_ATTENTION'" 2>&1 | Out-String
            if ($activeEnv -notmatch 'OLLAMA_FLASH_ATTENTION=1') { $needsRestart = $true }
        } else {
            $needsRestart = $true
        }
    }

    if (-not $ollamaRunning -or $needsRestart) {
        if ($needsRestart) {
            Write-Host "  Restarting ollama serve with agentic settings..." -ForegroundColor Yellow
            & ssh @sshProbeArgs "pkill -f 'ollama serve' 2>/dev/null; sleep 2; pkill -9 -f 'ollama serve' 2>/dev/null; sleep 1; echo KILLED" 2>&1 | Out-Null
        } else {
            Write-Host "  Starting ollama serve..." -ForegroundColor Yellow
        }
        & ssh @sshProbeArgs "$ollamaEnvExports; nohup ollama serve > /tmp/ollama.log 2>&1 &" 2>&1 | Out-Null
        # Wait up to 60s for it to come up
        $serveDeadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $serveDeadline) {
            Start-Sleep -Seconds 3
            $tagsRaw = & ssh @sshProbeArgs "curl -s --max-time 3 http://localhost:11434/api/tags 2>/dev/null || echo UNREACHABLE" 2>&1
            if ($tagsRaw -notmatch 'UNREACHABLE' -and -not [string]::IsNullOrWhiteSpace($tagsRaw)) { break }
            Write-Host "  Waiting for ollama serve..." -ForegroundColor DarkGray
        }
        if ($tagsRaw -match 'UNREACHABLE' -or [string]::IsNullOrWhiteSpace($tagsRaw)) {
            Write-Warning "ollama serve did not start within 60s. Tunnel will open anyway."
        } else {
            Write-Host "  Ollama is up (agentic settings active)." -ForegroundColor Green
        }
    } else {
        Write-Host "  Ollama already running with agentic settings." -ForegroundColor Green
    }

    # --- Restore model cache (rclone) if configured ---
    # When DevServerModelCacheRclone is set (e.g. 'r2:bucket/ollama-models'), restore
    # model blobs from cloud storage before attempting Ollama pulls. This turns a
    # 40-min registry pull into a ~5-min R2 download on any machine, independent of
    # whether the ollama_models persistent volume is attached.
    $rcloneConfigured = -not [string]::IsNullOrWhiteSpace($DevServerModelCacheRclone)
    if ($rcloneConfigured) {
        Write-Host "Restoring model cache from '$DevServerModelCacheRclone'..." -ForegroundColor Cyan
        # Find rclone config on Windows (two common locations)
        $rcloneConfLocal = $null
        $rcloneConfCandidates = @(
            (Join-Path $env:APPDATA 'rclone\rclone.conf'),
            (Join-Path $env:USERPROFILE '.config\rclone\rclone.conf')
        )
        foreach ($c in $rcloneConfCandidates) {
            if (Test-Path $c) { $rcloneConfLocal = $c; break }
        }
        if (-not $rcloneConfLocal) {
            Write-Host "  Warning: rclone config not found at $($rcloneConfCandidates -join ' or ')." -ForegroundColor Yellow
            Write-Host "  Run 'rclone config' locally to set up the remote, then re-run this script." -ForegroundColor Yellow
            $rcloneConfigured = $false
        } else {
            # Install rclone on remote if not present (curl-based installer, fast)
            $rcloneCheck = & ssh @sshProbeArgs 'command -v rclone >/dev/null 2>&1 && echo PRESENT || echo MISSING' 2>&1 | Out-String
            if ($rcloneCheck -match 'MISSING') {
                Write-Host "  Installing rclone on remote..." -ForegroundColor DarkGray
                & ssh @sshProbeArgs 'curl -fsSL https://rclone.org/install.sh | bash 2>&1 | tail -3' 2>&1 | Out-Null
            }
            # Copy rclone config to remote
            $rcloneConfB64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($rcloneConfLocal))
            & ssh @sshProbeArgs "mkdir -p /root/.config/rclone && echo '$rcloneConfB64' | base64 -d > /root/.config/rclone/rclone.conf && chmod 600 /root/.config/rclone/rclone.conf" 2>&1 | Out-Null
            # Restore blobs from cache (copy = only download files not already present)
            # --size-only: compare by size instead of checksum (avoids Class B read ops on R2)
            # --max-transfer: hard cap on total data transferred; rclone exits code 8 if exceeded
            $maxXfer = if ($DevServerModelCacheMaxTransferGB -and [int]$DevServerModelCacheMaxTransferGB -gt 0) { "${DevServerModelCacheMaxTransferGB}G" } else { '30G' }
            Write-Host "  Restoring blobs (skipping files already on disk, cap: $maxXfer)..." -ForegroundColor DarkGray
            $restoreOut = & ssh @sshProbeArgs "rclone copy '$DevServerModelCacheRclone' /root/.ollama/models/ --size-only --progress --transfers=8 --checkers=16 --max-transfer=$maxXfer 2>&1" 2>&1 | Out-String
            if ($LASTEXITCODE -eq 8) {
                Write-Host "  WARNING: rclone hit the $maxXfer transfer cap (exit code 8). Restore stopped early." -ForegroundColor Red
                Write-Host "  If you need more data, raise \$DevServerModelCacheMaxTransferGB in ~/.devserver-config.ps1." -ForegroundColor Yellow
            } else {
                Write-Host "  Cache restore complete." -ForegroundColor Green
            }
            Write-Host $restoreOut
        }
    }

    # --- Pull any missing models ---
    if ($tagsRaw -notmatch 'UNREACHABLE' -and -not [string]::IsNullOrWhiteSpace($tagsRaw)) {
        try {
            $tags          = ($tagsRaw | Out-String) | ConvertFrom-Json -AsHashTable -ErrorAction SilentlyContinue
            $pulledModels  = @($tags['models'] | ForEach-Object { $_['name'] -replace ':latest$', '' })
        } catch { $pulledModels = @() }

        foreach ($model in $requiredModels) {
            $modelBase = $model -replace ':latest$', ''
            $alreadyPulled = $pulledModels | Where-Object { $_ -eq $modelBase -or $_ -like "$modelBase*" }
            if ($alreadyPulled) {
                Write-Host "  Model $model already present." -ForegroundColor Green
            } else {
                Write-Host "  Pulling $model (this may take several minutes)..." -ForegroundColor Yellow
                # Use sshProbeArgs (ControlMaster=no) -- a stale socket causes $sshBase to silently
                # no-op, leaving the model absent with no error output.
                & ssh @sshProbeArgs "ollama pull $model" 2>&1
                Write-Host "  Model $model ready." -ForegroundColor Green
            }
        }
        # Always ensure the embedding model is present (tiny, fast, needed for @codebase RAG)
        $embedModel = 'nomic-embed-text'
        $embedPulled = $pulledModels | Where-Object { $_ -eq $embedModel -or $_ -like "$embedModel*" }
        if ($embedPulled) {
            Write-Host "  Embedding model $embedModel already present." -ForegroundColor Green
        } else {
            Write-Host "  Pulling $embedModel (embedding model for @codebase search)..." -ForegroundColor Yellow
            & ssh @sshProbeArgs "ollama pull $embedModel" 2>&1
            Write-Host "  Embedding model $embedModel ready." -ForegroundColor Green
        }

        # Sync newly pulled models back to the cache (background, non-blocking)
        if ($rcloneConfigured) {
            $maxXfer = if ($DevServerModelCacheMaxTransferGB -and [int]$DevServerModelCacheMaxTransferGB -gt 0) { "${DevServerModelCacheMaxTransferGB}G" } else { '30G' }
            Write-Host "  Syncing new models back to cache '$DevServerModelCacheRclone' (background, cap: $maxXfer)..." -ForegroundColor DarkGray
            & ssh @sshProbeArgs "nohup rclone sync /root/.ollama/models/ '$DevServerModelCacheRclone' --size-only --transfers=8 --max-transfer=$maxXfer > /tmp/rclone-sync.log 2>&1 &" 2>&1 | Out-Null
        }
    }

    # --- Deploy and start the agentic MCP server ---
    # devserver-mcp.py exposes run_shell / read_file / write_file / list_directory via SSE.
    # Continue.dev connects to it as an MCP server -- no per-tool approval prompts.
    Write-Host "Setting up MCP server..." -ForegroundColor Cyan
    $mcpScriptLocal = Join-Path $PSScriptRoot 'devserver-mcp.py'
    if (Test-Path $mcpScriptLocal) {
        # Copy script to remote via base64 to avoid scp dependency
        $mcpScriptContent = [System.IO.File]::ReadAllText($mcpScriptLocal)
        $mcpScriptB64     = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($mcpScriptContent))
        $copyOut = & ssh @sshProbeArgs "echo '$mcpScriptB64' | base64 -d > /root/devserver-mcp.py && echo COPIED" 2>&1 | Out-String
        if ($copyOut -notmatch 'COPIED') {
            Write-Host "  Warning: could not copy devserver-mcp.py to remote." -ForegroundColor Yellow
        }
    }
    # Install fastmcp if not present
    $fastmcpCheck = & ssh @sshProbeArgs "python3 -c 'import fastmcp; print(fastmcp.__version__)' 2>/dev/null || echo MISSING" 2>&1 | Out-String
    if ($fastmcpCheck -match 'MISSING') {
        Write-Host "  Installing fastmcp..." -ForegroundColor DarkGray
        & ssh @sshProbeArgs "pip install -q fastmcp" 2>&1 | Out-Null
    }
    # Restart MCP server if script was updated or it isn't running
    $mcpRunning = & ssh @sshProbeArgs "curl -s --max-time 2 http://127.0.0.1:3100/sse 2>/dev/null | head -c 1 && echo SSE_UP || echo SSE_DOWN" 2>&1 | Out-String
    if ($mcpRunning -notmatch 'SSE_UP') {
        & ssh @sshProbeArgs "pkill -f devserver-mcp.py 2>/dev/null; sleep 1; DEVSERVER_WORKSPACE='$DevServerRepo' nohup python3 /root/devserver-mcp.py > /tmp/devserver-mcp.log 2>&1 &" 2>&1 | Out-Null
        Start-Sleep -Seconds 3
        $mcpRunning = & ssh @sshProbeArgs "curl -s --max-time 3 http://127.0.0.1:3100/sse 2>/dev/null | head -c 1 && echo SSE_UP || echo SSE_DOWN" 2>&1 | Out-String
        if ($mcpRunning -match 'SSE_UP') {
            Write-Host "  MCP server running on remote port 3100." -ForegroundColor Green
        } else {
            Write-Host "  Warning: MCP server did not start. Check /tmp/devserver-mcp.log on the instance." -ForegroundColor Yellow
        }
    } else {
        & ssh @sshProbeArgs "pkill -f devserver-mcp.py 2>/dev/null; sleep 1; DEVSERVER_WORKSPACE='$DevServerRepo' nohup python3 /root/devserver-mcp.py > /tmp/devserver-mcp.log 2>&1 &" 2>&1 | Out-Null
        Write-Host "  MCP server restarted (script updated)." -ForegroundColor Green
    }
    # Install a cron watchdog so the MCP server auto-restarts if it crashes between rent runs.
    & ssh @sshProbeArgs "(crontab -l 2>/dev/null | grep -v devserver-mcp; echo '* * * * * pgrep -f devserver-mcp.py > /dev/null || DEVSERVER_WORKSPACE=$DevServerRepo nohup python3 /root/devserver-mcp.py >> /root/devserver-mcp.log 2>&1 &') | crontab -" 2>&1 | Out-Null

    # --- Install extensions on remote VS Code Server ---
    # Use sshProbeArgs (ControlMaster=no): ControlMaster may not be established yet
    # and silently no-ops on Windows, leaving extensions absent with no error.
    # Wait up to 30s for VS Code Server to write its binary before installing.
    Write-Host "Installing remote extensions (Continue.dev, Copilot)..." -ForegroundColor Cyan
    $extDeadline = (Get-Date).AddSeconds(30)
    $codeServerBin = $null
    while ((Get-Date) -lt $extDeadline) {
        $codeServerBin = (& ssh @sshProbeArgs "ls /root/.vscode-server/cli/servers/Stable-*/server/bin/code-server 2>/dev/null | head -1" 2>&1 | Out-String).Trim()
        if (-not [string]::IsNullOrWhiteSpace($codeServerBin)) { break }
        Start-Sleep -Seconds 3
    }
    if ([string]::IsNullOrWhiteSpace($codeServerBin)) {
        Write-Host "  VS Code Server binary not found -- extensions not installed. Reconnect to retry." -ForegroundColor Yellow
    } else {
        $extensions = @('GitHub.copilot', 'GitHub.copilot-chat', 'continue.continue')
        foreach ($ext in $extensions) {
            $result = & ssh @sshProbeArgs "$codeServerBin --install-extension $ext 2>&1 | tail -1" 2>&1 | Out-String
            if ($result -match 'successfully installed|already installed') {
                Write-Host "  $ext : OK" -ForegroundColor Green
            } else {
                Write-Host "  $ext : $($result.Trim())" -ForegroundColor Yellow
            }
        }
    }

    # --- Open VS Code Remote SSH window ---
    # This connects VS Code to the remote machine so you can edit code there.
    # Continue.dev in the remote window talks to Ollama directly (localhost:11434
    # on the remote machine -- no tunnel needed for this path).
    Write-Host ""
    Write-Host "Opening VS Code Remote SSH window..." -ForegroundColor Cyan

    # --- Open Ollama SSH tunnel (detached) ---
    # The tunnel (localhost:11435 -> remote:11434) lets the local config.yaml
    # also work, and is used by the safety watcher.
    Write-Host ""
    Write-Host "##########################################################" -ForegroundColor Green
    Write-Host "#                                                        #" -ForegroundColor Green
    Write-Host "#  REMOTE WINDOW OPENING. In that window:               #" -ForegroundColor Green
    Write-Host "#    Ctrl+L  -> Continue.dev (Ollama, no sign-in)       #" -ForegroundColor Green
    Write-Host "#    Copilot -> sign in to GitHub once (first time only) #" -ForegroundColor Green
    Write-Host "#                                                        #" -ForegroundColor Green
    Write-Host "#  Tunnels (both via the same SSH process):             #" -ForegroundColor Green
    Write-Host "#    localhost:$localTunnelPort -> remote:11434  (Ollama)          #" -ForegroundColor Green
    Write-Host "#    localhost:$DevServerMcpTunnelPort -> remote:3100    (MCP server)      #" -ForegroundColor Green
    Write-Host "#                                                        #" -ForegroundColor Green
    Write-Host "##########################################################" -ForegroundColor Green
    Write-Host ""

    $sshTunnelBaseArgs = @(
        '-i', $DevServerKey,
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=NUL',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=6',
        '-p', "$sshPort",
        "root@$instIp"
    )

    # Start tunnels as separate processes so that if VS Code's Remote SSH extension
    # has already claimed localTunnelPort (11435), only the Ollama tunnel fails --
    # the MCP tunnel (3100) still comes up independently and vice versa.
    $ollamaTunnelAlreadyUp = (Get-NetTCPConnection -LocalPort $localTunnelPort -State Listen -ErrorAction SilentlyContinue) -ne $null
    if ($ollamaTunnelAlreadyUp) {
        Write-Host "  Port $localTunnelPort already forwarded (VS Code Remote). Skipping Ollama tunnel." -ForegroundColor DarkGray
        $sshOllamaProc = $null
    } else {
        $sshOllamaProc = Start-Process -FilePath 'ssh' -ArgumentList (@('-N', '-L', "${localTunnelPort}:localhost:11434") + $sshTunnelBaseArgs) -WindowStyle Minimized -PassThru
    }

    $mcpTunnelAlreadyUp = (Get-NetTCPConnection -LocalPort $DevServerMcpTunnelPort -State Listen -ErrorAction SilentlyContinue) -ne $null
    if ($mcpTunnelAlreadyUp) {
        Write-Host "  Port $DevServerMcpTunnelPort already forwarded. Skipping MCP tunnel." -ForegroundColor DarkGray
        $sshMcpProc = $null
    } else {
        $sshMcpProc = Start-Process -FilePath 'ssh' -ArgumentList (@('-N', '-L', "${DevServerMcpTunnelPort}:localhost:3100") + $sshTunnelBaseArgs) -WindowStyle Minimized -PassThru
    }

    $tunnelReadyDeadline = (Get-Date).AddSeconds(20)
    $tunnelReady = $false
    while ((Get-Date) -lt $tunnelReadyDeadline) {
        Start-Sleep -Milliseconds 300
        $livePort = Get-NetTCPConnection -LocalPort $localTunnelPort -State Listen -ErrorAction SilentlyContinue
        if ($livePort) { $tunnelReady = $true; break }
        if ($sshOllamaProc -and $sshOllamaProc.HasExited) { break }
    }

    $ollamaPidInfo = if ($sshOllamaProc) { "PID: $($sshOllamaProc.Id)" } else { "via VS Code Remote" }
    $mcpPidInfo    = if ($sshMcpProc)    { "PID: $($sshMcpProc.Id)" }    else { "via VS Code Remote" }
    if ($tunnelReady) {
        Write-Host "Tunnel connected on localhost:$localTunnelPort ($ollamaPidInfo)." -ForegroundColor Green
        Write-Host "MCP tunnel on localhost:$DevServerMcpTunnelPort ($mcpPidInfo)." -ForegroundColor Green
        if ($sshOllamaProc) { Write-Host "  Stop Ollama tunnel: Stop-Process -Id $($sshOllamaProc.Id)" -ForegroundColor DarkGray }
        if ($sshMcpProc)    { Write-Host "  Stop MCP tunnel:    Stop-Process -Id $($sshMcpProc.Id)" -ForegroundColor DarkGray }
    } else {
        Write-Host "Warning: tunnel did not come up within 20s. Continue may show ECONNREFUSED until tunnel is restarted." -ForegroundColor Yellow
    }
}

function Wait-ForRunning {
    param($InstanceId)
    Write-Host ""
    Write-Host "Waiting for instance $InstanceId to reach 'running' status (up to 30 minutes)..." -ForegroundColor Cyan
    $deadline  = (Get-Date).AddMinutes(30)
    $startTime = Get-Date
    $instData  = $null
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 10
        $pollJson = (Invoke-VastaiRaw @('show', 'instances-v1', '--raw')) | Out-String
        try {
            $pollParsed = $pollJson | ConvertFrom-Json -AsHashTable
            $pollList   = if ($pollParsed -is [hashtable] -and $pollParsed.ContainsKey('instances')) { $pollParsed['instances'] } else { $pollParsed }
            $instData   = @($pollList | Where-Object { $_['id'] -eq $InstanceId }) | Select-Object -First 1
        } catch {
            Write-Host "  Warning: could not parse Vast.ai instance status JSON. Waiting for the next poll." -ForegroundColor DarkYellow
        }
        $status  = if ($instData) { $instData['actual_status'] } else { 'unknown' }
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        Write-Host "  [$($elapsed)s] Status: $status" -ForegroundColor DarkGray
        if ($status -eq 'running') { break }
    }
    return $instData
}

# --- Use case definitions (loaded from devserver.config.ps1, overridable in ~/.devserver-config.ps1) ---
$useCases = $DevServerUseCases

# --- Pick use case interactively if not supplied ---
# Must run before the instance check so UseCase is known for all Open-DevServerAndChat call sites.
if (-not $UseCase) {
    Write-Host ""
    Write-Host "Select use case:" -ForegroundColor Cyan
    $useCaseKeys = @($useCases.Keys)
    for ($i = 0; $i -lt $useCaseKeys.Count; $i++) {
        $k = $useCaseKeys[$i]
        Write-Host ("  [{0}] {1,-12} -- {2}" -f ($i + 1), $k, $useCases[$k].label)
    }
    Write-Host ""
    $pick = Read-Host "Enter 1-$($useCaseKeys.Count) [default: 1]"
    $pickIdx = if ([string]::IsNullOrWhiteSpace($pick)) { 0 } else { [int]$pick - 1 }
    if ($pickIdx -lt 0 -or $pickIdx -ge $useCaseKeys.Count) { $pickIdx = 0 }
    $UseCase = $useCaseKeys[$pickIdx]
}

# --- Check for existing ollama_models volume (host-locked; needed for the volume-mismatch warning) ---
$ollamaVol = $null
try {
    $volumeJson2 = Invoke-Vastai @('show', 'volumes', '--raw')
    try {
        $volumesParsed2 = $volumeJson2 | ConvertFrom-Json
        $volumes2Early = if ($volumesParsed2 -is [array]) { $volumesParsed2 }
                         elseif ($volumesParsed2.PSObject.Properties['volumes']) { @($volumesParsed2.volumes) }
                         elseif ($volumesParsed2.PSObject.Properties['error']) { @() }
                         else { @($volumesParsed2) }
        $ollamaVol = @($volumes2Early) | Where-Object { $_ -is [pscustomobject] -and $_.PSObject.Properties['label'] -and $_.label -eq 'ollama_models' } | Select-Object -First 1
    } catch {
        Write-Host "  Warning: could not parse Vast.ai volume JSON. The volume mismatch warning will be skipped." -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "  Warning: could not query Vast.ai volumes. The volume mismatch warning will be skipped." -ForegroundColor DarkYellow
    }

# --- Check for existing instances (running or stopped) ---
# Allows reconnecting to a running instance or restarting a stopped one without re-renting.
$existingRaw = (Invoke-VastaiRaw @('show', 'instances-v1', '--raw')) | Out-String
$existList = @()
try {
    $existParsed = $existingRaw | ConvertFrom-Json -AsHashTable
    $existList   = if ($existParsed -is [hashtable] -and $existParsed.ContainsKey('instances')) { $existParsed['instances'] } else { @($existParsed) }
} catch {
    Write-Host "  Warning: could not parse the current instance list from Vast.ai. Continuing with an empty list." -ForegroundColor DarkYellow
}

$runningInst = @($existList | Where-Object { $_['actual_status'] -eq 'running' })
$stoppedInst = @($existList | Where-Object { $_['actual_status'] -eq 'stopped' })

if ($runningInst.Count -gt 0) {
    Write-Host ""
    Write-Host "You already have $($runningInst.Count) running instance(s):" -ForegroundColor Green
    foreach ($r in $runningInst) {
        $rGpu = if ($r['gpu_name']) { $r['gpu_name'] } else { 'Unknown GPU' }
        Write-Host "  ID $($r['id']): $rGpu -- `$$($r['dph_total'])/hr ($($r['geolocation']))" -ForegroundColor Green
    }
    if ($NonInteractive) {
        Write-Host "NonInteractive: connecting to existing running instance." -ForegroundColor Cyan
        Open-DevServerAndChat -Inst $runningInst[0] -UseCase $UseCase
        exit 0
    }
    # Warn if the running instance is on a different machine than the ollama_models volume.
    $runningMachineId = $runningInst[0]['machine_id']
    if ($ollamaVol -and $runningMachineId -and ($runningMachineId -ne $ollamaVol.machine_id)) {
        Write-Host "" 
        Write-Host "WARNING: The running instance is on machine $runningMachineId ($($runningInst[0]['geolocation']))," -ForegroundColor Yellow
        Write-Host "  but the 'ollama_models' volume is on machine $($ollamaVol.machine_id) ($($ollamaVol.geolocation))." -ForegroundColor Yellow
        Write-Host "  The volume CANNOT attach to this instance -- Ollama models will not be available." -ForegroundColor Yellow
        Write-Host "  To use the volume: say N here, then rent a new instance (the script will filter to the right host)." -ForegroundColor Yellow
        Write-Host ""
    }
    $reuseRunning = Read-Host "Connect to running instance? (Y/n)"
    if ($reuseRunning -notmatch '^[nN]') {
        Open-DevServerAndChat -Inst $runningInst[0] -UseCase $UseCase
        exit 0
    }
}

if ($stoppedInst.Count -gt 0) {
    Write-Host ""
    Write-Host "You have $($stoppedInst.Count) stopped instance(s) (disk preserved, no GPU charges):" -ForegroundColor Yellow
    for ($si = 0; $si -lt $stoppedInst.Count; $si++) {
        $s = $stoppedInst[$si]
        $sGpu = if ($s['gpu_name']) { $s['gpu_name'] } else { 'Unknown GPU' }
        Write-Host "  [$si] ID $($s['id']): $sGpu ($($s['geolocation']))" -ForegroundColor Yellow
    }
    if ($NonInteractive) {
        Write-Host "NonInteractive: restarting stopped instance $($stoppedInst[0]['id'])." -ForegroundColor Cyan
        $toResume = $stoppedInst[0]
        Invoke-VastaiRaw @('start', 'instance', "$($toResume['id'])") | ForEach-Object { Write-Host $_ }
        $resumed = Wait-ForRunning -InstanceId $toResume['id']
        if ($resumed -and $resumed['actual_status'] -eq 'running') {
            Write-Host "Instance is running!" -ForegroundColor Green
            Open-DevServerAndChat -Inst $resumed -UseCase $UseCase
        } else {
            Write-Error "Instance did not reach running state. Check https://vast.ai/console/instances"
            exit 1
        }
        exit 0
    }
    $resumeIdx = Read-Host "Restart a stopped instance? Enter index or press Enter to rent new"
    if ($resumeIdx -match '^\d+$' -and [int]$resumeIdx -lt $stoppedInst.Count) {
        $toResume = $stoppedInst[[int]$resumeIdx]
        Write-Host "Starting instance $($toResume['id'])..." -ForegroundColor Cyan
        Invoke-VastaiRaw @('start', 'instance', "$($toResume['id'])") | ForEach-Object { Write-Host $_ }
        $resumed = Wait-ForRunning -InstanceId $toResume['id']
        if ($resumed -and $resumed['actual_status'] -eq 'running') {
            Write-Host "Instance is running!" -ForegroundColor Green
            Open-DevServerAndChat -Inst $resumed -UseCase $UseCase
        } else {
            Write-Host "Instance did not reach running state after 30 minutes. Check https://vast.ai/console/instances" -ForegroundColor Yellow
        }
        exit 0
    }
}

# (use case already picked above)

$cfg = $useCases[$UseCase]
Write-Host ""
Write-Host "Use case : $($cfg.label)" -ForegroundColor Green
Write-Host "Min VRAM : $($cfg.min_vram_gb) GB"
Write-Host "Max price: `$$($cfg.max_cost_hr)/hr"
Write-Host ""

# --- Query offers ---
# vastai search offers returns JSON with --raw
# Key filters: gpu_ram in GB, dph_total = price including storage, reliability
# verified=true is already applied by the vastai CLI default query
Write-Host "Querying Vast.ai offers..." -ForegroundColor Cyan

# $ollamaVol was fetched above (before the instance check) -- no need to re-query here.

$searchQuery = "gpu_ram>=$($cfg.min_vram_gb) dph_total<=$($cfg.max_cost_hr) reliability>0.99"
$searchArgs  = @('search', 'offers', '--raw', '--limit', '50', '-o', 'dph_total')
if ($UseCase -eq 'batch') {
    # Batch mode: search interruptible (spot) market for 20-60% GPU cost savings.
    # Spot instances pause (not destroy) if outbid; git-committed work is preserved.
    $searchArgs += '--type', 'bid'
    Write-Host "(Batch mode: searching interruptible/spot market)" -ForegroundColor DarkGray
}
$searchArgs += $searchQuery
$rawJson = Invoke-Vastai $searchArgs

try {
    $parsed = $rawJson | ConvertFrom-Json
} catch {
    Write-Error "Could not parse Vast.ai response. Output:`n$rawJson"
    exit 1
}
# API may return {"error":true,...} or {"offers":[...]} wrapper instead of a bare array
if ($parsed -is [array]) {
    $offers = $parsed
} elseif ($null -ne $parsed -and $parsed.PSObject.Properties['offers']) {
    $offers = @($parsed.offers)
} elseif ($null -ne $parsed -and $parsed.PSObject.Properties['error']) {
    Write-Host "Vast.ai API error: $($parsed.msg)" -ForegroundColor Red
    Write-Host "Run: vastai set api-key <YOUR_API_KEY>  (get the key from https://vast.ai/account)" -ForegroundColor Yellow
    Write-Host "Or re-run scripts/setup-devserver.ps1 to reconfigure everything." -ForegroundColor Yellow
    exit 1
} else {
    Write-Error "Unexpected response from Vast.ai. Output:`n$rawJson"
    exit 1
}

if ($null -eq $offers -or $offers.Count -eq 0) {
    Write-Host "No offers matched. Try a different use case or check https://vast.ai/console/create" -ForegroundColor Yellow
    exit 1
}

# --- Filter out hosts in countries with high data-sovereignty / legal risk ---
# Geolocation format: "Region, CC" — extract the trailing two-letter country code.
$blockedCC = @('CN', 'RU', 'BY', 'IR', 'KP', 'SY', 'CU', 'VE')
$offers = @($offers | Where-Object {
    $cc = if ($_.geolocation -match ',\s*([A-Z]{2})$') { $Matches[1] } else { '' }
    $blockedCC -notcontains $cc
})
if ($offers.Count -eq 0) {
    Write-Host "All offers are in blocked jurisdictions. Try widening the price range or check https://vast.ai/console/create" -ForegroundColor Yellow
    exit 1
}

# --- Filter offers to volume's host if a volume exists ---
# Vast.ai volumes are host-locked: a volume can only attach to an instance on the same machine.
$volumeExistsElsewhere = $false
if ($ollamaVol) {
    $compatibleOffers = @($offers | Where-Object { $_.machine_id -eq $ollamaVol.machine_id })
    if ($compatibleOffers.Count -gt 0) {
        Write-Host "Showing offers on the same host as 'ollama_models' ($($ollamaVol.geolocation), machine $($ollamaVol.machine_id)):" -ForegroundColor Cyan
        $offers = $compatibleOffers
    } else {
        # Volume machine has no offers in budget. Try progressively wider price caps
        # before giving up so the user gets a chance to stick with the same host.
        $volMachineId  = $ollamaVol.machine_id
        $volGeo        = $ollamaVol.geolocation
        $baseMaxCost   = $cfg.max_cost_hr
        $widenFactors  = @(1.5, 2.5)
        $widenedOffers = @()
        foreach ($factor in $widenFactors) {
            $widenedCap  = [math]::Round($baseMaxCost * $factor, 3)
            $widenQuery  = "gpu_ram>=$($cfg.min_vram_gb) dph_total<=$widenedCap reliability>0.99"
            $widenRaw    = Invoke-Vastai @('search', 'offers', '--raw', '--limit', '20', '-o', 'dph_total', $widenQuery)
            try {
                $allWide = $widenRaw | ConvertFrom-Json
                if ($allWide -is [array]) { $widenedOffers = @($allWide | Where-Object { $_.machine_id -eq $volMachineId }) }
            } catch {}
            if ($widenedOffers.Count -gt 0) { break }
        }
        if ($widenedOffers.Count -gt 0) {
            $cheapest  = $widenedOffers[0]
            $overBudget = [math]::Round($cheapest.dph_total - $baseMaxCost, 3)
            Write-Host ""
            Write-Host "Warning: 'ollama_models' volume is on machine $volMachineId ($volGeo)." -ForegroundColor Yellow
            Write-Host "  No offers within budget (`$$baseMaxCost/hr) on that machine, but found $($widenedOffers.Count) offer(s) above budget:" -ForegroundColor Yellow
            Write-Host "    Cheapest: $($cheapest.gpu_name) @ `$$($cheapest.dph_total)/hr (+`$$overBudget over cap, ID $($cheapest.id))" -ForegroundColor Yellow
            Write-Host "  Options:" -ForegroundColor Cyan
            Write-Host "    [1] Use the above (volume attached, models already present -- no re-download)" -ForegroundColor White
            Write-Host "    [2] Rent cheapest available machine (volume NOT attached -- models must be re-downloaded)" -ForegroundColor White
            $volChoice = if ($NonInteractive) { '2' } else { (Read-Host '  Choose [1/2]').Trim() }
            if ($volChoice -eq '1') {
                $offers = $widenedOffers
                Write-Host "  Using volume host offers (budget override accepted)." -ForegroundColor Green
            } else {
                Write-Host "  Proceeding without volume -- model weights will not persist on this instance." -ForegroundColor Yellow
                $ollamaVol = $null
                $volumeExistsElsewhere = $true
            }
        } else {
            Write-Host ""
            Write-Host "Warning: 'ollama_models' volume is on machine $volMachineId ($volGeo), which has no GPU offers" -ForegroundColor Yellow
            Write-Host "  even at 2.5x your price cap. The volume cannot be attached to any current offer." -ForegroundColor Yellow
            if (-not [string]::IsNullOrWhiteSpace($DevServerModelCacheRclone)) {
                Write-Host "  Model cache (rclone) is configured -- models will be restored from '$DevServerModelCacheRclone'." -ForegroundColor Cyan
            } else {
                Write-Host "  Tip: configure a rclone model cache (\$DevServerModelCacheRclone in ~/.devserver-config.ps1)" -ForegroundColor DarkGray
                Write-Host "       to restore models in ~5 min on any machine instead of re-downloading from Ollama." -ForegroundColor DarkGray
            }
            Write-Host "  Showing all offers -- volume will NOT be attached." -ForegroundColor Yellow
            $ollamaVol = $null
            $volumeExistsElsewhere = $true
        }
    }
}

# --- Display top 10 ---
Write-Host ""
Write-Host "Top available offers (sorted by price):" -ForegroundColor Cyan
Write-Host ("-" * 108)
Write-Host ("{0,-4} {1,-24} {2,8} {3,10} {4,8} {5,10} {6,-22} {7}" -f "Idx", "GPU", "VRAM(GB)", "Price/hr", "Rely%", "Stor/GB/mo", "Location", "ID")
Write-Host ("-" * 108)

$displayOffers = $offers | Select-Object -First 10
for ($i = 0; $i -lt $displayOffers.Count; $i++) {
    $o = $displayOffers[$i]
    $vram     = [math]::Round($o.gpu_ram / 1024, 1)
    $price    = "`${0:F3}" -f $o.dph_total
    $rely     = "{0:F1}" -f ($o.reliability * 100)
    $region   = if ($o.geolocation) { $o.geolocation } else { "?" }
    $gpuName  = if ($o.gpu_name) { $o.gpu_name } else { "Unknown" }
    $storCost = if ($o.storage_cost) { "`${0:F3}" -f $o.storage_cost } else { "?" }
    Write-Host ("{0,-4} {1,-24} {2,8} {3,10} {4,8} {5,10} {6,-22} {7}" -f "[$i]", $gpuName, $vram, $price, $rely, $storCost, $region, $o.id)
}

Write-Host ("-" * 108)
Write-Host ""

# --- Pick an offer ---
if ($NonInteractive) {
    $selected = $displayOffers[0]
    Write-Host "NonInteractive: auto-selecting best offer index 0." -ForegroundColor Cyan
} else {
    $choice = Read-Host "Enter index to rent [0], or 'q' to quit"
    if ($choice -eq 'q' -or $choice -eq 'Q') {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit 0
    }
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = 0 }
    $selected = $displayOffers[[int]$choice]
}

Write-Host ""
Write-Host "Selected: $($selected.gpu_name) — `$$($selected.dph_total)/hr (ID $($selected.id))" -ForegroundColor Green

# --- Confirm / create volume if none exists ---
if ($ollamaVol) {
    Write-Host "Found volume 'ollama_models' (ID $($ollamaVol.id)) — will attach at /root/.ollama" -ForegroundColor Green
} elseif ($volumeExistsElsewhere) {
    Write-Host ""
    Write-Host "Proceeding without volume — model weights will not persist on this instance." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "No 'ollama_models' volume found. Model weights will not persist without one." -ForegroundColor Yellow
    $createVol = if ($NonInteractive) { 'y' } else { Read-Host "Create a 60 GB persistent volume on the same host now? (Y/n)" }
    if ($createVol -notmatch '^[nN]') {
        # Storage cost cap: skip creation if cheapest offer on this machine is too expensive
        $maxVolCostPerGbMonth = 0.20
        # Prefer a volume offer on the same machine as the selected instance
        Write-Host "Searching for a volume offer on machine $($selected.machine_id)..." -ForegroundColor Cyan
        $volOffersJson = Invoke-Vastai @('search', 'volumes', '--raw', '--limit', '50', '-o', 'storage_cost', "disk_space>=60 reliability>0.99 machine_id=$($selected.machine_id)")
        try { $volOffers = $volOffersJson | ConvertFrom-Json } catch { $volOffers = @() }
        # Filter out offers that exceed the cost cap
        $volOffers = @($volOffers | Where-Object { $_.storage_cost -le $maxVolCostPerGbMonth })
        if (-not $volOffers -or $volOffers.Count -eq 0) {
            $rawCostJson = Invoke-Vastai @('search', 'volumes', '--raw', '--limit', '5', '-o', 'storage_cost', "disk_space>=60 reliability>0.99 machine_id=$($selected.machine_id)")
            try { $rawCost = ($rawCostJson | ConvertFrom-Json)[0].storage_cost } catch { $rawCost = $null }
            if ($rawCost) {
                Write-Host "Storage on this machine costs `$$([math]::Round($rawCost,3))/GB/month (~`$$([math]::Round($rawCost*60,2))/month for 60 GB) — above the `$$maxVolCostPerGbMonth cap." -ForegroundColor Yellow
                Write-Host "Pick a host with cheaper storage (see Stor/GB/mo column). Continuing without volume." -ForegroundColor Yellow
            } else {
                Write-Host "No volume offer found on that machine. Continuing without volume." -ForegroundColor Yellow
            }
            $volOffers = @()
        }
        if ($volOffers.Count -eq 0) {
            # nothing to do
        } else {
            $best = $volOffers[0]
            $costPerMonth = [math]::Round($best.storage_cost * 60, 2)
            Write-Host "Best offer: $($best.geolocation) — `$$($best.storage_cost)/GB/month = ~`$$costPerMonth/month for 60 GB (offer ID $($best.id))" -ForegroundColor Cyan
            $confirmVol = if ($NonInteractive) { 'y' } else { Read-Host "Create volume from this offer? (Y/n)" }
            if ($confirmVol -notmatch '^[nN]') {
                $createVolOut = Invoke-Vastai @('create', 'volume', "$($best.id)", '--size', '60', '--name', 'ollama_models')
                Write-Host $createVolOut
                # Re-fetch volumes to pick up the new one
                $volumeJson2 = Invoke-Vastai @('show', 'volumes', '--raw')
                try { $volumes2 = $volumeJson2 | ConvertFrom-Json } catch { $volumes2 = @() }
                $ollamaVol = $volumes2 | Where-Object { $_.label -eq 'ollama_models' } | Select-Object -First 1
                if ($ollamaVol) {
                    if ($ollamaVol.machine_id -ne $selected.machine_id) {
                        Write-Host "Note: volume is on a different host ($($ollamaVol.machine_id)) than the selected instance ($($selected.machine_id)) — cannot attach." -ForegroundColor Yellow
                        Write-Host "Re-run the script to see offers on the volume's host." -ForegroundColor Yellow
                        $ollamaVol = $null
                    } else {
                        Write-Host "Volume created (ID $($ollamaVol.id)) — will attach at /root/.ollama" -ForegroundColor Green
                    }
                } else {
                    Write-Host "Volume created but not yet visible — continuing without attach. Re-run after it appears." -ForegroundColor Yellow
                }
            } else {
                Write-Host "Skipping volume creation. Model weights will not persist." -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "Skipping volume creation. Model weights will not persist." -ForegroundColor Yellow
    }
}

# --- Confirm ---
Write-Host ""
if (-not $NonInteractive) {
    $confirm = Read-Host "Rent this instance? (y/N)"
    if ($confirm -notmatch '^[yY]') {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit 0
    }
}

# --- Rent ---
# Build the vastai create instance command
$createArgs = @(
    'create', 'instance', "$($selected.id)",
    # vastai/ollama: Ollama pre-installed, CUDA-ready, mounts /root/.ollama for model persistence
    # Image: https://hub.docker.com/r/vastai/ollama/tags  (no 'latest' tag — use explicit version)
    # Template readme: https://cloud.vast.ai/template/readme/cffafec15755aebe76d27010c0f1bce1
    '--image', 'vastai/ollama:0.24.0',
    '--disk', '80',
    '--ssh',
    '--direct'
)

if ($ollamaVol) {
    $createArgs += @('--link-volume', "$($ollamaVol.id)", '--mount-path', '/root/.ollama')
}

# --- Spot pricing for batch (min_bid field only present on --type bid search results) ---
if ($UseCase -eq 'batch' -and $selected.PSObject.Properties['min_bid'] -and $selected.min_bid) {
    $bidPrice    = [math]::Round($selected.min_bid * 1.15, 4)
    $createArgs += @('--bid_price', "$bidPrice")
    Write-Host "Interruptible bid: `$$bidPrice/hr (floor: `$$($selected.min_bid)/hr). Instance pauses if outbid -- not destroyed." -ForegroundColor Cyan
    Write-Host "  To resume if paused: vastai update instance <ID> --bid_price <higher>" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Renting instance..." -ForegroundColor Cyan
$createArgs += '--raw'
$rentResult = Invoke-Vastai $createArgs

# Parse the new instance ID from JSON response
$newInstanceId = $null
try {
    $rentJson = $rentResult | ConvertFrom-Json
    # Vast.ai sometimes returns success=false even when the contract was created.
    # Trust new_contract if present; success is unreliable.
    if ($rentJson.new_contract) {
        $newInstanceId = $rentJson.new_contract
    }
} catch {
    Write-Host "  Warning: could not parse the rent response as JSON. The raw response will be shown below." -ForegroundColor DarkYellow
}

if (-not $newInstanceId) {
    Write-Host $rentResult
    Write-Error "Failed to rent instance or could not parse instance ID from response."
    exit 1
}

Write-Host "Instance $newInstanceId created." -ForegroundColor Green

# --- Attach all registered SSH keys so the instance's authorized_keys is populated ---
# Vast.ai does not automatically inject account SSH keys at instance creation time.
# Without this step, no key is in authorized_keys and all SSH connections are rejected.
$sshKeysJson = Invoke-Vastai @('show', 'ssh-keys', '--raw')
try {
    $sshKeyObjs = $sshKeysJson | ConvertFrom-Json
    foreach ($keyObj in $sshKeyObjs) {
        $keyId = $keyObj.id
        $attachOut = Invoke-Vastai @('attach', 'ssh', "$newInstanceId", $keyObj.public_key)
        if ($attachOut -match '"success":\s*true') {
            Write-Host "  Attached SSH key $keyId to instance." -ForegroundColor Cyan
        } else {
            Write-Host "  Warning: could not attach SSH key $keyId. You may need to run 'vastai attach ssh $newInstanceId <pubkey>' manually." -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "  Warning: could not auto-attach SSH keys. Run 'vastai attach ssh $newInstanceId $(cat ~/.ssh/vast_key.pub)' manually." -ForegroundColor Yellow
}

# --- Wait for running ---
$instData = Wait-ForRunning -InstanceId $newInstanceId

if (-not $instData -or $instData['actual_status'] -ne 'running') {
    Write-Host ""
    Write-Host "Instance not yet running after 30 minutes. Check https://vast.ai/console/instances" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Instance is running!" -ForegroundColor Green

# --- Clone moved inside Open-DevServerAndChat (runs after SSH readiness check) ---

Open-DevServerAndChat -Inst $instData -UseCase $UseCase
