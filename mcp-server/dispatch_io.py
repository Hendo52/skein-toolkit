#!/usr/bin/env python3
"""
dispatch_io.py -- AT-1228. Functions backing dispatch_coding_task /
get_coding_task_status / promote_coding_task (local-mcp.py), split out the
same way ledger_io.py split out the ledger-mutation logic: the highest-stakes
code (spawns real processes, creates/removes git worktrees, decides which
model to use) should be unit-testable without actually spawning a Cline
process or hitting a real LiteLLM endpoint.

Design decisions this module encodes, all resolved in
odysseus-agentic-dispatch-architecture.md (OQ-285..289, CB-23/24/25):
- One job at a time per repo (OQ-285) -- find_busy_job_for_repo.
- Commits land on a dedicated git-worktree branch, never the shared working
  directory's checkout (OQ-286 + the worktree-isolation addendum).
- Job state lives in its own directory, not ~/.cf_proxy_orchestrator/
  (OQ-287), and uses PID-liveness first with a CB-24-style timestamp-
  staleness fallback, exactly mirroring toolchain-doctor.ps1's
  Test-OrchestratorRunActive rather than reinventing it.
- Killing a job tree uses taskkill /F /T, never a single-process kill
  (CB-25) -- see kill_job_process_tree.
- Model selection resolves the AT row's own Model: tier annotation through
  a real LiteLLM probe call, not a hardcoded default -- this session found
  every tier flaky at a different point (Anthropic credit exhaustion, CF
  capacity 429s, a local model hallucinating a tool call), so the dispatch
  tool checks what's actually reachable right now rather than assuming.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from typing import Optional

import httpx
import psutil

# ---------------------------------------------------------------------------
# Model tier resolution
# ---------------------------------------------------------------------------

# AT-1231 settled the Tier-R/C/M vs Level-1/2/3 naming drift by mapping
# Tier-R=Level-1, Tier-C=Level-2, Tier-M=Level-3 rather than renaming either
# document. Candidate lists below are ranked by ai-model-selection-policy.md's
# own tier preference, with cf/kimi-k2.6 included as a real, empirically-
# proven (this session, post CB-23 fix) fallback that predates the policy
# document and isn't named in it.
#
# Tier-M's first listed Local-Reason option (phi4-reasoning) is deliberately
# EXCLUDED here: that tier has no tool-calling capability at all (policy
# S6/S8.1), so it cannot run as a Cline agent regardless of how well-suited
# it is for manual math consultation. Listing it here would be a candidate
# dispatch_coding_task could never actually use.
#
# Tier-R's first candidate is NOT local/qwen2.5-coder:7b, for the identical
# reason -- ai-model-selection-policy.md S8.1 already documents it directly:
# "intercepted by Continue but model stops generating after tool call JSON;
# agent loop does not complete. Works as a chat model but not as an agent."
# dispatch_coding_task is ALWAYS a full agentic Cline session (never a bare
# completion), so this finding applies here exactly as it does to Tier-M's
# exclusion above -- it just wasn't cross-referenced when this list was
# first written. Confirmed again directly, 2026-06-20 (AT-1196): dispatched
# for real, probed reachable, ran 64.9s exit 0, produced a hand-rolled JSON
# blob inventing a fake tool ("eval_goose") instead of any real tool call --
# zero files written, zero commits. cf/kimi-k2.6 retried the identical task
# and made real tool calls throughout. qwen2.5-coder:7b stays listed (last)
# for the rare case every agentic candidate is unreachable -- something is
# better than an outright dispatch failure -- but is never tried first.
#
# local/qwen3.6 added 2026-06-20 (same tier review): already pulled (23GB,
# litellm_config.yaml already lists it as "Best local general model...
# tools") but had never been added as a dispatch candidate anywhere despite
# being a better-suited local option than qwen2.5-coder for agentic work --
# simply never wired in. Placed ahead of the qwen2.5-coder variants as the
# preferred local-only fallback; cf/kimi-k2.6 still tried first since it's
# the only candidate with confirmed-reliable real-world agentic runs today.
TIER_MODEL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Tier-R": ("cf/kimi-k2.6", "local/qwen3.6", "local/qwen2.5-coder:32b", "local/qwen2.5-coder:7b"),
    "Tier-C": ("claude/sonnet-4", "cf/kimi-k2.6", "local/deepseek-r1:32b"),
    "Tier-M": ("claude/sonnet-4", "local/deepseek-r1:32b", "local/llama3.3:70b"),
}

DEFAULT_LITELLM_BASE_URL = "http://127.0.0.1:4000"
_PROBE_TIMEOUT_SECONDS = 15.0

# Real incident, 2026-06-20 (AT-1197 dispatch attempt): every local/*
# candidate in a tier was marked unreachable by resolve_model_for_tier, even
# though each one worked fine seconds later. Root cause confirmed directly:
# Ollama unloads idle models (default keep_alive ~5min) and a cold reload of
# a 12-23GB model on this machine's partial-GPU-offload hardware (RTX 3070,
# 8GB VRAM + 64GB RAM -- ai-model-selection-policy.md S4.2) genuinely takes
# well over 15s -- confirmed: qwen3.6 timed out at 20s but succeeded within
# 120s. A cloud model (cf/kimi-k2.6) has no equivalent cold-start cost and
# should still fail fast on a real outage, so it keeps the short timeout;
# local models get a generous one instead of being misdiagnosed as down.
_LOCAL_PROBE_TIMEOUT_SECONDS = 90.0


def load_litellm_master_key(skein_mcp_server_dir: str) -> str:
    """Reads LITELLM_MASTER_KEY from the process environment first (the
    normal case once a caller has exported it), falling back to parsing
    mcp-server/litellm.env directly -- local-mcp.py is a separate process
    from LiteLLM itself and does not load that file at startup, but it is
    the established source of truth other scripts (start-litellm.ps1) read
    from. Returns "" (not a guessed default) if neither source has it --
    callers must treat that as "cannot probe any model," not silently skip
    auth."""
    env_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if env_key:
        return env_key
    env_file = os.path.join(skein_mcp_server_dir, "litellm.env")
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("LITELLM_MASTER_KEY="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""


async def probe_model(
    model: str,
    master_key: str,
    base_url: str = DEFAULT_LITELLM_BASE_URL,
    timeout: float = _PROBE_TIMEOUT_SECONDS,
) -> bool:
    """A minimal, real LiteLLM chat-completion call -- the same kind of probe
    used manually this session before each Cline dispatch attempt. Returns
    True only on a clean 200 with no error field; False on any non-200,
    timeout, or connection failure. Deliberately does not distinguish WHY a
    model failed (429 vs missing key vs no credit) -- resolve_model_for_tier
    only needs "is this one usable right now," not a full diagnosis; that's
    toolchain-doctor.ps1's job, not this function's."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "reply with just the word ok"}], "max_tokens": 5},
            )
    except (httpx.TimeoutException, httpx.ConnectError):
        return False
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
    except Exception:
        return False
    return "error" not in data and bool(data.get("choices"))


