Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-BatchFileState {
	param(
		[Parameter(Mandatory = $true)][string]$FilePath
	)

	if (-not (Test-Path -LiteralPath $FilePath)) {
		throw "Batch file not found: $FilePath"
	}

	$raw = Get-Content -LiteralPath $FilePath -Raw
	$statusMatch = [regex]::Match($raw, '<!--\s*Status:\s*([A-Za-z-]+)\s*-->')
	if (-not $statusMatch.Success) {
		throw "Missing status frontmatter comment in $FilePath"
	}

	$status = $statusMatch.Groups[1].Value.Trim().ToUpperInvariant()
	$validStatuses = @('STAGING', 'READY', 'ACTIVE', 'DONE', 'HOLD')
	if ($validStatuses -notcontains $status) {
		throw "Invalid batch status '$status' in $FilePath"
	}

	$taskStatusMap = @{}
	$readyTaskCount = 0
	$lines = Get-Content -LiteralPath $FilePath
	foreach ($line in $lines) {
		$match = [regex]::Match($line, '^\|\s*(AT-\d+)\s*\|.*\|\s*(Ready|In Progress|Done|Blocked)\s*\|\s*$')
		if (-not $match.Success) {
			continue
		}

		$taskId = $match.Groups[1].Value.Trim()
		$taskStatus = $match.Groups[2].Value.Trim()
		if (-not $taskStatusMap.ContainsKey($taskId)) {
			$taskStatusMap[$taskId] = New-Object System.Collections.Generic.HashSet[string]
		}
		$null = $taskStatusMap[$taskId].Add($taskStatus)
		if ($taskStatus -eq 'Ready') {
			$readyTaskCount += 1
		}
	}

	return [pscustomobject]@{
		Path = $FilePath
		Status = $status
		ReadyTaskCount = $readyTaskCount
		TaskStatusMap = $taskStatusMap
	}
}

function Get-QueueTaskSets {
	param(
		[Parameter(Mandatory = $true)][string]$FilePath
	)

	if (-not (Test-Path -LiteralPath $FilePath)) {
		throw "Queue file not found: $FilePath"
	}

	$currentSection = ''
	$inProgress = New-Object System.Collections.Generic.HashSet[string]
	$readyPoolActive = New-Object System.Collections.Generic.HashSet[string]
	$done = New-Object System.Collections.Generic.HashSet[string]

	$lines = Get-Content -LiteralPath $FilePath
	foreach ($line in $lines) {
		$sectionMatch = [regex]::Match($line, '^##\s+(.+)$')
		if ($sectionMatch.Success) {
			$currentSection = $sectionMatch.Groups[1].Value.Trim()
			continue
		}

		$rowMatch = [regex]::Match($line, '^\|\s*(AT-\d+)\s*\|')
		if (-not $rowMatch.Success) {
			continue
		}

		$taskId = $rowMatch.Groups[1].Value.Trim()
		switch ($currentSection) {
			'In Progress' { $null = $inProgress.Add($taskId) }
			'Ready Pool' {
				if ($line -notmatch '\*\*Done' -and $line -notmatch '~~') {
					$null = $readyPoolActive.Add($taskId)
				}
			}
			'Done' { $null = $done.Add($taskId) }
		}
	}

	return [pscustomobject]@{
		InProgress = $inProgress
		ReadyPoolActive = $readyPoolActive
		Done = $done
	}
}

