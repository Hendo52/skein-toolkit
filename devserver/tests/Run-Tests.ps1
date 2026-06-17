#Requires -Version 5.1
# =============================================================================
# Run-Tests.ps1
# Test runner for Dev Server lifecycle tests.
#
# Usage:
#   scripts\tests\Run-Tests.ps1                     # run all tests
#   scripts\tests\Run-Tests.ps1 -Tag WATCH          # run watcher tests only
#   scripts\tests\Run-Tests.ps1 -Tag READ,BATCH     # run multiple tags
# =============================================================================

param(
    # Filter to one or more Pester Describe-level tag(s): READ, CREATE, UPDATE, DELETE, WATCH, BATCH, OLLAMA
    [string[]]$Tag = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Ensure Pester v5 is available ---
$pesterMin = [Version]'5.0.0'
$pesterAvailable = Get-Module -ListAvailable Pester |
    Where-Object { $_.Version -ge $pesterMin } |
    Select-Object -First 1

if (-not $pesterAvailable) {
    Write-Host "Pester v5 not found. Installing to CurrentUser scope..." -ForegroundColor Cyan
    Install-Module Pester -MinimumVersion 5.0.0 -Force -SkipPublisherCheck -AllowClobber -Scope CurrentUser
    Write-Host "Pester v5 installed." -ForegroundColor Green
}

# Import v5 explicitly (v3.4.0 ships with Windows PowerShell and may load first)
Import-Module Pester -MinimumVersion 5.0.0 -Force

# --- Configure run ---
$config = New-PesterConfiguration
$config.Run.Path      = Join-Path $PSScriptRoot 'DevServer.Lifecycle.Tests.ps1'
$config.Output.Verbosity = 'Detailed'
$config.TestResult.Enabled = $true
$config.TestResult.OutputPath = Join-Path $PSScriptRoot 'TestResults.xml'
$config.Run.Exit = $true   # exit 1 on failures -- no manual result inspection needed

if ($Tag.Count -gt 0) {
    $config.Filter.Tag = $Tag
    Write-Host "Running tests tagged: $($Tag -join ', ')" -ForegroundColor Cyan
}

# --- Run ---
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Dev Server Lifecycle Tests" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

Invoke-Pester -Configuration $config
