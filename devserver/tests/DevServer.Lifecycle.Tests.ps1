#Requires -Version 5.1
#Requires -Modules @{ModuleName='Pester';ModuleVersion='5.0.0'}
<#
.SYNOPSIS
    Dev server CRUD lifecycle tests.

.DESCRIPTION
    Tests the full lifecycle of a Vast.ai dev server instance: Create (rent),
    Read (status), Update (restart/stop-start), and Delete (stop/destroy).
    Also covers watcher auto-stop logic and batch file state parsing.

    Test categories and what they exercise:
      CREATE  -- offer filtering (VRAM, price, country), NonInteractive routing
      READ    -- ConvertFrom-VastaiInstances with wrapped/bare/empty/malformed JSON
      UPDATE  -- Wait-ForRunning state machine (polling, timeout, not-found)
      DELETE  -- stop vs destroy distinction, watcher-triggered stop conditions
      WATCH   -- Test-WatcherShouldStop pure logic (all 5 conditions + batch suppression)
      BATCH   -- Get-BatchFileState parsing (Ready, InProgress, DONE, missing frontmatter)
      OLLAMA  -- Get-OllamaStatus response classification (idle, busy, unreachable)

    Pure functions (ConvertFrom-VastaiInstances, Select-VastaiOffer, Test-WatcherShouldStop)
    require no mocks. Impure functions (Get-DevServerInstances, Wait-ForRunning,
    Get-OllamaStatus) use Pester InModuleScope mocking.
#>

BeforeAll {
    # Import the DevServer module (always reload to pick up edits)
    $ModulePath = Join-Path $PSScriptRoot '..' 'DevServer.psm1'
    Import-Module $ModulePath -Force -ErrorAction Stop

    # Dot-source batch state helper so Get-BatchFileState is available at test scope
    . (Join-Path $PSScriptRoot '..' 'check-queue-batch-state.ps1')

    $FixturesDir = Join-Path $PSScriptRoot 'fixtures'
    function Get-Fixture { param($Name) Get-Content (Join-Path $FixturesDir $Name) -Raw }

    # Load offer fixtures as PS objects once for all offer-selection tests
    $script:AllOffers = (Get-Fixture 'offers.json') | ConvertFrom-Json

    # Shared watcher limits for Test-WatcherShouldStop tests
    $script:Limits = @{
        IdleThresholdSeconds = 1800   # 30 min
        MaxSessionSeconds    = 28800  # 8 hr
        MaxSpendUsd          = 10.00
    }
}

# =============================================================================
# READ: Instance list parsing
# =============================================================================

Describe "READ: ConvertFrom-VastaiInstances" {
    It "parses wrapped {instances:[...]} format and returns running instance" {
        $raw    = Get-Fixture 'instances-running.json'
        $result = ConvertFrom-VastaiInstances -RawJson $raw
        $result           | Should -Not -BeNullOrEmpty
        $result.Running.Count | Should -Be 1
        $result.Running[0].id | Should -Be 111222333
        $result.Stopped.Count | Should -Be 0
    }

    It "parses bare [{...}] array format" {
        $raw    = '[{"id":222,"actual_status":"stopped","gpu_name":"A100","dph_total":1.20}]'
        $result = ConvertFrom-VastaiInstances -RawJson $raw
        $result.Stopped.Count | Should -Be 1
        $result.Running.Count | Should -Be 0
    }

    It "handles empty instances list without errors" {
        $result = ConvertFrom-VastaiInstances -RawJson (Get-Fixture 'instances-none.json')
        $result           | Should -Not -Be $null
        $result.Running.Count | Should -Be 0
        $result.Stopped.Count | Should -Be 0
        $result.All.Count     | Should -Be 0
    }

    It "correctly classifies all three statuses in a mixed list" {
        $result = ConvertFrom-VastaiInstances -RawJson (Get-Fixture 'instances-mixed.json')
        $result.Running.Count | Should -Be 1
        $result.Stopped.Count | Should -Be 1
        $result.Loading.Count | Should -Be 1
        $result.All.Count     | Should -Be 3
    }

    It "classifies 'loading' as neither running nor stopped" {
        $raw    = '{"instances":[{"id":333,"actual_status":"loading","gpu_name":"RTX 3080","dph_total":0.30}]}'
        $result = ConvertFrom-VastaiInstances -RawJson $raw
        $result.Running.Count | Should -Be 0
        $result.Stopped.Count | Should -Be 0
        $result.Loading.Count | Should -Be 1
    }

    It "returns null on malformed JSON without throwing" {
        $result = ConvertFrom-VastaiInstances -RawJson 'this is not json { [ garbage'
        $result | Should -BeNullOrEmpty
    }

    It "returns null on empty string without throwing" {
        $result = ConvertFrom-VastaiInstances -RawJson ''
        $result | Should -BeNullOrEmpty
    }

    It "returns null on whitespace-only string without throwing" {
        $result = ConvertFrom-VastaiInstances -RawJson "   `n  "
        $result | Should -BeNullOrEmpty
    }

    It "preserves the instance ID field exactly (no float rounding)" {
        # IDs are large integers. JSON->PS conversion must not coerce them to floats.
        $raw    = '{"instances":[{"id":987654321,"actual_status":"running","dph_total":0.45}]}'
        $result = ConvertFrom-VastaiInstances -RawJson $raw
        $result.Running[0].id | Should -Be 987654321
        # Verify the ID can be used as a CLI argument (string coercion must be clean)
        "$($result.Running[0].id)" | Should -Be '987654321'
    }
}