function Get-Overlaps {
	param(
		[Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.HashSet[string]]$Left,
		[Parameter(Mandatory = $true)][AllowEmptyCollection()][System.Collections.Generic.HashSet[string]]$Right
	)

	$overlap = New-Object System.Collections.Generic.List[string]
	foreach ($item in $Left) {
		if ($Right.Contains($item)) {
			$null = $overlap.Add($item)
		}
	}
	return $overlap.ToArray()
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$queuePath = Join-Path $repoRoot 'architecture-docs/global/ai-task-queue.md'
$tikPath = Join-Path $repoRoot 'architecture-docs/global/ai-task-tik.md'
$tokPath = Join-Path $repoRoot 'architecture-docs/global/ai-task-tok.md'

$tik = Get-BatchFileState -FilePath $tikPath
$tok = Get-BatchFileState -FilePath $tokPath
$queueSets = Get-QueueTaskSets -FilePath $queuePath

$errors = New-Object System.Collections.Generic.List[string]
$readyCount = @($tik.Status, $tok.Status | Where-Object { $_ -eq 'READY' }).Count
$activeCount = @($tik.Status, $tok.Status | Where-Object { $_ -eq 'ACTIVE' }).Count

if ($tik.Status -eq 'DONE' -and $tok.Status -eq 'DONE') {
	$null = $errors.Add("Both batch files are DONE. At least one batch must be READY for continuous execution.")
}

if ($readyCount -lt 1) {
	$null = $errors.Add("No READY batch found. Policy requires at least one READY batch at all times.")
}

foreach ($batch in @($tik, $tok)) {
	if ($batch.Status -eq 'READY' -and $batch.ReadyTaskCount -lt 1) {
		$null = $errors.Add("$($batch.Path) is marked READY but has no task rows with Status=Ready.")
	}
}

if ($activeCount -gt 1) {
	$null = $errors.Add("Both batches are ACTIVE. Only one ACTIVE batch is allowed.")
}

$queueOverlap = @(Get-Overlaps -Left $queueSets.InProgress -Right $queueSets.Done)
if ($queueOverlap.Count -gt 0) {
	$null = $errors.Add("Queue overlap: task(s) appear in both In Progress and Done: $($queueOverlap -join ', ')")
}

$batchActive = New-Object System.Collections.Generic.HashSet[string]
$batchDone = New-Object System.Collections.Generic.HashSet[string]
foreach ($batch in @($tik, $tok)) {
	foreach ($taskId in $batch.TaskStatusMap.Keys) {
		$statuses = $batch.TaskStatusMap[$taskId]
		if ($statuses.Contains('In Progress')) {
			$null = $batchActive.Add($taskId)
		}
		if ($statuses.Contains('Done')) {
			$null = $batchDone.Add($taskId)
		}
	}
}

$crossSurfaceActive = New-Object System.Collections.Generic.HashSet[string]
foreach ($taskId in $queueSets.InProgress) { $null = $crossSurfaceActive.Add($taskId) }
foreach ($taskId in $queueSets.ReadyPoolActive) { $null = $crossSurfaceActive.Add($taskId) }
foreach ($taskId in $batchActive) { $null = $crossSurfaceActive.Add($taskId) }

$crossSurfaceDone = New-Object System.Collections.Generic.HashSet[string]
foreach ($taskId in $queueSets.Done) { $null = $crossSurfaceDone.Add($taskId) }
foreach ($taskId in $batchDone) { $null = $crossSurfaceDone.Add($taskId) }

$activeDoneOverlap = @(Get-Overlaps -Left $crossSurfaceActive -Right $crossSurfaceDone)
if ($activeDoneOverlap.Count -gt 0) {
	$null = $errors.Add("Cross-surface overlap: task(s) appear as active and done: $($activeDoneOverlap -join ', ')")
}

Write-Host "Batch status: tik=$($tik.Status), tok=$($tok.Status)"
Write-Host "Queue rows: In Progress=$($queueSets.InProgress.Count), ReadyPoolActive=$($queueSets.ReadyPoolActive.Count), Done=$($queueSets.Done.Count)"

if ($errors.Count -gt 0) {
	Write-Host ''
	Write-Host 'Queue batch-state check FAILED:' -ForegroundColor Red
	foreach ($err in $errors) {
		Write-Host " - $err" -ForegroundColor Red
	}
	exit 1
}

Write-Host 'Queue batch-state check PASSED.' -ForegroundColor Green
exit 0