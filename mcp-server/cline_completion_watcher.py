#!/usr/bin/env python3
"""
cline_completion_watcher.py -- closes a real verification gap interactive Cline
sessions have that dispatch_coding_task already doesn't.

Background: SR-1.14's VERIFY-1 requires checking independently-observable
evidence, never a model's self-reported completion claim. dispatch_coding_task
already does this (get_coding_task_status checks real git state). Interactive
Cline sessions (the VS Code extension) have no equivalent -- a human reads
attempt_completion's text directly, and nothing automatically checks it.

Cline's own mechanisms can't fill this gap today: hooks have no event that
fires around attempt_completion at all, and the whole hooks system is
macOS/Linux only (unsupported on Windows, which is what this machine runs).
"Double-Check Completion" is text-only self-critique (Self-Refine pattern,
confirmed by reading its actual checklist text directly from the extension
source) -- it asks the model to re-read its own diff, never to re-run
anything, so it would not reliably catch a runtime-only bug.

Real incident this fixes (2026-06-20, odysseus): a Cline session declared
"Done. I fixed the two root causes" and committed -- before ever running the
launcher script it had just written. It crashed immediately on the next
command: ModuleNotFoundError (wrong Python interpreter, no venv check). No
automatic mechanism caught this; a human had to ask.

This is the CRITIC pattern (tool-interactive critiquing -- verify via actual
execution, not re-reading) applied externally, since Cline can't apply it to
itself on this platform: poll Cline's task storage for new completion_result
events, determine which repo(s) the task touched, run that repo's own test
suite, and -- the part that actually matters for this incident class -- if
any touched file looks like a launcher/entrypoint, spawn it for real,
briefly, and confirm it doesn't crash immediately. Reports failures; does
not attempt to fix anything (that decision belongs to the architect or a
follow-up task, not this watcher).
"""

import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dispatch_io  # noqa: E402 -- kill_job_process_tree, reused not reimplemented

CLINE_TASKS_DIR = os.path.expandvars(
    r"%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\tasks"
)

# Known repos this watcher checks -- mirrors scheduled-git-push.ps1's $Repos
# list (same 3 sibling repos, same convention, not a new one).
DEFAULT_REPOS = {
    "Electron-Splines": r"C:\Users\jakeh\source\repos\Electron-Splines",
    "skein-toolkit": r"C:\Users\jakeh\source\repos\skein-toolkit",
    "odysseus": r"C:\Users\jakeh\source\repos\odysseus",
}

# Each repo's own real test command -- reuses what already exists (confirmed
# directly: package.json's "test" script, this session's own unittest
# invocation, odysseus's own venv pytest), does not invent a new test
# mechanism. None = no command configured (skip, don't guess).
TEST_COMMANDS: "dict[str, list[str] | None]" = {
    "Electron-Splines": ["npm", "test"],
    "skein-toolkit": [sys.executable, "-m", "unittest", "discover", "-s", "mcp-server/tests", "-p", "test_*.py"],
    "odysseus": [r"venv\Scripts\python.exe", "-m", "pytest", "tests/", "-q"],
}

# Filename patterns that mean "this is a launcher/entrypoint, not a regular
# module" -- the one class of bug a test suite alone won't catch (a script
# that imports fine but crashes when actually run, e.g. wrong interpreter
# spawning a subprocess that then fails).
_ENTRYPOINT_PATTERNS = (
    re.compile(r"(^|/)tray\.py$"),
    re.compile(r"(^|/)start[-_].*\.(py|ps1)$"),
    re.compile(r"(^|/)launch[-_].*\.(py|ps1)$"),
    re.compile(r"\.service$"),
)

DEFAULT_STATE_PATH = os.path.expandvars(r"%USERPROFILE%\.cline_completion_watcher_state.json")
DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS = 8.0