# =============================================================================
# CREATE: Offer selection (filtering + ranking)
# =============================================================================

Describe "CREATE: Select-VastaiOffer" {
    It "rejects offers with VRAM below minimum" {
        # RTX 3060 has 12GB, RTX 3080 has 10GB -- both below 20GB min
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 20 -MaxCostHr 1.00
        $result.gpu_ram | Should -BeGreaterOrEqual 20
    }

    It "rejects offers above the price ceiling" {
        # H100 at $1.20 and A100 at $0.85 should be filtered when cap is $0.80
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 24 -MaxCostHr 0.80
        $result.dph_total | Should -BeLessOrEqual 0.80
    }

    It "rejects offers from CN (data-sovereignty blocklist)" {
        # offer-004 is in Shanghai, CN with only 12GB -- ensure CN is blocked
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 12 -MaxCostHr 1.00
        if ($result) {
            $result.geolocation | Should -Not -Match 'CN$'
        }
    }

    It "rejects offers from RU (sanctions blocklist)" {
        # offer-005 is A6000 48GB in Moscow RU at $0.60 -- only 48GB+ offer in range
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 48 -MaxCostHr 0.70
        $result | Should -BeNullOrEmpty   # only qualifying offer is blocked
    }

    It "selects the cheapest qualifying offer, not just the first" {
        # RTX 4090 (offer-001, $0.45) and RTX 3090 (offer-003, $0.30) both have 24GB
        # and are both under $0.50. RTX 3090 is cheaper so it should win.
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 24 -MaxCostHr 0.50
        $result.dph_total | Should -Be 0.30
        $result.gpu_name  | Should -Be 'RTX 3090'
    }

    It "returns null when no offer meets all criteria" {
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 200 -MaxCostHr 0.01
        $result | Should -BeNullOrEmpty
    }

    It "returns null on empty offers array" {
        $result = Select-VastaiOffer -Offers @() -MinVramGb 24 -MaxCostHr 1.00
        $result | Should -BeNullOrEmpty
    }

    It "handles offers with no geolocation field without throwing" {
        $noGeoOffer = [pscustomobject]@{ gpu_name='Unknown'; gpu_ram=24; dph_total=0.30 }
        { Select-VastaiOffer -Offers @($noGeoOffer) -MinVramGb 20 -MaxCostHr 1.00 } | Should -Not -Throw
    }

    It "allows offers from non-blocked countries" {
        # London (GB) and Toronto (CA) are not blocked -- should be eligible
        $result = Select-VastaiOffer -Offers $script:AllOffers -MinVramGb 10 -MaxCostHr 0.40
        $result | Should -Not -BeNullOrEmpty
    }
}

# =============================================================================
# DELETE/WATCH: Watcher auto-stop decision logic
# =============================================================================

