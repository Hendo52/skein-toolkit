#Requires -Module Pester
# =============================================================================
# scheduled-git-push.Tests.ps1
#
# AT-1247 exit evidence: "verified it does not act on a repo mid-rebase or
# other transient state ... confirmed by test." Real repos (created in a temp
# directory, not mocked) are put into each transient state and the
# transient-state guard is verified to actually detect them.
#
# Run with: Invoke-Pester docs\scheduled-git-push.Tests.ps1
# =============================================================================

BeforeAll {
    . "$PSScriptRoot\scheduled-git-push.ps1" -WhatIf 2>$null | Out-Null
    # Sourcing with -WhatIf and no real $Repos match avoids the main loop
    # doing anything real; we only need Test-RepoInTransientState defined.
}

Describe "Test-RepoInTransientState" {
    BeforeEach {
        $script:TestRepo = Join-Path ([System.IO.Path]::GetTempPath()) "at1247-test-$(New-Guid)"
        New-Item -ItemType Directory -Path $script:TestRepo -Force | Out-Null
        Push-Location $script:TestRepo
        git init --quiet | Out-Null
        git config user.email "test@example.com" | Out-Null
        git config user.name "Test" | Out-Null
        "x" | Out-File "f.txt"
        git add f.txt | Out-Null
        git commit -m "initial" --quiet | Out-Null
    }

    AfterEach {
        Pop-Location
        Remove-Item -Recurse -Force $script:TestRepo -ErrorAction SilentlyContinue
    }

    It "returns false for a clean, non-transient repo" {
        Test-RepoInTransientState -RepoPath $script:TestRepo | Should -Be $false
    }

    It "returns true for a repo mid-merge (real MERGE_HEAD)" {
        git checkout -b branch-a --quiet | Out-Null
        "y" | Out-File "f.txt"
        git commit -am "branch-a change" --quiet | Out-Null
        git checkout main --quiet 2>$null
        if ($LASTEXITCODE -ne 0) { git checkout master --quiet | Out-Null }
        "z" | Out-File "f.txt"
        git commit -am "main change" --quiet | Out-Null
        git merge branch-a --no-edit 2>$null | Out-Null
        # Real conflict -> real MERGE_HEAD left on disk
        Test-RepoInTransientState -RepoPath $script:TestRepo | Should -Be $true
    }

    It "returns true for a repo mid-rebase (real rebase-merge dir)" {
        $defaultBranch = (git branch --show-current).Trim()
        git checkout -b branch-b --quiet | Out-Null
        "y" | Out-File "f.txt" -Encoding ascii
        git commit -am "branch-b change" --quiet | Out-Null
        git checkout $defaultBranch --quiet | Out-Null
        "z" | Out-File "f.txt" -Encoding ascii
        git commit -am "conflicting main change" --quiet | Out-Null
        git checkout branch-b --quiet | Out-Null
        git rebase $defaultBranch 2>$null | Out-Null
        # Real conflicting rebase leaves .git/rebase-merge or rebase-apply on disk
        Test-RepoInTransientState -RepoPath $script:TestRepo | Should -Be $true
    }

    It "returns true for a path that is not a git repo at all" {
        $notARepo = Join-Path ([System.IO.Path]::GetTempPath()) "at1247-not-a-repo-$(New-Guid)"
        New-Item -ItemType Directory -Path $notARepo -Force | Out-Null
        try {
            Test-RepoInTransientState -RepoPath $notARepo | Should -Be $true
        } finally {
            Remove-Item -Recurse -Force $notARepo -ErrorAction SilentlyContinue
        }
    }
}

Describe "Invoke-GitPush argument safety" {
    It "the actual git push invocation line (not surrounding comments) never passes a force flag" {
        # Isolate just the executable invocation line itself, not the
        # function's documentation comments (which deliberately mention
        # --force to say it's NOT used -- a substring match on the whole
        # function body would false-positive on those comments).
        $funcDef = (Get-Item "function:Invoke-GitPush").Definition
        $invocationLine = ($funcDef -split "`n" | Where-Object { $_ -match '^\s*&\s*git\s' })
        $invocationLine | Should -Not -BeNullOrEmpty
        $invocationLine | Should -Not -Match '--force'
        $invocationLine | Should -Match '^\s*&\s*git\s+-C\s+\$RepoPath\s+push\s+2>&1\s*$'
    }
}
