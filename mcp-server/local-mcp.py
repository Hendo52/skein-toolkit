#!/usr/bin/env python3
"""
local-mcp.py -- Local agentic MCP server for vibe coding without a devserver.

Exposes the same tools as devserver-mcp.py but runs on Windows and writes
directly to the local workspace. Use this when no Vast.ai GPU devserver is
active and you want the LLM to create files, run commands, and read code.

Transport: SSE on http://127.0.0.1:3100/sse  (same port as devserver tunnel)

Usage:
    python mcp-server\\local-mcp.py

Requirements:
    pip install "mcp[cli]" fastmcp

Workspace root defaults to the parent of this script's directory (see
WORKSPACE below); override with the WORKSPACE_ROOT environment variable to
point this server at a different project checkout.
"""

import os
import subprocess
import time
import sys

# ledger_io.py is a sibling module with the pure OQ/AT ledger-text functions
# (next_oq_id, insert_oq_row, etc.) -- inserted on sys.path via __file__ (not
# a hardcoded path) so the import works both when this script is run directly
# and when a test loads it via importlib.util.spec_from_file_location.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_io
import dispatch_io  # AT-1228: model resolution, job state, git ops for dispatch_coding_task

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.server import TransportSecuritySettings
except ImportError:
    print("mcp not installed. Run: pip install mcp[cli]", file=sys.stderr)
    sys.exit(1)

# Workspace root: the consuming project's repo root. Defaults to the parent
# of this script's directory (mcp-server/../ when run from a clone of this
# repo's layout); override with WORKSPACE_ROOT to point at any other checkout.
WORKSPACE = os.environ.get(
    "WORKSPACE_ROOT", os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

mcp = FastMCP(
    "local-devtools",
    host="127.0.0.1",
    port=3100,
    # Allow both 127.0.0.1 and localhost -- Continue.dev connects with Host: localhost
    transport_security=TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    ),
    instructions=(
        "Agentic coding tools for the local workspace. "
        "Use run_shell for git, npm, tests, builds, grep, and any shell task. "
        "Use create_test(name) to create a TypeScript Mocha/Chai test -- ALWAYS use this for new test files. "
        "Use read_file/write_file for reliable file I/O. "
        "Use load_skill(name) to load a project workflow skill by name. "
        "Use list_skills() to see all available skills. "
        "Use list_open_questions() / get_open_question(id) / resolve_open_question(id) "
        "to read or resolve rows in the OQ ledger without reading the whole file. "
        "All paths are relative to the workspace root unless absolute. "
        f"Workspace root: {WORKSPACE}"
    ),
)


