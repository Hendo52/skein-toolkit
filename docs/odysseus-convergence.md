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
- **Process unknowns (need verification before a real PR):** Odysseus's
  `CONTRIBUTING.md` exists but its DCO/CLA requirements weren't readable via
  the fetch performed for this investigation (GitHub rate-limited a follow-up
  search request). Before opening a PR: read `CONTRIBUTING.md` and
  `ROADMAP.md` directly, confirm whether a CLA/DCO sign-off is required, and
  check the "help wanted" framing the README gives ("fresh-install testing,
  provider setup bugs, mobile/editor polish, docs, and small focused
  refactors") -- a new MCP-server-integration feature may need a
  design-discussion issue first rather than a direct PR.

## (c) Concrete follow-up AT items if convergence is pursued

1. **AT-1152 (Small, exploratory verification):** Stand up `local-mcp.py`
   locally, register it in a local Odysseus instance as
   `McpServer(transport="sse", url="http://127.0.0.1:3100/sse")`, and confirm
   Odysseus's agent loop lists and can call its tools under the
   `mcp__local-mcp__<tool>` namespace. This is the "no/minimal changes"
   hypothesis above turned into an actual test -- currently unverified.
   Depends on AT-1146 (needs a working Docker/Python environment to run both
   projects side by side).

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
   real upstream PR.

4. **AT-1155 (Medium, contingent on AT-1152-1154):** Open a draft PR to
   Odysseus adding `local-mcp.py`/`devserver-mcp.py` as a documented
   "external MCP server" example (registry entry + short doc page), with
   Apache-2.0 attribution added to `ACKNOWLEDGMENTS.md`. This is the actual
   convergence deliverable; everything above is verification and prep.

## Caveats on this investigation

This doc was written from `WebFetch` reads of the upstream repo's README,
`mcp_servers/memory_server.py`, `src/agent_loop.py`, `src/tool_utils.py`, and
`core/database.py` (one fetch per file; a follow-up GitHub code-search request
was rate-limited at HTTP 429 and not retried). The `McpServer` schema and
`mcp__<server>__<tool>` namespacing are read directly from source and are
high-confidence; the `CONTRIBUTING.md`/DCO process is not yet verified (see
AT-1154). No Odysseus code was run -- AT-1152 is the first item that requires
actually exercising the integration.