def find_cline_task_dirs(tasks_dir: str = CLINE_TASKS_DIR) -> "list[str]":
    """Return Cline task directory paths, newest first."""
    if not os.path.isdir(tasks_dir):
        return []
    entries = [os.path.join(tasks_dir, d) for d in os.listdir(tasks_dir)]
    entries = [d for d in entries if os.path.isdir(d)]
    entries.sort(key=lambda d: os.path.getmtime(d), reverse=True)
    return entries


def get_latest_completion_event(task_dir: str) -> "dict | None":
    """Return {"ts": <ms>, "index": <int>} for the most recent completion_result
    ask in this task's ui_messages.json, or None if the task never reached one."""
    ui_path = os.path.join(task_dir, "ui_messages.json")
    if not os.path.isfile(ui_path):
        return None
    try:
        with open(ui_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("ask") == "completion_result":
            return {"ts": m.get("ts"), "index": i}
    return None


def load_watcher_state(state_path: str = DEFAULT_STATE_PATH) -> dict:
    """processed: {task_dir_basename: last_processed_completion_ts}"""
    if not os.path.isfile(state_path):
        return {"processed": {}}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"processed": {}}


def save_watcher_state(state: dict, state_path: str = DEFAULT_STATE_PATH) -> None:
    tmp_path = state_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, state_path)


def find_new_commits(repo_path: str, since_unix_ts: float) -> "list[str]":
    """Commit hashes on the current branch authored after since_unix_ts.
    Used to find what a just-completed task actually changed -- not the
    task's own self-reported summary."""
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return []
    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since_unix_ts))
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--format=%H"],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [h for h in result.stdout.strip().splitlines() if h]


def changed_files_in_commits(repo_path: str, since_unix_ts: float) -> "list[str]":
    """Union of files touched by every commit since since_unix_ts, relative
    paths -- one git invocation total, not one per commit.

    Real performance finding (2026-06-20): the original implementation
    called `git show` once per commit hash. Several of this project's own
    historical Cline tasks matched 1000+ commits in their lookback window
    (an old completion timestamp plus a long session's worth of subsequent
    activity) -- thousands of subprocess spawns per task, which is what
    actually made a "nothing new to report" scan take minutes, not the
    JSON-parsing last_scan_ts already fixed. `git log --name-only` over
    the same --since window gets the same union of files in one call."""
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return []
    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(since_unix_ts))
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--name-only", "--format="],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def find_entrypoint_candidates(changed_files: "list[str]") -> "list[str]":
    """Of the changed files, which ones look like a launcher/entrypoint --
    the class of file a passing test suite would not exercise."""
    return [f for f in changed_files if any(p.search(f) for p in _ENTRYPOINT_PATTERNS)]


def _resolve_python_for(repo_path: str) -> str:
    """Same interpreter-resolution logic tray.py already uses (and
    start-local.py's real bug was skipping): a repo's own venv if it has
    one, else this watcher's own interpreter. Never assume sys.executable
    has the target repo's dependencies installed."""
    for venv_name in ("venv", ".venv"):
        candidate = Path(repo_path) / venv_name / "Scripts" / "python.exe"
        if candidate.exists():
            return str(candidate)
    return sys.executable