def _resolve(path: str) -> str:
    """Resolve a path: absolute stays as-is, relative is joined to WORKSPACE."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(WORKSPACE, path))


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
        f"        // TODO: import the class under test and replace this placeholder\n"
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
    Execute a shell command in the workspace and return combined stdout + stderr.

    Use this for: git operations, npm build/test/lint, grep/find, file moves,
    package installs, or any other shell task.

    On Windows this runs via PowerShell (pwsh). Use standard Unix-style paths
    for the workspace -- they will be resolved correctly.

    Args:
        command: The shell command to run.
        cwd:     Working directory. Defaults to the workspace root if empty.
    """
    working_dir = _resolve(cwd) if cwd else WORKSPACE
    if not os.path.isdir(working_dir):
        working_dir = WORKSPACE

    # Use PowerShell on Windows, bash on Unix
    if sys.platform == "win32":
        shell_args = ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
        use_shell = False
    else:
        shell_args = command
        use_shell = True

    try:
        result = subprocess.run(
            shell_args,
            shell=use_shell,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 120 seconds"
    except FileNotFoundError as e:
        return f"[error] Shell not found: {e}"

    parts = []
    if result.stdout.strip():
        parts.append(result.stdout.rstrip())
    if result.stderr.strip():
        parts.append("[stderr]\n" + result.stderr.rstrip())
    if result.returncode != 0:
        parts.append(f"[exit {result.returncode}]")

    return "\n".join(parts) if parts else "(no output)"


@mcp.tool()
def fs_read_file(path: str) -> str:
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


# ---------------------------------------------------------------------------
# Guarded overwrite checkpoint for fs_write_file -- this tool sits at a
# tool-call -> filesystem boundary that, until 2026-06-08, had no validator:
# no logging, no shrink-sanity check, and no recovery path for files that were
# never committed to git (so `git checkout` can't restore them either). That
# day a degenerate/truncated CF completion overwrote ~95% of
# DEV_TOOLKIT_PLAN.md with a partial rewrite -- the model recovered by
# recreating the content from memory into a brand-new file, but the original
# sat wrecked on disk with zero trace in any log, and would have been an
# unrecoverable loss if the model hadn't happened to remember the content.
#
# The guard below is deliberately mechanical (byte-count comparison, not
# semantic judgment) -- the same "artifact over self-report" philosophy as the
# orchestrator's validator (_run_validator_pass): a model that just generated
# 400 bytes for a file that was 12KB cannot be trusted to also accurately
# self-assess whether that's intentional, so the boundary checks the artifact
# itself rather than asking the model to confirm its own output.
# ---------------------------------------------------------------------------

_FS_WRITE_BACKUP_DIR = os.path.join(WORKSPACE, ".fs_write_backups")
# Below this size, "shrinkage" is noise (READMEs get trimmed, stubs get
# filled in) -- the guard exists for "a real document collapsed to a stub",
# not "a 40-byte file became a 30-byte file".
_FS_WRITE_SHRINK_GUARD_MIN_BYTES = 500
_FS_WRITE_SHRINK_GUARD_RATIO = 0.4


def _backup_overwritten_file(full_path: str, old_content: str) -> str:
    """Snapshot about-to-be-clobbered content to a timestamped sidecar so a
    recovery path exists even for files that were never committed to git --
    exactly the gap that turned the planning-doc incident from "annoying" into
    "could have been a silent, permanent loss". Returns the backup path, or ""
    if the snapshot failed. A failed backup must not block the write itself
    (that would convert a safety net into a new way to get stuck) -- it is
    logged instead, so the gap stays visible rather than silent."""
    try:
        os.makedirs(_FS_WRITE_BACKUP_DIR, exist_ok=True)
        rel_flat = os.path.relpath(full_path, WORKSPACE).replace(os.sep, "__").replace("/", "__")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = os.path.join(_FS_WRITE_BACKUP_DIR, f"{rel_flat}.{stamp}.bak")
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(old_content)
        return backup_path
    except Exception as e:
        print(f"[mcp] fs_write_file: failed to back up {full_path} before overwrite: {e}", file=sys.stderr)
        return ""


@mcp.tool()
def fs_write_file(path: str, content: str) -> str:
    """
    Write content to a file, creating parent directories if needed.
    Overwrites the file if it already exists.

    On every overwrite of an existing file: the write is logged (old/new byte
    counts) and the previous content is snapshotted to .fs_write_backups/ so
    it can be recovered even if the file was never committed to git. An
    overwrite that would shrink an existing file of meaningful size (>= 500
    bytes) to less than 40% of its prior size is REFUSED outright -- that
    shape (a real document collapsing to a stub) is the signature of a
    truncated/degenerate generation about to clobber real content, not a
    legitimate edit; write the new version to a different path instead and let
    the architect diff and merge it deliberately.

    Args:
        path:    File path, relative to workspace root or absolute.
        content: Full file content to write (UTF-8).
    """
    full_path = _resolve(path)
    new_size = len(content.encode("utf-8"))
    try:
        old_content = None
        old_size = None
        if os.path.isfile(full_path):
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                old_content = f.read()
            old_size = len(old_content.encode("utf-8"))

            if old_size >= _FS_WRITE_SHRINK_GUARD_MIN_BYTES and new_size < old_size * _FS_WRITE_SHRINK_GUARD_RATIO:
                pct = new_size * 100 // old_size
                print(
                    f"[mcp] fs_write_file: REFUSED overwrite of {full_path} -- "
                    f"new content is {new_size} bytes ({pct}% of the existing "
                    f"{old_size} bytes) -- looks like a truncated/partial generation "
                    f"about to destroy most of an existing file; nothing was written.",
                    file=sys.stderr,
                )
                return (
                    f"[refused] {full_path} is currently {old_size} bytes; the content "
                    f"you're writing is only {new_size} bytes ({pct}% of the original). "
                    f"That shrink ratio looks like a truncated rewrite about to destroy "
                    f"most of an existing file, so nothing was touched. If a near-total "
                    f"rewrite is genuinely what you intend, write it to a new path (e.g. "
                    f"`{path}.new`) so the architect can diff and merge it deliberately -- "
                    f"do not overwrite the original directly."
                )

        parent = os.path.dirname(full_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        backup_note = ""
        if old_content is not None:
            backup_path = _backup_overwritten_file(full_path, old_content)
            if backup_path:
                backup_note = f" (previous {old_size} bytes backed up to {backup_path})"

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        delta_note = "" if old_size is None else f", was {old_size} bytes ({new_size - old_size:+d})"
        print(f"[mcp] fs_write_file: wrote {new_size} bytes to {full_path}{delta_note}{backup_note}", file=sys.stderr)
        return f"Written {new_size} bytes to {full_path}{backup_note}"
    except PermissionError:
        return f"[error] Permission denied: {full_path}"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def load_skill(name: str) -> str:
    """
    Load a project skill by name and return its full content.

    Call list_skills() with no arguments to get the current list.

    Args:
        name: Skill name (directory name under .github/skills/).
    """
    skill_path = os.path.join(WORKSPACE, ".github", "skills", name, "SKILL.md")
    if not os.path.isfile(skill_path):
        skills_dir = os.path.join(WORKSPACE, ".github", "skills")
        try:
            available = sorted(e.name for e in os.scandir(skills_dir) if e.is_dir())
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
    """List all available project skills (directories under .github/skills/)."""
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



@mcp.tool()
def web_search(query: str, num_results: int = 5) -> str:
    """
    Search the web via the local self-hosted SearXNG instance and return a
    digested list of results (title, URL, snippet). Use this to research prior
    art, library docs, error messages, or anything not in the local workspace.

    Requires SearXNG running locally (free, unlimited, no API key) --
    see scripts/searxng/README.md. Start it with `docker compose up -d`
    in scripts/searxng/ if this tool reports a connection error.

    Args:
        query:       Search query string.
        num_results: Max number of results to return (default 5, capped at 20).
    """
    num_results = max(1, min(num_results, 20))
    try:
        resp = httpx.get(
            "http://127.0.0.1:8080/search",
            params={"q": query, "format": "json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.ConnectError:
        return (
            "[error] Could not reach the local SearXNG instance at "
            "http://127.0.0.1:8080 -- is it running? Start it with "
            "`docker compose up -d` in scripts/searxng/."
        )
    except Exception as e:
        return f"[error] web_search failed: {e}"

    results = data.get("results", [])[:num_results]
    if not results:
        unresponsive = data.get("unresponsive_engines", [])
        note = f" (unresponsive engines: {unresponsive})" if unresponsive else ""
        return f"No results for {query!r}{note}"

    lines = [f"Web search results for {query!r}:"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        lines.append(f"\n{i}. {title}\n   {url}")
        if content:
            lines.append(f"   {content}")
    return "\n".join(lines)


@mcp.tool()
def fetch_page(url: str, max_chars: int = 8000) -> str:
    """
    Fetch a web page and return its content as clean, LLM-ready markdown
    (via the free Jina Reader service, https://r.jina.ai/). Use this after
    web_search to read the actual content of a promising result -- snippets
    alone are often too short to answer the question accurately.

    No API key required; Jina Reader is free for moderate use.

    Args:
        url:       Full URL of the page to fetch (must start with http:// or https://).
        max_chars: Truncate the returned markdown to this many characters
                   (default 8000, capped at 30000) to avoid blowing the context budget.
    """
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return f"[error] fetch_page requires a full http(s) URL, got: {url!r}"
    max_chars = max(500, min(max_chars, 30000))

    try:
        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            timeout=45.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text
    except httpx.ConnectError:
        return "[error] Could not reach r.jina.ai -- check network connectivity."
    except httpx.HTTPStatusError as e:
        return f"[error] fetch_page got HTTP {e.response.status_code} for {url}"
    except Exception as e:
        return f"[error] fetch_page failed: {e}"

    text = text.strip()
    if not text:
        return f"[error] fetch_page returned empty content for {url}"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated to {max_chars} chars ...]"
    return f"Content of {url}:\n\n{text}"


# ---------------------------------------------------------------------------
# CF API proxy -- converts Qwen/Llama <tools> XML to OpenAI tool_calls format
# Continue.dev sends requests to http://127.0.0.1:3100/cfproxy/{account_id}/...
# The proxy forwards to CF and rewrites any non-standard tool call responses.
# ---------------------------------------------------------------------------

import asyncio
import contextlib
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, StreamingResponse

# Matches both <tools>...</tools> and <tool_call>...</tool_call>
_TOOLS_RE = re.compile(
    r'<tool_call>\s*(.*?)\s*</tool_call>|<tools>\s*(.*?)\s*</tools>',
    re.DOTALL
)

# Known tool names -- used to detect bare function-call text like list_skills()
# Includes both this MCP server's own tools (create_test, run_shell, ...) and
# Cline's built-in tool vocabulary (write_to_file, execute_command, ...): when
# CF models are driven by Cline's system prompt, hallucinated inline tool-call
# JSON names Cline's tools, not this server's.
_KNOWN_TOOLS = {
    "create_test", "run_shell", "read_file", "write_file",
    "list_directory", "load_skill", "list_skills",
    "write_to_file", "replace_in_file", "execute_command", "list_files",
    "search_files", "list_code_definition_names", "ask_followup_question",
    "attempt_completion", "use_mcp_tool", "access_mcp_resource",
    "new_task", "plan_mode_respond", "web_fetch",
}

# Matches bare Python-style calls: tool_name() or tool_name("arg") or tool_name(key="val")
# The content may be the entire response or a line within it.
_FUNC_CALL_RE = re.compile(
    r'\b(' + '|'.join(_KNOWN_TOOLS) + r')\s*\(([^)]*)\)',
    re.DOTALL
)

# AT-1245: a narrow subset of _KNOWN_TOOLS above -- specifically the tool
# names Cline's own system prompt registers regardless of which MCP servers
# are connected, used to scope the multi-step interceptor (below) to Cline
# traffic specifically. attempt_completion/ask_followup_question/
# plan_mode_respond are Cline-specific concepts vanishingly unlikely to
# appear in another OpenAI-compatible client's tool definitions.
_CLINE_DISTINCTIVE_TOOL_NAMES = {"attempt_completion", "ask_followup_question", "plan_mode_respond"}


def _is_cline_traffic(body: dict) -> bool:
    """True if this request's `tools` array includes at least one of
    Cline's own distinctive built-in tool names.

    Found 2026-06-19 (AT-1245): the multi-step interceptor
    (_detect_multi_step_ask, used below) was built and tested only against
    Cline traffic, with no way to exclude any other OpenAI-compatible
    client hitting the same cf/* models. A real aider-evaluation task
    message (long, multi-verb -- exactly _detect_multi_step_ask's documented
    trigger shape) got silently decomposed into 3 separate autonomous
    orchestrator runs, invisible to both aider and the operator, discovered
    only by chance via an OQ-ledger diff. aider's diff-edit-format mode (the
    one used in that evaluation) sends no `tools` array at all -- it doesn't
    use native tool-calling, it parses SEARCH/REPLACE text itself -- so this
    check correctly excludes it.

    Defaults to False (do not intercept) for any request without a
    recognized Cline tool name, per the Validator-at-the-Boundary policy:
    this is an opt-in allowlist of known-Cline traffic, not a denylist of
    known-bad clients that would need updating every time a new client
    shows up."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function")
        name = fn.get("name") if isinstance(fn, dict) else tool.get("name")
        if name in _CLINE_DISTINCTIVE_TOOL_NAMES:
            return True
    return False


def _strip_wrapper(content: str) -> str:
    """
    Strip a single wrapping markdown code fence or inline backticks and a
    trailing semicolon, so callers can test whether the ENTIRE message is a
    bare tool-call rather than a tool name merely mentioned inside prose.
    """
    s = content.strip()
    fence = re.match(r'^```[\w]*\s*\n?(.*?)\n?```$', s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    s = s.strip('`').strip()
    return s.rstrip(';').strip()


def _parse_func_call(content: str):
    """
    Parse bare function-call syntax that Qwen sometimes emits instead of XML.
    Handles: list_skills()  create_test("Foo")  run_shell("git status")
    Returns an OpenAI tool_calls entry, or None.

    Uses fullmatch on the de-wrapped content -- a tool name that merely
    appears inside an explanation ("I'll call `list_skills()` for you...")
    must NOT be hijacked into a forced tool invocation; only a message whose
    entire content IS the call should be treated as one.
    """
    m = _FUNC_CALL_RE.fullmatch(_strip_wrapper(content))
    if not m:
        return None
    name = m.group(1)
    raw_args = m.group(2).strip()
    arguments: dict = {}
    if raw_args:
        # Try JSON object first: tool({"key": "val"})
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                arguments = parsed
            else:
                raise ValueError("bare scalar — treat as positional arg")
        except Exception:
            # Positional string arg: tool("value")  or  tool('value')
            s = re.match(r'^["\'](.+)["\']$', raw_args)
            if s:
                # Map positional arg to the first required param name
                _first_param = {
                    "create_test": "name",
                    "run_shell": "command",
                    "read_file": "path",
                    "write_file": "path",
                    "list_directory": "path",
                    "load_skill": "name",
                    "list_skills": None,
                }
                param = _first_param.get(name)
                if param:
                    arguments = {param: s.group(1)}
            else:
                # keyword args: key="val", key2="val2"
                for kv in re.finditer(r'(\w+)\s*=\s*["\']([^"\']*)["\']', raw_args):
                    arguments[kv.group(1)] = kv.group(2)
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _make_tool_call(name: str, args: dict) -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


# Graceful-stop tool calls for the orchestrator's terminal synthetic
# responses (run complete, halted, paused for OQ). A plain-text,
# no-tool-call assistant turn (finish_reason: "stop") is accepted as "done"
# by Cline's one-shot CLI (the process simply exits) but NOT by Cline's
# interactive task loop (VS Code extension), which requires either a tool
# call or attempt_completion/ask_followup_question on every turn. A bare
# "stop" there gets "[ERROR] You did not use a tool in your previous
# response!", and after 5 such retries Cline's own "[YOLO MODE] Task failed:
# Too many consecutive mistakes" safety net fires, leaving the task on an
# unresolved `ask: resume_task` -- a failure state invisible to
# ~/.cf_proxy_orchestrator/*.json (observed 2026-06-13). Wrapping these
# terminal messages in attempt_completion/ask_followup_question makes them
# harness-compliant for both consumers.
def _terminal_completion_tool_call(text: str) -> list:
    """For run-complete / halted / failed messages: tell Cline the task (or
    this orchestrated portion of it) is finished, presenting `text` as the
    result."""
    return [_make_tool_call("attempt_completion", {"result": text})]


def _terminal_followup_question_tool_call(text: str) -> list:
    """For the paused_for_oq ambiguity pause: ask Cline's harness to pause and
    wait for the architect's reply (continue/stop), matching the
    orchestrator's own paused_for_oq semantics."""
    return [_make_tool_call("ask_followup_question", {
        "question": text,
        "options": json.dumps(["continue", "stop"]),
    })]


# Matches the START of a `{"name": "...", "arguments"/"parameters": ...}` blob
# ANYWHERE in text -- deliberately not anchored, unlike _TOOLS_RE / Format-2 in
# _parse_any_tool_call (which only fire when the call is cleanly isolated).
# This exists purely to *detect* the failure mode where those clean parsers
# correctly decline to fire: a model writes substantial prose, then trails off
# into one or more tool-call-shaped JSON fragments glued into the same message
# (sometimes malformed, sometimes using Continue's prefixed tool names like
# `local_devtools_run_shell` rather than the bare names this proxy knows).
# Verified empirically 2026-06-08: CF qwen2.5-coder:32b produced a ~700-word
# planning document, then appended two such fragments back to back -- the
# second with a syntactically invalid `"cwd":}}` -- then continued in prose
# ("Please replace <your-github-username>..."). Forcing these into real
# tool_calls would be unsafe (malformed JSON, unvetted `git clone` argument);
# the honest move is to name what happened so the user isn't left staring at
# raw JSON wondering if something ran.
#
# Also matches the `"tool"` key (instead of `"name"`): gpt-oss-120b driven by
# Cline's system prompt invents its own shorthand `{"tool": "read_file",
# "arguments": {...}}` rather than emitting real tool_calls or Cline's XML
# tags -- verified empirically 2026-06-10 (Cline session ending in "[YOLO MODE]
# Task failed: Too many consecutive mistakes (3)" after two such fragments).
_EMBEDDED_TOOL_CALL_RE = re.compile(r'\{\s*"(?:name|tool)"\s*:\s*"([\w.\-]+)"\s*,\s*"(?:arguments|parameters)"\s*:')


def _detect_hallucinated_tool_call_text(content: str, model_name: str) -> str:
    """Return a diagnostic suffix if `content` looks like prose with one or more
    tool-call attempts written as inline JSON text rather than real tool_calls;
    "" if it doesn't match this signature. Caller appends the result (if any)
    to the assistant message so the model/user sees an honest accounting
    instead of opaque JSON fragments sitting in the middle of an answer."""
    matches = list(_EMBEDDED_TOOL_CALL_RE.finditer(content))
    if not matches:
        return ""
    names = ", ".join(f"`{m.group(1)}`" for m in matches)
    plural = "s" if len(matches) != 1 else ""
    return (
        f"\n\n---\n[cfproxy] NOTE: this response contains {len(matches)} apparent "
        f"tool-call attempt{plural} ({names}) written as inline JSON text instead of "
        f"real tool_calls -- they were NOT executed (the JSON may be malformed, and "
        f"blindly running an unvetted command like `git clone <url>` from hallucinated "
        f"text would be unsafe). This is a known failure mode of {model_name or 'this model'} "
        f"on long multi-step asks: it drifts from structured tool-calling into free-form "
        f"prose mid-response. Two ways forward: (1) split the ask into one step at a time "
        f"so the model stays in tool-calling mode, or (2) switch to a model with more "
        f"reliable native tool_calls for multi-step agentic work (e.g. CF gpt-oss:120b)."
    )


def _parse_any_tool_call(content: str):
    """
    Try every tool-call format CF models emit:
    1. <tools>{"name":...,"arguments":...}</tools>  or  <tool_call>...</tool_call>
    2. Bare JSON object: {"type":"function","name":"x","parameters":{}}
       or {"name":"x","arguments":{}}  or {"name":"x","parameters":{}}
       -- "tool" is accepted as an alias for "name" (gpt-oss-120b's shorthand
       when driven by Cline's prompt, e.g. {"tool":"read_file","arguments":{}})
    3. Bare function-call text: list_skills()  create_test("Foo")
    """
    # --- Format 1: XML wrapper ---
    m = _TOOLS_RE.search(content)
    if m:
        raw = (m.group(1) or m.group(2) or "").strip()
        raw = re.sub(r'"arguments"\s*:\s*([,}])', r'"arguments": {}\1', raw)
        try:
            data = json.loads(raw)
            name = data.get("name") or data.get("tool")
            if name:
                args = data.get("arguments") or data.get("parameters") or {}
                if not isinstance(args, dict):
                    args = {}
                return _make_tool_call(name, args)
        except Exception:
            pass

    # --- Format 2: bare JSON tool-call object as the ENTIRE message ---
    # (not merely a JSON example mentioned inside an explanation -- same
    # hijacking concern as Format 3, see _parse_func_call). Parsed with
    # json.loads rather than a brace-matching regex so nested argument
    # objects (e.g. {"name": "read_file", "arguments": {"path": "x"}})
    # are handled correctly. Accepts "tool" as an alias for "name" -- see
    # _EMBEDDED_TOOL_CALL_RE for why (gpt-oss-120b's own shorthand).
    stripped = _strip_wrapper(content)
    if stripped.startswith('{') and stripped.endswith('}'):
        try:
            data = json.loads(stripped)
            name = data.get("name") or data.get("tool") or ""
            if name in _KNOWN_TOOLS:
                args = data.get("arguments") or data.get("parameters") or {}
                if not isinstance(args, dict):
                    args = {}
                return _make_tool_call(name, args)
        except Exception:
            pass

    # --- Format 3: bare function-call text ---
    return _parse_func_call(content)


def _sanitize_messages_for_cf(body: dict) -> dict:
    """
    CF Workers AI's chat schema validator rejects `content: null` on assistant
    messages -- e.g. {"role": "assistant", "content": null, "tool_calls": [...]}
    -- with "AiError: Type mismatch of '/messages/N/content', 'string' not in
    'null'" (HTTP 400), even though `content: null` alongside `tool_calls` is
    standard, valid OpenAI format that Continue.dev itself produces and resends
    on every follow-up turn of an agentic conversation. Coerce null -> "" at
    this boundary so multi-turn tool-using conversations survive the round trip.
    """
    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict) and msg.get("content") is None:
                msg["content"] = ""
    return body


# Tool-call results are the dominant source of oversized prompts (confirmed
# empirically 2026-06-08: a single ~95K-char tool message made up ~40% of a
# 57K-token prompt, and that prompt shape degenerated CF's gpt-oss-120b into
# empty responses 2 of 3 times -- see _summarize_message_composition's log
# output and the large-prompt-composition diagnostic it feeds). Continue.dev
# resends the full accumulated conversation on every turn, so one oversized
# result anchors EVERY subsequent prompt in the session at the same inflated
# size -- the same prompt keeps failing the same way because it IS the same
# prompt. Truncating the worst offenders at the proxy boundary is the most
# surgical available lever: it shrinks exactly the entries that are oversized,
# leaves normally-sized history untouched, and -- critically -- is never
# silent (CLAUDE.md First-Class Scenarios Policy: every alternative-mode path
# needs an observable signal + tests + docs). The model still receives
# *something* useful plus an honest, actionable note about what's missing,
# which beats both failure modes it's currently stuck between: nothing
# (degenerate response) or everything (the same degenerate response, slower).
_TOOL_RESULT_TRUNCATION_CHARS_DEFAULT = 20000

# Per-model overrides for the two prompt-shrinking budgets in this section
# (_TOOL_RESULT_TRUNCATION_CHARS_DEFAULT and
# _HISTORY_COMPACTION_TRIGGER_CHARS_DEFAULT below). The defaults were
# calibrated against confirmed CB-1 degeneracy on
# cf/gpt-oss-120b around ~35-40K prompt tokens (~56K-77K chars at this
# codebase's ~1.6-2.0 chars/token ratio) -- see _compact_conversation_history.
# kimi-k2.6 has a 262K-token context window (~2x gpt-oss-120b's 128K) and no
# confirmed prompt-size degeneracy of its own (test #11's CB-1 at a 13.6K-token
# prompt is attributed to the now-fixed max_tokens=8192, not prompt size --
# see cf-proxy-cheap-model-context-budget-roadmap.md). Per architect direction
# (2026-06-11): give kimi a generous (10x) budget so troubleshooting sessions
# aren't truncated/compacted prematurely; revisit against real CB-1 evidence
# once a cost/optimization pass starts. Keys are CF model identifiers as they
# appear in the proxied request body's "model" field (e.g. "@cf/moonshotai/
# kimi-k2.6"), matching _CF_MODEL_PRICING_USD_PER_M's keys.
_PROMPT_BUDGET_CHARS = {
    "@cf/moonshotai/kimi-k2.6": {"tool_result": 200000, "history_trigger": 500000},
}


def _truncate_oversized_tool_results(body: dict, model: str = "") -> dict:
    """Mutates body['messages'] in place: any tool-role message whose string
    content exceeds the model's tool-result budget (_PROMPT_BUDGET_CHARS
    override, else _TOOL_RESULT_TRUNCATION_CHARS_DEFAULT) is cut to that length
    with a visible `TRUNCATED BY LOCAL PROXY` marker describing the original
    size and how to get the rest -- never a silent substitution. Logs a
    one-line summary (which messages, original sizes) whenever it actually
    fires, so the truncation is auditable from the same logs that would
    otherwise show a degenerate-response cascade. Returns body for chaining."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body
    limit = _PROMPT_BUDGET_CHARS.get(model, {}).get("tool_result", _TOOL_RESULT_TRUNCATION_CHARS_DEFAULT)
    truncated = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or len(content) <= limit:
            continue
        original_len = len(content)
        marker = (
            f"\n\n[... TRUNCATED BY LOCAL PROXY: this tool result was {original_len} chars; "
            f"only the first {limit} are shown above. The full result "
            f"is still obtainable from its source (the file on disk, the search you ran, "
            f"etc.) -- re-run the tool with a narrower scope (a smaller path, a tighter "
            f"pattern, a line range) if you need the rest. This truncation exists because "
            f"oversized tool results anchor every later prompt in a session at an inflated "
            f"size, which correlates with CF gpt-oss models returning empty responses "
            f"(see _truncate_oversized_tool_results in scripts/local-mcp.py).]"
        )
        msg["content"] = content[:limit] + marker
        truncated.append((i, original_len))
    if truncated:
        details = ", ".join(f"#{i} ({n} -> {limit} chars)" for i, n in truncated)
        print(
            f"[cfproxy] truncated {len(truncated)} oversized tool result(s) before forwarding to CF: {details}",
            file=sys.stderr,
        )
    return body


# Truncating the single worst offender (above) treats the symptom, not the
# mechanism: Continue.dev resends the FULL accumulated conversation every
# turn, so the prompt keeps growing turn over turn regardless -- confirmed
# 2026-06-08 by _final_turn_fingerprint evidence showing the byte-identical
# final turn ('The search returned no results.', sha256:d840307...) succeed
# at 36,643 prompt-tokens and degenerate 3/3 at 40,794 tokens just a few
# turns later in the SAME session. Size of the resent history -- not what's
# being asked -- is the dominant lever once the worst single-message outlier
# is capped.
#
# This is the same problem PewDiePie's self-hosted "Odysseus" workspace
# solves with a ChromaDB vector store: "Context management is decentralized
# -- agents can access persistent memory rather than relying solely on
# conversation history, reducing prompt bloat in long interactions"
# (github.com/pewdiepie-archdaemon/odysseus, reviewed 2026-06-08). We borrow
# the *pattern* -- keep what's recent verbatim, shrink what's old -- without
# the embeddings/vector-store dependency: this is also exactly what Claude
# Code's own context management does per its system prompt ("summarizes
# prior messages as it nears context limits"). If keep-recent-and-shrink
# proves insufficient, upgrading the stub step into real keyword/embedding
# retrieval is a natural next increment, and _lightweight_oq_precedent_note
# already demonstrates the keyword-overlap half of that in this same file.
#
# Mutates messages IN PLACE (preserving count, order, and role/tool_call
# pairing -- never collapses multiple messages into one, which would risk
# malformed assistant/tool_call <-> tool/tool_result structure) so this
# carries zero structural risk: only long-enough *older* messages get their
# content shrunk to a labeled stub, exactly like _truncate_oversized_tool_
# results but keyed on age rather than size, and with a much smaller cap.
#
# Trigger is in characters, not tokens, because token counts are only known
# AFTER CF responds (in `usage`) -- chars are the only size signal available
# before forwarding. Empirical chars/token ratio in this codebase's prompts
# (derived from cf_proxy_live.log large-prompt-composition lines, 2026-06-08):
# ~1.6-2.0 chars/token (code- and whitespace-heavy content tokenizes denser
# than English's typical ~4 chars/token). Degeneracy starts appearing around
# prompt_tokens ~35-40K (~56K-77K message chars observed); this trigger sits
# comfortably below that band so compaction engages before the danger zone.
# Per-model overrides (e.g. kimi-k2.6's larger budget) live in
# _PROMPT_BUDGET_CHARS above, alongside _TOOL_RESULT_TRUNCATION_CHARS_DEFAULT.
_HISTORY_COMPACTION_TRIGGER_CHARS_DEFAULT = 50000

# How many of the most-recent messages (after any leading system message(s))
# are left completely untouched. Large enough to cover several recent
# tool-call round-trips so the model keeps full fidelity on what it's
# actively working on; small enough to meaningfully shrink long sessions.
# Starting point per architect direction (2026-06-08) -- recalibrate from
# the [cfproxy] compacted ... log lines once real sessions exercise this.
_HISTORY_COMPACTION_KEEP_RECENT = 12

# How much of each compacted-away message's content survives as a labeled
# stub -- enough to recall *what* a turn was about (a snippet, like
# _final_turn_fingerprint logs) without spending meaningful prompt budget on
# it.
_HISTORY_COMPACTION_STUB_CHARS = 200


def _compact_conversation_history(body: dict, model: str = "") -> dict:
    """Mutates body['messages'] in place: once total message content exceeds
    the model's history-compaction trigger (_PROMPT_BUDGET_CHARS override,
    else _HISTORY_COMPACTION_TRIGGER_CHARS_DEFAULT), every message older than
    the most recent _HISTORY_COMPACTION_KEEP_RECENT (and not a leading system
    message) has its content shrunk to a _HISTORY_COMPACTION_STUB_CHARS-char
    snippet plus a visible `COMPACTED BY LOCAL PROXY` marker stating the
    original size and how to recover it -- never a silent substitution, and
    never a change to message count/order/role (so tool_call <-> tool_result
    pairing stays intact). Logs a one-line summary whenever it actually fires,
    so compaction is auditable from the same logs that would otherwise show a
    degenerate-response cascade. Returns body for chaining."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body

    trigger = _PROMPT_BUDGET_CHARS.get(model, {}).get("history_trigger", _HISTORY_COMPACTION_TRIGGER_CHARS_DEFAULT)
    total_chars = sum(len(_message_text(m) or "") for m in messages if isinstance(m, dict))
    if total_chars <= trigger:
        return body

    lead = 0
    while lead < len(messages) and isinstance(messages[lead], dict) and messages[lead].get("role") == "system":
        lead += 1

    keep_from = len(messages) - _HISTORY_COMPACTION_KEEP_RECENT
    if keep_from <= lead:
        return body

    compacted = []
    for i in range(lead, keep_from):
        msg = messages[i]
        if not isinstance(msg, dict):
            continue
        text = _message_text(msg) or ""
        if len(text) <= _HISTORY_COMPACTION_STUB_CHARS:
            continue
        original_len = len(text)
        snippet = text[:_HISTORY_COMPACTION_STUB_CHARS].replace("\n", " ")
        # Deliberately terse: this marker can repeat across dozens of older
        # turns in one compaction pass, so per-message boilerplate directly
        # eats into the chars it's meant to save. The full rationale lives
        # once in _compact_conversation_history's docstring/comments, not
        # here -- this just needs to be enough for the model (and a human
        # reading the log) to know what happened and how to recover.
        marker = (
            f"{snippet} [COMPACTED BY LOCAL PROXY: was {original_len} chars, full turn still "
            f"in session history -- ask the user to restate it if you need exact details "
            f"(see _compact_conversation_history in scripts/local-mcp.py)]"
        )
        msg["content"] = marker
        compacted.append((i, original_len))

    if compacted:
        saved = sum(n for _, n in compacted) - sum(len(_message_text(messages[i]) or "") for i, _ in compacted)
        details = ", ".join(f"#{i} ({n} chars)" for i, n in compacted)
        print(
            f"[cfproxy] compacted {len(compacted)} older turn(s) before forwarding to CF "
            f"(saved ~{saved} chars): {details}",
            file=sys.stderr,
        )
    return body


# ---------------------------------------------------------------------------
# Daily spend review flag -- Cloudflare's pay-as-you-go billing has no
# built-in hard cap (only after-the-fact alerts), so a runaway agent loop
# could rack up real charges before anyone notices. This tracks estimated USD
# spend per UTC day in a local file and, once a configurable threshold is
# crossed, logs a review flag (denominated in AUD, the architect's home
# currency) -- it does NOT refuse the request. Failing a query because token
# usage is high just wastes the tokens already spent reaching that point; the
# architect reviews ~/.cf_proxy_spend.json and decides whether usage looks
# wrong.
#
# The threshold is derived from a monthly AUD budget the architect agreed is
# reasonable (CF_PROXY_MONTHLY_BUDGET_AUD, default $100 AUD/month, 2026-06-11)
# converted to a daily USD figure via CF_PROXY_USD_TO_AUD_RATE (default 1.42,
# per foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-
# roadmap.md test #6). Set CF_PROXY_DAILY_REVIEW_THRESHOLD_USD directly to
# bypass the conversion. Resets automatically at UTC midnight (matches
# Cloudflare's billing day).
# ---------------------------------------------------------------------------

# 1 USD = this many AUD. Used only to express spend in the architect's home
# currency for the review flag below; CF/Groq/DeepSeek bill in USD, so all
# internal accounting stays in USD.
USD_TO_AUD_RATE = float(os.environ.get("CF_PROXY_USD_TO_AUD_RATE", "1.42"))

# Monthly CF spend the architect has agreed is reasonable, in AUD (2026-06-11).
MONTHLY_BUDGET_AUD = float(os.environ.get("CF_PROXY_MONTHLY_BUDGET_AUD", "100.00"))

DAILY_SPEND_REVIEW_THRESHOLD_USD = float(os.environ.get(
    "CF_PROXY_DAILY_REVIEW_THRESHOLD_USD",
    str(round(MONTHLY_BUDGET_AUD / USD_TO_AUD_RATE / 30, 4)),
))

# Path (relative to WORKSPACE) to the consuming repo's "open questions" /
# architect-decision ledger that the bounded-ambiguity escalation path
# (_raise_step_ambiguity_oq / _append_oq_row) reads and appends rows to.
# Defaults to this repo's own convention; set to a different path (or to a
# file that doesn't exist) for repos that don't use this ledger format --
# _append_oq_row already logs and returns False rather than raising if the
# path can't be read or written, so a missing/incompatible ledger degrades
# to "ambiguity surfaced inline, no OQ row appended" rather than a crash.
ORCHESTRATOR_OQ_LEDGER_PATH = os.environ.get(
    "CF_PROXY_OQ_LEDGER_PATH", "architecture-docs/global/architect-open-questions.md"
)

# Path (relative to WORKSPACE) to the consuming repo's AT (actionable task)
# queue that create_actionable_task appends rows to. Same degradation story
# as ORCHESTRATOR_OQ_LEDGER_PATH: _append_at_row logs and returns False
# rather than raising if the path can't be read or written.
AT_QUEUE_PATH = os.environ.get(
    "CF_PROXY_AT_QUEUE_PATH", "architecture-docs/global/ai-task-queue.md"
)

# Odysseus-Notes alternative mode (AT-1153): when ODYSSEUS_API_URL and
# ODYSSEUS_API_TOKEN are both set and {ODYSSEUS_API_URL}/api/notes
# authenticates with that token, create_open_question/create_actionable_task
# write to a reachable Odysseus instance's Notes API (POST /api/notes)
# instead of the markdown ledgers above. Both modes are first-class (named,
# tested, observable via a stderr log line naming the active mode) per the
# First-Class Scenarios policy -- see _odysseus_notes_mode_active and
# docs/odysseus-convergence.md.
ODYSSEUS_API_URL = os.environ.get("ODYSSEUS_API_URL", "").rstrip("/")
ODYSSEUS_API_TOKEN = os.environ.get("ODYSSEUS_API_TOKEN", "")

# Number of automatic retries when a streamed response comes back fully empty
# (no content, no tool_calls, finish_reason="stop") -- a known CF gpt-oss
# degenerate-reasoning quirk where the model spends its whole turn in
# `reasoning_content` and never emits a final answer. See _stream() in
# _cf_proxy for the detection and recovery logic.
CF_DEGENERATE_RETRY_LIMIT = 2

# gpt-oss models support a "reasoning_effort" request field (low/medium/high)
# that controls how much of the turn's budget goes to internal reasoning before
# the model commits to a final-channel answer (OpenAI's documented control for
# their gpt-oss/Harmony-format models; Cloudflare's OpenAI-compatible endpoint
# passes extra chat-completions fields through -- see
# https://blog.cloudflare.com/openai-gpt-oss-on-workers-ai/ and
# https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/).
# Confirmed empirically 2026-06-08 that the giveup cases logged completion_tokens
# of 70-238 -- nowhere near the 4096 cap -- meaning the model isn't running out
# of budget, it is CHOOSING to stop after reasoning and never starting the final
# answer. Asking for "low" effort is a direct, low-risk lever on exactly that
# choice (worst case CF ignores the unknown field and behavior is unchanged).
# Applied from attempt 1 -- the giveup logs show degeneracy reproducing on the
# very first attempt, so a fix that only kicks in on retries never helps the
# common case.
CF_GPT_OSS_REASONING_EFFORT = "low"
CF_GPT_OSS_MODEL_PREFIX = "@cf/openai/gpt-oss-"

# Temperatures applied to retry attempts 2..N (never attempt 1 -- that keeps
# the common-case request byte-identical to what the client sent, preserving
# its cost/behavior profile). Without this, a retry resends an EXACTLY
# identical body, which only helps when the degeneracy is independent per-call
# noise. Confirmed empirically 2026-06-08 that it often isn't: a give-up
# sequence's logged prompt was 4822 tokens on all 3 identical attempts, and
# all 3 degenerated identically (finish_reason="stop", near-zero content).
# When CF's inference is this consistent for a given input, an identical
# retry just reproduces the identical failure -- perturbing `temperature` is
# the smallest change that can break that loop without altering the
# conversation the model sees. Indexed by (attempt - 2); the last value
# repeats if CF_DEGENERATE_RETRY_LIMIT ever grows past this tuple's length.
CF_DEGENERATE_RETRY_TEMPERATURES = (0.7, 1.0)

# CB-23 (2026-06-18): CF Workers AI returns HTTP 429 with code 3040
# ("AiError: Capacity temporarily exceeded, please try again") when a model is
# momentarily overloaded -- confirmed transient empirically: a direct probe
# against the same model succeeded between two failed Cline-dispatched
# attempts on the same model, seconds apart. Before this fix, the streaming
# path treated EVERY status_code >= 400 (429 alongside genuinely permanent
# 401/403 auth failures) as non-transient and surfaced it to the client
# immediately -- Cline's CLI then gives up on the whole task rather than
# retrying the LLM call itself, even though CF's own error message says to
# retry. 429 now reuses the existing attempt loop (see CF_CAPACITY_RETRY_LIMIT)
# instead of returning immediately, with a short sleep first so the retry
# doesn't immediately re-hit the same capacity wall.
#
# First version of this fix gave 429 only CF_DEGENERATE_RETRY_LIMIT's small
# shared budget (2 retries) -- live-tested same day against a real degraded
# kimi-k2.6 window: it turned an instant 100%-failure rate into multiple
# successful tool calls per Cline run, but a long multi-call agentic session
# could still exhaust 2 retries on one unlucky call and abort the whole task.
# CF_CAPACITY_RETRY_LIMIT is deliberately larger and independent of the
# degenerate-response budget -- the loop bound (see max_attempts below) covers
# whichever of the two needs more attempts. Indexed by (attempt - 1); the last
# value repeats if CF_CAPACITY_RETRY_LIMIT ever grows past this tuple's length.
CF_CAPACITY_RETRY_LIMIT = 5
CF_CAPACITY_RETRY_BACKOFF_SECONDS = (2.0, 4.0, 8.0, 15.0, 25.0)

# Real incident, 2026-06-20 (AT-1196): a long, otherwise-successful
# kimi-k2.6 dispatch (genuine edits made throughout) lost all its work when
# CF returned a 500 "Internal server error" (code 8004) on what was likely
# the final tool-result round trip -- the diff was never persisted to disk.
# This status code wasn't retried at all (the carve-out below only checked
# == 429), so it fell straight through to the "genuinely permanent failure"
# path alongside actual auth/permission errors, exactly the failure mode
# CB-23's comment above already describes for 429. A 500 from CF's own
# infrastructure is the same kind of transient server-side hiccup, not a
# problem with the request -- it belongs in the same retry carve-out.
CF_TRANSIENT_RETRY_STATUS_CODES = (429, 500)

# Timeout for CF forward calls, both non-streaming and streaming. The previous
# 60s value was tuned around gpt-oss's fast (often degenerate-empty, sub-10s)
# responses and is far too short for kimi-k2.6's realistic completions: a
# 2026-06-11 probe with max_tokens=25600 returned a complete, non-degenerate
# 9153-token completion (finish_reason="stop") after 175s -- ~52 tokens/sec. At
# kimi-k2.6's configured max_tokens=8192 (litellm_config.yaml), a full-budget
# response would need ~158s, well past 60s. Kept comfortably under LiteLLM's
# own `request_timeout: 600` (litellm_config.yaml litellm_settings, raised for
# CB-10(a) -- see ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS below) so this proxy
# surfaces a named, logged timeout before LiteLLM's client gives up silently.
#
# CB-16 (2026-06-12): _stream() (the streaming/SSE path Cline actually uses
# for every request, stream=true) had its own separate, never-updated 60.0
# literal and was NOT covered by this constant -- causing a ReadTimeout ->
# Cline-retry -> growing-context -> repeat loop on large kimi-k2.6 contexts.
# _stream() now shares this constant too.
CF_FORWARD_TIMEOUT_SECONDS = 290.0

# Timeout for orchestrator step-dispatch calls specifically (CB-10(a)).
# Step-dispatch prompts can grow far larger than ordinary chat turns -- the
# 97ee060abc9315f1 step 6/8 ReadTimeout (2026-06-11) involved a 178,311-char
# prompt and exceeded CF_FORWARD_TIMEOUT_SECONDS. CB-10(b)'s findings
# carry-forward (OQ-263) addresses the root cause (steps re-reading whole
# source documents), but a single step can still legitimately need to read
# one large file, so step dispatch gets its own, larger budget. Set just
# under the matching `request_timeout: 600` in litellm_config.yaml so this
# proxy surfaces a named, logged timeout before LiteLLM's client gives up
# silently (same "just under" pattern as CF_FORWARD_TIMEOUT_SECONDS/290).
ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS = 590.0

# Above this prompt size, log a per-role composition breakdown alongside the
# ordinary spend line (see _summarize_message_composition). Degenerate
# responses correlate with large prompts (confirmed empirically 2026-06-08:
# ~57K-token prompts degenerated 2 of 3 times vs. a 4822-token sample that
# degenerated once) -- but "large" is consistent with two structurally
# different problems that call for different fixes (conversation-history
# compaction vs. selective-retrieval/RAG for oversized doc dumps), and we
# can't tell which we're looking at from the token count alone. 20K is well
# below where degeneracy has been observed, so this fires early enough to
# build a picture before the failure, not just at the moment of it.
_LARGE_PROMPT_DIAGNOSTIC_THRESHOLD_TOKENS = 20000


def _summarize_message_composition(messages) -> str:
    """Cheap, single-line breakdown of a chat-completion request's `messages`
    array by role -- count and total character length per role, plus the
    single largest message's role/index/length. Tells us WHERE a large
    prompt's bulk lives -- spread across many small accumulated turns
    (history-compaction territory) vs. concentrated in one or two oversized
    entries such as a large file-read tool result (selective-retrieval/RAG
    territory) -- without the cost or noise of logging message content."""
    if not isinstance(messages, list):
        return "messages: (not a list)"
    by_role: dict = {}
    largest = (0, "?", -1)
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        role = m.get("role", "?")
        length = len(_message_text(m) or "")
        counts = by_role.setdefault(role, [0, 0])
        counts[0] += 1
        counts[1] += length
        if length > largest[0]:
            largest = (length, role, i)
    per_role = ", ".join(f"{role}={n}msg/{chars}chars" for role, (n, chars) in by_role.items())
    return (f"{len(messages)} messages ({per_role}); "
            f"largest single message: {largest[1]} #{largest[2]} ({largest[0]} chars)")


def _final_turn_fingerprint(messages) -> str:
    """Short fingerprint of the LAST message in the prompt -- role, length,
    a content hash, and a short snippet. The composition breakdown alone
    cannot explain why two same-sized prompts diverge: in cf_proxy_live.log
    a 36502-token prompt degenerated 3/3 while a 37647-token prompt (one
    turn earlier, in the same session) succeeded cleanly, and #37 -- the
    largest message in both -- was byte-identical. Size and shape were
    confounds; the only thing that can differ between such prompts is WHAT
    the model is actually being asked to do in the newest turn. This lets
    us correlate degenerate vs. clean outcomes against that turn's content
    across many requests without paying the cost/noise of logging full
    message bodies."""
    if not isinstance(messages, list) or not messages:
        return "(no messages)"
    msg = messages[-1]
    if not isinstance(msg, dict):
        return "(last message not a dict)"
    role = msg.get("role", "?")
    text = _message_text(msg) or ""
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    snippet = text[:160].replace("\n", " ")
    return f"last={role} #{len(messages) - 1} ({len(text)} chars, sha256:{digest}): {snippet!r}"


_SPEND_FILE = os.path.join(os.path.expanduser("~"), ".cf_proxy_spend.json")
_spend_lock = asyncio.Lock()

# USD per 1M tokens -- queried from Cloudflare's model catalog (ai/models/search)
# on 2026-06-07. CF doesn't report per-request cost in chat completion responses
# (only token counts), so this table converts usage -> an estimated dollar figure
# for the circuit breaker. Cloudflare bills in "Neurons"; these per-token USD
# rates are the figures CF itself publishes for budgeting, so the estimate
# should track real billing closely. Re-query the catalog if CF reprices.
_CF_MODEL_PRICING_USD_PER_M = {
    "@cf/openai/gpt-oss-20b":                   {"input": 0.20,  "output": 0.30},
    "@cf/openai/gpt-oss-120b":                  {"input": 0.35,  "output": 0.75},
    "@cf/qwen/qwen2.5-coder-32b-instruct":      {"input": 0.66,  "output": 1.00},
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": {"input": 0.293, "output": 2.253},
    "@cf/moonshotai/kimi-k2.6":                 {"input": 0.95,  "output": 4.00},
}
# Conservative fallback for models not in the table above (e.g. newly added to
# config but not yet priced here) -- overestimates rather than underestimates,
# so the breaker stays safe rather than silently under-tracking spend.
_CF_FALLBACK_PRICING_USD_PER_M = {"input": 1.00, "output": 3.00}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_spend() -> dict:
    today = _today_utc()
    try:
        with open(_SPEND_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except Exception:
        pass
    return {"date": today, "total_usd": 0.0, "requests": 0}


def _save_spend(data: dict) -> None:
    try:
        with open(_SPEND_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[cfproxy] failed to persist spend tracker {_SPEND_FILE}: {e}", file=sys.stderr)


async def _spend_review_threshold_exceeded() -> tuple[bool, dict]:
    """Returns (exceeded, spend_record) for today (UTC), resetting if the day rolled over."""
    async with _spend_lock:
        spend = _load_spend()
        return (spend["total_usd"] >= DAILY_SPEND_REVIEW_THRESHOLD_USD, spend)


async def _record_cf_spend(model: str, usage: dict) -> dict:
    """
    Estimate the USD cost of a completed request from its token usage and add
    it to today's running total. Returns the updated spend record.
    """
    pricing = _CF_MODEL_PRICING_USD_PER_M.get(model, _CF_FALLBACK_PRICING_USD_PER_M)
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    cost = (prompt_tokens / 1_000_000) * pricing["input"] + (completion_tokens / 1_000_000) * pricing["output"]

    async with _spend_lock:
        spend = _load_spend()
        spend["total_usd"] += cost
        spend["requests"] += 1
        _save_spend(spend)
        return spend


def _spend_review_flag_message(spend: dict) -> str:
    spent_aud = spend["total_usd"] * USD_TO_AUD_RATE
    threshold_aud = DAILY_SPEND_REVIEW_THRESHOLD_USD * USD_TO_AUD_RATE
    return (
        f"[cfproxy] FLAG FOR REVIEW: today's estimated CF spend is ~${spent_aud:.2f} AUD "
        f"(review threshold ~${threshold_aud:.2f} AUD/day, derived from a "
        f"${MONTHLY_BUDGET_AUD:.2f} AUD/month budget at {USD_TO_AUD_RATE} USD/AUD -- see "
        f"CF_PROXY_MONTHLY_BUDGET_AUD / CF_PROXY_USD_TO_AUD_RATE / "
        f"CF_PROXY_DAILY_REVIEW_THRESHOLD_USD). Continuing the request -- high spend no "
        f"longer blocks requests, but the architect should check ~/.cf_proxy_spend.json."
    )


# ---------------------------------------------------------------------------
# Lightweight measurement counters -- coarse, daily-reset operational signals
# (mirrors the _load_spend/_save_spend pattern above) so the architect can
# periodically skim ~/.cf_proxy_metrics.json and notice drift -- e.g.
# "hallucination-detector fires tripled this week" or "the orchestrator keeps
# landing on AMBIGUOUS" -- without grepping stderr logs by hand. These are
# not billing-grade or alerting-grade; they're a trend signal, not a trigger.
# ---------------------------------------------------------------------------

_METRICS_FILE = os.path.join(os.path.expanduser("~"), ".cf_proxy_metrics.json")
_metrics_lock = asyncio.Lock()


def _load_metrics() -> dict:
    today = _today_utc()
    try:
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except Exception:
        pass
    return {"date": today, "counters": {}}


def _save_metrics(data: dict) -> None:
    try:
        with open(_METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[cfproxy] failed to persist metrics tracker {_METRICS_FILE}: {e}", file=sys.stderr)


async def _record_metric(name: str, by: int = 1) -> None:
    """Increment a named daily counter (resets at UTC midnight)."""
    async with _metrics_lock:
        metrics = _load_metrics()
        metrics["counters"][name] = metrics["counters"].get(name, 0) + by
        _save_metrics(metrics)


# ---------------------------------------------------------------------------
# Multi-step ask interception -- propose a queue breakdown instead of letting
# a long, multi-subsystem ask reach the executor model in one turn.
#
# Both CF model classes we've observed degrade specifically on long agentic
# chains, in different ways: qwen2.5-coder-32b drifts from structured
# tool_calls into hallucinated inline JSON mid-response (see
# _detect_hallucinated_tool_call_text and commit 066e6dd1), and gpt-oss-120b
# burns its whole completion budget on internal reasoning and returns empty
# (see CF_DEGENERATE_RETRY_LIMIT). System-prompt steering alone narrowed the
# damage but did not change the underlying rate -- confirmed empirically
# 2026-06-08 (the exact "clone the dev stack to a standalone repo" ask
# produced a hallucinated-tool-call response from qwen and three consecutive
# empty responses from gpt-oss, even with the corrected tool names and
# decompose-first guidance from continue-prompts/rules/00-project.md in
# place). Decomposition is a categorically smaller, more bounded task than
# sustained multi-step execution, so the proxy does it itself -- via a
# narrowly-scoped planner call with no tool schema and a tight output
# contract -- rather than trusting the executor model to self-decompose
# reliably mid-stream.
# ---------------------------------------------------------------------------

_MULTI_STEP_MIN_CHARS = 350
_MULTI_STEP_CONNECTOR_RE = re.compile(
    r'\b(and then|after that|as well as|additionally|also|once that|finally|'
    r'then we|we can then)\b',
    re.IGNORECASE,
)
# CB-4 (foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-roadmap.md
# strategy backlog): the original verb list below was code-modification-oriented and
# missed investigation-style asks ("review X, then verify Y, then summarize Z"), which
# are exactly the asks most likely to accumulate large raw tool-result contexts and
# trigger the gpt-oss degenerate-empty-response failure (see roadmap section 2). Added
# review/examine/investigate/analyze/verify/summarize/locate/identify/audit/compare so
# these asks get decomposed into narrower per-step contexts too.
_MULTI_STEP_ACTION_VERB_RE = re.compile(
    r'\b(create|copy|configure|set ?up|wire|build|write|document|migrate|'
    r'install|update|refactor|implement|test|deploy|integrate|move|rename|'
    r'clone|adapt|port|review|examine|investigate|analyze|verify|summarize|'
    r'locate|identify|audit|compare)\b',
    re.IGNORECASE,
)
_MULTI_STEP_MIN_CONNECTORS = 2
_MULTI_STEP_MIN_VERBS = 3


def _flatten_content_block(block: object) -> str:
    """Convert a single OpenAI content block to a plain string."""
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return str(block)
    t = block.get("type", "")
    if t == "text":
        return block.get("text", "")
    if t == "tool_result":
        inner = block.get("content", "")
        if isinstance(inner, list):
            inner = "\n".join(_flatten_content_block(b) for b in inner)
        return f"[tool result: {inner}]"
    if t == "tool_use":
        import json as _json
        return f"[tool call: {block.get('name','')} {_json.dumps(block.get('input', {}))}]"
    if t == "image_url":
        return "[image]"
    return str(block)


def _normalize_cf_messages(messages: list) -> list:
    """Flatten any array-typed content fields to plain strings.

    CF Workers AI gpt-oss models only accept content as a string. Modern OpenAI
    clients (Cline, Claude Code) send content as typed-block arrays. Flatten
    them here so the upstream never sees the schema mismatch.
    """
    out = []
    for msg in messages:
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            flat = "\n".join(_flatten_content_block(b) for b in msg["content"])
            msg = {**msg, "content": flat}
        out.append(msg)
    return out


# AT-1170: Validator-at-the-boundary for outbound _cf_proxy traffic. The proxy
# forwards full conversation/tool-output text to external Cloudflare Workers
# AI models (gpt-oss, kimi-k2.6) with no check for secret-shaped content --
# this is that check. Redacts rather than rejects: blocking an entire request
# over an incidental secret-shaped string in unrelated context (e.g. a code
# sample showing *how* to set an env var) would halt legitimate work. Every
# redaction is logged (First-Class Scenarios policy, CLAUDE.md) so a real leak
# is noticed rather than silently dropped.
_SECRET_REDACTION_PATTERNS: list = [
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("env-style-assignment", re.compile(r"\b[A-Z][A-Z0-9_]*_(?:KEY|SECRET|TOKEN)\s*=\s*\S+")),
]


def _scrub_secrets(text: str) -> str:
    """Redact secret-shaped substrings in `text`, logging each redaction.
    Returns `text` unchanged if it is empty/falsy or has no matches."""
    if not text:
        return text
    scrubbed = text
    for name, pattern in _SECRET_REDACTION_PATTERNS:
        def _redact(match, _name=name):
            print(f"[cfproxy] secret-scrubber: redacted a {_name} match before forwarding outbound", file=sys.stderr)
            return f"<REDACTED:{_name}>"
        scrubbed = pattern.sub(_redact, scrubbed)
    return scrubbed


def _scrub_secrets_from_body(body: dict) -> dict:
    """Apply _scrub_secrets to every message's text content in an outbound CF
    request body. Handles both plain-string content and typed-block-array
    content (array form may still be present for callers that invoke this
    before _normalize_cf_messages)."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body
    scrubbed_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            scrubbed_messages.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, str):
            msg = {**msg, "content": _scrub_secrets(content)}
        elif isinstance(content, list):
            new_content = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block = {**block, "text": _scrub_secrets(block["text"])}
                new_content.append(block)
            msg = {**msg, "content": new_content}
        scrubbed_messages.append(msg)
    return {**body, "messages": scrubbed_messages}


def _latest_user_message(body: dict) -> str:
    for msg in reversed(body.get("messages") or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _strip_cline_injected_context(message: str) -> str:
    """Strip Cline-injected wrapper sections from a user message so that
    _detect_multi_step_ask and _run_planner_pass see only the architect's
    literal typed text, not Cline's appended environment metadata.

    Strips:
    - <environment_details>...</environment_details> blocks (may span many lines)
    - 'Recently Modified Files' section header and any following indented/blank lines

    AT-1174 / BUG-SR-1.4: the 2026-06-15 incident showed that Cline's
    injected environment context can dominate the message text in length and
    action-verb density, causing the heuristic to misclassify the *context*
    as the *request*.
    """
    import re
    stripped = re.sub(r"<environment_details>.*?</environment_details>", "", message, flags=re.DOTALL)
    stripped = re.sub(r"(?m)^Recently Modified Files\b.*?(?=\n\S|\Z)", "", stripped, flags=re.DOTALL)
    return stripped.strip()


def _conversation_has_tool_use(messages: list) -> bool:
    """True if any assistant message in `messages` already contains a tool
    call -- i.e. Cline is mid-task and the "latest user message" is tool-result
    feedback from its own previous turn, not a fresh ask.

    Guards the Phase 2 multi-step interceptor (_detect_multi_step_ask), which
    runs on _latest_user_message: re-decomposing a tool-result blob as if it
    were a new multi-part request spins up a spurious orchestrator run keyed
    off that blob. Observed 2026-06-13 (run `bdeaa11e30a35d7a`): a 6218-char
    tool-result happened to contain >= 3 tracked action verbs, so the
    interceptor fired; the planner pass, given that blob, correctly found no
    real task and returned a single degenerate step ("Provide a concrete task
    or user request to decompose into steps."), which got auto-confirmed and
    dispatched. Cline's real, unrelated, in-progress task kept making real
    edits, so the validator scored that step YES and the run "completed" --
    injecting a "Run complete... nothing further needed" turn into Cline's
    actual in-progress task. Cline's interactive harness does not accept a
    no-tool-call turn as done (see _terminal_completion_tool_call), replied
    "[ERROR] You did not use a tool in your previous response!", and after 5
    such retries hit its own "[YOLO MODE] Task failed: Too many consecutive
    mistakes" stop -- a failure state visible only in that VS Code task's own
    ui_messages.json, invisible to ~/.cf_proxy_orchestrator/*.json."""
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if msg.get("tool_calls"):
            return True
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content
        ):
            return True
    return False


def _detect_multi_step_ask(message: str) -> tuple[bool, str]:
    """Heuristic: does this message describe several distinct actions/subsystems
    rather than one bounded step? Deliberately conservative (length floor +
    two independent signals) so short, single-purpose asks pass through
    untouched -- false positives here cost a planner-pass CF call and an
    unwanted detour, so the bar is "clearly multi-part," not "might be."
    Returns (True, human-readable reason) or (False, "")."""
    if len(message) < _MULTI_STEP_MIN_CHARS:
        return False, ""
    connectors = _MULTI_STEP_CONNECTOR_RE.findall(message)
    verbs = sorted({v.lower().replace(" ", "") for v in _MULTI_STEP_ACTION_VERB_RE.findall(message)})
    if len(connectors) >= _MULTI_STEP_MIN_CONNECTORS or len(verbs) >= _MULTI_STEP_MIN_VERBS:
        verb_sample = ", ".join(verbs[:6]) + (", ..." if len(verbs) > 6 else "")
        return True, (
            f"{len(message)}-char message with {len(connectors)} sequencing "
            f"connector(s) and {len(verbs)} distinct action verb(s) ({verb_sample})"
        )
    return False, ""


_PLANNER_SYSTEM_PROMPT = (
    "You are a task-decomposition assistant. Read the user's request and break "
    "it into an ordered, numbered list of small, single-action steps -- each "
    "one independently completable and verifiable (one file, one command, one "
    "subsystem at a time; nothing that itself bundles multiple actions). "
    "Output ONLY the numbered list -- one short imperative sentence per step. "
    "No preamble, no explanation, no code, no closing remarks."
)


async def _run_planner_pass(cf_base_url: str, auth_header: str, model_name: str, user_message: str):
    """Make a narrowly-scoped CF call (no tools, tight output contract) that
    decomposes `user_message` into an ordered step list. Returns the list of
    step strings, or None if the call failed or produced nothing numbered-list
    shaped (caller falls back to forwarding the original request unchanged --
    a planner failure must never block the user from at least trying)."""
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        # Was 1024 -- per cf-proxy-cheap-model-context-budget-roadmap.md test #11,
        # kimi-k2.6 burned its entire 1024-token budget on reasoning every turn
        # and never emitted a step list, so the planner pass degenerated on
        # every call. 8192 matches the model's prior chat-completion default
        # and is well above the community-reported degeneracy floor (~4096).
        "max_tokens": 8192,
        "stream": False,
    }
    try:
        # Was 60.0 -- too short once max_tokens is large enough for kimi-k2.6 to
        # actually finish (test #10: 175s for a 9153-token completion). Match
        # CF_FORWARD_TIMEOUT_SECONDS so this pass surfaces a named, logged
        # timeout instead of a silent httpx.ReadTimeout before the model is done.
        async with httpx.AsyncClient(timeout=CF_FORWARD_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                cf_base_url,
                json=payload,
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
            )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[cfproxy] planner pass failed ({exc!r}) -- forwarding original request unchanged", file=sys.stderr)
        return None

    usage = data.get("usage")
    if isinstance(usage, dict):
        await _record_cf_spend(model_name, usage)

    if not content:
        reasoning_present = data["choices"][0]["message"].get("reasoning_content") is not None
        print(
            f"[cfproxy] planner pass returned no content "
            f"(reasoning_content present: {reasoning_present}) -- forwarding original request unchanged",
            file=sys.stderr,
        )
        return None

    steps = [
        re.sub(r'^\s*\d+[\.\)]\s*', '', line).strip()
        for line in content.splitlines()
        if re.match(r'^\s*\d+[\.\)]\s*\S', line)
    ]
    if not steps:
        print(
            f"[cfproxy] planner pass returned no numbered steps "
            f"(content: {content[:200]!r}) -- forwarding original request unchanged",
            file=sys.stderr,
        )
        return None
    return steps


def _synthetic_assistant_response(model_name: str, content, is_stream: bool, tool_calls: list = None, finish_reason: str = "stop"):
    """Build a complete, well-formed assistant turn from proxy-generated content,
    short-circuiting before the request ever reaches CF (or re-rendering a result
    the proxy obtained out-of-band). Mirrors CF's response shape (see _cf_proxy)
    so both streaming and non-streaming Continue.dev sessions render it
    identically to a normal model turn -- including tool_calls, which the
    Phase-3 orchestrator (below) needs when relaying a step's tool-call turns."""
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    if is_stream:
        async def _gen():
            base = {"id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion.chunk", "model": model_name}
            delta = {"role": "assistant"}
            if content:
                delta["content"] = content
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})}\n\n"
            for i, tc in enumerate(tool_calls or []):
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, 'id': tc['id'], 'type': 'function', 'function': tc['function']}]}, 'finish_reason': None}]})}\n\n"
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish_reason}]})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream")
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": model_name,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
    })


# ===========================================================================
# Phase 3 -- Orchestrated multi-step execution (planner/executor split)
#
# Phase 2 (above) stops at proposing a breakdown and hands control back to the
# architect. This extends it: once the architect confirms a breakdown, the
# proxy drives the steps one at a time --
#   * narrowing each step's context to just that task's prompt + its own
#     tool-call tail (not the accumulated multi-turn history -- intermediate-
#     step noise corrupts later reasoning, the "context drift" failure mode
#     documented in arXiv:2512.21354, "Reflection-Driven Control for
#     Trustworthy Code Agents"),
#   * snapshotting the working tree before each step (a precise, reviewable
#     `git status`-based diff -- NOT a commit; auto-committing on the
#     orchestrator's behalf would violate this project's one-commit-per-task /
#     no-`git add -A` discipline, see CLAUDE.md "Commit Hygiene" -- so a bad
#     step is a clean revert rather than a forensic exercise),
#   * and validating each step against observable evidence before proceeding.
#
# Stage 1 shipped a manual "continue?" gate -- safe, observable, end-to-end
# testable, and a deliberate stepping stone (see its note: "Stage 2 replaces
# this with an automatic artifact-based validator"). Stage 2+3 (merged just
# below, in "Stage 2+3 -- artifact-based validation and bounded ambiguity
# escalation") IS that replacement: an automatic YES/NO/AMBIGUOUS verdict
# computed from the diff and the executor's own claims -- not its self-report
# taken at face value (arXiv:2512.21354 names that "overconfidence": models
# assert completion without adequate evidence) -- drives the run forward
# (YES), halts it outright (NO -- a demonstrated failure is not auto-retried),
# or pauses it behind a bounded, one-shot OQ (AMBIGUOUS -- capped at one
# automated raise per step; a second AMBIGUOUS on the same step is a hard stop,
# not a second OQ). That cap is directly informed by the publicly documented
# $47K runaway-loop postmortem, where two LangChain agents' unbounded
# "clarification ping-pong" ran for 11 days and compounded from $127/week to
# $18,400/week
# (https://dev.to/gabrielanhaia/the-agent-that-spent-47k-on-itself-an-autonomous-loop-postmortem-3313).
# Loop detector + step cap + the existing spend cap are the three independent
# circuit breakers that keep this from becoming that story.
#
# YES verdicts auto-advance WITHOUT waiting for a reply -- which is what makes
# this "Option B" (the architect's own framing: "practically necessary ... but
# ... we should focus on validating that the previous task was fully and
# successfully implemented and ... surface an OQ when ambiguity arises ... is
# the mechanism we use to prevent option B getting out of hand"). Mechanically,
# auto-advance means chaining multiple upstream CF calls inside ONE incoming
# request from Continue -- the proxy can only respond to requests Continue
# sends, it cannot push a "go to the next step" message on its own, so a step
# that finishes clean must immediately dispatch the next step's first turn
# itself rather than returning control and waiting. `_finish_step` is where
# that chaining happens (verdict "yes" -> straight into `_dispatch_step` for
# `step_idx + 1`, all still inside the same response to Continue).
# ===========================================================================

_ORCHESTRATOR_STATE_DIR = os.path.join(os.path.expanduser("~"), ".cf_proxy_orchestrator")

# Hard ceiling on steps per orchestrated run -- independent of (and in addition
# to) the daily spend cap. A breakdown proposing more than this is too coarse
# to orchestrate safely; the architect should re-slice it first.
_ORCHESTRATOR_MAX_STEPS = 12

_ORCHESTRATOR_CONTINUE_RE = re.compile(
    r"\b(continue|next(?:\s+step)?|go\s+on|proceed|keep\s+going)\b", re.IGNORECASE)
_ORCHESTRATOR_HALT_RE = re.compile(
    r"\b(stop|halt|cancel|abort|hold\s+on|wait|pause)\b", re.IGNORECASE)
# Replies at confirmation/checkpoint gates must be SHORT affirmations -- a long
# message that happens to contain "yes" somewhere is a new ask, not a gate reply.
_ORCHESTRATOR_GATE_REPLY_MAX_CHARS = 200


_ORCHESTRATOR_KEY_RE = re.compile(r"\[orchestrator-key:\s*([0-9a-f]{16})\]")


def _orchestrator_key(trigger_text: str) -> str:
    """Stable identity for an orchestration run.

    Normally a hash of the first user message in the conversation: that
    message stays put in conversation history for the run's lifetime, so
    re-deriving the key from it (rather than a session ID Continue.dev
    doesn't expose to the proxy) reliably finds the same state across every
    subsequent request in the same thread.

    If `trigger_text` instead embeds an explicit `[orchestrator-key: <hex>]`
    marker, that key is reused directly. This is the resume path
    (CB-9/OQ-262 Option C): `_format_resume_prompt` puts this marker in the
    first message of a FRESH (non-`--id`) cline session that resumes a
    paused run, so the new session's first message re-derives the SAME run
    identity without any Cline session replay."""
    m = _ORCHESTRATOR_KEY_RE.search(trigger_text)
    if m:
        return m.group(1)
    return hashlib.sha256(trigger_text.strip().encode("utf-8")).hexdigest()[:16]


def _orchestrator_state_path(key: str) -> str:
    return os.path.join(_ORCHESTRATOR_STATE_DIR, f"{key}.json")


def _load_orchestrator_state(key: str):
    try:
        with open(_orchestrator_state_path(key), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_orchestrator_state(key: str, state: dict) -> None:
    """Persist orchestrator state to disk under an advisory lock (AT-1162) so
    a concurrent writer (e.g. orchestrator_status.py --apply running alongside
    an active orchestrator request) blocks and retries rather than clobbering
    the in-flight update."""
    os.makedirs(_ORCHESTRATOR_STATE_DIR, exist_ok=True)
    state["updated"] = datetime.now(timezone.utc).isoformat()
    path = _orchestrator_state_path(key)
    try:
        with _ledger_lock(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except Exception as e:
                print(f"[cfproxy][orchestrator] failed to persist state {key}: {e}", file=sys.stderr)
    except RuntimeError as e:
        print(f"[cfproxy][orchestrator] _save_orchestrator_state lock error: {e}", file=sys.stderr)


def _orchestrator_log(state: dict, message: str) -> None:
    state.setdefault("log", []).append({"ts": datetime.now(timezone.utc).isoformat(), "message": message})
    print(f"[cfproxy][orchestrator] {message}", file=sys.stderr)


def _new_orchestrator_state(steps: list, reason: str, model: str = None) -> dict:
    return {
        "created": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "steps": steps,                      # list[str] -- the confirmed plan, fixed at creation
        "current": 0,                        # 0 = not yet dispatched; 1-based once running
        "anchor_index": None,                # index of the last message before the current step's tail begins
        "status": "running",                 # running -> (paused_for_oq ->) halted | complete
        "snapshot_before_step": None,
        "ambiguity_raised_for_step": None,   # Stage-3 loop detector: at most one OQ per step
        "ambiguity_last_summary": None,      # CB-12: the AMBIGUOUS step's own executor summary,
                                              # so an Option-A "continue" resolution can still
                                              # extract and record its finding (see
                                              # _record_resolved_step_finding)
        "ambiguity_oq_id": None,             # CB-12: the OQ id raised for ambiguity_raised_for_step,
                                              # used in the synthesized-finding fallback text
        "model": model,                      # cf/<model> used for this run -- needed by
                                              # resume-orchestrator-run.ps1 (CB-9/OQ-262) to
                                              # relaunch a paused run with the same model
        "findings": [],                      # OQ-263/CB-10(b): mechanical per-step findings
                                              # carry-forward, oldest-first, each
                                              # {"step": int, "total": int, "text": str}
        "log": [],
    }


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _find_breakdown_trigger(messages: list):
    """Locate (index, text) of the first user-role message in the conversation --
    the original ask that, if it matched _detect_multi_step_ask, seeded an
    orchestrator run keyed on _orchestrator_key(this text). Continue/Cline
    always keep this as the first user turn for the run's lifetime, so it
    reliably re-derives the same key on every subsequent request in the
    thread without needing a session ID Continue.dev doesn't expose to the
    proxy."""
    for i, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return i, _message_text(msg)
    return None, None


async def _git_snapshot(workspace: str) -> dict:
    """Record enough of the working tree's state to precisely identify what a
    step changed -- WITHOUT creating a commit (auto-committing on the
    orchestrator's behalf would violate this project's one-commit-per-task /
    no-`git add -A` discipline; see CLAUDE.md "Commit Hygiene"). A porcelain
    snapshot diffed before/after gives the architect the same "what did this
    touch" answer a commit would, and `git checkout`/`git clean` on the
    specific paths gives the same rollback guarantee, without polluting history."""
    async def _run(*args):
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=workspace,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate()
        return out.decode("utf-8", "replace").strip()
    try:
        return {"head": await _run("rev-parse", "HEAD"), "dirty": (await _run("status", "--porcelain")).splitlines()}
    except Exception as e:
        return {"head": None, "dirty": [], "error": str(e)}


def _diff_snapshots(before: dict, after: dict) -> list:
    """Paths that became dirty, or whose dirty status changed, between two
    snapshots -- i.e. what THIS step touched. Compares whole porcelain lines
    (not just paths): a file already dirty before the step, in the same way,
    didn't change because of this step and is deliberately excluded -- showing
    it would mislead the architect into reviewing pre-existing, unrelated work."""
    new_or_changed = set(after.get("dirty", [])) - set(before.get("dirty", []))
    return sorted({line[3:] for line in new_or_changed if len(line) > 3})


# ---------------------------------------------------------------------------
# Stage 2+3 -- artifact-based validation and bounded ambiguity escalation.
#
# Stage 1's checkpoint trusted the architect to read the diff. Stage 2 replaces
# that with an automatic verdict computed from the SAME evidence (the diff,
# plus what the executor's own summary claims) -- not the executor's self-
# report taken at face value. arXiv:2512.21354 names this failure mode
# "overconfidence": models assert completion without adequate evidence; the
# documented fix is "execution-based validation" -- judge from artifacts.
#
# A verdict of YES or NO is unambiguous enough to act on automatically. A
# verdict of AMBIGUOUS is exactly the case the architect's own framing called
# out: "surfacing OQs ... is necessary ... but may also derail task progress."
# Stage 3 (merged here, since AMBIGUOUS *is* what triggers it) answers that by
# raising a bounded OQ -- capped at ONE automated raise per step via
# `ambiguity_raised_for_step`. A second AMBIGUOUS verdict on the same step is a
# hard stop, not a second OQ: this is the loop-detector the $47K postmortem
# (two LangChain agents' unbounded "clarification ping-pong" running 11 days,
# https://dev.to/gabrielanhaia/the-agent-that-spent-47k-on-itself-an-autonomous-loop-postmortem-3313)
# says the ambiguity-resolution mechanism itself needs, or it becomes the very
# runaway loop it exists to prevent.
#
# Deliberately NOT a two-tier "mechanical-then-model-judgment" design: a second
# tier means a second upstream CF call per step -- an unbounded-cost surface of
# exactly the kind the spend cap and step cap exist to bound. Mechanical-only
# checks against the diff and the summary's own language are enough to catch
# the two failure shapes that matter here (explicit failure language, and
# "claims a change but none occurred") without adding a cost surface.
# ---------------------------------------------------------------------------

_VALIDATOR_FAILURE_RE = re.compile(
    r"\b(fail(?:ed|s|ure)?|error(?:s|ed)?|could ?n[o']?t|unable to|"
    r"did ?n[o']?t work|cannot proceed|is broken|not working|crash(?:ed|es)?)\b",
    re.IGNORECASE)

# A read-only step's honest summary routinely says things like "no errors
# found" or "the file does not contain any failures" -- _VALIDATOR_FAILURE_RE
# matches the bare noun ("error(s)"/"fail(s|ure)") in both that sentence and a
# genuine "I hit an error" report, so it can't tell them apart on its own.
# Strip negated-failure phrases (verified empirically 2026-06-10: step 1 of an
# 8-step gpt-oss-120b run -- "Open the file ... " -- was marked NO on its first
# successful pass for exactly this reason, halting the run after step 1 every
# time) before running _VALIDATOR_FAILURE_RE so a clean "no errors" summary
# doesn't read as a failure report.
_VALIDATOR_NEGATED_FAILURE_RE = re.compile(
    r"\b(?:no|not|n[o']t|without|zero|never|nothing|none(?: of the)?)\s+(?:\w+\s+){0,3}?"
    r"(?:error(?:s|ed)?|fail(?:ed|s|ure)?|issues?|problems?|warnings?)\b",
    re.IGNORECASE)

# CB-8 (2026-06-11, test #12): a step that quotes/transcribes literal text
# from a source document (per _ORCHESTRATOR_STEP_SYSTEM_PROMPT's verbatim-quote
# requirement) routinely reproduces that source's own discussion of failures --
# e.g. this very roadmap doc's prose about CB-1 "degenerate-empty-response
# failures". _VALIDATOR_FAILURE_RE matched "failures" inside such a quote and
# returned NO on a fully-correct, 0-files-changed read step. The system prompt
# now requires reproduced source text to be set apart as a markdown blockquote
# (lines starting with '>') or a fenced code block; strip both before running
# the failure-language scan so a verbatim quote's own wording can't be
# mistaken for the executor's self-report of THIS step's outcome.
_VALIDATOR_FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_VALIDATOR_BLOCKQUOTE_LINE_RE = re.compile(r"^[ \t]*>.*$", re.MULTILINE)

# The step system prompt explicitly tells the executor to say so plainly and
# STOP if its assumptions don't match the codebase -- this regex recognizes
# that exact escape hatch being used, which is itself an ambiguity signal.
_VALIDATOR_STOP_RE = re.compile(
    r"\b(assumptions? (?:don'?t|do ?not) match|can'?t be done as written|"
    r"stopping here|won'?t improvise|need(?:s)? (?:clarification|the architect))\b",
    re.IGNORECASE)

_VALIDATOR_CHANGE_VERB_RE = re.compile(
    r"\b(add|create|write|implement|fix|update|modify|change|remove|delete|"
    r"refactor|rename|replace|move|wire|hook ?up|integrate)\b", re.IGNORECASE)

_VALIDATOR_NO_CHANGE_NEEDED_RE = re.compile(
    r"\b(no changes? (?:were |was )?(?:needed|necessary|required)|"
    r"already (?:correct|implemented|in place|done|present)|"
    r"nothing (?:to change|needed (?:to change|changing))|"
    r"(?:investigation|read-only|verification) only)\b",
    re.IGNORECASE)

# CB-11 (2026-06-12, test #13/#14, second+third occurrences): a step whose
# task is "Record/Identify/Quote/Note the exact quote/sentence/value stating
# X" is read-only by design -- an empty diff IS the correct result. Twice now
# (run `97ee060abc9315f1` step 4/8, run `a731f317e9507669` step 4/8) such a
# step's own task wording happened to also contain an incidental change-verb
# word (e.g. "...after the fix...") that tripped _VALIDATOR_CHANGE_VERB_RE,
# producing a spurious AMBIGUOUS verdict on an otherwise-correct read step.
# CB-11 (2026-06-12, test #15, fourth occurrence): "Copy the exact sentence
# stating X" is the same read-only-by-design shape as "Record/Identify/..."
# above, but the verb alternation didn't include "copy" -- added here along
# with "transcribe"/"extract", which describe the same read-and-quote action
# and are guarded by the same "exact quote/sentence/wording/text/value"
# requirement so they can't match a refactor-style "extract a function" step.
_VALIDATOR_RECORD_ONLY_STEP_RE = re.compile(
    r"^\s*(?:record|identify|note|quote|locate|copy|transcribe|extract)\b.*\bexact\s+(?:quote|sentence|wording|text|value)\b",
    re.IGNORECASE)


def _run_validator_pass(step_task: str, summary_text: str, changed_files: list, head_changed: bool = False) -> tuple[str, str]:
    """Execution-based validator: returns (verdict, reason), verdict in
    {"yes", "no", "ambiguous"}. Judges from the diff and the summary's own
    claims -- the observable artifacts -- not from trusting the self-report.

    - explicit failure language in the summary -> "no"
    - executor used its documented stop-and-say-so escape hatch -> "ambiguous"
    - the step's own wording implies a code change, the diff shows none, HEAD
      didn't move, and the summary doesn't explain why -> "ambiguous"
      (contradiction between what the step asked for and what observably
      happened)
    - otherwise -> "yes"

    `head_changed` (CB-11, 2026-06-12, third occurrence): True when the
    pre-/post-step `git rev-parse HEAD` differ, i.e. the step made a commit.
    A successful commit leaves the working tree clean vs. the new HEAD, so
    `changed_files` (a working-tree dirty-state diff) is empty even though the
    step succeeded -- `head_changed` is the corresponding evidence for
    "1 commit ahead" that `changed_files` can't express.
    """
    summary = (summary_text or "").strip()

    if _VALIDATOR_STOP_RE.search(summary):
        return "ambiguous", "executor used its stop-and-say-so escape hatch -- its assumptions didn't match what it found"

    summary_sans_quotes = _VALIDATOR_FENCED_BLOCK_RE.sub("", summary)
    summary_sans_quotes = _VALIDATOR_BLOCKQUOTE_LINE_RE.sub("", summary_sans_quotes)
    summary_sans_negated_failures = _VALIDATOR_NEGATED_FAILURE_RE.sub("", summary_sans_quotes)
    if _VALIDATOR_FAILURE_RE.search(summary_sans_negated_failures):
        return "no", "summary contains explicit failure language (error / failed / could not / ...)"

    implies_change = bool(_VALIDATOR_CHANGE_VERB_RE.search(step_task))
    explains_no_change = bool(_VALIDATOR_NO_CHANGE_NEEDED_RE.search(summary))
    is_record_only_step = bool(_VALIDATOR_RECORD_ONLY_STEP_RE.search(step_task))
    if implies_change and not changed_files and not head_changed and not explains_no_change and not is_record_only_step:
        return "ambiguous", "the step's own wording implies a working-tree change, but the diff is empty and the summary doesn't explain why"

    if changed_files:
        return "yes", "no failure language detected; the diff is consistent with the step's claims"
    if head_changed:
        return "yes", "no failure language detected; the working tree is clean but HEAD advanced (a commit was made), consistent with the step's claims"
    if is_record_only_step:
        return "yes", "no failure language detected; step is a read-only 'record/identify the exact ...' step, so an empty diff is expected"
    return "yes", "no failure language detected; this step did not imply a working-tree change"


# _next_oq_id / _format_oq_row: see ledger_io.py for implementation and docs --
# moved there (AT-1161) so the OQ-ledger text logic can be unit-tested without
# a FastMCP server or tempfile. Aliased here under their original names so
# existing call sites and tests (test_local_mcp_oq_at_tools.py) are unaffected.
_next_oq_id = ledger_io.next_oq_id
_format_oq_row = ledger_io.format_oq_row


_OQ_SEARCH_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "into", "this", "that", "then",
    "than", "have", "has", "had", "are", "was", "were", "will", "would",
    "should", "could", "step", "task", "make", "ensure", "update", "create",
    "add", "implement", "build", "write", "verify", "check", "confirm",
})


def _oq_search_keywords(step_task: str) -> list[str]:
    """Pull distinguishing words (length > 4, not stopwords, de-duplicated, in
    order of first appearance) out of a step's task text -- input to the
    lightweight automated precedent search below. Mirrors the *spirit* of
    policy SR-1.12 oq-authoring-and-precedent-search-policy.md S4.1 step 1
    ('grep the live ledger for keywords describing the subject -- the noun,
    not the verb'); the stopword list is verb/filler-heavy for that reason."""
    words = re.findall(r"[a-z][a-z\-_]{4,}", step_task.lower())
    seen: list[str] = []
    for w in words:
        if w not in _OQ_SEARCH_STOPWORDS and w not in seen:
            seen.append(w)
    return seen[:6]


def _lightweight_oq_precedent_note(oq_doc_text: str, step_task: str) -> str:
    """Produce the mandatory S6.2 precedent-search note for an automated
    ambiguity OQ. An automated path can mechanically do the *cheapest* leg of
    S4.1 (keyword-overlap grep of the live ledger's Question cells) but cannot
    do the other three (oq-decision-triage.md, owning-spec INDEX.md notes,
    design-goals.md directives -- all of which require subsystem judgment this
    escalation path doesn't have). Per S4.2 'no precedent found', saying
    plainly what was and wasn't searched is itself useful signal -- it tells
    the architect whether to spend a minute on their own grep before answering."""
    keywords = _oq_search_keywords(step_task)
    if not keywords:
        return ("Automated keyword search found no distinguishing terms in this step's task "
                "text to search on (too short / too generic) -- skipped. A full S4.1 search "
                "(oq-decision-triage.md, owning-spec INDEX.md, design-goals.md directives) was "
                "not attempted by this automated path; the architect may want to run one manually.")
    hits: list[str] = []
    for line in oq_doc_text.splitlines():
        m = re.match(r"\|\s*OQ-(\d+)\s*\|", line)
        if not m:
            continue
        lowered = line.lower()
        if sum(1 for kw in keywords if kw in lowered) >= 2:
            hits.append(f"OQ-{m.group(1)}")
    keyword_list = ", ".join(keywords)
    if hits:
        return (f"Automated keyword-overlap search of the live ledger (terms: {keyword_list}) "
                f"surfaced possible adjacent precedent(s): {', '.join(hits[:5])}. Per policy "
                f"S4.2, if one of these settles this case by analogy, applying it directly (and "
                f"citing it) is preferable to answering fresh -- worth a glance before replying. "
                f"This automated path did not check oq-decision-triage.md, the owning spec's "
                f"INDEX.md notes, or design-goals.md directives (S4.1 steps 2-4); those remain "
                f"open if the hits above don't resolve it.")
    return (f"Automated keyword-overlap search of the live ledger (terms: {keyword_list}) found "
            f"no adjacent OQ -- this looks like a fresh question for this step shape, though "
            f"this automated path could only check the live ledger's Question cells, not "
            f"oq-decision-triage.md, owning-spec INDEX.md notes, or design-goals.md directives "
            f"(S4.1 steps 2-4). Noting an empty result here per S4.2 so the architect knows "
            f"what was and wasn't searched, rather than assuming a full search occurred.")


def _format_step_ambiguity_oq(run_key: str, step_idx: int, total: int, step_task: str,
                              verdict_reason: str, summary_text: str,
                              oq_doc_text: str = "") -> tuple[str, str, str, str]:
    """Build the (question, context, unblocks, date) cells for an OQ raised by
    the bounded ambiguity-escalation path -- one per step, never more (see the
    Stage 2+3 module docstring for why a second one is a hard stop instead).
    Conforms to the structure mandated by SR-1.12's
    oq-authoring-and-precedent-search-policy.md S6: a problem statement that
    names the actual tension (not just 'verdict was ambiguous'), a mandatory
    S6.2 precedent-search note (S4, scoped to what an automated path can
    mechanically do -- see _lightweight_oq_precedent_note), options with real
    pros/cons rather than terse labels, a recommendation held loosely (S6.4),
    and an unblocks section that names the cascade possibility (S6.5/S7)."""
    excerpt = (summary_text or "").strip()[:500].replace("\n", " ")
    precedent_note = _lightweight_oq_precedent_note(oq_doc_text, step_task)
    question = (
        f"**[ORCHESTRATOR] Step {step_idx}/{total} of automated run `{run_key}` came back "
        f"AMBIGUOUS -- how should it proceed?**\n\n"
        f"**Problem.** Step as confirmed: *{step_task}*. The mechanical, artifact-based "
        f"validator (`_run_validator_pass` -- it inspects the actual working-tree diff, not the "
        f"executor's self-report, per the validator-at-the-boundary principle) could not "
        f"classify the result as a clean YES (diff matches the step's intent) or NO (diff "
        f"contradicts it). Verdict: AMBIGUOUS -- {verdict_reason}. Executor's own closing "
        f"summary (excerpt, may be truncated): \"{excerpt}\" "
        f"This is a genuine tension, not a coin flip dressed up as one: an AMBIGUOUS verdict "
        f"is exactly what a near-empty or hard-to-classify diff produces, and that same "
        f"signature is consistent with two very different realities -- 'this step legitimately "
        f"required no working-tree change' and 'the executor silently failed to do the thing "
        f"and is reporting success anyway'. A mechanical check cannot tell those apart; that is "
        f"the entire reason this routes to the architect rather than guessing. The stakes are "
        f"asymmetric, too: guessing 'fine, continue' when it wasn't compounds an undetected "
        f"defect onto every later step that assumes this one's output exists, while guessing "
        f"'halt' when it was actually fine burns a stop-and-resume cycle and an OQ slot on "
        f"nothing.\n\n"
        f"**Precedent search (S6.2).** {precedent_note}\n\n"
        f"**Options considered (S6.3):**\n"
        f"- **(A) Treat as complete, continue the run.** What it is: architect confirms the "
        f"near-empty/ambiguous diff is *expected* here (e.g. a verification-only step with no "
        f"working-tree footprint by design, or the validator's heuristic mis-firing on a "
        f"legitimate edge case), and the run advances to the next step. Pros: zero lost "
        f"progress; the run completes in one pass. Cons: if the read is wrong, this is the "
        f"costliest mistake of the three -- a silent failure now propagates uncaught into every "
        f"step downstream that assumes this one actually happened.\n"
        f"- **(B) Treat as incomplete, halt the run.** What it is: architect agrees the step "
        f"did not do what it claims, inspects the diff directly, reverts if needed "
        f"(`git checkout`/`git clean` on the touched paths -- the run never auto-commits, so "
        f"nothing is destructively lost), and re-confirms a corrected breakdown before "
        f"resuming. Pros: the safest failure mode -- a human looks at the real artifact before "
        f"anything else builds on it. Cons: costs a full stop-and-resume cycle even in the "
        f"case (the more common one, per the Stage 2+3 design rationale -- AMBIGUOUS is "
        f"deliberately the minority verdict) where the step actually was fine.\n"
        f"- **(C) Re-slice this step.** What it is: architect judges that the step's *wording*, "
        f"not its execution, was the root problem -- ambiguous enough that both the executor "
        f"and the mechanical validator struggled with it -- rewrites it more precisely, and "
        f"restarts the run from here. Pros: fixes the root cause rather than papering over one "
        f"instance; later steps phrased similarly won't repeat this. Cons: the most expensive "
        f"option -- effectively a partial re-plan -- and only the right call when the task "
        f"*description* (not the agent's execution of it) is actually at fault.\n\n"
        f"**Recommendation, held loosely (S6.4).** No option here is mechanically preferable -- "
        f"that asymmetry is *why* this is an OQ and not a heuristic. My inclination is that the "
        f"deciding factor is something only visible in the artifact itself: if `git diff` on the "
        f"touched paths shows *some* plausible, intent-aligned change, (A) is probably right; "
        f"if it shows *nothing* where the step's wording clearly implied something should "
        f"change, (B); if the diff looks like a defensible-but-wrong reading of genuinely vague "
        f"wording, (C). I can't make that call from here without inspecting the diff -- which "
        f"is precisely the validator-at-the-boundary principle this whole escalation path "
        f"exists to honor rather than bypass with a guess.\n\n"
        f"**Unblocks (S6.5).** Orchestrator run `{run_key}` is paused at step {step_idx}/{total} "
        f"and will not advance, retry, or raise a second OQ for this step (bounded "
        f"loop-detector: at most one automated OQ per step) until this is answered. Note also, "
        f"per the course-correction lifecycle (S7): a *custom* answer that doesn't match A/B/C "
        f"-- e.g. 'the validator's AMBIGUOUS heuristic itself needs a new case for {{X}}, fix "
        f"that and don't ask again for this shape' -- would be expected to cascade into a "
        f"follow-up OQ about `_run_validator_pass`'s classification rules. That would be the "
        f"process working as intended, not a detour from it."
    )
    context = (
        f"Orchestrator run `{run_key}`, step {step_idx}/{total}; "
        f"state file `{_orchestrator_state_path(run_key)}` (full transition log); "
        f"raised by the Phase-3 Stage 2+3 bounded-ambiguity escalation path in `scripts/local-mcp.py` "
        f"(`_run_validator_pass` / `_format_step_ambiguity_oq`), authored to conform with "
        f"`foundation/SR-1.12-autonomous-coordination/specs/oq-authoring-and-precedent-search-policy.md`."
    )
    unblocks = f"Orchestrator run `{run_key}`, step {step_idx}/{total} -- the run is paused and will not proceed until this is answered."
    return question, context, unblocks, _today_utc()


# ---------------------------------------------------------------------------
# Advisory file locking for shared ledger / state read-modify-write cycles
# (AT-1162). Uses a .lock sidecar file created with O_CREAT|O_EXCL (atomic
# exclusive creation on every OS Python supports) to prevent two concurrent
# writers from racing and silently clobbering each other on the OQ ledger,
# the AT queue, and the orchestrator-state JSON files. No new dependency --
# stdlib only. ledger_io.py pure functions remain lock-free; locking lives
# here in the I/O wrappers.
# ---------------------------------------------------------------------------

_LEDGER_LOCK_TIMEOUT = float(os.environ.get("CF_PROXY_LOCK_TIMEOUT_SECONDS", "10"))
_LEDGER_LOCK_RETRY_INTERVAL = 0.05  # 50 ms between acquisition attempts


@contextlib.contextmanager
def _ledger_lock(path: str, timeout: float = _LEDGER_LOCK_TIMEOUT):
    """Cross-platform advisory lock around a shared file read-modify-write.

    Creates a PATH.lock sidecar file with O_CREAT|O_EXCL (atomic on both
    POSIX and Windows). Retries every _LEDGER_LOCK_RETRY_INTERVAL seconds
    until `timeout` seconds have elapsed. Releases (deletes) the sidecar
    on exit regardless of whether the body raised.

    Raises RuntimeError if the lock cannot be acquired within `timeout`
    seconds -- the caller catches this and returns False / an error string
    rather than letting it propagate into the FastMCP response frame.

    This is an advisory lock: it only guards against processes that also
    use _ledger_lock on the same sidecar path (all local-mcp.py write
    paths do). A process that writes without locking (e.g. an architect
    hand-editing the file) is not prevented from doing so -- the goal is
    to protect concurrent MCP-server / orchestrator sessions from each
    other, not to prevent intentional direct edits."""
    lock_path = path + ".lock"
    deadline = time.monotonic() + timeout
    waited = False
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break  # acquired
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"[cfproxy][lock] could not acquire advisory lock {lock_path!r} "
                    f"within {timeout}s -- another writer may be stuck"
                )
            if not waited:
                print(
                    f"[cfproxy][lock] waiting for advisory lock {lock_path!r} "
                    f"(another writer holds it)",
                    file=sys.stderr,
                )
                waited = True
            time.sleep(_LEDGER_LOCK_RETRY_INTERVAL)
    if waited:
        print(
            f"[cfproxy][lock] acquired {lock_path!r} after brief wait",
            file=sys.stderr,
        )
    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except OSError as exc:
            print(
                f"[cfproxy][lock] failed to remove lock file {lock_path!r}: {exc}",
                file=sys.stderr,
            )


def _append_oq_row(row: str) -> bool:
    """Append a freshly-formatted OQ row directly below the table's header
    separator -- the file's existing convention is newest-first (OQ-258 sits
    above OQ-257, etc.), so a fresh row belongs at the top of the table body,
    not the bottom. Returns False (and logs) if the separator can't be found --
    the caller must not silently lose an OQ it believes it raised. The "where
    in the text does this go" logic lives in ledger_io.insert_oq_row (unit
    tested); this function is just the file I/O + path resolution around it.

    Also bumps the doc's high-water-mark marker (CB-18 fix, see
    ledger_io.next_oq_id) to this row's id, so a future next_oq_id() call
    still skips this id even after the row itself is later deleted on
    resolution. A missing marker line is logged, not silently ignored --
    next_oq_id() falls back to its row-scan in that case, which is the
    pre-fix (CB-18-prone) behavior.

    AT-1162: the read-modify-write is wrapped in _ledger_lock so a second
    concurrent writer blocks and retries rather than racing."""
    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with _ledger_lock(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc_text = f.read()
            except Exception as e:
                print(f"[cfproxy][orchestrator] failed to read OQ doc to append a row: {e}", file=sys.stderr)
                return False
            row_id_match = re.match(r"^\|\s*OQ-(\d+)\s*\|", row)
            if row_id_match:
                doc_text, bumped = ledger_io.bump_oq_high_water_mark(doc_text, int(row_id_match.group(1)))
                if not bumped:
                    print(f"[cfproxy][orchestrator] OQ high-water-mark marker not found or not raised for {row_id_match.group(0)} -- next_oq_id() will rely on row-scan only", file=sys.stderr)
            new_text, inserted = ledger_io.insert_oq_row(doc_text, row)
            if not inserted:
                print("[cfproxy][orchestrator] OQ doc has no '|---' header separator -- refusing to guess where to insert", file=sys.stderr)
                return False
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_text)
            except Exception as e:
                print(f"[cfproxy][orchestrator] failed to write OQ doc after appending a row: {e}", file=sys.stderr)
                return False
    except RuntimeError as e:
        print(f"[cfproxy][orchestrator] _append_oq_row lock error: {e}", file=sys.stderr)
        return False
    return True


_OQ_VALID_REVERSIBILITY = ("Reversible", "Irreversible")


def _odysseus_notes_mode_active() -> bool:
    """True when ODYSSEUS_API_URL/ODYSSEUS_API_TOKEN are both set and
    GET {ODYSSEUS_API_URL}/api/notes authenticates with the bearer token --
    the AT-1153 reachability check. Any other outcome (env vars unset,
    connection error, non-200 response) means the markdown-ledger mode stays
    active; a failed reachability check is logged so the choice of mode is
    always observable, not silent."""
    if not ODYSSEUS_API_URL or not ODYSSEUS_API_TOKEN:
        return False
    try:
        resp = httpx.get(
            f"{ODYSSEUS_API_URL}/api/notes",
            headers={"Authorization": f"Bearer {ODYSSEUS_API_TOKEN}"},
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[cfproxy][odysseus] Notes-mode reachability check failed, using markdown ledger: {e}", file=sys.stderr)
        return False


def _odysseus_create_note(label: str, title: str, content: str, items: list[dict]) -> str:
    """POST a new agent-authored checklist note (AT-1153 Odysseus-Notes
    alternative mode) to a reachable Odysseus instance. Returns
    "<label>-odysseus-<note_id>" on success -- the "-odysseus-" infix
    disambiguates Notes-mode IDs (Odysseus's own Note primary key, an
    independent ID space) from the markdown ledgers' OQ-<N>/AT-<N> sequences,
    per OQ-269's preemptive answer. Returns an "ERROR: ..." string on any
    failure (connection error, non-2xx response, or a response missing
    'id'), writing nothing -- reject, don't substitute, per the
    Validator-at-the-Boundary policy."""
    try:
        resp = httpx.post(
            f"{ODYSSEUS_API_URL}/api/notes",
            headers={"Authorization": f"Bearer {ODYSSEUS_API_TOKEN}"},
            json={
                "note_type": "checklist",
                "label": label,
                "source": "agent",
                "title": title,
                "content": content,
                "items": items,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        note = resp.json()
    except Exception as e:
        print(f"[cfproxy][odysseus] failed to create {label} note: {e}", file=sys.stderr)
        return f"ERROR: failed to create Odysseus {label} note: {e}"
    note_id = note.get("id")
    if note_id is None:
        print(f"[cfproxy][odysseus] {label} note created but response had no 'id': {note}", file=sys.stderr)
        return f"ERROR: Odysseus {label} note created but response had no 'id': {note}"
    print(f"[cfproxy][odysseus] {label}-odysseus-{note_id} created via Odysseus Notes mode (note_type=checklist, label={label})", file=sys.stderr)
    return f"{label}-odysseus-{note_id}"


@mcp.tool()
def create_open_question(
    question: str,
    options: list[str],
    preemptive_answer: str,
    preemptive_reasoning: str,
    reversibility: str,
    context_spec: str,
    unblocks: str,
    precedent_search_note: str,
) -> str:
    """Append a new row to the OQ ledger (ADR-011 Part 2 schema:
    task-and-oq-authoring-standard.md). `question` is the fully-composed
    Question cell content -- by this project's content-authoring policy
    (oq-authoring-and-precedent-search-policy.md S6) it should already embed
    the problem statement, lettered options, a held-loosely recommendation,
    and the precedent-search note; the separate `options`/`preemptive_answer`/
    `preemptive_reasoning`/`precedent_search_note`/`reversibility` fields are
    validated here (per the Validator-at-the-Boundary policy) so a caller
    cannot skip the ADR-011 authoring steps, even though they are not
    re-rendered into a second copy inside the cell.

    Returns "OQ-<N>" on success (the freshly-minted id, one greater than the
    current live max per _next_oq_id). On a missing/invalid required field,
    REJECTS -- returns an "ERROR: ..." string naming the field(s) and writes
    nothing. On an I/O failure reading/writing the ledger, returns an
    "ERROR: ..." string and writes nothing."""
    errors: list[str] = []
    if not question or not question.strip():
        errors.append("question")
    if not options or len(options) < 2:
        errors.append("options (must be a list of at least 2 lettered options)")
    if not preemptive_answer or not preemptive_answer.strip():
        errors.append("preemptive_answer")
    if not preemptive_reasoning or not preemptive_reasoning.strip():
        errors.append("preemptive_reasoning")
    if reversibility not in _OQ_VALID_REVERSIBILITY:
        errors.append(f"reversibility (must be one of {_OQ_VALID_REVERSIBILITY})")
    if not context_spec or not context_spec.strip():
        errors.append("context_spec")
    if not unblocks or not unblocks.strip():
        errors.append("unblocks")
    if not precedent_search_note or not precedent_search_note.strip():
        errors.append("precedent_search_note")
    if errors:
        return f"ERROR: create_open_question rejected -- missing/invalid field(s): {', '.join(errors)}. No row written."

    if _odysseus_notes_mode_active():
        title = question.strip().splitlines()[0][:200]
        content = "\n".join([
            question,
            "",
            f"**Options:** {' / '.join(options)}",
            f"**Preemptive answer:** {preemptive_answer}",
            f"**Preemptive reasoning:** {preemptive_reasoning}",
            f"**Reversibility:** {reversibility}",
            f"**Context / Spec:** {context_spec}",
            f"**Unblocks:** {unblocks}",
            f"**Precedent search:** {precedent_search_note}",
        ])
        items = [{"text": opt, "done": False} for opt in options]
        return _odysseus_create_note("OQ", title, content, items)

    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc_text = f.read()
    except Exception as e:
        print(f"[cfproxy][oq] failed to read OQ doc to compute next id: {e}", file=sys.stderr)
        return f"ERROR: could not read OQ ledger at {path}: {e}"
    oq_id = _next_oq_id(doc_text)
    row = _format_oq_row(oq_id, question, context_spec, unblocks, _today_utc())
    if not _append_oq_row(row):
        return "ERROR: failed to append OQ row -- see server log for details"
    print(f"[cfproxy][oq] OQ-{oq_id} appended to markdown ledger {path} (Odysseus Notes mode inactive)", file=sys.stderr)
    return f"OQ-{oq_id}"


@mcp.tool()
def list_open_questions() -> str:
    """List every OQ in the Open Questions table as a one-line summary:
    "OQ-<N> (<date>): <title>", newest-first (the ledger's own ordering).

    Use this instead of reading the whole OQ ledger file when the question is
    "what's open" -- the ledger's "Last updated" header is a long prose
    history of every previously-resolved OQ that is irrelevant to that
    question and costs many tokens to read.

    Returns "No open questions found." if the table is empty, or an
    "ERROR: ..." string if the ledger can't be read."""
    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc_text = f.read()
    except Exception as e:
        return f"ERROR: could not read OQ ledger at {path}: {e}"
    entries = ledger_io.parse_oq_summaries(doc_text)
    if not entries:
        return "No open questions found."
    return "\n".join(f"OQ-{e['id']} ({e['date'] or '?'}): {e['summary']}" for e in entries)


@mcp.tool()
def get_open_question(oq_id: int) -> str:
    """Return the full text of OQ-<oq_id>'s row, including any multi-line
    continuation (many orchestrator-raised OQs embed several paragraphs in
    their Question cell). Returns "ERROR: OQ-<oq_id> not found ..." if no row
    with that id exists in the Open Questions table.

    Use this to read one specific OQ's full content cheaply, instead of
    reading the whole ledger file (which also contains the long "Last
    updated" changelog history of every previously-resolved OQ)."""
    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc_text = f.read()
    except Exception as e:
        return f"ERROR: could not read OQ ledger at {path}: {e}"
    block = ledger_io.get_oq_block(doc_text, oq_id)
    if block is None:
        return f"ERROR: OQ-{oq_id} not found in the Open Questions table at {path}"
    return block


@mcp.tool()
def resolve_open_question(oq_id: int) -> str:
    """Remove OQ-<oq_id>'s row from the Open Questions table and return its
    full text. Returns "ERROR: OQ-<oq_id> not found ..." (and writes nothing)
    if no row with that id exists.

    This is deliberately ONLY the mechanical half of resolving an OQ: it does
    not compose a "Last updated" changelog entry summarizing the architect's
    decision. That entry requires the architect's actual answer and an
    agent's judgment about how to phrase it -- a first-class step of its own,
    not a "fallback" this tool skips. After calling this, write a new
    "Previously: (<date>) (**OQ-<oq_id> resolved ...** -- <summary of the
    decision>)" entry prepended to the ledger's "Last updated" line, following
    the existing entries there as a format model."""
    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc_text = f.read()
    except Exception as e:
        return f"ERROR: could not read OQ ledger at {path}: {e}"
    new_text, removed = ledger_io.remove_oq_block(doc_text, oq_id)
    if removed is None:
        return f"ERROR: OQ-{oq_id} not found in the Open Questions table at {path}"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    except Exception as e:
        print(f"[cfproxy][oq] failed to write OQ doc after removing OQ-{oq_id}: {e}", file=sys.stderr)
        return f"ERROR: failed to write OQ ledger after removing OQ-{oq_id}: {e}"
    print(f"[cfproxy][oq] OQ-{oq_id} row removed from {path} -- caller must still record a 'Last updated' changelog entry", file=sys.stderr)
    return removed


# Fixed A/B/C option labels for the bounded ambiguity-escalation path's OQ --
# the full pros/cons for each are embedded in _format_step_ambiguity_oq's
# "Options considered (S6.3)" section of the question cell; these short
# labels exist only so _raise_step_ambiguity_oq can satisfy
# create_open_question's >=2-lettered-options validation without duplicating
# that prose a second time.
_STEP_AMBIGUITY_OPTIONS = [
    "(A) Treat as complete, continue the run.",
    "(B) Treat as incomplete, halt the run.",
    "(C) Re-slice this step.",
]


def _raise_step_ambiguity_oq(run_key: str, state: dict, step_idx: int, step_task: str, verdict_reason: str, summary_text: str) -> str:
    """Format and append the bounded, one-per-step ambiguity OQ; returns the OQ
    id string (e.g. "OQ-259") on success, or "" if the append failed (in which
    case the caller falls back to surfacing the ambiguity inline rather than
    claiming an OQ exists when it doesn't)."""
    path = _resolve(ORCHESTRATOR_OQ_LEDGER_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc_text = f.read()
    except Exception as e:
        print(f"[cfproxy][orchestrator] failed to read OQ doc to compute next id: {e}", file=sys.stderr)
        return ""
    total = len(state["steps"])
    question, context, unblocks, _date = _format_step_ambiguity_oq(run_key, step_idx, total, step_task, verdict_reason, summary_text, doc_text)
    result = create_open_question(
        question=question,
        options=list(_STEP_AMBIGUITY_OPTIONS),
        preemptive_answer="No option is mechanically preferable -- see 'Recommendation, held loosely (S6.4)' embedded in the question cell.",
        preemptive_reasoning="The deciding factor (what the actual diff on the touched paths shows) is only visible to a human inspecting the artifact, which is the entire point of escalating rather than guessing.",
        reversibility="Reversible",
        context_spec=context,
        unblocks=unblocks,
        precedent_search_note=_lightweight_oq_precedent_note(doc_text, step_task),
    )
    if result.startswith("OQ-"):
        return result
    print(f"[cfproxy][orchestrator] create_open_question failed: {result}", file=sys.stderr)
    return ""


# ---------------------------------------------------------------------------
# create_actionable_task -- ADR-011 Part 1 AT (Actionable Task) creation
# ---------------------------------------------------------------------------

_AT_VALID_STATES = ("Ready", "Blocked", "In Progress", "Done", "Decomposed")


# _next_at_id / _format_at_row / the _AT_* layout constants: see ledger_io.py
# for implementation and docs -- moved there (AT-1161) alongside the OQ-side
# functions. Aliased here under their original names so existing call sites
# and tests (test_local_mcp_oq_at_tools.py) are unaffected.
_next_at_id = ledger_io.next_at_id
_format_at_row = ledger_io.format_at_row
_AT_READY_POOL_HEADING_PREFIX = ledger_io._AT_READY_POOL_HEADING_PREFIX
_AT_INTAKE_HEADING = ledger_io._AT_INTAKE_HEADING
_AT_INTAKE_INTRO = ledger_io._AT_INTAKE_INTRO
_AT_TABLE_HEADER = ledger_io._AT_TABLE_HEADER
_AT_TABLE_SEP = ledger_io._AT_TABLE_SEP


def _append_at_row(row: str) -> bool:
    """Append a freshly-formatted AT row to the `### Newly Decomposed Tasks
    (Intake)` subsection at the top of `## Ready Pool ...`, creating that
    subsection (with its own table) if it doesn't exist yet. New rows go
    directly below the subsection's table header separator (newest first,
    matching _append_oq_row's convention for the OQ ledger). Returns False
    (and logs) if the insertion point can't be found -- the caller must not
    silently lose an AT it believes it created. The "where in the text does
    this go" logic lives in ledger_io.insert_at_row (unit tested); this
    function is just the file I/O + path resolution around it.

    AT-1162: the read-modify-write is wrapped in _ledger_lock so a second
    concurrent writer blocks and retries rather than racing.

    CB-26: also bumps the doc's high-water-mark marker to this row's id,
    mirroring _append_oq_row's existing CB-18 fix, so a future next_at_id()
    call still skips this id even after the row is later archived out of
    the live file (see ledger_io.next_at_id)."""
    path = _resolve(AT_QUEUE_PATH)
    try:
        with _ledger_lock(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    queue_text = f.read()
            except Exception as e:
                print(f"[cfproxy][taskqueue] failed to read AT queue to append a row: {e}", file=sys.stderr)
                return False
            row_id_match = re.match(r"^\|\s*AT-(\d+)\s*\|", row)
            if row_id_match:
                queue_text, bumped = ledger_io.bump_at_high_water_mark(queue_text, int(row_id_match.group(1)))
                if not bumped:
                    print(f"[cfproxy][taskqueue] AT high-water-mark marker not found or not raised for {row_id_match.group(0)} -- next_at_id() will rely on row-scan only", file=sys.stderr)
            new_text, inserted = ledger_io.insert_at_row(queue_text, row)
            if not inserted:
                print(f"[cfproxy][taskqueue] AT queue has no '{_AT_INTAKE_HEADING}' subsection with a table separator and no '{_AT_READY_POOL_HEADING_PREFIX}' heading -- refusing to guess where to insert", file=sys.stderr)
                return False
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_text)
            except Exception as e:
                print(f"[cfproxy][taskqueue] failed to write AT queue after appending a row: {e}", file=sys.stderr)
                return False
    except RuntimeError as e:
        print(f"[cfproxy][taskqueue] _append_at_row lock error: {e}", file=sys.stderr)
        return False
    return True


@mcp.tool()
def create_actionable_task(
    description: str,
    spec_issue: str,
    dependencies: str,
    exit_evidence: str,
    effort: str,
    state: str = "Ready",
) -> str:
    """Append a new row to the AT queue's "Newly Decomposed Tasks (Intake)"
    subsection (ADR-011 Part 1 schema: task-and-oq-authoring-standard.md).

    `description` is one imperative sentence naming a single deliverable.
    `dependencies` is a comma-separated list of AT IDs that must be Done
    first, or the literal string "None". `state` defaults to "Ready" and
    must be one of Ready/Blocked/In Progress/Done/Decomposed; non-"Ready"
    states are rendered as a "**<state>** -- " prefix on the Task cell.

    Returns "AT-<N>" on success (the freshly-minted id, one greater than the
    current max AT-<N> anywhere in the queue, ignoring .N subtask suffixes).
    On a missing/invalid required field, REJECTS -- returns an "ERROR: ..."
    string naming the field(s) and writes nothing. On an I/O failure
    reading/writing the queue, returns an "ERROR: ..." string and writes
    nothing."""
    errors: list[str] = []
    if not description or not description.strip():
        errors.append("description")
    if not spec_issue or not spec_issue.strip():
        errors.append("spec_issue")
    if not dependencies or not dependencies.strip():
        errors.append("dependencies")
    if not exit_evidence or not exit_evidence.strip():
        errors.append("exit_evidence")
    if not effort or not effort.strip():
        errors.append("effort")
    if state not in _AT_VALID_STATES:
        errors.append(f"state (must be one of {_AT_VALID_STATES})")
    if errors:
        return f"ERROR: create_actionable_task rejected -- missing/invalid field(s): {', '.join(errors)}. No row written."

    if _odysseus_notes_mode_active():
        task_cell = f"**{description}**"
        if state != "Ready":
            task_cell = f"**{state}** -- {task_cell}"
        title = description.strip().splitlines()[0][:200]
        content = "\n".join([
            task_cell,
            "",
            f"**Spec / Issue:** {spec_issue}",
            f"**Exit Evidence:** {exit_evidence}",
            f"**Effort:** {effort}",
            f"**Depends On:** {dependencies}",
            f"**State:** {state}",
        ])
        items = [{"text": exit_evidence, "done": state == "Done"}]
        return _odysseus_create_note("AT", title, content, items)

    path = _resolve(AT_QUEUE_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            queue_text = f.read()
    except Exception as e:
        print(f"[cfproxy][taskqueue] failed to read AT queue to compute next id: {e}", file=sys.stderr)
        return f"ERROR: could not read AT queue at {path}: {e}"
    at_id = _next_at_id(queue_text)
    row = _format_at_row(at_id, description, spec_issue, dependencies, exit_evidence, effort, state)
    if not _append_at_row(row):
        return "ERROR: failed to append AT row -- see server log for details"
    print(f"[cfproxy][taskqueue] AT-{at_id} appended to markdown queue {path} (Odysseus Notes mode inactive)", file=sys.stderr)
    return f"AT-{at_id}"


# AT-1228/1227/1230: coding-task dispatch. Job state lives in its own
# directory (OQ-287), separate from ORCHESTRATOR_OQ_LEDGER_PATH's
# ~/.cf_proxy_orchestrator/ -- these are a different kind of job (a whole
# Cline run against an AT, not a single orchestrated step).
CODING_TASK_STATE_DIR = os.environ.get(
    "CODING_TASK_STATE_DIR", os.path.join(os.path.expanduser("~"), ".coding_task_dispatch")
)
RUN_CLINE_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-cline.ps1")
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 1200


@mcp.tool()
async def dispatch_coding_task(at_id: int, repo_root: str) -> str:
    """Dispatches a Cline CLI coding-agent run against AT-<at_id>, isolated
    in its own git worktree on a dedicated branch (at-<at_id>-dispatch), and
    returns immediately with a job_id once the run is launched in the
    background. Poll get_coding_task_status(job_id) for progress;
    promote_coding_task(job_id) merges the result once it's done.

    Resolved design (odysseus-agentic-dispatch-architecture.md S3.1):
    - repo_root must exist and be a git repository.
    - AT-<at_id> must exist in ai-task-queue.md and carry a "Model: Tier-X"
      annotation -- no guessed default if it's missing.
    - repo_root must have a clean working tree; if dirty, raises an OQ via
      create_open_question (the existing escalation path) rather than
      silently proceeding or silently refusing.
    - repo_root must not already have a running job (OQ-285: one job at a
      time per repo).
    - At least one of the tier's candidate models must respond to a live
      LiteLLM probe; if every candidate fails, returns an ERROR naming all
      of them.
    - Uses git worktree (not checkout -b) so the job's branch switch never
      disturbs whatever the shared working directory currently has checked
      out."""
    if not os.path.isdir(repo_root):
        return f"ERROR: repo_root does not exist: {repo_root}"
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        return f"ERROR: repo_root is not a git repository (no .git): {repo_root}"

    queue_path = _resolve(AT_QUEUE_PATH)
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            queue_text = f.read()
    except Exception as e:
        return f"ERROR: could not read AT queue at {queue_path}: {e}"

    at_row = ledger_io.parse_at_row(queue_text, at_id)
    if at_row is None:
        return f"ERROR: AT-{at_id} not found in {queue_path}"
    if at_row["model_tier"] is None:
        return (
            f"ERROR: AT-{at_id} has no 'Model: Tier-X' annotation -- cannot resolve a model "
            f"without one (no guessed default; see ai-model-selection-policy.md S11.2)"
        )

    busy_job_id = dispatch_io.find_busy_job_for_repo(CODING_TASK_STATE_DIR, repo_root, at_id=at_id)
    if busy_job_id is not None:
        return (
            f"ERROR: AT-{at_id} already has a running job ({busy_job_id}) in {repo_root} -- "
            f"one job at a time per (repo, AT-id) pair (relaxed from OQ-285's original "
            f"whole-repo serialization, 2026-06-20 -- see agent-harness-reliability-standard.md). "
            f"Check get_coding_task_status('{busy_job_id}') or wait for it to finish. Different "
            f"AT-ids may run concurrently against the same repo."
        )

    clean, dirty_detail = dispatch_io.is_working_tree_clean(repo_root)
    if not clean:
        oq_id = create_open_question(
            question=(
                f"dispatch_coding_task(AT-{at_id}, {repo_root}) found the target repo has "
                f"uncommitted changes. The job runs in an isolated git worktree, so it will not "
                f"touch these files either way -- but proceeding leaves them uncommitted "
                f"alongside whatever the job produces, while waiting defers dispatch until "
                f"they're committed/stashed. Options: (A) proceed anyway -- the dirty files are "
                f"unrelated to this job's isolated worktree; (B) hold dispatch until the working "
                f"tree is clean. Dirty files:\n{dirty_detail[:1000]}"
            ),
            options=[
                "A: Proceed anyway -- isolated worktree, dirty files are unrelated",
                "B: Hold dispatch until the working tree is clean",
            ],
            preemptive_answer="B: Hold dispatch until the working tree is clean",
            preemptive_reasoning=(
                "An ambiguous base state risks a misleading mental model of what's actually "
                "committed even though the job's own changes are isolated; resolved as a "
                "working-tree precondition in odysseus-agentic-dispatch-architecture.md S3.1."
            ),
            reversibility="Reversible",
            context_spec="odysseus-agentic-dispatch-architecture.md S3.1 (working-tree precondition)",
            unblocks=f"AT-{at_id} dispatch",
            precedent_search_note="OQ-285/286/287/288/289 (this dispatch tool's own prior planning)",
        )
        return f"ERROR: {repo_root} has uncommitted changes -- raised {oq_id} rather than guessing. Dirty files: {dirty_detail[:500]}"

    master_key = dispatch_io.load_litellm_master_key(os.path.dirname(os.path.abspath(__file__)))
    model, attempted = await dispatch_io.resolve_model_for_tier(at_row["model_tier"], master_key)
    if model is None:
        return f"ERROR: no model responded for {at_row['model_tier']} -- attempted {attempted}. Check toolchain-doctor.ps1."

    job_id = dispatch_io.new_job_id(at_id)
    branch_name = dispatch_io.dispatch_branch_name(at_id)
    abs_repo_root = os.path.abspath(repo_root)
    worktree_path = os.path.join(
        os.path.dirname(abs_repo_root), f"{os.path.basename(abs_repo_root)}-at-{at_id}-dispatch"
    )
    if os.path.exists(worktree_path):
        return (
            f"ERROR: worktree path already exists: {worktree_path} -- a prior dispatch for "
            f"AT-{at_id} may not have been cleaned up (promote_coding_task removes it on success)"
        )

    base_branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=15,
    )
    base_branch = base_branch_result.stdout.strip() or "HEAD"

    ok, err = dispatch_io.create_worktree(repo_root, worktree_path, branch_name)
    if not ok:
        return f"ERROR: git worktree add failed: {err}"

    task_prompt = dispatch_io.build_task_prompt(at_id, at_row, worktree_path)
    os.makedirs(CODING_TASK_STATE_DIR, exist_ok=True)
    log_path = os.path.join(CODING_TASK_STATE_DIR, f"{job_id}.log")

    log_file = open(log_path, "w", encoding="utf-8")
    try:
        proc = dispatch_io.spawn_cline_process(
            RUN_CLINE_SCRIPT_PATH, worktree_path, model, task_prompt,
            DEFAULT_DISPATCH_TIMEOUT_SECONDS, log_file,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except Exception as e:
        dispatch_io.remove_worktree(repo_root, worktree_path, force=True)
        return f"ERROR: failed to spawn run-cline.ps1: {e}"
    finally:
        # The child inherits its own duplicated handle to log_path via
        # stdout=log_file -- this parent-side handle is safe to close
        # immediately rather than leaking it for the rest of this long-
        # running MCP server process's lifetime.
        log_file.close()

    dispatch_io.write_job_state(CODING_TASK_STATE_DIR, job_id, {
        "job_id": job_id,
        "at_id": at_id,
        "repo_root": abs_repo_root,
        "worktree_path": worktree_path,
        "branch_name": branch_name,
        "base_branch": base_branch,
        "model": model,
        "model_attempts": attempted,
        "pid": proc.pid,
        "status": "running",
        "log_path": log_path,
        "started_at": time.time(),
        "updated_at": time.time(),
    })
    print(
        f"[cfproxy][dispatch] {job_id}: AT-{at_id} dispatched to {model} in worktree "
        f"{worktree_path} (pid {proc.pid})",
        file=sys.stderr,
    )
    return job_id


@mcp.tool()
def get_coding_task_status(job_id: str) -> str:
    """Reports the current status of a job started by dispatch_coding_task.
    If the recorded PID is no longer alive, this call also updates the job
    state from "running" to "complete" or "failed" (failed if the worktree
    branch has no commits beyond the base, complete otherwise) -- status
    transitions happen lazily, on the next poll, rather than via a separate
    watcher process (AT-1227's resolved scope; a watcher is OQ-289's
    separate, not-yet-built supervisor layer)."""
    state = dispatch_io.read_job_state(CODING_TASK_STATE_DIR, job_id)
    if state is None:
        return f"ERROR: no job found with id {job_id}"

    if state.get("status") == "running" and not dispatch_io.is_pid_alive(state.get("pid")):
        worktree_path = state.get("worktree_path", "")
        base_branch = state.get("base_branch", "")
        commit_count = "unknown"
        has_new_commits = False
        try:
            # Compare against base_branch, not "does the branch have any
            # commits" -- every branch has at least the seed/base commit,
            # so that check is always true and would never report "failed".
            result = subprocess.run(
                ["git", "log", "--oneline", f"{base_branch}..HEAD", "-5"],
                cwd=worktree_path, capture_output=True, text=True, timeout=15,
            )
            commit_count = result.stdout.strip()
            has_new_commits = bool(result.stdout.strip())
        except Exception as e:
            commit_count = f"(could not check: {e})"
        state["status"] = "complete" if has_new_commits else "failed"
        state["recent_commits"] = commit_count
        state["updated_at"] = time.time()
        dispatch_io.write_job_state(CODING_TASK_STATE_DIR, job_id, state)

    log_tail = ""
    log_path = state.get("log_path")
    if log_path and os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            log_tail = "".join(lines[-30:])
        except Exception:
            log_tail = "(could not read log)"

    return (
        f"job_id: {job_id}\n"
        f"AT-{state.get('at_id')}\n"
        f"status: {state.get('status')}\n"
        f"model: {state.get('model')}\n"
        f"repo_root: {state.get('repo_root')}\n"
        f"worktree_path: {state.get('worktree_path')}\n"
        f"branch_name: {state.get('branch_name')}\n"
        f"recent_commits: {state.get('recent_commits', '(job still running)')}\n"
        f"--- log tail ---\n{log_tail}"
    )


@mcp.tool()
def promote_coding_task(job_id: str) -> str:
    """Promotes a completed coding-task job by merging its dispatch branch
    into the target repo's default branch, then cleaning up the worktree.
    This is the explicit human-approval step OQ-286 requires: the architect
    reviews via get_coding_task_status(job_id)'s diff summary (or a richer
    Monaco diff view, AT-1221) before calling this.

    Validator-at-the-boundary: rejects with a clear error if the job is
    still running, failed, or was already promoted -- only a job whose
    status is exactly 'complete' can be promoted.

    On success:
      - Fast-forward merges the job's dispatch branch into the repo's
        default branch (the branch the main worktree had checked out when
        dispatch_coding_task ran, recorded in the job state as base_branch).
      - Removes the git worktree (dispatch_coding_task created it; this
        tool removes it per odysseus-agentic-dispatch-architecture.md S3.1).
      - Deletes the local dispatch branch (it is merged; no orphaned refs).
      - Updates the job state to status='promoted'.

    Spec: odysseus-agentic-dispatch-architecture.md S3.2a (AT-1229/AT-1230,
    OQ-286 Option B)."""
    state = dispatch_io.read_job_state(CODING_TASK_STATE_DIR, job_id)
    if state is None:
        return f"ERROR: no job found with id {job_id!r}"

    status = state.get("status", "")
    at_id = state.get("at_id", "?")

    # Validator-at-the-boundary: only 'complete' jobs can be promoted.
    if status == "running":
        return (
            f"ERROR: job {job_id!r} (AT-{at_id}) is still running -- wait for it "
            f"to finish before promoting. Use get_coding_task_status('{job_id}') "
            f"to check progress."
        )
    if status == "failed":
        return (
            f"ERROR: job {job_id!r} (AT-{at_id}) has status 'failed' -- the agent "
            f"did not produce any commits on the dispatch branch. Promotion is not "
            f"possible. Review the log via get_coding_task_status('{job_id}') and "
            f"re-dispatch if needed."
        )
    if status == "promoted":
        promoted_at = state.get("promoted_at", "(unknown time)")
        merged_sha = state.get("merged_sha", "(unknown)")
        return (
            f"ERROR: job {job_id!r} (AT-{at_id}) was already promoted "
            f"(promoted_at={promoted_at}, merged_sha={merged_sha}). "
            f"Nothing to do."
        )
    if status != "complete":
        return (
            f"ERROR: job {job_id!r} (AT-{at_id}) has unexpected status {status!r}. "
            f"Only jobs with status='complete' can be promoted."
        )

    repo_root = state.get("repo_root", "")
    worktree_path = state.get("worktree_path", "")
    branch_name = state.get("branch_name", "")
    base_branch = state.get("base_branch", "")

    if not repo_root or not os.path.isdir(repo_root):
        return (
            f"ERROR: job {job_id!r} (AT-{at_id}) has a missing or inaccessible "
            f"repo_root: {repo_root!r}. Cannot merge."
        )
    if not branch_name:
        return f"ERROR: job {job_id!r} (AT-{at_id}) has no branch_name recorded. Cannot merge."

    # Resolve target branch: prefer the recorded base_branch (set at dispatch
    # time -- the most reliable record of what the repo's HEAD was at that
    # moment); fall back to querying the current HEAD if not recorded.
    if base_branch:
        default_branch = base_branch
    else:
        default_branch, err = dispatch_io.get_default_branch(repo_root)
        if not default_branch:
            return (
                f"ERROR: could not determine the default branch of {repo_root!r}: {err}. "
                f"Set base_branch in the job state manually or re-dispatch."
            )

    # Merge the dispatch branch into the default branch.
    ok, merge_out = dispatch_io.merge_branch_into_default(
        repo_root, branch_name, default_branch
    )
    if not ok:
        return (
            f"ERROR: merge of {branch_name!r} into {default_branch!r} failed for job "
            f"{job_id!r} (AT-{at_id}): {merge_out}. The dispatch branch and worktree "
            f"are untouched -- review, resolve, and retry."
        )

    # Read the resulting HEAD SHA so we can record it in the state.
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root, capture_output=True, text=True, timeout=15,
    )
    merged_sha = sha_result.stdout.strip() or "(unknown)"

    # Remove the worktree (per spec S3.1: promote_coding_task removes it).
    # Not a hard failure if it's already gone -- the merge succeeded, which
    # is the critical step; a leftover worktree path is cosmetic.
    wt_removed = False
    wt_remove_note = ""
    if worktree_path and os.path.isdir(worktree_path):
        wt_ok, wt_err = dispatch_io.remove_worktree(repo_root, worktree_path, force=True)
        if wt_ok:
            wt_removed = True
        else:
            wt_remove_note = (
                f" (WARNING: git worktree remove failed: {wt_err}"
                f" -- remove {worktree_path!r} manually)"
            )
            print(
                f"[cfproxy][promote] {job_id}: worktree remove failed"
                f" for {worktree_path!r}: {wt_err}",
                file=sys.stderr,
            )
    else:
        wt_removed = True  # already gone or never created (edge case)

    # Delete the local branch (already merged; -d is safe).
    branch_note = ""
    br_ok, br_err = dispatch_io.delete_local_branch(repo_root, branch_name)
    if not br_ok:
        branch_note = (
            f" (WARNING: git branch -d {branch_name!r} failed: {br_err}"
            f" -- delete manually)"
        )
        print(
            f"[cfproxy][promote] {job_id}: branch delete failed"
            f" for {branch_name!r}: {br_err}",
            file=sys.stderr,
        )

    # Update job state to promoted.
    state["status"] = "promoted"
    state["promoted_at"] = time.time()
    state["merged_sha"] = merged_sha
    state["merged_into"] = default_branch
    state["worktree_removed"] = wt_removed
    state["updated_at"] = time.time()
    dispatch_io.write_job_state(CODING_TASK_STATE_DIR, job_id, state)

    print(
        f"[cfproxy][promote] {job_id}: AT-{at_id} merged {branch_name!r}"
        f" -> {default_branch!r} at {merged_sha[:12]}",
        file=sys.stderr,
    )
    return (
        f"promoted: job {job_id} (AT-{at_id})\n"
        f"merged: {branch_name} -> {default_branch}\n"
        f"sha: {merged_sha}\n"
        f"worktree removed: {wt_removed}\n"
        f"git output: {merge_out}"
        f"{wt_remove_note}{branch_note}"
    )



_ORCHESTRATOR_STEP_SYSTEM_PROMPT = (
    "You are executing exactly ONE step of a pre-approved, decomposed plan -- "
    "and only this step. Do not start later steps even if you can infer what "
    "they are. Use your tools to make the change and verify it (read the "
    "relevant files; run the relevant tests/build for THIS step's change). "
    "If this step asks you to record, transcribe, or apply a fact, decision, "
    "value, status, or quote that is defined in another document (a decision "
    "log, an OQ ledger, a spec, a prior step's output, etc.), you MUST open "
    "that document with a tool call FIRST and copy the exact text -- do not "
    "state it from memory or by reasoning about what it 'should' say. Your own "
    "inference about what a decision ought to be is not a substitute for the "
    "literal source text; if they differ, the literal text wins, verbatim. "
    "If your final summary reproduces literal text copied from a source "
    "document, set that reproduced text apart as a markdown blockquote "
    "(prefix every line of it with '> ') or a fenced code block, so it is "
    "structurally distinguishable from your own description of what you did "
    "-- this is required even if the quoted text itself uses words like "
    "'error' or 'failure' to describe something else. "
    "When you are done, give a concrete final summary: which files you changed, "
    "what commands you ran, and what their output showed. If this step's "
    "assumptions don't match what you find in the codebase, or it can't be done "
    "as written, say so plainly and STOP -- do not improvise a different change. "
    "Finally, end your summary with one line in the exact form `FINDING: <text>` "
    "stating the single most important fact, value, decision, or quote this step "
    "produced -- this line is carried forward verbatim into later steps' prompts "
    "(OQ-263), so make it self-contained and specific (name the source document "
    "if it's a quote). If this step produced no standalone fact worth carrying "
    "forward (e.g. a pure file edit with nothing later steps need to know), omit "
    "the FINDING line entirely."
)


_ORCHESTRATOR_FINDING_RE = re.compile(r"^\s*FINDING:\s*(.+)$", re.MULTILINE)
ORCHESTRATOR_FINDING_MAX_CHARS = 1000     # OQ-263: per-finding cap before storage
ORCHESTRATOR_FINDINGS_CHAR_BUDGET = 4000  # OQ-263: total budget for the "Prior step findings" block


def _extract_step_finding(summary_text: str) -> str:
    """OQ-263: pull this step's carry-forward finding out of its final summary.
    Prefers an explicit `FINDING: <text>` line (per
    _ORCHESTRATOR_STEP_SYSTEM_PROMPT); if the executor omitted it, falls back
    to the whole (CB-8-fixed) validator-pass summary text, capped at
    ORCHESTRATOR_FINDING_MAX_CHARS."""
    match = _ORCHESTRATOR_FINDING_RE.search(summary_text or "")
    text = match.group(1).strip() if match else (summary_text or "").strip()
    return text[:ORCHESTRATOR_FINDING_MAX_CHARS]


def _record_resolved_step_finding(state: dict, step_idx: int) -> None:
    """CB-12 (2026-06-12): when an AMBIGUOUS-paused step is resolved via
    architect Option A ("treat as complete, continue"), record its finding the
    same way `_finish_step`'s YES path does -- otherwise the step's fact
    silently drops out of the OQ-263/CB-10(b) findings-carry-forward block for
    every later step (confirmed 2026-06-12, run `a731f317e9507669`: step 4/8's
    through-proxy-result fact never reached step 6/8's file-creation prompt).
    Extracts from `state["ambiguity_last_summary"]` (the step's own executor
    summary, recorded by `_finish_step` when it raised the ambiguity OQ); if
    that yields no text (e.g. an empty summary), synthesizes a placeholder
    finding from the step's task text and OQ id so later steps at least know
    this step was resolved manually rather than silently disappearing."""
    total = len(state["steps"])
    step_task = state["steps"][step_idx - 1]
    finding_text = _extract_step_finding(state.get("ambiguity_last_summary") or "")
    if not finding_text:
        oq_id = state.get("ambiguity_oq_id") or "an architect OQ"
        finding_text = (f"Step {step_idx}/{total} ({step_task}) was resolved via architect Option A "
                        f"(see {oq_id}); its executor summary produced no extractable finding text.")
    state.setdefault("findings", []).append({"step": step_idx, "total": total, "text": finding_text})
    _orchestrator_log(state, f"step {step_idx}/{total} finding recorded on Option-A resolution: {finding_text[:200]!r}")


def _format_findings_block(findings: list) -> str:
    """OQ-263: render accumulated step findings as a 'Prior step findings'
    block for later steps' prompts. Walks newest-first, keeping findings while
    the running total stays within ORCHESTRATOR_FINDINGS_CHAR_BUDGET -- i.e.
    the OLDEST findings are rotated out first when the budget is exceeded --
    then re-orders the kept findings oldest-first for presentation. The
    newest finding is always kept even if it alone exceeds the budget."""
    if not findings:
        return ""
    kept = []
    total_chars = 0
    for f in reversed(findings):
        line = f"- Step {f['step']}/{f['total']}: {f['text']}"
        if kept and total_chars + len(line) > ORCHESTRATOR_FINDINGS_CHAR_BUDGET:
            break
        kept.append(line)
        total_chars += len(line)
    kept.reverse()
    return "Prior step findings:\n" + "\n".join(kept) + "\n\n"


def _build_step_dispatch_body(original_body: dict, tail_messages: list, step_task: str, step_index: int, total: int,
                               findings: list = None, model: str = None) -> dict:
    """Replace the accumulated conversation with a fresh, narrow frame: the
    step's own prompt plus only the tool-call/result turns generated since THIS
    step began (`tail_messages`). Everything from the original multi-step ask,
    the breakdown proposal, and any prior steps is deliberately left out --
    except `findings` (OQ-263/CB-10(b)), the mechanical per-step findings
    carry-forward, which is prepended to the step prompt as a "Prior step
    findings" block so later steps don't need to re-read source documents to
    recover earlier steps' results."""
    system_prompt = _ORCHESTRATOR_STEP_SYSTEM_PROMPT
    if model:
        system_prompt = (
            system_prompt
            + f" When making git commits in this step, include the trailer "
            f"`Co-Authored-By: {model} <noreply@cf-proxy.local>` in the commit message body "
            f"(on its own line, after a blank line following the summary)."
        )
    narrowed = dict(original_body)
    narrowed["messages"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{_format_findings_block(findings or [])}Step {step_index} of {total} -- do ONLY this step: {step_task}"},
    ] + tail_messages
    narrowed["stream"] = False
    return narrowed


async def _cf_complete_once(cf_url: str, auth_header: str, body: dict):
    """POST a narrowed body to CF non-streaming and return a normalized
    (content, tool_calls, finish_reason) triple, recording spend through the
    same path as ordinary traffic. Returns None on transport/parse failure --
    the caller halts the run rather than guessing at what would have happened."""
    forward = dict(body)
    forward["stream"] = False
    # CF Workers AI rejects "stream_options" (e.g. {"include_usage": true}) with
    # a generic "AiError: Invalid input" (HTTP 400, code 8001) when stream is
    # false -- per the OpenAI-compatible spec stream_options is only meaningful
    # alongside stream=true. original_body carries it through from Cline's
    # streaming request; strip it for this forced-non-streaming call (verified
    # empirically 2026-06-11: removing it turns the same 400 into a 200).
    forward.pop("stream_options", None)
    try:
        async with httpx.AsyncClient(timeout=ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS) as client:
            resp = await client.post(cf_url, json=forward, headers={"Authorization": auth_header, "Content-Type": "application/json"})
        data = resp.json()
        if "choices" not in data:
            dump_path = os.path.join(WORKSPACE, "cf_proxy_failed_dispatch_body.json")
            with open(dump_path, "w", encoding="utf-8") as f:
                json.dump(forward, f, indent=2)
            print(f"[cfproxy][orchestrator] step-dispatch call failed: CF returned status {resp.status_code} "
                  f"with no 'choices' key -- body: {json.dumps(data)[:500]} -- request body dumped to {dump_path}", file=sys.stderr)
            return None
        choice = data["choices"][0]
        msg = choice.get("message", {})
    except httpx.TimeoutException:
        prompt_chars = sum(len(m.get("content") or "") for m in forward.get("messages", []))
        print(f"[cfproxy][orchestrator] step-dispatch call timed out after "
              f"{ORCHESTRATOR_DISPATCH_TIMEOUT_SECONDS:.0f}s (prompt: {len(forward.get('messages', []))} "
              f"msgs / {prompt_chars} chars, model={forward.get('model')!r})", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"[cfproxy][orchestrator] step-dispatch call failed: {exc!r}", file=sys.stderr)
        return None
    usage = data.get("usage")
    if isinstance(usage, dict):
        await _record_cf_spend(forward.get("model", ""), usage)
    content, tool_calls = msg.get("content"), msg.get("tool_calls")
    if not tool_calls and content:
        tc = _parse_any_tool_call(content)
        if tc:
            tool_calls, content = [tc], None
    return content, tool_calls, choice.get("finish_reason", "stop")


def _format_resume_prompt(key: str, state: dict) -> str:
    """Build the first (and only) user message for a FRESH cline session that
    resumes a paused_for_oq run (CB-9/OQ-262 Option C). The embedded
    `[orchestrator-key: ...]` marker lets `_orchestrator_key` re-derive this
    run's identity without a Cline session ID, and `_handle_orchestrated_request`
    recognizes a fresh single-message session carrying this marker against a
    paused_for_oq run as the architect's resolved "continue" -- see the resume
    branch there. `resume-orchestrator-run.ps1` prints this via
    `--print-resume-prompt` and feeds it to `run-cline.ps1`."""
    total = len(state["steps"])
    resolved_idx = state["current"]
    next_idx = resolved_idx + 1
    if next_idx > total:
        next_clause = "the run has no further steps -- mark it complete."
    else:
        next_clause = f"proceed with step {next_idx}/{total}: {state['steps'][next_idx - 1]}"
    return (
        f"[orchestrator-key: {key}] continue -- resuming the paused {total}-step run. "
        f"Step {resolved_idx}/{total} is resolved (treat as complete). {next_clause}"
    )


def _format_run_complete(key: str, total: int) -> str:
    return (
        f"[cfproxy][orchestrator] Run complete -- all {total} step(s) validated and applied automatically. "
        f"Full transition log and per-step diffs: `{_orchestrator_state_path(key)}`. "
        f"Nothing here was committed on your behalf -- review `git status` / `git diff` and commit when "
        f"you're satisfied (see CLAUDE.md Commit Hygiene for the one-commit-per-task convention)."
    )


def _format_step_failure_report(step_idx: int, total: int, step_task: str, changed_files: list,
                                summary: str, reason: str) -> str:
    files_block = "\n".join(f"- `{f}`" for f in changed_files) if changed_files else "_(no working-tree changes detected)_"
    return (
        f"[cfproxy][orchestrator] Step {step_idx}/{total} FAILED validation -- *{step_task}*\n\n"
        f"**Automated verdict: NO** -- {reason}\n\n"
        f"**What the executor said:**\n{(summary or '').strip()[:1200]}\n\n"
        f"**Files touched before the failure (`git status` diff vs. the pre-step snapshot):**\n{files_block}\n\n"
        f"---\nThe run is halted here -- a demonstrated failure does not get auto-retried (an automatic "
        f"retry loop is exactly the kind of compounding-cost failure mode the validator and step cap exist "
        f"to prevent; see the Stage 2+3 module docs for the $47K postmortem this is informed by). Review "
        f"the diff, revert anything you don't want (`git checkout` / `git clean` on the touched paths -- "
        f"nothing here was committed on your behalf), and re-confirm a corrected breakdown when ready."
    )


def _format_step_ambiguity_pause(step_idx: int, total: int, step_task: str, changed_files: list,
                                 summary: str, reason: str, oq_id: str) -> str:
    files_block = "\n".join(f"- `{f}`" for f in changed_files) if changed_files else "_(no working-tree changes detected)_"
    oq_line = (
        f"I've raised **{oq_id}** in `{ORCHESTRATOR_OQ_LEDGER_PATH}` with the full "
        f"context and three options (treat as complete and continue / treat as incomplete and halt / "
        f"re-slice the step)."
        if oq_id else
        f"I tried to raise an OQ for this but the append failed (see the proxy's stderr log for why) -- "
        f"you'll have to make this call without that paper trail; consider raising one by hand."
    )
    next_step_clause = (
        f"continue on to step {step_idx + 1}/{total}" if step_idx < total else "mark the run complete"
    )
    return (
        f"[cfproxy][orchestrator] Step {step_idx}/{total} came back AMBIGUOUS -- *{step_task}*\n\n"
        f"**Automated verdict: AMBIGUOUS** -- {reason}\n\n"
        f"**What the executor said:**\n{(summary or '').strip()[:1200]}\n\n"
        f"**Files touched so far (`git status` diff vs. the pre-step snapshot):**\n{files_block}\n\n"
        f"---\n{oq_line}\n\n"
        f"The run is paused here -- per the bounded loop-detector it will not advance, retry, or raise a "
        f"second OQ for this step no matter how you reply. Reply **continue** to treat this step as "
        f"complete and {next_step_clause}, or **stop** to halt here for manual review and revert."
    )


async def _finish_step(key: str, state: dict, step_idx: int, summary_text: str, cf_url: str, auth_header: str,
                       original_body: dict, is_stream: bool, model_name: str):
    """A step's executor turn produced a final answer (no further tool calls).
    Snapshot, diff against the pre-step snapshot, and run the artifact-based
    validator over that evidence -- Stage 2+3's replacement for Stage 1's
    "does this diff look right to you?" manual gate (see `_run_validator_pass`
    and the Stage 2+3 module docstring for the YES/NO/AMBIGUOUS branches and
    why each is handled the way it is)."""
    total = len(state["steps"])
    step_task = state["steps"][step_idx - 1]
    before = state.get("snapshot_before_step") or {"dirty": [], "head": None}
    after = await _git_snapshot(WORKSPACE)
    changed = _diff_snapshots(before, after)
    head_changed = bool(after.get("head")) and after.get("head") != before.get("head")
    verdict, reason = _run_validator_pass(step_task, summary_text, changed, head_changed)
    await _record_metric(f"orchestrator_verdict_{verdict}")
    _orchestrator_log(state, f"step {step_idx}/{total} validator verdict: {verdict.upper()} -- {reason} ({len(changed)} file(s) changed, head_changed={head_changed})")

    if verdict == "yes":
        finding_text = _extract_step_finding(summary_text)
        state.setdefault("findings", []).append({"step": step_idx, "total": total, "text": finding_text})
        _orchestrator_log(state, f"step {step_idx}/{total} finding recorded: {finding_text[:200]!r}")
        next_idx = step_idx + 1
        if next_idx > total:
            state["status"] = "complete"
            await _record_metric("orchestrator_run_completed")
            _orchestrator_log(state, f"step {step_idx}/{total} validated YES -- run complete ({total}/{total})")
            _save_orchestrator_state(key, state)
            return _synthetic_assistant_response(
                model_name, "", is_stream, tool_calls=_terminal_completion_tool_call(_format_run_complete(key, total)))
        # Auto-advance: the next step's tail begins empty, right after whatever
        # is currently the last message in this request's history -- so THAT
        # index is the new anchor (mirrors how the confirm-branch anchors on
        # the architect's reply, which is likewise the last message at the
        # moment of a fresh dispatch). This is what makes chaining multiple
        # upstream CF calls inside one incoming request possible without a
        # session id: the anchor travels with the conversation, not with a
        # human reply that (in the auto-advance path) never arrives.
        state.update(current=next_idx, anchor_index=len(original_body["messages"]) - 1,
                     snapshot_before_step=await _git_snapshot(WORKSPACE))
        _orchestrator_log(state, f"step {step_idx}/{total} validated YES -- auto-advancing to step {next_idx}/{total}: {state['steps'][next_idx - 1]!r}")
        _save_orchestrator_state(key, state)
        return await _dispatch_step(key, state, next_idx, cf_url, auth_header, original_body, [], is_stream, model_name)

    if verdict == "no":
        state["status"] = "halted"
        await _record_metric("orchestrator_run_halted")
        _save_orchestrator_state(key, state)
        return _synthetic_assistant_response(
            model_name, "", is_stream,
            tool_calls=_terminal_completion_tool_call(
                _format_step_failure_report(step_idx, total, step_task, changed, summary_text, reason)))

    # verdict == "ambiguous" -- Stage 3's bounded, one-shot OQ escalation.
    if state.get("ambiguity_raised_for_step") == step_idx:
        state["status"] = "halted"
        await _record_metric("orchestrator_run_halted")
        _orchestrator_log(state, f"step {step_idx}/{total} is AMBIGUOUS again after an OQ was already raised for it -- hard stop, no second OQ (loop-detector)")
        _save_orchestrator_state(key, state)
        return _synthetic_assistant_response(
            model_name, "", is_stream,
            tool_calls=_terminal_completion_tool_call(
                f"[cfproxy][orchestrator] Step {step_idx}/{total} came back AMBIGUOUS a second time -- an OQ "
                f"was already raised for it (`ambiguity_raised_for_step={step_idx}` in the run's state file). "
                f"Per the bounded loop-detector this is a hard stop, not a second OQ: unbounded clarification "
                f"ping-pong is the exact $47K-postmortem failure mode that cap exists to prevent. The run is "
                f"halted -- resolve the existing OQ and re-confirm a corrected breakdown manually when ready."))

    oq_id = _raise_step_ambiguity_oq(key, state, step_idx, step_task, reason, summary_text)
    if oq_id:
        await _record_metric("orchestrator_oq_raised")
    state["ambiguity_raised_for_step"] = step_idx
    state["ambiguity_last_summary"] = summary_text  # CB-12: needed if Option A later resolves this step
    state["ambiguity_oq_id"] = oq_id
    state["status"] = "paused_for_oq"
    await _record_metric("orchestrator_run_paused_for_oq")
    _orchestrator_log(state, f"step {step_idx}/{total} is AMBIGUOUS -- raised {oq_id or '(OQ append failed)'} and paused pending the architect's call")
    _save_orchestrator_state(key, state)
    return _synthetic_assistant_response(
        model_name, "", is_stream,
        tool_calls=_terminal_followup_question_tool_call(
            _format_step_ambiguity_pause(step_idx, total, step_task, changed, summary_text, reason, oq_id)))


# CB-14 (2026-06-12): tool names whose Cline-side handler ENDS the CLI
# session (attempt_completion) or pauses it waiting for a human (
# ask_followup_question, plan_mode_respond) instead of producing a tool
# result that continues the conversation. Relaying a step response made up
# ENTIRELY of these tool_calls via the normal "relay to Cline" path leaves
# Cline with a terminal/paused action and no further turn to send -- the
# orchestrator never sees a follow-up request, so `_finish_step` (validator
# pass, finding recording, auto-advance) never runs and the run is stranded
# at status="running" forever with no halt, no OQ, and no error (AT-1140
# test #16). The value is the request-body argument key holding the text
# Cline would have shown the user for that tool.
_CLINE_TERMINAL_TOOL_ARG_KEYS = {
    "attempt_completion": "result",
    "ask_followup_question": "question",
    "plan_mode_respond": "response",
}


def _cline_terminal_tool_summary(tool_calls: list, content) -> "str | None":
    """CB-14: if `tool_calls` consists ENTIRELY of Cline-terminal tool calls
    (see `_CLINE_TERMINAL_TOOL_ARG_KEYS`), return a step-summary string built
    from `content` plus each call's text argument, so the caller can route it
    through `_finish_step` directly instead of relaying to Cline.

    Returns None if `tool_calls` is empty or contains ANY tool call that is
    not in `_CLINE_TERMINAL_TOOL_ARG_KEYS` -- a real action tool takes
    precedence over any terminal tool present alongside it, and the whole
    response is relayed to Cline unchanged (the existing, regression-tested
    path)."""
    if not tool_calls:
        return None
    parts = [str(content).strip()] if content else []
    for tool_call in tool_calls:
        name = (tool_call.get("function") or {}).get("name")
        arg_key = _CLINE_TERMINAL_TOOL_ARG_KEYS.get(name)
        if arg_key is None:
            return None
        try:
            args = json.loads((tool_call.get("function") or {}).get("arguments") or "{}")
        except (TypeError, ValueError):
            args = {}
        text = args.get(arg_key)
        if text:
            parts.append(str(text).strip())
    return "\n\n".join(part for part in parts if part)


async def _dispatch_step(key: str, state: dict, step_idx: int, cf_url: str, auth_header: str, original_body: dict,
                         tail_messages: list, is_stream: bool, model_name: str):
    """Send one step's narrowed prompt (+ its own tail of tool turns, if this is
    a mid-step continuation) to CF and either relay its tool calls back to
    Continue (the loop continues) or hand the final answer to the validator."""
    total = len(state["steps"])
    await _record_metric("orchestrator_step_dispatched")
    dispatch_body = _build_step_dispatch_body(original_body, tail_messages, state["steps"][step_idx - 1], step_idx, total,
                                              state.get("findings", []), state.get("model"))
    result = await _cf_complete_once(cf_url, auth_header, dispatch_body)
    if result is None:
        state["status"] = "halted"
        await _record_metric("orchestrator_run_halted")
        _orchestrator_log(state, f"step {step_idx}/{total} dispatch failed (transport/parse error) -- halting; no further steps will auto-run")
        _save_orchestrator_state(key, state)
        return _synthetic_assistant_response(
            model_name, "", is_stream,
            tool_calls=_terminal_completion_tool_call(
                f"[cfproxy][orchestrator] Lost contact with the model mid-step {step_idx}/{total} -- halting the run here. "
                f"Anything it had already changed is still on disk (`git status` to see it). Re-send your last message to retry."))
    content, tool_calls, _finish_reason = result
    if tool_calls:
        terminal_summary = _cline_terminal_tool_summary(tool_calls, content)
        if terminal_summary is not None:
            tool_names = ", ".join((tc.get("function") or {}).get("name", "?") for tc in tool_calls)
            _orchestrator_log(
                state,
                f"step {step_idx}/{total} response was a Cline-terminal tool call only ({tool_names}) -- "
                f"routing its text through the validator instead of relaying to Cline (CB-14)")
            return await _finish_step(key, state, step_idx, terminal_summary, cf_url, auth_header, original_body, is_stream, model_name)
        return _synthetic_assistant_response(model_name, content, is_stream, tool_calls=tool_calls)
    return await _finish_step(key, state, step_idx, content or "", cf_url, auth_header, original_body, is_stream, model_name)


async def _handle_orchestrated_request(cf_url: str, auth_header: str, body: dict, is_stream: bool, model_name: str):
    """Entry point called from _cf_proxy. Returns a Response if this request is
    part of an active (or just-confirmed) orchestrated run; None if the proxy
    should forward it normally. See the Phase-3 / Stage 2+3 module docstrings
    for the overall design and the YES/NO/AMBIGUOUS branching this drives."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    trigger_idx, trigger_text = _find_breakdown_trigger(messages)
    if trigger_idx is None:
        return None
    key = _orchestrator_key(trigger_text)
    state = _load_orchestrator_state(key)
    if not state:
        return None

    last_user_idx = next((i for i in range(len(messages) - 1, -1, -1)
                          if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    last_user_text = _message_text(messages[last_user_idx]) if last_user_idx is not None else ""
    total = len(state["steps"])

    def _is_short_gate_reply(rx) -> bool:
        return bool(last_user_text) and len(last_user_text) < _ORCHESTRATOR_GATE_REPLY_MAX_CHARS and bool(rx.search(last_user_text))

    # --- (a-resume) Resume path (CB-9/OQ-262 Option C): a FRESH session (no
    # `--id` replay, so this marker-bearing message is the conversation's only
    # -- and therefore both first and last -- user turn) whose text embeds the
    # `[orchestrator-key: ...]` marker `_format_resume_prompt` produces for a
    # paused_for_oq run. `resume-orchestrator-run.ps1` builds this via
    # `--print-resume-prompt` and feeds it to a non-`--id` `run-cline.ps1`
    # invocation specifically so a paused run can be continued without
    # replaying the (often huge) original Cline session. Treat it exactly like
    # the architect's "continue" gate reply in (a) below, but re-anchor to THIS
    # session's message indexing since the session that raised the OQ is gone.
    if state["status"] == "paused_for_oq" and trigger_idx == last_user_idx and _ORCHESTRATOR_KEY_RE.search(trigger_text):
        resolved_idx = state["current"]
        _orchestrator_log(state, f"resumed in a fresh session -- treating step {resolved_idx}/{total} ambiguity as resolved (continue), advancing")
        _record_resolved_step_finding(state, resolved_idx)
        next_idx = resolved_idx + 1
        if next_idx > total:
            state["status"] = "complete"
            await _record_metric("orchestrator_run_completed")
            _save_orchestrator_state(key, state)
            return _synthetic_assistant_response(
                model_name, "", is_stream, tool_calls=_terminal_completion_tool_call(_format_run_complete(key, total)))
        state.update(status="running", current=next_idx, anchor_index=last_user_idx,
                     snapshot_before_step=await _git_snapshot(WORKSPACE))
        _orchestrator_log(state, f"dispatching step {next_idx}/{total}: {state['steps'][next_idx - 1]!r}")
        _save_orchestrator_state(key, state)
        return await _dispatch_step(key, state, next_idx, cf_url, auth_header, body, [], is_stream, model_name)

    # --- (a) The run is paused on a bounded ambiguity OQ -- the architect's
    # next reply IS the resolution: continue (treat step as complete, advance),
    # stop (halt for manual revert), or anything else (off-script -- end
    # automation and let the conversation through untouched rather than
    # reinterpreting an unrelated message as a verdict on the paused step).
    if state["status"] == "paused_for_oq":
        if last_user_idx is None or last_user_idx <= state.get("anchor_index", -1):
            return None  # nothing new since the pause -- let it pass through untouched
        resolved_idx = state["current"]
        if _is_short_gate_reply(_ORCHESTRATOR_HALT_RE):
            state["status"] = "halted"
            await _record_metric("orchestrator_run_halted")
            _orchestrator_log(state, f"architect chose to halt at the step {resolved_idx}/{total} ambiguity pause -- run parked for manual review/revert")
            _save_orchestrator_state(key, state)
            return None
        if _is_short_gate_reply(_ORCHESTRATOR_CONTINUE_RE):
            _orchestrator_log(state, f"architect resolved the step {resolved_idx}/{total} ambiguity as complete -- advancing")
            _record_resolved_step_finding(state, resolved_idx)
            next_idx = resolved_idx + 1
            if next_idx > total:
                state["status"] = "complete"
                await _record_metric("orchestrator_run_completed")
                _save_orchestrator_state(key, state)
                return _synthetic_assistant_response(
                    model_name, "", is_stream, tool_calls=_terminal_completion_tool_call(_format_run_complete(key, total)))
            state.update(status="running", current=next_idx, anchor_index=last_user_idx,
                         snapshot_before_step=await _git_snapshot(WORKSPACE))
            _orchestrator_log(state, f"dispatching step {next_idx}/{total}: {state['steps'][next_idx - 1]!r}")
            _save_orchestrator_state(key, state)
            return await _dispatch_step(key, state, next_idx, cf_url, auth_header, body, [], is_stream, model_name)
        _orchestrator_log(state, f"off-script reply at the step {resolved_idx}/{total} ambiguity pause -- ending automation, forwarding normally ({last_user_text[:80]!r})")
        state["status"] = "halted"
        await _record_metric("orchestrator_run_halted")
        _save_orchestrator_state(key, state)
        return None

    if state["status"] != "running":
        return None  # halted / complete -- stop intercepting; let traffic through untouched

    anchor = state.get("anchor_index")
    if anchor is None:
        return None

    # --- (b) Mid-step continuation: Continue is relaying tool results back to
    # the model for the step currently in flight. Detected by the ABSENCE of any
    # new user-role message after the anchor -- nothing in the fully-automatic
    # path ever pauses for a reply while status == "running" (YES auto-advances
    # silently; NO/AMBIGUOUS transition out of "running" before returning), so
    # if no user message has appeared since the anchor was set, this can only be
    # Continue completing a tool-call round trip for that in-flight step -- the
    # SAME test that correctly distinguished this in Stage 1's user-anchored
    # design, generalized to also cover anchors set by silent auto-advances.
    new_user_idx = next((i for i in range(len(messages) - 1, anchor, -1)
                         if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    if new_user_idx is None:
        return await _dispatch_step(key, state, state["current"], cf_url, auth_header, body, messages[anchor + 1:], is_stream, model_name)

    # A new user message appeared while status == "running" -- shouldn't happen
    # in the fully-automatic flow (see above), but if the architect interjects
    # anyway, don't swallow it: end automation and let it through untouched
    # rather than misinterpreting an unrelated message as a verdict.
    _orchestrator_log(state, f"unexpected new user message while step {state['current']}/{total} was running -- ending automation, forwarding normally ({last_user_text[:80]!r})")
    state["status"] = "halted"
    await _record_metric("orchestrator_run_halted")
    _save_orchestrator_state(key, state)
    return None


_CF_BLOCKED_IP_RE = re.compile(r"location:\s*([0-9a-fA-F:.]+)")


async def _diagnose_upstream_error(status_code: int, body_text: str, auth_header: str, account_id: str) -> str:
    """Translate a raw CF API error into an actionable message where we can.

    CF's Workers AI gateway collapses several distinct auth-failure root causes
    (bad token, expired token, *and* a client-IP-allowlist rejection) into the
    same generic `{"errors":[{"code":10000,"message":"Authentication error"}]}` /
    401 shape -- so the raw body alone is not actionable. A user reading
    "Authentication error" will reasonably (and wrongly) suspect a typo'd or
    expired token.

    Initial diagnosis (2026-06-08) guessed "token missing the Workers AI
    permission scope" -- WRONG, the user confirmed the token already has Edit
    (which is a superset of Read). The actual cause, found by replaying the
    *same* token against a plain account-details endpoint
    (`GET /accounts/{id}`), is CF's "Client IP Address Filtering": that endpoint
    surfaces the real reason explicitly --
    `{"code":9109,"message":"Cannot use the access token from location: <ip>"}`
    (403) -- while the Workers AI gateway swallows it into the generic
    code-10000/401. Same token, same request origin, two different CF surfaces,
    two different error fidelities.

    So when we see the generic code-10000/401 from the AI gateway, we replay
    the request against the account-details endpoint with the *same*
    Authorization header to ask CF to name the real reason. If CF answers with
    code 9109, we now know -- not guess -- the blocking IP, and can tell the
    user exactly which address to add to the token's allowlist. If the probe
    comes back clean or with a different code, we say so plainly rather than
    repeating a diagnosis we have already gotten wrong once.
    """
    try:
        parsed = json.loads(body_text)
        errors = parsed.get("errors") or []
    except Exception:
        errors = []

    cf_codes = {e.get("code") for e in errors if isinstance(e, dict)}

    if status_code == 401 and 10000 in cf_codes and auth_header:
        # NOTE: /user/tokens/verify does NOT enforce Client IP Address Filtering
        # (confirmed empirically -- it reports "active" even from a blocked IP),
        # so it cannot surface code 9109. Account-resource-scoped endpoints DO
        # enforce it; GET /accounts/{id} is the cheapest read-only one that
        # needs no permissions beyond what a Workers-AI-scoped token already has.
        probe_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                probe = await client.get(probe_url, headers={"Authorization": auth_header})
            probe_errors = (probe.json().get("errors") or []) if probe.status_code >= 400 else []
        except Exception as exc:
            probe_errors = []
            print(f"[cfproxy] IP-allowlist probe itself failed: {exc!r}", file=sys.stderr)

        for err in probe_errors:
            if not isinstance(err, dict):
                continue
            if err.get("code") == 9109:
                m = _CF_BLOCKED_IP_RE.search(err.get("message", ""))
                ip = m.group(1) if m else "(unknown -- CF didn't include it this time)"
                return (
                    f"[cfproxy] CF API error (status 401): Authentication error (code 10000) -- "
                    f"CONFIRMED CAUSE: Client IP Address Filtering. Replaying the same "
                    f"token against GET /accounts/{{id}} from this network gets rejected with "
                    f"'Cannot use the access token from location: {ip}' (code 9109); the "
                    f"Workers AI gateway just reports it as a generic auth error instead. "
                    f"Fix: Cloudflare dashboard -> My Profile -> API Tokens -> edit the token "
                    f"-> Client IP Address Filtering -> add {ip} (or widen/remove the filter "
                    f"if this network's address changes often)."
                )

        return (
            "[cfproxy] CF API error (status 401): Authentication error (code 10000). "
            "Re-checked against CF's token-verify endpoint with the same credential and "
            "did NOT get the IP-allowlist signature (code 9109) we saw before from this "
            "token/network combination -- so this occurrence may have a different cause "
            "(token rotated/revoked since the last check, transient CF-side issue, etc). "
            "Re-run the diagnostic probes from the 2026-06-08 session before assuming the "
            "same fix applies twice."
        )

    return f"[cfproxy] CF API error (status {status_code}): {body_text[:300]}"


async def _cf_proxy(request: StarletteRequest):
    """Proxy handler: forwards to CF API and rewrites <tools> XML → tool_calls."""
    account_id = request.path_params["account_id"]
    rest = request.path_params.get("rest", "")
    cf_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/{rest}"
    )

    body = _sanitize_messages_for_cf(await request.json())
    model_name = body.get("model", "")
    body = _truncate_oversized_tool_results(_compact_conversation_history(body, model_name), model_name)

    # --- Request intake log: model, message shape, tool schema presence ---
    _req_model = body.get("model", "(none)")
    _req_msgs = body.get("messages", [])
    _req_total_chars = sum(len(_message_text(m) or "") for m in _req_msgs if isinstance(m, dict))
    _req_has_tools = bool(body.get("tools"))
    _req_stream = body.get("stream", False)
    print(
        f"[cfproxy] -> {_req_model} | {len(_req_msgs)} msgs | {_req_total_chars} chars | "
        f"tools={'yes' if _req_has_tools else 'no'} | stream={'yes' if _req_stream else 'no'}",
        file=sys.stderr,
    )
    is_stream = body.get("stream", False)
    headers = {
        "Authorization": request.headers.get("authorization", ""),
        "Content-Type": "application/json",
    }

    # --- Daily spend review flag -- log (don't block) once today's estimated
    # spend crosses the AUD-denominated review threshold. See
    # _spend_review_flag_message: high spend no longer refuses requests --
    # failing a query over token/cost usage just wastes the tokens already
    # spent reaching that point. The architect reviews the flagged total.
    exceeded, spend = await _spend_review_threshold_exceeded()
    if exceeded:
        print(_spend_review_flag_message(spend), file=sys.stderr)

    # --- Phase 3: orchestrated execution of an already-confirmed breakdown.
    # Checked BEFORE Phase 2's detector below -- an active run's step-dispatch
    # turns ("step 2 of 5...") would otherwise look like a fresh multi-step ask
    # and get re-decomposed instead of progressed. See _handle_orchestrated_request
    # and the Phase-3 module docs for the full design and its safety mechanisms.
    if isinstance(body.get("messages"), list):
        orchestrated = await _handle_orchestrated_request(cf_url, headers["Authorization"], body, is_stream, model_name)
        if orchestrated is not None:
            return orchestrated

    # --- Multi-step ask interception -- decompose before executing, not during.
    # Only fires on /v1/chat/completions-shaped bodies (it needs a `messages`
    # array to find the user's ask in); other CF endpoints pass through untouched.
    # See _detect_multi_step_ask for why this exists and what evidence backs it.
    #
    # AT-1245 (2026-06-19): also gated on _is_cline_traffic(body) now. This
    # interceptor was built and tested only against Cline traffic, with no
    # way to exclude any other OpenAI-compatible client hitting the same
    # cf/* models -- a real aider-evaluation task message (long, multi-verb,
    # exactly the shape below detects) was silently decomposed into 3
    # separate autonomous orchestrator runs, invisible to both aider and the
    # operator, discovered only by chance via an OQ-ledger diff. See
    # _is_cline_traffic's docstring for the detection signal and why it
    # defaults to NOT intercepting unrecognized callers.
    #
    # Auto-confirms and dispatches step 1 immediately rather than proposing the
    # breakdown via ask_followup_question and waiting for an architect reply to
    # confirm it: there is no turn on which that reply can arrive (Cline
    # requires exactly one tool call per assistant turn -- including this one
    # -- and Continue never sends a bare "yes" of its own accord), so the
    # proposal was never recognized as confirmed and _detect_multi_step_ask kept
    # firing on the same original message every subsequent turn -- an unbounded
    # re-decomposition loop, each iteration burning its own planner-pass CF call
    # (verified empirically 2026-06-11: 3 successive re-proposals for the same
    # 403-char ask within 10 seconds, with the message history -- and therefore
    # the per-call cost -- growing each time). Auto-confirming removes the
    # unsatisfiable gate while keeping Phase 3's actual safety net -- per-step
    # git snapshots, automatic YES/NO/AMBIGUOUS validation, the bounded
    # ambiguity-OQ escalation, the step cap, and the daily spend cap -- none of
    # which require a human reply to function.
    if (
        isinstance(body.get("messages"), list)
        and not _conversation_has_tool_use(body["messages"])
        and _is_cline_traffic(body)
    ):
        messages = body["messages"]
        user_message = _latest_user_message(body)
        architect_ask = _strip_cline_injected_context(user_message)
        is_multi_step, reason = _detect_multi_step_ask(architect_ask)
        if is_multi_step:
            await _record_metric("multi_step_heuristic_fired")
            print(f"[cfproxy] multi-step ask detected ({reason}) -- running planner pass", file=sys.stderr)
            await _record_metric("planner_pass_triggered")
            steps = await _run_planner_pass(cf_url, headers["Authorization"], model_name, architect_ask)
            if steps and len(steps) > _ORCHESTRATOR_MAX_STEPS:
                print(f"[cfproxy] planner pass produced {len(steps)} steps, exceeds the {_ORCHESTRATOR_MAX_STEPS}-step "
                      f"orchestration cap -- forwarding original request unchanged (a hard circuit breaker; "
                      f"see the Phase-3 module docs for why unbounded step counts are a runaway-cost failure mode)",
                      file=sys.stderr)
                await _record_metric("planner_pass_too_many_steps")
            elif steps:
                trigger_idx = next((i for i in range(len(messages) - 1, -1, -1)
                                     if isinstance(messages[i], dict) and messages[i].get("role") == "user"), len(messages) - 1)
                key = _orchestrator_key(user_message)
                state = _new_orchestrator_state(steps, reason, model=model_name)
                state.update(current=1, anchor_index=trigger_idx,
                             snapshot_before_step=await _git_snapshot(WORKSPACE))
                _orchestrator_log(state, f"auto-confirmed {len(steps)}-step breakdown ({reason}) -- dispatching step 1/{len(steps)}: {steps[0]!r}")
                _save_orchestrator_state(key, state)
                await _record_metric("orchestrator_auto_confirmed")
                return await _dispatch_step(key, state, 1, cf_url, headers["Authorization"], body, [], is_stream, model_name)
            # steps is None/empty, or over-cap: planner failed or produced
            # nothing usable -- fall through and forward the original request so
            # the user isn't blocked.
            await _record_metric("planner_pass_failed")

    # Normalize message content for CF Workers AI compatibility.
    # Cline (and modern OpenAI clients) send content as an array of typed blocks,
    # e.g. [{"type":"text","text":"..."}]. CF gpt-oss models only accept content
    # as a plain string. Flatten any array content to a string here, once, before
    # any forwarding path touches the body.
    if isinstance(body.get("messages"), list):
        body = {**body, "messages": _normalize_cf_messages(body["messages"])}

    # AT-1170: scrub secret-shaped content before it leaves this process toward
    # the external CF model. Runs after normalization (content is always a
    # plain string by this point) and immediately before both the streaming
    # and non-streaming forward paths below, so neither path can bypass it.
    body = _scrub_secrets_from_body(body)

    if not is_stream:
        # CB-23: same 429-capacity retry as the streaming path below -- see
        # CF_CAPACITY_RETRY_BACKOFF_SECONDS for why this is transient and
        # worth retrying rather than surfacing immediately like a genuine
        # (non-transient) auth/permission failure.
        _non_stream_max_attempts = CF_CAPACITY_RETRY_LIMIT + 1
        for _non_stream_attempt in range(1, _non_stream_max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=CF_FORWARD_TIMEOUT_SECONDS) as client:
                    resp = await client.post(cf_url, json=body, headers=headers)
            except httpx.TimeoutException:
                print(
                    f"[cfproxy] CF request exceeded the proxy's "
                    f"{CF_FORWARD_TIMEOUT_SECONDS:.0f}s non-streaming timeout "
                    f"(model={body.get('model')!r}, max_tokens={body.get('max_tokens')!r}) "
                    f"-- the model is likely still generating a long completion",
                    file=sys.stderr,
                )
                return JSONResponse(
                    {"error": {
                        "message": (
                            f"CF did not respond within {CF_FORWARD_TIMEOUT_SECONDS:.0f}s. "
                            f"This model may need stream=true or a smaller max_tokens for "
                            f"non-streaming requests."
                        ),
                        "type": "cf_proxy_timeout",
                    }},
                    status_code=504,
                )
            try:
                data = resp.json()
            except Exception:
                print(
                    f"[cfproxy] CF returned non-JSON (status {resp.status_code}): "
                    f"{resp.text[:300]!r}",
                    file=sys.stderr,
                )
                return JSONResponse(
                    {"error": {
                        "message": await _diagnose_upstream_error(resp.status_code, resp.text, headers["Authorization"], account_id),
                        "type": "upstream_error",
                    }},
                    status_code=resp.status_code if resp.status_code >= 400 else 502,
                )

            if resp.status_code in CF_TRANSIENT_RETRY_STATUS_CODES and _non_stream_attempt < _non_stream_max_attempts:
                backoff = CF_CAPACITY_RETRY_BACKOFF_SECONDS[
                    min(_non_stream_attempt - 1, len(CF_CAPACITY_RETRY_BACKOFF_SECONDS) - 1)
                ]
                print(
                    f"[cfproxy] CF transient error ({resp.status_code}) from {body.get('model')!r} "
                    f"(non-streaming attempt {_non_stream_attempt}/{_non_stream_max_attempts}) -- "
                    f"retrying after {backoff}s: {resp.text[:200]!r}",
                    file=sys.stderr,
                )
                await asyncio.sleep(backoff)
                continue

            if resp.status_code >= 400:
                diagnosis = await _diagnose_upstream_error(resp.status_code, resp.text, headers["Authorization"], account_id)
                print(diagnosis, file=sys.stderr)
                return JSONResponse(
                    {"error": {"message": diagnosis, "type": "upstream_error"}},
                    status_code=resp.status_code,
                )

            break

        for choice in data.get("choices", []):
            msg = choice.get("message", {})
            if msg.get("role") == "assistant" and msg.get("content"):
                tc = _parse_any_tool_call(msg["content"])
                if tc:
                    print(
                        f"[cfproxy] rewrote assistant content -> tool_call "
                        f"{tc['function']['name']}({tc['function']['arguments']}) "
                        f"(was: {msg['content'][:120]!r})",
                        file=sys.stderr,
                    )
                    msg["content"] = None
                    msg["tool_calls"] = [tc]
                    choice["finish_reason"] = "tool_calls"
                else:
                    note = _detect_hallucinated_tool_call_text(msg["content"], model_name)
                    if note:
                        await _record_metric("hallucination_detector_fired")
                        print(
                            f"[cfproxy] flagged hallucinated inline tool-call text in "
                            f"assistant content (model={model_name}): {msg['content'][:200]!r}",
                            file=sys.stderr,
                        )
                        msg["content"] += note

        usage = data.get("usage")
        if isinstance(usage, dict):
            spend = await _record_cf_spend(model_name, usage)
            print(
                f"[cfproxy] spend: ${spend['total_usd']:.4f} USD "
                f"(~${spend['total_usd'] * USD_TO_AUD_RATE:.2f} AUD) total today "
                f"(model={model_name}, prompt={usage.get('prompt_tokens')}, "
                f"completion={usage.get('completion_tokens')}, "
                f"review-flag=${DAILY_SPEND_REVIEW_THRESHOLD_USD * USD_TO_AUD_RATE:.2f} AUD/day)",
                file=sys.stderr,
            )
            if (usage.get("prompt_tokens") or 0) > _LARGE_PROMPT_DIAGNOSTIC_THRESHOLD_TOKENS:
                print(
                    f"[cfproxy] large-prompt composition ({usage.get('prompt_tokens')} tokens): "
                    f"{_summarize_message_composition(body.get('messages'))}; "
                    f"{_final_turn_fingerprint(body.get('messages'))}",
                    file=sys.stderr,
                )
        return JSONResponse(data)

    # --- Streaming path ---
    async def _stream():
        # Buffer all content chunks — we can't stream-through because we don't
        # know until finish_reason whether the response is a tool call or plain text.
        # For plain text we emit the buffer at the end (slight latency but correct).
        #
        # Degenerate-response recovery: gpt-oss models hosted on CF sometimes end
        # a turn having spent their entire token budget on internal reasoning
        # (`reasoning_content`) without ever producing a final-channel answer --
        # finish_reason="stop", completion_tokens > 0, but delta.content is empty
        # and no tool_calls were emitted. Left unhandled, the proxy forwards an
        # empty stream and Continue.dev looks like it's silently ignoring the
        # user (verified empirically 2026-06-07: three consecutive empty turns
        # from @cf/openai/gpt-oss-120b at ~30K-char prompt size, 39-154
        # completion_tokens each, content=''). Since plain-text content is
        # already fully buffered before being forwarded (see above), nothing
        # has been sent to the client yet when we detect this -- so retrying
        # with a fresh CF call is safe and invisible to the client when it
        # succeeds. Native tool_calls are streamed through live as they arrive
        # and are never degenerate, so a retry never duplicates visible output.
        first_id = None
        first_model = body.get("model", "")
        # CB-23: the loop bound covers whichever retry reason needs more
        # attempts -- degenerate-response retries (temperature perturbation,
        # CF_DEGENERATE_RETRY_TEMPERATURES) or 429 capacity retries (backoff
        # sleep, CF_CAPACITY_RETRY_BACKOFF_SECONDS). Both share this same
        # attempt counter and loop; a request only ever needs one budget or
        # the other in practice, so sharing the larger of the two ceilings
        # costs nothing extra in the common case.
        max_attempts = max(CF_DEGENERATE_RETRY_LIMIT, CF_CAPACITY_RETRY_LIMIT) + 1

        for attempt in range(1, max_attempts + 1):
            buffered = ""
            native_tool_call_seen = False
            finish_raw = None
            reasoning_chars = 0  # chars seen in delta.reasoning_content this attempt
            # CF repeats `usage` on multiple terminal chunks (we observed it on
            # both finish_reason chunks in testing) -- keep the latest one and
            # record spend exactly once, after each attempt completes.
            final_usage = None

            # Attempts 2+ are the degenerate-response retries -- perturb
            # `temperature` so the request isn't byte-identical to the one that
            # just degenerated (see CF_DEGENERATE_RETRY_TEMPERATURES for why an
            # identical retry reproduces an identical failure). Every attempt
            # (including the first) gets a low reasoning-effort hint for
            # gpt-oss models -- see CF_GPT_OSS_REASONING_EFFORT for why this
            # targets the choice to stop after reasoning without ever starting
            # the final answer, not a retry-recovery concern.
            overrides = {}
            if first_model.startswith(CF_GPT_OSS_MODEL_PREFIX):
                overrides["reasoning_effort"] = CF_GPT_OSS_REASONING_EFFORT
            if attempt > 1:
                retry_temp = CF_DEGENERATE_RETRY_TEMPERATURES[
                    min(attempt - 2, len(CF_DEGENERATE_RETRY_TEMPERATURES) - 1)
                ]
                overrides["temperature"] = retry_temp
                print(
                    f"[cfproxy] degenerate-response retry {attempt}/{max_attempts}: "
                    f"perturbing temperature -> {retry_temp} (an identical retry "
                    f"reproduces an identical failure when the degeneracy is "
                    f"prompt-correlated rather than per-call noise)",
                    file=sys.stderr,
                )
            attempt_body = {**body, **overrides} if overrides else body

            # Was 60.0 (CB-16) -- too short for kimi-k2.6 on large contexts;
            # see CF_FORWARD_TIMEOUT_SECONDS for the measured rationale.
            async with httpx.AsyncClient(timeout=CF_FORWARD_TIMEOUT_SECONDS) as client:
                async with client.stream("POST", cf_url, json=attempt_body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        # CF returns a plain JSON error body (not SSE) on failure --
                        # e.g. 400 Bad Request when the conversation exceeds the
                        # model's context length. Left unchecked, the loop below
                        # finds no "data: " lines, and the proxy silently emits an
                        # empty stream (200 OK + only [DONE]), which looks to
                        # Continue.dev like a broken connection rather than a
                        # readable error. Surface the real upstream error instead.
                        error_body = (await resp.aread()).decode("utf-8", "replace")

                        # CB-23: 429 capacity errors are transient (CF's own
                        # message says "please try again") -- retry within the
                        # existing attempt budget instead of giving up. Checked
                        # before _diagnose_upstream_error/auth handling below,
                        # which is only correct for genuinely permanent failures.
                        if resp.status_code in CF_TRANSIENT_RETRY_STATUS_CODES and attempt < max_attempts:
                            backoff = CF_CAPACITY_RETRY_BACKOFF_SECONDS[
                                min(attempt - 1, len(CF_CAPACITY_RETRY_BACKOFF_SECONDS) - 1)
                            ]
                            print(
                                f"[cfproxy] CF transient error ({resp.status_code}) from {first_model} "
                                f"(attempt {attempt}/{max_attempts}) -- retrying after {backoff}s: "
                                f"{error_body[:200]!r}",
                                file=sys.stderr,
                            )
                            await asyncio.sleep(backoff)
                            continue

                        err_text = await _diagnose_upstream_error(resp.status_code, error_body, headers["Authorization"], account_id)
                        print(err_text, file=sys.stderr)
                        base = {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "model": first_model,
                        }
                        # Auth/permission failures (401/403) are not transient --
                        # retrying hits the exact same wall and only burns spend
                        # and CF_DEGENERATE_RETRY_LIMIT attempts on a problem that
                        # can only be fixed by editing the CF token's permissions
                        # (see _diagnose_upstream_error). Surface immediately.
                        # (429 is handled above and never reaches here unless the
                        # retry budget is also exhausted, in which case it falls
                        # through to this same honest-error path.)
                        yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': err_text}, 'finish_reason': None}]})}\n\n"
                        yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except Exception:
                            continue

                        if first_id is None:
                            first_id = chunk.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}")
                            first_model = chunk.get("model", first_model)

                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            final_usage = usage

                        choice0 = chunk.get("choices", [{}])[0]
                        delta = choice0.get("delta", {})
                        finish = choice0.get("finish_reason")

                        # Native tool_calls -- the model (gpt-oss, llama-4-scout,
                        # etc.) emitted standard OpenAI tool-call deltas directly.
                        # These chunks are already in the exact shape Continue.dev
                        # expects (function name/arguments streamed incrementally
                        # across multiple chunks). Pass them straight through --
                        # routing them into the text-buffering path below would
                        # silently drop them, since they carry no delta.content
                        # for `buffered` to accumulate. A native tool_call is
                        # never degenerate, so once seen we commit to this attempt.
                        if delta.get("tool_calls"):
                            native_tool_call_seen = True
                            yield f"data: {raw}\n\n"
                            continue

                        # gpt-oss Harmony streaming format: the model emits
                        # reasoning/analysis via delta.reasoning_content (the
                        # <|channel|>analysis channel) before final-channel content.
                        # Log when we see reasoning tokens so we can correlate
                        # "all reasoning, no final answer" with degenerate responses.
                        reasoning_piece = delta.get("reasoning_content")
                        if reasoning_piece:
                            reasoning_chars += len(str(reasoning_piece))

                        # CF's tokenizer sometimes serializes markdown list numbers
                        # ("1.", "2.", "3." in numbered lists) as raw JSON integers
                        # rather than strings -- e.g. {"delta": {"content": 1}} --
                        # so coerce to str rather than assuming content is textual.
                        piece = delta.get("content")
                        if piece is not None and piece != "":
                            buffered += str(piece)

                        if finish and finish_raw is None:
                            # Keep consuming after the first finish chunk -- CF
                            # sometimes sends a trailing usage-only chunk before
                            # [DONE] that we still want to capture.
                            if finish == "length":
                                # Token cap hit -- response was cut off mid-output.
                                # This is NOT the same as the degenerate-empty case:
                                # there IS content, but it's truncated. Raise
                                # max_tokens in litellm_config.yaml for this model.
                                print(
                                    f"[cfproxy] WARN finish_reason=length from {first_model} "
                                    f"(attempt {attempt}/{max_attempts}): response truncated at "
                                    f"token limit -- raise max_tokens in litellm_config.yaml "
                                    f"for this model (current buffered={len(buffered)} chars, "
                                    f"reasoning={reasoning_chars} chars)",
                                    file=sys.stderr,
                                )
                            finish_raw = raw

            if final_usage is not None:
                spend = await _record_cf_spend(first_model, final_usage)
                print(
                    f"[cfproxy] spend: ${spend['total_usd']:.4f} USD "
                    f"(~${spend['total_usd'] * USD_TO_AUD_RATE:.2f} AUD) total today "
                    f"(model={first_model}, prompt={final_usage.get('prompt_tokens')}, "
                    f"completion={final_usage.get('completion_tokens')}, "
                    f"review-flag=${DAILY_SPEND_REVIEW_THRESHOLD_USD * USD_TO_AUD_RATE:.2f} AUD/day, "
                    f"attempt={attempt}/{max_attempts})",
                    file=sys.stderr,
                )
                if (final_usage.get("prompt_tokens") or 0) > _LARGE_PROMPT_DIAGNOSTIC_THRESHOLD_TOKENS:
                    print(
                        f"[cfproxy] large-prompt composition ({final_usage.get('prompt_tokens')} tokens, "
                        f"attempt {attempt}/{max_attempts}): "
                        f"{_summarize_message_composition(attempt_body.get('messages'))}; "
                        f"{_final_turn_fingerprint(attempt_body.get('messages'))}",
                        file=sys.stderr,
                    )

            if native_tool_call_seen:
                print(
                    f"[cfproxy] <- {first_model} | native tool_calls | attempt {attempt}/{max_attempts}",
                    file=sys.stderr,
                )
                if finish_raw:
                    yield f"data: {finish_raw}\n\n"
                yield "data: [DONE]\n\n"
                return

            base = {"id": first_id, "object": "chat.completion.chunk", "model": first_model}
            tc = _parse_any_tool_call(buffered) if buffered else None
            if tc:
                print(
                    f"[cfproxy] rewrote streamed content -> tool_call "
                    f"{tc['function']['name']}({tc['function']['arguments']}) "
                    f"(was: {buffered[:120]!r})",
                    file=sys.stderr,
                )
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': tc['id'], 'type': 'function', 'function': {'name': tc['function']['name'], 'arguments': ''}}]}, 'finish_reason': None}]})}\n\n"
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': tc['function']['arguments']}}]}, 'finish_reason': None}]})}\n\n"
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}\n\n"
                yield "data: [DONE]\n\n"
                return

            if buffered:
                note = _detect_hallucinated_tool_call_text(buffered, first_model)
                if note:
                    await _record_metric("hallucination_detector_fired")
                    print(
                        f"[cfproxy] flagged hallucinated inline tool-call text in "
                        f"streamed content (model={first_model}): {buffered[:200]!r}",
                        file=sys.stderr,
                    )
                    buffered += note
                reasoning_note = f" | reasoning={reasoning_chars} chars" if reasoning_chars else ""
                print(
                    f"[cfproxy] <- {first_model} | text ({len(buffered)} chars){reasoning_note} | attempt {attempt}/{max_attempts} | snippet: {buffered[:80]!r}",
                    file=sys.stderr,
                )
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'content': buffered}, 'finish_reason': None}]})}\n\n"
                if finish_raw:
                    yield f"data: {finish_raw}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Degenerate: this attempt produced neither content nor a tool call.
            # Nothing has been forwarded to the client yet (plain text is fully
            # buffered above), so a retry is safe and invisible if it succeeds.
            if attempt < max_attempts:
                await _record_metric("degenerate_response_retry")
                print(
                    f"[cfproxy] degenerate empty response from {first_model} "
                    f"(attempt {attempt}/{max_attempts}, "
                    f"completion_tokens={(final_usage or {}).get('completion_tokens')}) -- retrying "
                    f"-- {_final_turn_fingerprint(attempt_body.get('messages'))}",
                    file=sys.stderr,
                )
                continue

            await _record_metric("degenerate_response_giveup")
            print(
                f"[cfproxy] degenerate empty response from {first_model} "
                f"persisted across {max_attempts} attempts -- giving up, "
                f"surfacing an honest message instead of going silent "
                f"-- {_final_turn_fingerprint(attempt_body.get('messages'))}",
                file=sys.stderr,
            )
            msg = (
                f"[cfproxy] {first_model} returned an empty response {max_attempts} times "
                f"in a row -- it spent the whole turn on internal reasoning without "
                f"producing an answer (a known CF gpt-oss inference quirk, not a tool "
                f"or config problem). Please resend your last message, or switch to a "
                f"different model (e.g. CF qwen2.5-coder:32b) for this turn."
            )
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': msg}, 'finish_reason': None}]})}\n\n"
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"
            return

    return StreamingResponse(_stream(), media_type="text/event-stream")


# AT-1142 / CB-15: the skein-toolkit repo root (NOT `WORKSPACE`, which points at
# the *consuming* project and is overridable via WORKSPACE_ROOT) -- this is the
# source tree local-mcp.py itself lives in, so its commit SHA identifies which
# version of the server code a running process was started from.
_SERVER_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _get_server_commit_sha() -> str:
    """Short commit SHA of the skein-toolkit working tree this server was
    started from. Printed at startup and served on /health so
    toolchain-doctor.ps1 can detect a stale running server (CB-15: the server
    process keeps serving an old commit after the working tree has moved on)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_SERVER_REPO_ROOT,
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        print(f"[cfproxy][health] git rev-parse failed (rc={result.returncode}): "
              f"{result.stderr.strip()}", file=sys.stderr)
        return "unknown"
    except Exception as e:
        print(f"[cfproxy][health] could not determine server commit SHA: {e}", file=sys.stderr)
        return "unknown"


# Computed once at import time (process start) and frozen for the process's
# lifetime: this is "what commit was this running process loaded from", NOT
# "what is HEAD right now" -- re-running git on every /health call would
# always report the CURRENT working tree, making a stale in-memory process
# look fresh and defeating the staleness check entirely.
_SERVER_STARTUP_COMMIT_SHA = _get_server_commit_sha()


async def _health(request: StarletteRequest) -> JSONResponse:
    """AT-1142 / CB-15: reports the commit SHA the running server process was
    started from, used by toolchain-doctor.ps1 to detect a stale server."""
    return JSONResponse({"status": "ok", "commit": _SERVER_STARTUP_COMMIT_SHA})


if __name__ == "__main__":
    # --print-resume-prompt <key>: CB-9/OQ-262 Option C resume support. Prints
    # the resume prompt for a paused_for_oq run to stdout and exits without
    # starting the server, so resume-orchestrator-run.ps1 can capture it and
    # feed it straight to a fresh run-cline.ps1 invocation.
    if len(sys.argv) >= 3 and sys.argv[1] == "--print-resume-prompt":
        resume_key = sys.argv[2]
        resume_state = _load_orchestrator_state(resume_key)
        if resume_state is None:
            print(f"No orchestrator state found for key {resume_key!r} "
                  f"(expected {_orchestrator_state_path(resume_key)})", file=sys.stderr)
            sys.exit(1)
        if resume_state.get("status") != "paused_for_oq":
            print(f"Run {resume_key} is not paused_for_oq (status={resume_state.get('status')!r}) "
                  f"-- resume only applies to runs paused on an ambiguity OQ.", file=sys.stderr)
            sys.exit(1)
        print(_format_resume_prompt(resume_key, resume_state))
        sys.exit(0)

    print(f"Local MCP server starting...")
    print(f"  running from commit {_SERVER_STARTUP_COMMIT_SHA} ({_SERVER_REPO_ROOT})")
    print(f"Workspace: {WORKSPACE}")
    print(f"Listening on http://127.0.0.1:3100/sse  (MCP tools)")
    print(f"CF proxy at   http://127.0.0.1:3100/cfproxy/{{account_id}}/v1")
    print(f"Health/staleness check at http://127.0.0.1:3100/health")
    print(f"Add to Continue.dev: run  .\\scripts\\set-continue-config.ps1 -McpLocal")

    # Combine FastMCP SSE app with CF proxy routes on a single uvicorn server
    mcp_app = mcp.sse_app()
    combined = Starlette(routes=[
        Route("/cfproxy/{account_id}/{rest:path}", _cf_proxy, methods=["POST", "GET", "OPTIONS"]),
        Route("/health", _health, methods=["GET"]),
        Mount("/", app=mcp_app),
    ])
    uvicorn.run(combined, host="127.0.0.1", port=3100, log_level="info")
