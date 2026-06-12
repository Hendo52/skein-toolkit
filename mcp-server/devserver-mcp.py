#!/usr/bin/env python3
"""
devserver-mcp.py -- Agentic coding MCP server for the GPU devserver.

Exposes four tools to Continue.dev (and any MCP client) via SSE:
  run_shell      -- execute any shell command (primary tool for agentic work)
  read_file      -- read a file from the workspace
  write_file     -- write/overwrite a file in the workspace (creates dirs)
  list_directory -- list directory contents

The agent can use run_shell for git, npm test, npm build, grep, sed, etc.
read_file/write_file are provided for reliable large file writes where
shell quoting/escaping would be fragile.

Transport: SSE on http://127.0.0.1:3100/sse
Rent script tunnels this to localhost:3100 on the developer's machine.

Usage:
  python3 /root/devserver-mcp.py

Logs: /tmp/devserver-mcp.log
Dependencies: pip install fastmcp   (installed by rent-devserver.ps1)
"""

import os
import subprocess
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("mcp not installed. Run: pip install mcp[cli]", file=sys.stderr)
    sys.exit(1)

WORKSPACE = os.environ.get("DEVSERVER_WORKSPACE", "/workspace/repo")

mcp = FastMCP(
    "devserver",
    host="127.0.0.1",
    port=3100,
    instructions=(
        "Agentic coding tools for the GPU devserver. "
        "Use run_shell for git, npm, tests, and builds. "
        "Use create_test(name) to create a TypeScript Mocha/Chai test -- ALWAYS use this for new test files, not write_file. "
        "Use read_file/write_file for reliable file I/O on non-test files. "
        "Use load_skill(name) to load a project workflow skill by name. "
        "Use list_skills() to see all available skills. "
        "All paths are relative to the workspace root unless absolute. "
        f"Workspace root: {WORKSPACE}"
    ),
)


def _resolve(path: str) -> str:
    """Resolve a path: absolute stays as-is, relative is joined to WORKSPACE."""
    if os.path.isabs(path):
        return path
    return os.path.join(WORKSPACE, path)


@mcp.tool()
def create_test(name: str, description: str = "") -> str:
    """
    Create a TypeScript Mocha/Chai test file in app/test/ with correct boilerplate.

    This is the PREFERRED way to create test files in this project.
    Do NOT use write_file for tests -- use this tool instead.

    Args:
        name:        Test name WITHOUT extension, e.g. "MyFeature" -> app/test/MyFeatureTest.ts
        description: Optional one-line description of what is being tested.
    """
    # Normalise: strip any existing Test suffix / extension so we don't double it
    base = name.rstrip(".")
    if base.endswith("Test"):
        base = base[:-4]
    if base.endswith(".ts"):
        base = base[:-3]

    filename = f"{base}Test.ts"
    full_path = os.path.join(WORKSPACE, "app", "test", filename)

    desc_comment = f"// Tests for: {description}\n" if description else ""
    content = (
        f"{desc_comment}"
        f"import {{ expect }} from 'chai';\n"
        f"import 'mocha';\n"
        f"\n"
        f"describe('{base}', () => {{\n"
        f"    it('should be defined', () => {{\n"
        f"        // TODO: import the subject under test and replace this placeholder\n"
        f"        expect(true).to.equal(true);\n"
        f"    }});\n"
        f"}});\n"
    )

    if os.path.exists(full_path):
        return f"[error] File already exists: {full_path}\nUse write_file to overwrite it intentionally."

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return (
            f"Created: app/test/{filename}\n"
            f"Run with: yarn test\n"
            f"Next step: import the class under test and replace the placeholder assertion."
        )
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def run_shell(command: str, cwd: str = "") -> str:
    """
    Execute a shell command on the devserver and return combined stdout + stderr.

    Use this for: git operations, npm build/test/lint, grep/find, sed, cat,
    file moves, package installs, or any other shell task.

    Args:
        command: The shell command to run (passed to bash -c).
        cwd:     Working directory. Defaults to the workspace root if empty.
    """
    working_dir = _resolve(cwd) if cwd else WORKSPACE
    if not os.path.isdir(working_dir):
        working_dir = WORKSPACE

    result = subprocess.run(
        command,
        shell=True,
        executable="/bin/bash",
        cwd=working_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )

    parts = []
    if result.stdout.strip():
        parts.append(result.stdout.rstrip())
    if result.stderr.strip():
        parts.append("[stderr]\n" + result.stderr.rstrip())
    if result.returncode != 0:
        parts.append(f"[exit {result.returncode}]")

    return "\n".join(parts) if parts else "(no output)"