async def resolve_model_for_tier(
    tier: str,
    master_key: str,
    base_url: str = DEFAULT_LITELLM_BASE_URL,
) -> "tuple[str | None, list[str]]":
    """Tries each of tier's candidates in ranked order via a real probe,
    returning the first that responds successfully. Returns (None, attempted)
    if every candidate failed or the tier is unrecognized -- the caller must
    surface this as a real failure (per the Validator-at-the-Boundary policy),
    not silently fall through to some other tier's model."""
    candidates = TIER_MODEL_CANDIDATES.get(tier, ())
    attempted: list[str] = []
    for model in candidates:
        attempted.append(model)
        timeout = _LOCAL_PROBE_TIMEOUT_SECONDS if model.startswith("local/") else _PROBE_TIMEOUT_SECONDS
        if await probe_model(model, master_key, base_url, timeout=timeout):
            return model, attempted
    return None, attempted


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------

# CB-24-style staleness threshold: a single orchestrator step's own dispatch
# timeout is well under 10 minutes; coding-task jobs run far longer (this
# session observed 200-1200+ seconds for a single AT), so this threshold is
# generous on purpose -- only reclaim a job whose state file genuinely
# stopped updating, not one that's legitimately still working.
DEFAULT_STALENESS_THRESHOLD_SECONDS = 3600


def job_state_path(state_dir: str, job_id: str) -> str:
    return os.path.join(state_dir, f"{job_id}.json")


