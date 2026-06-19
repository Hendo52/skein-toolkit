#Requires -Version 5.1
# =============================================================================
# setup-devserver.ps1  --  First-time setup wizard for the Dev Server scripts
#
# Guides a new user through:
#   1. Installing the vastai CLI (pip)
#   2. Setting their Vast.ai API key
#   3. Generating (or locating) an SSH key pair
#   4. Uploading the public key to Vast.ai
#   5. Setting their repo URL and remote path
#   6. Writing a personal config override at ~/.devserver-config.ps1
#
# Safe to re-run: skips steps that are already complete.
# =============================================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$userConfigPath = Join-Path $env:USERPROFILE '.devserver-config.ps1'
$secretRoot = Join-Path $env:LOCALAPPDATA 'Electron-Splines\devserver-secrets'
$vastaiSecretPath = Join-Path $secretRoot 'vastai-api-key.txt'
$gitHubSecretPath = Join-Path $secretRoot 'github-pat.txt'

function Write-Step { param([string]$Msg) Write-Host "`n[$Msg]" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Msg) Write-Host "  OK: $Msg" -ForegroundColor Green }
function Write-Skip { param([string]$Msg) Write-Host "  Skipped: $Msg" -ForegroundColor DarkGray }
function Prompt-User { param([string]$Msg, [string]$Default = '')
    if ($Default) { $hint = " [default: $Default]" } else { $hint = '' }
    $ans = Read-Host "  $Msg$hint"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $Default }
    return $ans.Trim()
}

function Fail-Script {
    param([string]$Message)
    Write-Error $Message
    exit 1
}

function Read-EncryptedSecret {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return '' }
    try {
        $encrypted = (Get-Content $Path -Raw).Trim()
        if ([string]::IsNullOrWhiteSpace($encrypted)) { return '' }
        $secure = ConvertTo-SecureString $encrypted
        return [System.Net.NetworkCredential]::new('', $secure).Password
    } catch {
        Fail-Script "Could not read secret file '$Path'. Delete it and run setup-devserver.ps1 again if it was created for another account. Details: $($_.Exception.Message)"
    }
}

function Save-EncryptedSecret {
    param(
        [string]$Path,
        [string]$Value,
        [string]$Label
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail-Script "$Label was left blank. The setup wizard needs a value so it can continue."
    }
    try {
        $secure = ConvertTo-SecureString $Value -AsPlainText -Force
        $encrypted = $secure | ConvertFrom-SecureString
        $parent = Split-Path $Path -Parent
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Set-Content -Path $Path -Value $encrypted -NoNewline -Encoding ASCII
    } catch {
        Fail-Script "Could not save $Label to '$Path'. Details: $($_.Exception.Message)"
    }
}

function Is-LikelyFilePath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return ($Value -match '^[A-Za-z]:\\' -or $Value -match '^\\\\')
}

function Is-GitRepoUrl {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    return ($Value -match '^https://[^\s]+$' -or $Value -match '^http://[^\s]+$' -or $Value -match '^git@[^\s]+:[^\s]+$')
}

function Is-UnixAbsolutePath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    return ($Value -match '^/[^\s]*$')
}