@mcp.tool()
def read_file(path: str) -> str:
    """
    Read and return the full contents of a file.

    Args:
        path: File path, relative to workspace root or absolute.
    """
    full_path = _resolve(path)
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return f"[error] File not found: {full_path}"
    except PermissionError:
        return f"[error] Permission denied: {full_path}"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """
    Write content to a file, creating parent directories if needed.
    Overwrites the file if it already exists.

    Args:
        path:    File path, relative to workspace root or absolute.
        content: Full file content to write (UTF-8).
    """
    full_path = _resolve(path)
    try:
        os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {full_path}"
    except PermissionError:
        return f"[error] Permission denied: {full_path}"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def load_skill(name: str) -> str:
    """
    Load a project skill by name and return its full content.

    Available skills:
      resume-briefing, geometry-tdd-loop, rca-instrument-diagnose,
      spec-from-design-goal, implementation-review, openscad-test-authoring,
      openscad-headless-render, mesh-quality-report, naming-convention-audit,
      doc-sync-after-change, git-operations, parameter-sweep-and-ranking,
      query-mode-diagnostic, geometry-acceptance-matrix,
      cad-geometry-contract-spec, task-decomposition, task-tier-classification,
      burst-merge, rca-from-evidence-pack, design-goal-evaluation,
      dashboard-staleness-audit, mermaid-c4-diagram-authoring

    Call list_skills() with no arguments to get the current list.

    Args:
        name: Skill name (directory name under .github/skills/).
    """
    skill_path = os.path.join(WORKSPACE, ".github", "skills", name, "SKILL.md")
    if not os.path.isfile(skill_path):
        # List what's available to help the model recover
        skills_dir = os.path.join(WORKSPACE, ".github", "skills")
        try:
            available = sorted(
                e.name for e in os.scandir(skills_dir) if e.is_dir()
            )
        except Exception:
            available = []
        return (
            f"[error] Skill '{name}' not found at {skill_path}\n"
            f"Available skills: {', '.join(available)}"
        )
    try:
        with open(skill_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"=== SKILL: {name} ===\n{content}"
    except Exception as e:
        return f"[error] Could not read skill '{name}': {e}"


@mcp.tool()
def list_skills() -> str:
    """
    List all available project skills (directories under .github/skills/).
    """
    skills_dir = os.path.join(WORKSPACE, ".github", "skills")
    try:
        skills = sorted(e.name for e in os.scandir(skills_dir) if e.is_dir())
        return "Available skills:\n" + "\n".join(f"  {s}" for s in skills)
    except Exception as e:
        return f"[error] Could not list skills: {e}"


@mcp.tool()
def list_directory(path: str = "") -> str:
    """
    List the contents of a directory. Shows files and subdirectories.

    Args:
        path: Directory path, relative to workspace root or absolute.
              Defaults to the workspace root if empty.
    """
    full_path = _resolve(path) if path else WORKSPACE
    try:
        entries = sorted(os.scandir(full_path), key=lambda e: (not e.is_dir(), e.name))
        lines = []
        for entry in entries:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                size = entry.stat().st_size
                lines.append(f"{entry.name}  ({size:,} bytes)")
        return "\n".join(lines) if lines else "(empty directory)"
    except FileNotFoundError:
        return f"[error] Directory not found: {full_path}"
    except PermissionError:
        return f"[error] Permission denied: {full_path}"
    except Exception as e:
        return f"[error] {e}"


if __name__ == "__main__":
    # Bind to 127.0.0.1 only -- the SSH tunnel exposes it to the developer.
    # Never bind to 0.0.0.0 on the devserver: this server has no auth.
    mcp.run(transport="sse")
