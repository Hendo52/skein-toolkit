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
# EXCLUDED here: that tier has no tool-calling capability at all (policy S6),
# so it cannot run as a Cline agent regardless of how well-suited it is for
# manual math consultation. Listing it here would be a candidate dispatch_
# coding_task could never actually use.
TIER_MODEL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Tier-R": ("local/qwen2.5-coder:7b", "cf/kimi-k2.6", "local/qwen2.5-coder:32b"),
    "Tier-C": ("claude/sonnet-4", "cf/kimi-k2.6", "local/deepseek-r1:32b"),
    "Tier-M": ("claude/sonnet-4", "local/deepseek-r1:32b", "local/llama3.3:70b"),
}

DEFAULT_LITELLM_BASE_URL = "http://127.0.0.1:4000"
_PROBE_TIMEOUT_SECONDS = 15.0


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
        if await probe_model(model, master_key, base_url):
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
    staleness_threshold_seconds: int = DEFAULT_STALENESS_THRESHOLD_SECONDS,
) -> "str | None":
    """OQ-285: one job at a time per repo. Returns the job_id of a job that
    counts as still occupying repo_root, or None if the repo is free.

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


# ---------------------------------------------------------------------------
# Task prompt construction
# ---------------------------------------------------------------------------


def build_task_prompt(at_id: int, at_row: dict, repo_root_for_paths: str) -> str:
    """Builds a self-contained Cline task prompt from a parsed AT row
    (ledger_io.parse_at_row's return shape), matching the structure used by
    hand throughout this session: CLAUDE.md/conventions reminder, the AT's
    own description/spec references verbatim, scope/exit-evidence as
    explicit acceptance criteria, and the commit-hygiene instruction."""
    return (
        f"Implement AT-{at_id} from {repo_root_for_paths}'s "
        f"architecture-docs/global/ai-task-queue.md.\n\n"
        f"Read CLAUDE.md first (repo root) and follow its conventions: "
        f"TypeScript section, Naming Enforcement Policy, encoding hygiene "
        f"(ASCII-only in source), commit hygiene policy.\n\n"
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