function Get-RepoFolderNameFromUrl {
    param([string]$RepoUrl)
    if ([string]::IsNullOrWhiteSpace($RepoUrl)) { return '' }
    $trimmed = $RepoUrl.Trim()
    if ($trimmed -match '^https?://[^/]+/.+/.+$') {
        $name = ($trimmed -split '/')[ -1 ]
        if ($name.EndsWith('.git')) { $name = $name.Substring(0, $name.Length - 4) }
        return $name
    }
    if ($trimmed -match '^git@[^:]+:.+/.+$') {
        $name = ($trimmed -split '/')[ -1 ]
        if ($name.EndsWith('.git')) { $name = $name.Substring(0, $name.Length - 4) }
        return $name
    }
    return ''
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "  Dev Server First-Time Setup" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "  This wizard configures your personal settings."
Write-Host "  Your settings are saved to: $userConfigPath"
Write-Host "  You can re-run this wizard at any time to change them."
Write-Host ""

# Load existing user config if present (so we show current values as defaults)
$existingKey          = ''
$existingRepo         = '/workspace/Electron-Splines'
$existingRepoUrl      = ''
$existingVastAiKey    = ''
$existingGitHubToken  = ''
$existingBatchPath    = ''
$DevServerKey         = ''
$DevServerRepo        = ''
$DevServerRepoUrl     = ''
$DevServerGitHubToken = ''
if (Test-Path $userConfigPath) {
    try {
        . $userConfigPath
    } catch {
        Fail-Script "Could not load existing user config '$userConfigPath'. Details: $($_.Exception.Message)"
    }
    if ($DevServerKey)          { $existingKey          = $DevServerKey }
    if ($DevServerRepo)         { $existingRepo         = $DevServerRepo }
    if ($DevServerRepoUrl)      { $existingRepoUrl      = $DevServerRepoUrl }
    if ($DevServerGitHubToken)  { $existingGitHubToken  = $DevServerGitHubToken }
    if ($BatchFilePath)         { $existingBatchPath    = $BatchFilePath }
}
if (-not $existingKey) { $existingKey = "$env:USERPROFILE\.ssh\vast_key" }
if (($existingRepo -eq '/root/repo' -or [string]::IsNullOrWhiteSpace($existingRepo)) -and -not [string]::IsNullOrWhiteSpace($existingRepoUrl)) {
    $repoNameFromExistingUrl = Get-RepoFolderNameFromUrl $existingRepoUrl
    if (-not [string]::IsNullOrWhiteSpace($repoNameFromExistingUrl)) {
        $existingRepo = "/workspace/$repoNameFromExistingUrl"
    }
}

$storedVastAiKey = Read-EncryptedSecret $vastaiSecretPath
if ($storedVastAiKey) { $existingVastAiKey = $storedVastAiKey }
$storedGitHubToken = Read-EncryptedSecret $gitHubSecretPath
if ($storedGitHubToken) { $existingGitHubToken = $storedGitHubToken }

# ===========================================================================
# STEP 1: vastai CLI
# ===========================================================================
Write-Step "Step 1/6: vastai CLI"
$vastaiExe = (Get-Command vastai -ErrorAction SilentlyContinue)?.Source
if (-not $vastaiExe) {
    $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
    if (Test-Path $fallback) { $vastaiExe = $fallback }
}
if ($vastaiExe) {
    Write-Ok "vastai found at $vastaiExe"
} else {
    Write-Host "  vastai CLI not found. Installing via pip..." -ForegroundColor Yellow
    $pip = (Get-Command pip -ErrorAction SilentlyContinue)?.Source
    if (-not $pip) { $pip = (Get-Command pip3 -ErrorAction SilentlyContinue)?.Source }
    if (-not $pip) {
        Write-Host "  ERROR: pip not found. Install Python 3 from https://python.org then re-run this wizard." -ForegroundColor Red
        exit 1
    }
    & $pip install vastai --quiet
    $vastaiExe = (Get-Command vastai -ErrorAction SilentlyContinue)?.Source
    if (-not $vastaiExe) {
        $fallback = "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\vastai.exe"
        if (Test-Path $fallback) { $vastaiExe = $fallback }
    }
    if ($vastaiExe) { Write-Ok "vastai installed at $vastaiExe" }
    else {
        Write-Host "  ERROR: vastai install succeeded but executable not found. Add Python Scripts to PATH and re-run." -ForegroundColor Red
        exit 1
    }
}

# ===========================================================================
# STEP 2: Vast.ai API key
# ===========================================================================
Write-Step "Step 2/6: Vast.ai API key"
Write-Host "  Get your API key from: https://cloud.vast.ai/account/" -ForegroundColor DarkGray
if ($existingVastAiKey) {
    $testOut = & $vastaiExe show user --api-key $existingVastAiKey --raw 2>&1 | Out-String
    if ($testOut -notmatch '"error"' -and $testOut -match '"id"') {
        Write-Ok "API key already configured securely."
    } else {
        Write-Host "  Stored Vast.ai API key did not validate. Please enter a new key." -ForegroundColor Yellow
        $existingVastAiKey = ''
    }
}

if (-not $existingVastAiKey) {
    $apiKey = ''
    while ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Host "  Paste your Vast.ai API key (input is hidden):" -ForegroundColor Yellow
        $secureApiKey = Read-Host "  API Key" -AsSecureString
        $apiKey = [System.Net.NetworkCredential]::new('', $secureApiKey).Password
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            Write-Host "  A Vast.ai API key is required." -ForegroundColor Red
        }
    }
    $testOut = & $vastaiExe show user --api-key $apiKey --raw 2>&1 | Out-String
    if ($testOut -match '"error"' -or $testOut -notmatch '"id"') {
        Fail-Script "The Vast.ai API key did not validate. Check the key at https://cloud.vast.ai/account/ and run setup-devserver.ps1 again."
    }
    Save-EncryptedSecret -Path $vastaiSecretPath -Value $apiKey -Label 'Vast.ai API key'
    Write-Ok "API key saved securely to $vastaiSecretPath"
}