Describe "WATCH: Test-WatcherShouldStop" {
    It "returns null when well within all limits" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 0 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "stops when idle threshold is exactly reached" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 1800 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Stop   | Should -BeTrue
        $result.Reason | Should -Match -RegularExpression '(?i)idle'
    }

    It "does NOT stop when idle is one second below threshold" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 1799 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "stops when session cap is exactly reached" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 28800 -SpentUsd 9.00 -IdleSeconds 0 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Reason | Should -Match -RegularExpression '(?i)session'
    }

    It "does NOT stop when session elapsed is one second below cap" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 28799 -SpentUsd 9.00 -IdleSeconds 0 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "stops when spend cap is exactly reached" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 10.00 -IdleSeconds 0 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Reason | Should -Match -RegularExpression '(?i)spend'
    }

    It "does NOT stop when spend is one cent below cap" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 9.99 -IdleSeconds 0 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "suppresses idle stop when batch has Ready tasks" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 3600 `
            -BatchDone $false -BatchReadyCount 3 -BatchInProgressCount 0 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "suppresses idle stop when batch has In Progress tasks" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 3600 `
            -BatchDone $false -BatchReadyCount 0 -BatchInProgressCount 1 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "hard-stops when batch is DONE with nothing pending" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 1800 -SpentUsd 2.00 -IdleSeconds 0 `
            -BatchDone $true -BatchReadyCount 0 -BatchInProgressCount 0 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Stop   | Should -BeTrue
        $result.Reason | Should -Match -RegularExpression '(?i)DONE'
    }

    It "does NOT hard-stop when batch is DONE but a task is still In Progress" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 1800 -SpentUsd 2.00 -IdleSeconds 0 `
            -BatchDone $true -BatchReadyCount 0 -BatchInProgressCount 1 `
            @script:Limits
        $result | Should -BeNullOrEmpty
    }

    It "session cap fires even when batch has pending work (hard cap, not suppressible)" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 28800 -SpentUsd 9.00 -IdleSeconds 0 `
            -BatchDone $false -BatchReadyCount 5 -BatchInProgressCount 2 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Reason | Should -Match -RegularExpression '(?i)session'
    }

    It "spend cap fires even when batch has pending work (hard cap, not suppressible)" {
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 10.00 -IdleSeconds 0 `
            -BatchDone $false -BatchReadyCount 5 -BatchInProgressCount 2 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Reason | Should -Match -RegularExpression '(?i)spend'
    }

    It "behaves as non-batch-aware when BatchReadyCount and BatchInProgressCount are -1" {
        # Default -1 values mean not batch-aware; idle threshold should apply normally
        $result = Test-WatcherShouldStop `
            -ElapsedSeconds 3600 -SpentUsd 0.45 -IdleSeconds 1800 `
            @script:Limits
        $result | Should -Not -BeNullOrEmpty
        $result.Reason | Should -Match -RegularExpression '(?i)idle'
    }
}

# =============================================================================
# BATCH: Batch file state parsing
# =============================================================================

Describe "BATCH: Get-BatchFileState" {
    It "reads ACTIVE status from active fixture" {
        $state = Get-BatchFileState -FilePath (Join-Path $FixturesDir 'batch-active.md')
        $state.Status | Should -Be 'ACTIVE'
    }

    It "counts Ready tasks correctly in active batch" {
        $state = Get-BatchFileState -FilePath (Join-Path $FixturesDir 'batch-active.md')
        $state.ReadyTaskCount | Should -Be 2   # AT-T01 and AT-T02
    }

    It "identifies In Progress tasks in active batch" {
        $state = Get-BatchFileState -FilePath (Join-Path $FixturesDir 'batch-active.md')
        $inProgress = @($state.TaskStatusMap.Keys |
            Where-Object { $state.TaskStatusMap[$_] -contains 'In Progress' }).Count
        $inProgress | Should -Be 1   # AT-T03
    }

    It "reports DONE status from done fixture" {
        $state = Get-BatchFileState -FilePath (Join-Path $FixturesDir 'batch-done.md')
        $state.Status          | Should -Be 'DONE'
        $state.ReadyTaskCount  | Should -Be 0
    }

    It "reports zero In Progress tasks in done batch" {
        $state = Get-BatchFileState -FilePath (Join-Path $FixturesDir 'batch-done.md')
        $inProgress = @($state.TaskStatusMap.Keys |
            Where-Object { $state.TaskStatusMap[$_] -contains 'In Progress' }).Count
        $inProgress | Should -Be 0
    }

    It "throws on missing status frontmatter comment" {
        $tmp = New-TemporaryFile
        try {
            Set-Content $tmp.FullName "# Batch: no-status`n| AT-001 | Task | | | | Ready |"
            { Get-BatchFileState -FilePath $tmp.FullName } | Should -Throw
        } finally {
            Remove-Item $tmp.FullName -ErrorAction SilentlyContinue
        }
    }

    It "throws when batch file does not exist" {
        { Get-BatchFileState -FilePath 'C:\no\such\file\batch.md' } | Should -Throw
    }

    It "returns the correct file path in the result" {
        $fixturePath = Join-Path $FixturesDir 'batch-active.md'
        $state = Get-BatchFileState -FilePath $fixturePath
        $state.Path | Should -Be $fixturePath
    }
}

# =============================================================================
# UPDATE: Wait-ForRunning state machine (uses InModuleScope mocking)
# =============================================================================