def smoke_test_entrypoint(
    repo_path: str, relative_file_path: str, timeout: float = DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS
) -> "tuple[bool, str]":
    """Actually run the entrypoint file briefly and confirm it doesn't crash
    immediately -- the one check a test suite alone does not provide.

    A `.ps1` file is run via pwsh; a `.py` file via the target repo's own
    venv python (resolved the same way tray.py does it, not sys.executable
    blindly -- that exact gap was today's real bug).

    Semantics: if the process is still running when the timeout elapses,
    that's a PASS for a long-running launcher (killed cleanly afterward).
    If it exits early with a non-zero code, that's a FAIL. An early exit
    with code 0 is treated as a pass but noted -- some entrypoints
    legitimately exit fast (e.g. a one-shot setup script)."""
    full_path = os.path.join(repo_path, relative_file_path)
    if not os.path.isfile(full_path):
        return False, f"{relative_file_path}: file no longer exists (deleted after the commit?)"

    if relative_file_path.endswith(".ps1"):
        argv = ["pwsh", "-NoProfile", "-NonInteractive", "-File", full_path]
    else:
        argv = [_resolve_python_for(repo_path), full_path]

    try:
        proc = subprocess.Popen(
            argv, cwd=repo_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError as exc:
        return False, f"{relative_file_path}: failed to even start -- {exc}"

    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Still running at the timeout -- the expected, good outcome for a
        # long-running launcher. Clean shutdown, not a crash.
        #
        # Real incident, 2026-06-20 (found running this live, the day this
        # was written): proc.kill() only kills the IMMEDIATE process, not
        # what it spawns. tray.py specifically launches a whole service
        # stack of its own (LiteLLM, Odysseus, multiple local-mcp.py
        # instances) -- testing it left genuine orphans (~18 duplicate
        # LiteLLM processes alone after a handful of smoke tests, plus
        # duplicate Odysseus servers and MCP sub-servers), exactly the
        # AT-1249 process-leak class this whole project already fixed
        # once, reintroduced here. dispatch_io.kill_job_process_tree
        # (taskkill /F /T) kills the whole tree, not just this one PID --
        # reused directly rather than reimplemented.
        dispatch_io.kill_job_process_tree(proc.pid)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return True, f"{relative_file_path}: still running after {timeout}s (no early crash) -- killed (whole tree) for cleanup"

    if proc.returncode != 0:
        tail = "\n".join(stdout.strip().splitlines()[-15:]) if stdout else "(no output captured)"
        return False, f"{relative_file_path}: exited early with code {proc.returncode}\n{tail}"
    return True, f"{relative_file_path}: exited 0 within {timeout}s (fast exit, not necessarily wrong)"


def run_test_suite(repo_name: str, repo_path: str) -> "tuple[bool, str] | None":
    """Run repo_name's configured test command. Returns None (not False) if
    no command is configured -- that's a real gap to report, not a failure
    to claim. Never invents a test command for a repo that doesn't have one
    confirmed."""
    cmd = TEST_COMMANDS.get(repo_name)
    if cmd is None:
        return None
    try:
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, f"test command timed out after 180s: {' '.join(cmd)}"
    except OSError as exc:
        return False, f"test command failed to start: {exc}"
    passed = result.returncode == 0
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-15:])
    return passed, tail