# ===========================================================================
# STEP 3: SSH key
# ===========================================================================
Write-Step "Step 3/6: SSH key"
# If a previous bad config stored the key content instead of the file path, reset to default.
if ($existingKey -match '^(ssh-|ecdsa-|sk-|-----BEGIN)' -or -not (Is-LikelyFilePath $existingKey)) {
    Write-Host "  WARNING: \$DevServerKey in your config looks like a key content string, not a file path." -ForegroundColor Yellow
    Write-Host "  Resetting to default path: $env:USERPROFILE\.ssh\vast_key" -ForegroundColor Yellow
    $existingKey = "$env:USERPROFILE\.ssh\vast_key"
}
$sshKeyPath = Prompt-User "Path to your SSH private key" $existingKey
# Guard: reject key content accidentally pasted as a path.
while ($sshKeyPath -match '^(ssh-|ecdsa-|sk-|-----BEGIN)' -or -not (Is-LikelyFilePath $sshKeyPath)) {
    Write-Host "  That does not look like a file path. Enter a path such as C:\Users\you\.ssh\vast_key." -ForegroundColor Red
    $sshKeyPath = Prompt-User "Path to your SSH private key" "$env:USERPROFILE\.ssh\vast_key"
}
$sshPubPath = "${sshKeyPath}.pub"

if (-not (Test-Path $sshKeyPath)) {
    Write-Host "  No key found at $sshKeyPath -- generating a new one..." -ForegroundColor Yellow
    $sshDir = Split-Path $sshKeyPath -Parent
    if (-not [string]::IsNullOrWhiteSpace($sshDir) -and -not (Test-Path $sshDir)) {
        New-Item -ItemType Directory -Path $sshDir | Out-Null
    }
    & ssh-keygen -t ed25519 -f $sshKeyPath -N '""' -C "vast-devserver" 2>&1 | Out-Null
    Write-Ok "Key pair generated: $sshKeyPath"
} else {
    Write-Ok "Key already exists: $sshKeyPath"
}

# ===========================================================================
# STEP 4: Upload public key to Vast.ai
# ===========================================================================
Write-Step "Step 4/6: Upload SSH public key to Vast.ai"
if (Test-Path $sshPubPath) {
    $pubKeyContent = (Get-Content $sshPubPath -Raw).Trim()
    # Check if this key is already registered
    $keysOut = & $vastaiExe --api-key $existingVastAiKey show ssh-keys 2>&1 | Out-String
    if ($keysOut -match [regex]::Escape($pubKeyContent)) {
        Write-Skip "Public key already registered with Vast.ai."
    } else {
        $addOut = & $vastaiExe --api-key $existingVastAiKey create ssh-key $sshPubPath -y 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or $addOut -match 'error') {
            Fail-Script "Could not upload the SSH public key to Vast.ai. Details: $addOut"
        }
        Write-Ok "Public key uploaded to Vast.ai."
    }
} else {
    Fail-Script "Public key not found at $sshPubPath. Generate the SSH key pair first, then re-run this wizard."
}