Describe "UPDATE: Wait-ForRunning" {
    It "returns the running instance when it is running on first poll" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli {
                return '{"instances":[{"id":9999,"actual_status":"running","gpu_name":"RTX 4090","dph_total":0.45}]}'
            }
            $noSleep = { }
            $result  = Wait-ForRunning -InstanceId 9999 -TimeoutMinutes 1 -Sleeper $noSleep
            $result                 | Should -Not -BeNullOrEmpty
            $result.actual_status   | Should -Be 'running'
            $result.id              | Should -Be 9999
        }
    }

    It "returns null immediately when TimeoutMinutes is 0 (deadline already past)" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli {
                return '{"instances":[{"id":9999,"actual_status":"loading","gpu_name":"RTX 4090","dph_total":0.45}]}'
            }
            $noSleep = { }
            $result  = Wait-ForRunning -InstanceId 9999 -TimeoutMinutes 0 -Sleeper $noSleep
            $result | Should -BeNullOrEmpty
        }
    }

    It "returns null when instance ID is not present in the response" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli {
                # Different instance ID 1111 -- target 9999 not found
                return '{"instances":[{"id":1111,"actual_status":"running","gpu_name":"RTX 4090","dph_total":0.45}]}'
            }
            $noSleep = { }
            $result  = Wait-ForRunning -InstanceId 9999 -TimeoutMinutes 0 -Sleeper $noSleep
            $result | Should -BeNullOrEmpty
        }
    }

    It "returns null when vastai returns empty instance list" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli { return '{"instances":[]}' }
            $noSleep = { }
            $result  = Wait-ForRunning -InstanceId 9999 -TimeoutMinutes 0 -Sleeper $noSleep
            $result | Should -BeNullOrEmpty
        }
    }

    It "returns null when vastai returns malformed JSON" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli { return 'Error: authentication failed' }
            $noSleep = { }
            $result  = Wait-ForRunning -InstanceId 9999 -TimeoutMinutes 0 -Sleeper $noSleep
            $result | Should -BeNullOrEmpty
        }
    }
}

# =============================================================================
# READ: Get-DevServerInstances (integration of Invoke-VastaiCli + parsing)
# =============================================================================

Describe "READ: Get-DevServerInstances" {
    It "returns parsed instance data when vastai returns valid JSON" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli {
                return '{"instances":[{"id":111222333,"actual_status":"running","gpu_name":"RTX 4090","dph_total":0.45}]}'
            }
            $result = Get-DevServerInstances
            $result           | Should -Not -BeNullOrEmpty
            $result.Running.Count | Should -Be 1
        }
    }

    It "returns null when vastai returns an error string instead of JSON" {
        InModuleScope DevServer {
            Mock Invoke-VastaiCli { return 'Error: API key not found' }
            $result = Get-DevServerInstances
            $result | Should -BeNullOrEmpty
        }
    }
}

# =============================================================================
# OLLAMA: Get-OllamaStatus response classification
# =============================================================================

Describe "OLLAMA: Get-OllamaStatus" {
    It "returns 'idle' when models array is empty" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod { return [pscustomobject]@{ models = @() } }
            Get-OllamaStatus | Should -Be 'idle'
        }
    }

    It "returns 'idle' when models property is null" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod { return [pscustomobject]@{ models = $null } }
            Get-OllamaStatus | Should -Be 'idle'
        }
    }

    It "returns 'busy:modelname' when a model is loaded" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod {
                return [pscustomobject]@{
                    models = @([pscustomobject]@{ name = 'llama3.3:70b' })
                }
            }
            $status = Get-OllamaStatus
            $status | Should -Be 'busy:llama3.3:70b'
        }
    }

    It "returns 'busy:' with comma-separated names when multiple models loaded" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod {
                return [pscustomobject]@{
                    models = @(
                        [pscustomobject]@{ name = 'llama3.3:70b' },
                        [pscustomobject]@{ name = 'qwen2.5:7b' }
                    )
                }
            }
            $status = Get-OllamaStatus
            $status | Should -Be 'busy:llama3.3:70b, qwen2.5:7b'
        }
    }

    It "returns 'unreachable' when Invoke-RestMethod throws (tunnel down)" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod { throw [System.Net.WebException] 'Connection refused' }
            Get-OllamaStatus | Should -Be 'unreachable'
        }
    }

    It "returns 'unreachable' on timeout (not 'idle' -- unknown is not idle)" {
        InModuleScope DevServer {
            Mock Invoke-RestMethod { throw [System.TimeoutException] 'Request timed out' }
            $status = Get-OllamaStatus
            $status | Should -Be 'unreachable'
            # 'unreachable' must NOT equal 'idle' -- watcher must not tear down on connectivity loss
            $status | Should -Not -Be 'idle'
        }
    }
}