def check_for_new_completions(
    repos: "dict[str, str]" = DEFAULT_REPOS,
    state_path: str = DEFAULT_STATE_PATH,
    tasks_dir: str = CLINE_TASKS_DIR,
    smoke_test_timeout: float = DEFAULT_SMOKE_TEST_TIMEOUT_SECONDS,
) -> "list[dict]":
    """The main entry point. Returns a list of report dicts, one per newly-
    completed task found since the last call (tracked via state_path):

    {
      "task_id": str,
      "completed_at": float (unix ts),
      "repos_touched": [str, ...],
      "test_results": {repo_name: (passed, detail) or None},
      "smoke_test_results": [(passed, detail), ...],
      "any_failures": bool,
    }

    Does not modify the repos or attempt any fix -- read-only verification.

    Performance note (found running this for real, 2026-06-20): with 28
    accumulated Cline task directories, a naive full scan took ~3.5
    minutes even with nothing new to report -- most of that is JSON-
    parsing every task's ui_messages.json (some multi-MB) on every single
    run. last_scan_ts skips that parse entirely for any task whose
    ui_messages.json mtime is older than the previous run -- it cannot
    have a new completion if its file hasn't changed since we last looked."""
    state = load_watcher_state(state_path)
    processed = state.setdefault("processed", {})
    last_scan_ts = state.get("last_scan_ts", 0)
    this_scan_started_at = time.time()
    reports: "list[dict]" = []

    for task_dir in find_cline_task_dirs(tasks_dir):
        task_id = os.path.basename(task_dir)
        ui_messages_path = os.path.join(task_dir, "ui_messages.json")
        try:
            if os.path.getmtime(ui_messages_path) < last_scan_ts:
                continue  # unchanged since the last scan -- cannot have a new completion
        except OSError:
            continue  # file missing entirely; get_latest_completion_event would also skip it
        completion = get_latest_completion_event(task_dir)
        if completion is None:
            continue
        completion_ts = completion["ts"]
        if processed.get(task_id) == completion_ts:
            continue  # already reported on this exact completion event

        completed_at_unix = (completion_ts or 0) / 1000.0
        # Look back further than just "since the task's own completion" --
        # a task can run for many minutes; use 2 hours before completion as
        # a deliberately generous window rather than guessing the task's
        # actual start time precisely.
        since_ts = completed_at_unix - 7200

        repos_touched: "list[str]" = []
        test_results: "dict[str, tuple]" = {}
        smoke_results: "list[tuple]" = []

        for repo_name, repo_path in repos.items():
            if not os.path.isdir(repo_path):
                continue
            commits = find_new_commits(repo_path, since_ts)
            if not commits:
                continue
            repos_touched.append(repo_name)
            changed = changed_files_in_commits(repo_path, since_ts)

            test_results[repo_name] = run_test_suite(repo_name, repo_path)

            for entry_file in find_entrypoint_candidates(changed):
                smoke_results.append(smoke_test_entrypoint(repo_path, entry_file, smoke_test_timeout))

        if repos_touched:
            any_failures = any(
                (tr is not None and tr[0] is False) for tr in test_results.values()
            ) or any(not passed for passed, _detail in smoke_results)
            reports.append({
                "task_id": task_id,
                "completed_at": completed_at_unix,
                "repos_touched": repos_touched,
                "test_results": test_results,
                "smoke_test_results": smoke_results,
                "any_failures": any_failures,
            })

        processed[task_id] = completion_ts

    # Use the scan's START time, not its end time, as the new cutoff -- a
    # file modified mid-scan (between this_scan_started_at and now) must
    # still have an mtime >= this_scan_started_at, guaranteeing the NEXT
    # run picks it up rather than silently skipping it forever.
    state["last_scan_ts"] = this_scan_started_at
    save_watcher_state(state, state_path)
    return reports


def format_report(report: dict) -> str:
    lines = [
        f"Task {report['task_id']} completed -- touched: {', '.join(report['repos_touched'])}",
    ]
    for repo_name, result in report["test_results"].items():
        if result is None:
            lines.append(f"  [{repo_name}] tests: no command configured -- not checked")
        else:
            passed, detail = result
            lines.append(f"  [{repo_name}] tests: {'PASS' if passed else 'FAIL'}")
            if not passed:
                lines.append(f"    {detail}")
    for passed, detail in report["smoke_test_results"]:
        lines.append(f"  smoke test: {'PASS' if passed else 'FAIL'} -- {detail}")
    if report["any_failures"]:
        lines.append("  >>> REAL FAILURE FOUND -- this completion claim does not match reality.")
    return "\n".join(lines)


if __name__ == "__main__":
    # --json: machine-readable mode for the Scheduled Task wrapper script --
    # ConvertFrom-Json against a stable structure, not regex against
    # human-readable text. Test-related fields (passed, detail) flattened
    # since plain tuples don't round-trip through json.dumps as anything
    # a caller could index cleanly.
    if "--json" in sys.argv:
        found = check_for_new_completions()
        serializable = []
        for r in found:
            serializable.append({
                "task_id": r["task_id"],
                "completed_at": r["completed_at"],
                "repos_touched": r["repos_touched"],
                "test_results": {
                    name: (None if res is None else {"passed": res[0], "detail": res[1]})
                    for name, res in r["test_results"].items()
                },
                "smoke_test_results": [
                    {"passed": passed, "detail": detail} for passed, detail in r["smoke_test_results"]
                ],
                "any_failures": r["any_failures"],
            })
        print(json.dumps(serializable))
    else:
        found = check_for_new_completions()
        if not found:
            print("No new Cline completions since last check.")
        for r in found:
            print(format_report(r))
            print()
