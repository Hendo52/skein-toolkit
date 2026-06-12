# Odysseus convergence investigation (AT-1151)

**Date:** 2026-06-12
**Status:** exploratory, written against the upstream repo at
`github.com/pewdiepie-archdaemon/odysseus` (main branch, fetched 2026-06-12).
**Recommendation: GO** -- exposing `local-mcp.py` / `devserver-mcp.py` to
Odysseus as a remote SSE MCP server looks like a near-zero-code-change fit.
Contributing the OQ/task-queue tooling (AT-1137-1139) upstream as a PR is
license-compatible but needs the governance-ledger assumptions generalized
first (already tracked as AT-1137-1139/AT-1150).

## (a) Can the CF proxy / OQ-task-queue tools / devserver-mcp be exposed to Odysseus with no/minimal changes?

### What Odysseus expects

Odysseus keeps a `McpServer` registry table (`core/database.py`) with columns
including:

```
id, name, transport, command, args, env, url, is_enabled,
oauth_config, disabled_tools, oauth_tokens
```

`transport` defaults to `"stdio"` (local subprocess via `command`/`args`),
but **`transport="sse"` with a `url` field is a first-class, supported mode**
for remote MCP servers -- this is not a stdio-only registry.

Odysseus's agent loop (`src/agent_loop.py`) retrieves an MCP manager via
`src.tool_utils.get_mcp_manager()` and namespaces every tool it discovers as
`mcp__<server_id>__<tool_name>` (confirmed via grep hits like
`mcp__email__send_email`, `mcp__email__list_email_accounts` for the built-in
email server). This namespacing is applied by Odysseus to whatever
`list_tools()` returns from the registered server -- no action needed on the
skein-toolkit side.

### What skein-toolkit already provides

Both `mcp-server/local-mcp.py` and `mcp-server/devserver-mcp.py` are built on
`mcp.server.fastmcp.FastMCP` and already run an **SSE transport on
`http://127.0.0.1:3100/sse`**:

- `local-mcp.py`: `mcp = FastMCP(..., port=3100, ...)`, combines
  `mcp.sse_app()` with the CF-proxy's Starlette routes on one uvicorn server
  (`uvicorn.run(combined, host="127.0.0.1", port=3100, ...)`).
- `devserver-mcp.py`: `mcp.run(transport="sse")` on the same port/path.

