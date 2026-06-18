#Requires -Version 5.1
# Start Skein MCP Server (SSE on port 3100).
# Launched by start-all.ps1; can also be run standalone.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$esPy      = "c:\Users\jakeh\source\repos\Electron-Splines\.venv\Scripts\python.exe"
$McpScript = Join-Path $ScriptDir "local-mcp.py"

if (-not (Test-Path $esPy)) {
    Write-Host "ERROR: Electron-Splines venv not found at $esPy" -ForegroundColor Red
    Write-Host "Run: py -3.12 -m venv c:\Users\jakeh\source\repos\Electron-Splines\.venv" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

$host.UI.RawUI.WindowTitle = "Skein MCP Server"
Write-Host "Starting Skein MCP Server (http://127.0.0.1:3100/sse)" -ForegroundColor Cyan

# WORKSPACE_ROOT was never set here (found 2026-06-18 while smoke-testing
# dispatch_coding_task): local-mcp.py's WORKSPACE defaults to the parent of
# its own script directory, i.e. skein-toolkit itself, which has no
# architecture-docs/ at all. Every WORKSPACE-relative tool
# (create_actionable_task, create_open_question, run_shell with no cwd,
# fs_read_file/fs_write_file with a relative path) has been silently
# targeting the wrong repo on every real invocation since this script was
# written -- never caught before because this session's own OQ/AT writes
# always went through direct file edits or ledger_io calls with an
# explicit, correct path, not through this server's actual tool-call path.
$env:WORKSPACE_ROOT = "c:\Users\jakeh\source\repos\Electron-Splines"

& $esPy $McpScript