def write_job_state(state_dir: str, job_id: str, state: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    path = job_state_path(state_dir, job_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, path)  # atomic on both POSIX and Windows


def read_job_state(state_dir: str, job_id: str) -> "dict | None":
    path = job_state_path(state_dir, job_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_job_states(state_dir: str) -> "list[dict]":
    """All job states in state_dir, each annotated with its own job_id
    (derived from the filename, not trusted from file content alone --
    a state dict with no "job_id" field, or a mismatched one, still gets
    indexed correctly by this function)."""
    if not os.path.isdir(state_dir):
        return []
    results = []
    for name in os.listdir(state_dir):
        if not name.endswith(".json") or name.endswith(".tmp"):
            continue
        job_id = name[: -len(".json")]
        state = read_job_state(state_dir, job_id)
        if state is not None:
            results.append({**state, "job_id": job_id})
    return results


def is_pid_alive(pid: "int | None") -> bool:
    if pid is None:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def find_busy_job_for_repo(
    state_dir: str,
    repo_root: str,
    at_id: "int | None" = None,
    staleness_threshold_seconds: int = DEFAULT_STALENESS_THRESHOLD_SECONDS,
) -> "str | None":
    """OQ-285 (2026-06-18) originally serialized to one job at a time per
    repo. Relaxed 2026-06-20 (agent-harness-reliability-standard.md tier
    review, architect-requested parallel-dispatch experiment) to one job at
    a time per (repo, AT-id) pair instead: verified directly that concurrent
    `git worktree add` against the same repo is safe (two simultaneous
    calls, `git fsck --full` clean afterward -- git's own internal locking
    serializes the metadata write, it does not race-corrupt), and every
    job's worktree path and branch name are already derived from at_id
    (dispatch_branch_name), so two different AT-ids can never collide on a
    path or branch even running at the same instant. The real, still-
    enforced collision risk is dispatching the SAME AT-id twice
    concurrently -- that WOULD collide on both the worktree path and the
    branch name -- so at_id is now part of the busy-check key. Passing
    at_id=None preserves the original whole-repo serialization (used by any
    caller not yet updated to pass it).

    A job counts as busy if its status is "running" AND EITHER its recorded
    PID is still alive OR (PID check inconclusive -- missing/dead PID but
    no staleness signal either) its last-updated timestamp is within the
    staleness window. PID-liveness is checked first and is authoritative
    when conclusive: a confirmed-dead PID with a "running" status is treated
    as a crashed job (free), not blocked on the staleness window -- this is
    the resolved 2026-06-18 design (PID-liveness primary, timestamp
    fallback), not the original CB-24-only approach."""
    now = time.time()
    for state in list_job_states(state_dir):
        if state.get("status") != "running":
            continue
        if os.path.normcase(os.path.normpath(state.get("repo_root", ""))) != os.path.normcase(os.path.normpath(repo_root)):
            continue
        if at_id is not None and state.get("at_id") != at_id:
            continue
        pid = state.get("pid")
        if pid is not None:
            if is_pid_alive(pid):
                return state["job_id"]
            continue  # PID recorded and confirmed dead -> crashed, not busy
        updated_at = state.get("updated_at")
        if updated_at is not None and (now - updated_at) < staleness_threshold_seconds:
            return state["job_id"]
    return None


def new_job_id(at_id: int) -> str:
    return f"at{at_id}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def is_working_tree_clean(repo_root: str) -> "tuple[bool, str]":
    """Returns (True, "") if `git status --porcelain` is empty, else
    (False, <porcelain output>) so the caller can report exactly what's
    dirty rather than a bare boolean (validator-at-the-boundary: reject with
    a specific reason, don't just refuse)."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout.strip()
    return (output == "", output)


def dispatch_branch_name(at_id: int) -> str:
    return f"at-{at_id}-dispatch"


def create_worktree(repo_root: str, worktree_path: str, branch_name: str) -> "tuple[bool, str]":
    """git worktree add <worktree_path> -b <branch_name>, run from repo_root.
    Returns (True, "") on success, (False, stderr) on failure -- e.g. the
    branch already exists from a prior failed attempt at the same AT."""
    result = subprocess.run(
        ["git", "worktree", "add", worktree_path, "-b", branch_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def remove_worktree(repo_root: str, worktree_path: str, force: bool = False) -> "tuple[bool, str]":
    args = ["git", "worktree", "remove", worktree_path]
    if force:
        args.append("--force")
    result = subprocess.run(args, cwd=repo_root, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


# ---------------------------------------------------------------------------
# Cline process spawn
# ---------------------------------------------------------------------------


def spawn_cline_process(
    run_cline_script: str,
    repo_root: str,
    model: str,
    task_prompt: str,
    timeout_sec: int,
    log_file,
    cwd: str,
) -> subprocess.Popen:
    """The one and only subprocess.Popen call site for a dispatched job --
    kept in its own function (not inlined at the call site in local-mcp.py)
    specifically so tests can mock this one function instead of
    subprocess.Popen itself. Mocking subprocess.Popen directly breaks
    subprocess.run too (CPython's subprocess.run is implemented via Popen
    internally, and they're the same shared module-level symbol) -- found
    while writing this module's own test suite: a test that mocked
    subprocess.Popen to avoid spawning a real Cline process also corrupted
    every git status/git worktree subprocess.run call made during the same
    test, with a confusing unrelated-looking "not enough values to unpack"
    error. Returns a non-blocking, already-started process (run-cline.ps1's
    own toolchain-doctor preflight and Cline invocation happen in that
    spawned process, not here)."""
    return subprocess.Popen(
        [
            # pwsh (PowerShell 7+), not the legacy `powershell` (5.1): found
            # 2026-06-18 during this AT's own smoke test -- toolchain-
            # doctor.ps1 (run-cline.ps1's own preflight) uses PowerShell-7-
            # only syntax (the `?.` null-conditional operator), so invoking
            # it via 5.1 fails with a parser error before anything real
            # runs. -ExecutionPolicy Bypass: a bare invocation spawned via
            # subprocess.Popen otherwise fails with "running scripts is
            # disabled on this system" (UnauthorizedAccess), even though the
            # same script runs fine through an interactive session -- a
            # per-process flag, not a persistent system-wide change.
            "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", run_cline_script,
            "-RepoRoot", repo_root,
            "-Model", model,
            "-Task", task_prompt,
            "-TimeoutSec", str(timeout_sec),
            "-AutoApprove",
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# Process tree kill (CB-25)
# ---------------------------------------------------------------------------


def kill_job_process_tree(pid: int) -> bool:
    """taskkill /F /T /PID -- kills the whole process tree, not just the
    immediate child. CB-25 (2026-06-18): a single-process kill on the
    PowerShell wrapper running `type file | npx cline ...` leaves the real
    cline.exe running downstream in the pipeline as an orphan -- confirmed
    live in this session, not hypothetical. Returns True if taskkill exited
    0 (it exits non-zero if the PID is already gone, which is fine -- the
    job is dead either way, so this returns True for "not alive anymore"
    rather than surfacing taskkill's own exit code as an error)."""
    result = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 or not is_pid_alive(pid)



def kill_orphaned_worktree_processes(worktree_path: str) -> "list[int]":
    """AT-1249 / REQ-6 / TOOL-3: command-line-match cleanup for orphaned
    processes whose wrapper parent has already exited.

    Background (2026-06-20, AT-1196 dispatch saga): a PowerShell wrapper
    script reporting 'Completed... exit 0' does not guarantee its child
    cline.exe process actually exited -- twice in that session an orphaned
    cline.exe survived its wrapper, holding a file lock on the job's
    worktree. kill_job_process_tree's PID-tree kill cannot catch this case:
    by the time a job transitions to terminal the intermediate parent (the
    wrapper) has already exited and its children have been re-parented under
    a new parent outside the original PID tree. A tree-rooted kill can no
    longer reach them.

    This function fixes the gap by searching ALL running processes for any
    whose command-line arguments reference worktree_path (normalized to
    lower-case, forward-slash form for cross-platform robustness), and
    killing each one with SIGKILL (Windows: TerminateProcess via
    psutil.Process.kill()). It skips the current process and any process
    for which it cannot obtain a command line (AccessDenied, NoSuchProcess).

    Returns a list of PIDs that were successfully killed (for the caller to
    log). An empty list means no orphans were found -- the normal case.

    Called by get_coding_task_status (local-mcp.py) immediately after a
    job transitions to a terminal state (complete or failed)."""
    if not worktree_path:
        return []
    # Normalize once; compare lower-case to lower-case to handle Windows
    # case-insensitive paths and mixed forward/back-slash representations.
    needle = worktree_path.replace("\\", "/").lower()
    my_pid = os.getpid()
    killed: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = proc.info["pid"]
            if pid == my_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            # cmdline is a list of argument strings; check each one.
            if any(needle in arg.replace("\\", "/").lower() for arg in cmdline):
                proc.kill()
                killed.append(pid)
                print(
                    f"[dispatch_io] REQ-6: killed orphaned process PID={pid} "
                    f"whose cmdline referenced worktree {worktree_path!r}",
                    file=sys.stderr,
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process gone between iteration and kill, or insufficient
            # permissions -- either way it is not our job to kill, skip.
            continue
    return killed


# ---------------------------------------------------------------------------
# Promote / merge (AT-1230)
# ---------------------------------------------------------------------------


def get_default_branch(repo_root: str) -> "tuple[str, str]":
    """Returns (branch_name, error_message). branch_name is the HEAD branch
    of the main working tree (i.e. whatever the original repo root currently
    has checked out -- the one that was current when dispatch_coding_task ran).
    Uses git symbolic-ref --short HEAD; falls back to rev-parse --abbrev-ref
    HEAD for detached-HEAD cases. Returns ("", error) if both fail."""
    for args in (
        ["git", "symbolic-ref", "--short", "HEAD"],
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    ):
        try:
            result = subprocess.run(
                args, cwd=repo_root, capture_output=True, text=True, timeout=15
            )
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch, ""
        except Exception:
            pass
    return "", "could not determine default branch (is the repo in detached HEAD state?)"


def merge_branch_into_default(
    repo_root: str,
    branch_name: str,
    default_branch: str,
) -> "tuple[bool, str]":
    """Fast-forward the dispatch branch into default_branch inside the
    MAIN working tree (repo_root, not the worktree). Steps:
      1. git checkout <default_branch>   -- switch the main worktree to target
      2. git merge --ff-only <branch_name>  -- fast-forward only (the dispatch
         worktree commits stack cleanly on top of the point it branched from,
         so a fast-forward is always correct here; if it fails that means
         something committed to the default branch concurrently, which is a
         genuine conflict worth surfacing rather than auto-resolving)
    Returns (True, merge_output) on success, (False, error_message) on any
    failure -- the caller must surface failures clearly, not swallow them."""
    # Step 1: switch the main worktree to the target branch.
    co_result = subprocess.run(
        ["git", "checkout", default_branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if co_result.returncode != 0:
        return False, f"git checkout {default_branch} failed: {co_result.stderr.strip()}"

    # Step 2: fast-forward merge.
    merge_result = subprocess.run(
        ["git", "merge", "--ff-only", branch_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if merge_result.returncode != 0:
        return False, (
            f"git merge --ff-only {branch_name} failed: "
            f"{merge_result.stderr.strip() or merge_result.stdout.strip()}"
        )
    return True, merge_result.stdout.strip() or merge_result.stderr.strip()


def delete_local_branch(repo_root: str, branch_name: str) -> "tuple[bool, str]":
    """git branch -d <branch_name> -- deletes the local branch after merge.
    Uses -d (safe delete, refuses if not merged) rather than -D (force);
    promote_coding_task calls this AFTER a successful merge, so -d is always
    safe: the branch IS merged. Returns (True, "") on success,
    (False, stderr) on failure -- a stale branch left behind after a
    successful merge is annoying but not a blocker, so callers log and
    continue rather than treating it as a hard error."""
    result = subprocess.run(
        ["git", "branch", "-d", branch_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


# ---------------------------------------------------------------------------
# Task prompt construction
# ---------------------------------------------------------------------------


def build_task_prompt(at_id: int, at_row: dict, repo_root_for_paths: str) -> str:
    """Builds a self-contained Cline task prompt from a parsed AT row
    (ledger_io.parse_at_row's return shape): CLAUDE.md/conventions reminder,
    the AT's own description/spec references verbatim, scope/exit-evidence
    as explicit acceptance criteria, and the commit-hygiene instruction.

    Real incident (2026-06-20, AT-1196 dispatched into skein-toolkit): the
    prior wording named a specific ai-task-queue.md path inside whichever
    repo the work happens to target, and asserted Electron-Splines-specific
    CLAUDE.md section names (e.g. "TypeScript section") unconditionally --
    both false when the dispatch target isn't Electron-Splines. The model
    burned several tool calls hunting across sibling repos for files that
    don't exist at the asserted path. Fix: don't tell the model to go reread
    the ledger at all (the description/spec/exit-evidence below are already
    the full extracted content, no re-read needed), and word the CLAUDE.md
    instruction generically rather than naming specific sections."""
    return (
        f"You are implementing AT-{at_id} (full description below -- this "
        f"is already the complete extracted task, no need to re-read any "
        f"ai-task-queue.md file).\n\n"
        f"Read this repo's CLAUDE.md in its root, if one exists, and follow "
        f"its conventions before making changes.\n\n"
        f"Task:\n{at_row['description']}\n\n"
        f"Spec / Issue references: {at_row['spec_issue']}\n\n"
        f"Exit evidence required (treat as acceptance criteria): "
        f"{at_row['exit_evidence']}\n\n"
        f"When finished and the exit evidence is satisfied: stage only the "
        f"files this task touches, then commit with a message starting "
        f"with a conventional prefix (feat:/fix:/docs:/test:) that "
        f"references AT-{at_id} in the body. Follow the repo's "
        f"one-commit-per-issue convention."
    )
