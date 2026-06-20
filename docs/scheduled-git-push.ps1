#Requires -Version 5.1
# =============================================================================
# scheduled-git-push.ps1
#
# Scheduled backup push routine for OQ-296 / AT-1247.
#
# Runs a no-frills `git push` across watched repos that have unpushed commits.
# Safety is structural, not heuristic:
#   - Skips any repo that is mid-rebase, merge, bisect, cherry-pick, revert,
#     or apply-mailbox -- these are transient states where pushing is never
#     sensible and git may behave unpredictably.
#   - Never passes --force, --force-with-lease, or any history-rewrite flag.
#   - Relies on git's own non-fast-forward refusal as the ultimate safety
#     boundary (the remote already disallows force-push via branch protection).
#
# Usage:
#   docs\scheduled-git-push.ps1                    # push watched repos
#   docs\scheduled-git-push.ps1 -WhatIf            # show what would happen
# =============================================================================

[CmdletBinding()]
param(
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -----------------------------------------------------------------------------
# Configuration: absolute paths to the three watched repos.
# These are the architect's active source checkouts on the local machine.
# -----------------------------------------------------------------------------
$Repos = @(
    "C:\Users\jakeh\source\repos\Electron-Splines"
    "C:\Users\jakeh\source\repos\skein-toolkit"
    "C:\Users\jakeh\source\repos\odysseus"
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

function Test-RepoInTransientState {
    param([string]$RepoPath)

    $gitDir = Join-Path $RepoPath ".git"
    if (-not (Test-Path $gitDir -PathType Container)) {
        # Not a git repo at all
        return $true
    }

    $transientMarkers = @(
        "rebase-merge"
        "rebase-apply"
        "MERGE_HEAD"
        "MERGE_MODE"
        "BISECT_LOG"
        "CHERRY_PICK_HEAD"
        "REVERT_HEAD"
    )

    foreach ($marker in $transientMarkers) {
        $p = Join-Path $gitDir $marker
        if (Test-Path $p) {
            return $true
        }
    }

    return $false
}

function Get-UnpushedCommits {
    param([string]$RepoPath)

    # @{u} = upstream branch.  If there is no upstream configured, git rev-list
    # exits non-zero.  We treat "no upstream" as "nothing to push" rather than
    # an error, because some repos may legitimately have no remote tracking.
    try {
        $count = [int](& git -C $RepoPath rev-list --count "@{u}..HEAD" 2>$null)
        return $count
    } catch {
        return 0
    }
}

function Invoke-GitPush {
    param([string]$RepoPath)

    # Explicit: no force, no lease override, no thin-pack trickery.
    # We deliberately do NOT pass --force, --force-with-lease, --delete,
    # or any refspec that could rewrite history.
    & git -C $RepoPath push 2>&1
    return $LASTEXITCODE
}

# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$results = @()

Write-Host ""
Write-Host "Scheduled Git Push - $timestamp" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

foreach ($repo in $Repos) {
    $name = Split-Path $repo -Leaf
    Write-Host ""
    Write-Host "[$name] $repo" -ForegroundColor Yellow

    # 1. Existence guard
    if (-not (Test-Path $repo -PathType Container)) {
        Write-Host "  SKIP: path does not exist" -ForegroundColor DarkGray
        $results += [PSCustomObject]@{ Repo = $name; Action = "SKIP"; Reason = "path missing"; ExitCode = $null }
        continue
    }

    # 2. Transient-state guard (rebase, merge, bisect, cherry-pick, revert)
    if (Test-RepoInTransientState -RepoPath $repo) {
        Write-Host "  SKIP: repo is in a transient state (rebase/merge/bisect/cherry-pick/revert)" -ForegroundColor DarkGray
        $results += [PSCustomObject]@{ Repo = $name; Action = "SKIP"; Reason = "transient state"; ExitCode = $null }
        continue
    }

    # 3. Unpushed-commit check
    $unpushed = Get-UnpushedCommits -RepoPath $repo
    if ($unpushed -eq 0) {
        Write-Host "  OK: nothing to push" -ForegroundColor Green
        $results += [PSCustomObject]@{ Repo = $name; Action = "OK"; Reason = "already pushed"; ExitCode = 0 }
        continue
    }

    Write-Host "  PUSH: $unpushed unpushed commit(s)" -ForegroundColor Cyan

    if ($WhatIf) {
        Write-Host "  WHATIF: would run 'git push' here" -ForegroundColor Magenta
        $results += [PSCustomObject]@{ Repo = $name; Action = "WHATIF"; Reason = "$unpushed to push"; ExitCode = $null }
        continue
    }

    # 4. Push (delegated to git's own safety rules)
    $pushOutput = Invoke-GitPush -RepoPath $repo
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "  OK: pushed successfully" -ForegroundColor Green
        $results += [PSCustomObject]@{ Repo = $name; Action = "PUSH_OK"; Reason = "pushed"; ExitCode = 0 }
    } else {
        # Git refused the push (non-fast-forward, network error, etc.).
        # We log it; the non-fast-forward case is the *intended* safety
        # boundary and should not be treated as a crash.
        Write-Host "  NOTICE: push exited $exitCode (git refused - see output above)" -ForegroundColor Yellow
        $results += [PSCustomObject]@{ Repo = $name; Action = "PUSH_REFUSED"; Reason = "git exit $exitCode"; ExitCode = $exitCode }
    }
}

Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "-------" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host

# Return data for callers (e.g. scheduled-task wrapper logging)
$results