# ===========================================================================
# STEP 5: Repo settings
# ===========================================================================
Write-Step "Step 5/6: Repository settings"
Write-Host "  These are used to clone your repo onto the rented GPU instance." -ForegroundColor DarkGray
$repoUrl  = Prompt-User "Git repo URL (e.g. https://github.com/you/your-repo.git or leave blank to skip)" $existingRepoUrl
while (-not (Is-GitRepoUrl $repoUrl)) {
    Write-Host "  That does not look like a Git repo URL. Enter https://..., http://..., git@..., or press Enter to skip." -ForegroundColor Red
    $repoUrl = Prompt-User "Git repo URL (e.g. https://github.com/you/your-repo.git or leave blank to skip)" ""
}
$repoNameFromUrl = Get-RepoFolderNameFromUrl $repoUrl
$repoPathDefault = $existingRepo
if (-not [string]::IsNullOrWhiteSpace($repoNameFromUrl)) {
    $repoPathDefault = "/workspace/$repoNameFromUrl"
}
# Guard: remote path must be a Unix absolute path, not a URL or Windows path
$repoPath = Prompt-User "Remote path on instance (Unix absolute path, e.g. /workspace/my-repo)" $repoPathDefault
while ($repoPath -match '^https?://' -or $repoPath -match '^[A-Za-z]:\\' -or -not (Is-UnixAbsolutePath $repoPath)) {
    Write-Host "  That looks like a URL or Windows path. Enter a Unix absolute path (e.g. /workspace/my-repo)." -ForegroundColor Red
    $repoPath = Prompt-User "Remote path on instance (Unix absolute path, e.g. /workspace/my-repo)" "/workspace/repo"
}
Write-Host "" 
Write-Host "  GitHub token (for private repos):" -ForegroundColor DarkGray
Write-Host "  Create a Fine-grained token with Contents=read at https://github.com/settings/tokens" -ForegroundColor DarkGray
Write-Host "  Leave blank if your repo is public." -ForegroundColor DarkGray
$gitHubToken = $existingGitHubToken
if (-not [string]::IsNullOrWhiteSpace($repoUrl) -and $repoUrl -match '^https://github.com/') {
    if ($gitHubToken) {
        $testUrl = $repoUrl -replace '^https://github.com/', "https://x-access-token:$gitHubToken@github.com/"
        $probeOut = & git ls-remote --heads $testUrl 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "GitHub token already configured securely."
        } else {
            Write-Host "  Stored GitHub token did not validate for $repoUrl. Enter a new token or press Enter if the repo is public." -ForegroundColor Yellow
            $gitHubToken = ''
        }
    }

    if (-not $gitHubToken) {
        Write-Host "  Paste your GitHub token now, or press Enter if the repo is public." -ForegroundColor Yellow
        $secureToken = Read-Host "  GitHub token" -AsSecureString
        $gitHubToken = [System.Net.NetworkCredential]::new('', $secureToken).Password
        if (-not [string]::IsNullOrWhiteSpace($gitHubToken)) {
            $testUrl = $repoUrl -replace '^https://github.com/', "https://x-access-token:$gitHubToken@github.com/"
            $probeOut = & git ls-remote --heads $testUrl 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Fail-Script "The GitHub token could not access '$repoUrl'. Check that the token has Contents: read access for this repository and re-run setup-devserver.ps1. Details: $probeOut"
            }
            Save-EncryptedSecret -Path $gitHubSecretPath -Value $gitHubToken -Label 'GitHub personal access token'
            Write-Ok "GitHub token saved securely to $gitHubSecretPath"
        } else {
            $probeOut = & git ls-remote --heads $repoUrl 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Fail-Script "'$repoUrl' could not be read anonymously. It appears to be private, so a GitHub token is required. Re-run setup-devserver.ps1 and enter a token. Details: $probeOut"
            }
            Write-Ok "Public repo detected; no GitHub token stored."
        }
    }
} elseif (-not [string]::IsNullOrWhiteSpace($repoUrl)) {
    Write-Host "  Repo URL does not look like GitHub; skipping GitHub token prompt." -ForegroundColor DarkGray
}

# ===========================================================================
# STEP 6: Tik/tok batch file
# ===========================================================================
Write-Step "Step 6/6: Tik/tok batch file"
Write-Host "  If you use the tik/tok dual-queue system, point to your batch file." -ForegroundColor DarkGray
Write-Host "  Leave blank to disable batch-aware mode." -ForegroundColor DarkGray
$batchPath = Prompt-User "Path to your project's tik/tok batch file" $existingBatchPath
while ($batchPath -and -not (Is-LikelyFilePath $batchPath)) {
    Write-Host "  That does not look like a file path. Enter an absolute Windows path (e.g. C:\Users\you\project\ai-task-tik.md) or leave blank." -ForegroundColor Red
    $batchPath = Prompt-User "Path to your project's tik/tok batch file" ""
}
if (-not $batchPath) { $batchPath = '' }

# ===========================================================================
# Write user config
# ===========================================================================
$configLines = @(
    "# Dev Server user config -- generated by setup-devserver.ps1"
    "# Edit this file directly or re-run setup-devserver.ps1 to change settings."
    ""
    "# Path to your SSH private key"
    "`$DevServerKey = `"$sshKeyPath`""
    ""
    "# Remote repo path on the instance"
    "`$DevServerRepo = `"$repoPath`""
    ""
    "# Git repo URL cloned onto a fresh instance (leave blank to skip)"
    "`$DevServerRepoUrl = `"$repoUrl`""
    ""
    "# GitHub personal access token is stored securely under LOCALAPPDATA."
    "# KEEP THIS FILE OUT OF VERSION CONTROL."
    "`$DevServerGitHubToken = ''"
    ""
    "# Path to your project's tik/tok batch file (leave blank to disable)"
    "`$BatchFilePath = `"$batchPath`""
)
try {
    [System.IO.File]::WriteAllLines($userConfigPath, $configLines)
    Write-Ok "Config written to $userConfigPath"
} catch {
    Fail-Script "Could not write user config to '$userConfigPath'. Details: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Setup complete! Run the Dev Server task in VS Code," -ForegroundColor Green
Write-Host "  or: scripts\rent-devserver.ps1" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