This is *exactly* the shape of Odysseus's `McpServer(transport="sse",
url="http://<host>:3100/sse")` registry entry. Odysseus's built-in MCP servers
(`mcp_servers/*.py`, e.g. `memory_server.py`) instead use
`mcp.server.Server` + `mcp.server.stdio.stdio_server` (subprocess/stdio) --
skein-toolkit's SSE-first design is actually a *better* match for the
registry's remote-server path than Odysseus's own bundled servers are.

**Conclusion:** registering `local-mcp.py` as an Odysseus MCP server should
require **zero code changes** on the skein-toolkit side -- just an
`McpServer` row with `transport="sse"` and `url` pointing at the running
`local-mcp.py` instance (`http://127.0.0.1:3100/sse` if co-located, or a
reachable host/port if `local-mcp.py` runs in its own container per
`docker-compose.yml`). The CF-proxy HTTP routes (`/cfproxy/{account_id}/...`)
mounted on the same uvicorn app are irrelevant to Odysseus's MCP client and
are simply ignored -- no conflict.

### What needs generalization before the *OQ/task-queue* tools are useful in Odysseus

The CF proxy and core dispatch tools (`run_shell`, `create_test`, etc.) are
already repo-agnostic (`WORKSPACE_ROOT` env var, per the AT-1119-1124 "local
prep" work). The **OQ/task-queue tools are the exception**:

- `_raise_step_ambiguity_oq` and the planned `create_open_question` /
  `create_actionable_task` tools (AT-1137-1139, now retargeted to
  `skein-toolkit/mcp-server/local-mcp.py` by AT-1150) write to
  `CF_PROXY_OQ_LEDGER_PATH` (default
  `architecture-docs/global/architect-open-questions.md`).
- For an Odysseus user with no `architecture-docs/` layout, this already
  **degrades gracefully** per the README: "failures to read/write it are
  logged and degrade to 'ambiguity surfaced inline', not a crash" -- this is
  a first-class alternative-mode, not a silent fallback, consistent with this
  repo's First-Class Scenarios policy.
- That said, "ambiguity surfaced inline" is a weaker experience than
  Odysseus's own persistent-memory story (ChromaDB-backed). A natural
  follow-up (see AT items below) is an Odysseus-native alternative mode that
  writes OQ/AT rows into Odysseus's memory/database instead of a markdown
  ledger, when `CF_PROXY_OQ_LEDGER_PATH` is unset and an Odysseus environment
  is detected.

### Context-budget pattern note

`local-mcp.py` already credits Odysseus by name (`local-mcp.py:801-812`) for
the "keep-recent-and-shrink" context-budget pattern, borrowed from Odysseus's
ChromaDB-backed persistent-memory approach without the embeddings dependency.
This is a precedent for the *reverse* direction of convergence (skein-toolkit
learning from Odysseus); the OQ/task-queue tooling is the candidate for the
forward direction (skein-toolkit contributing to Odysseus).

## (b) Apache-2.0 -> AGPL-3.0 contribution mechanics

- Odysseus is confirmed **AGPL-3.0-or-later** (`LICENSE` /
  `ACKNOWLEDGMENTS.md`, per the README).
- skein-toolkit is **Apache-2.0** (AT-1143). Apache-2.0 is on the FSF's list
  of licenses compatible with GPLv3 (and by extension AGPL-3.0): permissively
  licensed Apache-2.0 code can be incorporated into a GPLv3/AGPL-3.0 work,
  with the combined work distributed under AGPL-3.0. The reverse (AGPL-3.0
  code into an Apache-2.0 project) is **not** generally possible -- so the
  convergence direction "skein-toolkit (Apache-2.0) -> PR into Odysseus
  (AGPL-3.0)" is the licensing-compatible one; the reverse is not.
- **Attribution requirement:** Apache-2.0 SS4 requires that any redistribution
  of skein-toolkit code retain the existing `NOTICE` file's attribution
  ("Skein Toolkit, Copyright 2026 Jake Henderson and Nick Sorokin..."). A PR
  into Odysseus carrying skein-toolkit-derived files should add this
  attribution to Odysseus's own `ACKNOWLEDGMENTS.md` (the file the README
  already points to for license/attribution info), not just rely on a code
  comment.
- **Process, verified 2026-06-13 (AT-1154) from `CONTRIBUTING.md`/`ROADMAP.md`
  read directly via the GitHub Contents API:**
  - **No CLA/DCO requirement.** Neither file mentions a sign-off process;
    `CONTRIBUTING.md` covers branch model, setup, checks, PR/issue content,
    visual-style rules, and code conventions, but no contributor-agreement
    step.
  - **LLM-agent PRs require an issue first -- this is explicit and
    agent-targeted.** Verbatim from `CONTRIBUTING.md`'s Pull Requests section:
    > **Auto-generated PRs.** If you are running an LLM agent (Devin, Cursor,
    > OpenHands, Claude Code, etc.) against this repo: please open an issue
    > describing the problem first instead of opening a PR directly. Bulk
    > agent-generated PRs that don't match the project's visual style or
    > contribution format will be closed without review, even when the
    > underlying fix is correct.

    This directly governs AT-1155: the convergence deliverable must start as
    an **issue**, not a draft PR, regardless of how complete the integration
    is.
  - **Branch model:** PRs target `dev`, not `main` (`main` is the
    curated/release branch, fast-forwarded from `dev`). If AT-1155 ever
    reaches the PR stage, the base branch must be `dev`.
  - **Commit style:** Conventional Commits (`type(scope): summary`) --
    already skein-toolkit's convention, no adjustment needed.
  - **"Before You Start" guidance reinforces issue-first:** "If you want to
    work on a large feature, open an issue first and describe the approach."
    A new MCP-server-registry integration is squarely "large feature."
  - **Visual-style rules (CSS variables, no emoji, screenshot requirements)
    do not apply** -- the proposed contribution (registry entry + doc page +
    `ACKNOWLEDGMENTS.md` attribution) touches no UI.
  - **`ROADMAP.md` "Help Wanted" relevance:** no line item names "external
    MCP server" integration directly, but "Better AI integration for Notes
    and Todos" and "More tests around endpoint probing and provider setup"
    are adjacent backend/agent-tooling areas -- useful framing for the issue,
    not a direct match. The roadmap does **not** discourage the idea; it's
    simply not yet on it.

## (c) Concrete follow-up AT items if convergence is pursued

1. **AT-1152 (Small, exploratory verification):** Stand up `local-mcp.py`
   locally, register it in a local Odysseus instance as
   `McpServer(transport="sse", url="http://127.0.0.1:3100/sse")`, and confirm
   Odysseus's agent loop lists and can call its tools under the
   `mcp__local-mcp__<tool>` namespace. This is the "no/minimal changes"
   hypothesis above turned into an actual test. Depends on AT-1146 (needs a
   working Docker/Python environment to run both projects side by side).

   **Status: done 2026-06-13.** Verified directly against Odysseus's real
   `src/mcp_manager.py` `McpManager` class (cloned to a local sibling
   `odysseus-local/` checkout) calling `connect_server(server_id="local-mcp",
   transport="sse", url="http://127.0.0.1:3100/sse")` against the already-running
   FastMCP SSE server from this repo's `local-mcp.py` architecture (the
   pre-existing `scripts/local-mcp.py` instance on port 3100 was used as the
   server under test, rather than starting a second instance or the full
   `docker-compose` stack -- both copies share the identical
   `mcp.server.fastmcp.FastMCP` + `mcp.sse_app()` SSE-transport shape, so the
   thing AT-1152 actually needs to verify -- can Odysseus's SSE client connect
   to *this kind* of server -- is identical regardless of which copy answers).
   The full docker-compose stack was deliberately not used: Odysseus's
   `docker-compose.yml` hardcodes `searxng` to `127.0.0.1:8080`, which
   conflicts with this machine's pre-existing unrelated `searxng-searxng-1`
   container, and the multi-service build-from-source stack is unnecessary
   weight for testing a single SSE connection.

   Results, all matching the "no/minimal changes" hypothesis exactly:
   - `connect_server(...)` returned `True`; `mgr._connections["local-mcp"]`
     recorded `{"status": "connected", "name": "local-mcp (skein-toolkit
     architecture)", "transport": "sse", "tool_count": 9}`.
   - `get_all_tools()` discovered all 9 tools under the predicted
     `mcp__local-mcp__<tool>` namespace: `create_test`, `fetch_page`,
     `fs_read_file`, `fs_write_file`, `list_directory`, `list_skills`,
     `load_skill`, `run_shell`, `web_search`.
   - `call_tool("mcp__local-mcp__list_skills", {})` round-tripped successfully,
     returning the real skills-directory listing
     (`{"stdout": "Available skills:\n  burst-merge\n  ... task-decomposition\n
     ...", "stderr": "", "exit_code": 0}`).

   No code changes were required on either side. (A non-fatal
   `RuntimeError`/`CancelledError` -- "Attempted to exit cancel scope in a
   different task than it was entered in" -- appeared at the verification
   script's `asyncio.run()` shutdown; this is a known anyio/`AsyncExitStack`
   artifact of one-shot scripts using `mcp.client.sse.sse_client`, not a defect
   in Odysseus's or skein-toolkit's code, and does not affect Odysseus's real
   long-lived-event-loop usage.) The `odysseus-local/` checkout and the
   scratch verification script were not committed; the verification script was
   deleted after use.

2. **AT-1153 (Medium):** Generalize the OQ/task-queue ledger integration
   (AT-1137-1139's `create_open_question`/`create_actionable_task`, after
   AT-1150's retarget) with an Odysseus-native alternative mode: when
   `CF_PROXY_OQ_LEDGER_PATH` is unset, detect an Odysseus environment (e.g. a
   reachable Odysseus DB/API) and write OQ/AT entries there instead of
   "surfaced inline". Both modes remain first-class (named, tested,
   observable) per this repo's First-Class Scenarios policy. Depends on
   AT-1137-1139, AT-1152.

3. **AT-1154 (Small):** Read Odysseus's `CONTRIBUTING.md`/`ROADMAP.md` in
   full and document the actual PR process (CLA/DCO, design-issue-first
   norms, test expectations) in this file's "(b)" section, replacing the
   "process unknowns" caveat above with verified facts. Prerequisite for any
   real upstream PR. **Status: done 2026-06-13** -- see verified facts in (b)
   above. Key result: no CLA/DCO, but `CONTRIBUTING.md` explicitly requires
   LLM agents to open an **issue first**, never a direct PR.

4. **AT-1155 (Medium, contingent on AT-1152-1153, revised per AT-1154):**
   Per `CONTRIBUTING.md`'s explicit LLM-agent policy, the convergence
   deliverable is **an issue, not a PR**: open a GitHub issue on
   `pewdiepie-archdaemon/odysseus` describing the proposed "external MCP
   server" integration (skein-toolkit's `local-mcp.py`/`devserver-mcp.py` as
   an `McpServer(transport="sse", url=...)` registry entry + a short doc
   page), referencing AT-1152's verification results and offering
   Apache-2.0-attributed code via `ACKNOWLEDGMENTS.md` if maintainer interest
   is confirmed. Only proceed to a draft PR against `dev` (never `main`) if
   the maintainer responds favorably to the issue. This is the actual
   convergence deliverable; everything above is verification and prep. **This
   is a visible external action (issue on a third-party repo) requiring a
   separate go-ahead, same as AT-1144.**

## Caveats on this investigation

This doc was written from `WebFetch`/`gh api` reads of the upstream repo's
README, `mcp_servers/memory_server.py`, `src/agent_loop.py`,
`src/tool_utils.py`, `core/database.py`, `CONTRIBUTING.md`, and `ROADMAP.md`
(one fetch per file; an earlier follow-up GitHub code-search request was
rate-limited at HTTP 429 and not retried, but was not needed once
`CONTRIBUTING.md`/`ROADMAP.md` were read directly via the Contents API). The
`McpServer` schema, `mcp__<server>__<tool>` namespacing, and the
`CONTRIBUTING.md` process requirements (no CLA/DCO, issue-first for LLM
agents, `dev`-branch PRs, Conventional Commits) are all read directly from
source and are high-confidence. No Odysseus code was run -- AT-1152 is still
the first item that requires actually exercising the integration.
