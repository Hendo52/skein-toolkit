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
& $esPy $McpScript
