# Chat UI Landscape: Open WebUI, LibreChat, and Odysseus (AT-1197)

**Date:** 2026-06-20
**Scope:** Research-only survey of Open WebUI and LibreChat as alternatives to Odysseus for
consuming the Skein toolkit (LiteLLM proxy at `localhost:4000/v1`, MCP SSE server at
`localhost:3100/sse`). No installs performed; evidence drawn from upstream source,
documentation, and prior verified integration work (AT-1151, AT-1196).

---

## 1. LiteLLM proxy compatibility (Q1)

| UI | Connects to `http://localhost:4000/v1`? | How |
|---|---|---|
| **Open WebUI** | **Yes** | Admin Settings → Connections → OpenAI-compatible API. Enter any base URL (e.g. `http://host.docker.internal:4000/v1` when containerised, or `http://localhost:4000/v1` for pip/native installs). Supports custom API keys, multiple OpenAI-compatible backends, and LMStudio/Groq/OpenRouter out of the box. |
| **LibreChat** | **Yes** | `librechat.yaml` → `endpoints.custom` block with `baseURL: "http://localhost:4000/v1"` and optional `apiKey`. Also supports per-endpoint model lists, title generation models, and token-limit overrides. |
| **Odysseus** | **Yes** | Verified working (AT-1151). OpenAI-compatible client path; base URL configurable via UI settings or env fallback. |

**Finding:** All three connect to the LiteLLM proxy without friction. Open WebUI's Docker
default needs `host.docker.internal:4000` or `--network=host`; LibreChat's Docker stack
works the same way. This is table-stakes, not a differentiator.

---

## 2. Skein MCP SSE tool-calling (Q2)

Skein MCP (`local-mcp.py` / `devserver-mcp.py`) exposes **SSE transport** at
`http://127.0.0.1:3100/sse` via `FastMCP(..., port=3100)` + `mcp.sse_app()`.
The question is whether each UI can consume that endpoint **directly during chat
turns** (not via a secondary proxy process).

| UI | Raw SSE MCP at `localhost:3100/sse`? | MCP architecture |
|---|---|---|
| **Open WebUI** | **Indirect only** | MCP support exists but is shaped around **MCPO** (MCP-to-OpenAPI proxy) and **stdio subprocess** servers. Admin UI configures "Tool Servers" with OpenAPI specs or MCP command/args; remote SSE URLs are not a first-class connection type in `TOOL_SERVER_CONNECTIONS` (backend source shows `type: 'openapi'` and `type: 'mcp'` entries, but the MCP path appears to spawn stdio processes rather than opening an SSE stream to a remote URL). GitHub discussions (2025-06) show active community work on external MCP events but no stable SSE-native remote-MCP path. |
| **LibreChat** | **Yes** | First-class MCP with **dynamic server registration**, **request-scoped SSE connections**, and **in-turn tool-calling**. The `librechat.example.yaml` supports `url`, `command`, `args`, and `env` fields per server. `MCP.js` and `ToolService.js` implement OAuth-aware discovery, per-user permission checks (`userCanUseMCPServers`), ephemeral connections, and automatic reinitialisation. LibreChat's agent loop dynamically loads MCP tools into the LangChain tool registry for each chat turn. |
| **Odysseus** | **Yes** | Verified zero-code-change fit (AT-1151). `McpServer(transport="sse", url="http://127.0.0.1:3100/sse")` registry entry; tools namespaced as `mcp__<server>__<tool>`. |

**Finding:** Open WebUI cannot use Skein MCP directly today without an MCPO bridge or a
local stdio wrapper. LibreChat can connect to `localhost:3100/sse` natively and already
has the most sophisticated open-source MCP-in-turn implementation documented.

---

## 3. AT/OQ project-management differentiation (Q3)

Neither Open WebUI nor LibreChat has any equivalent of Skein's **Actionable Tasks / Open
Questions** governance layer, the **multi-step orchestrator**, or the **dispatch pipeline**.

| Capability | Open WebUI | LibreChat | Odysseus (with Skein MCP) |
|---|---|---|---|
| **Task tracking (AT-*)** | None | None | Native: `create_actionable_task`, `resolve_actionable_task`, ledger-backed markdown tables |
| **Open-question governance (OQ-*)** | None | None | Native: `create_open_question`, `resolve_open_question`, bounded-ambiguity escalation in orchestrator |
| **Multi-step dispatch** | None | None | `dispatch_coding_task` + `supervisor_triage.py` + orchestrator resume |
| **Cost accounting / spend review** | LiteLLM proxy can meter; no project-scoped ledger | LiteLLM proxy can meter; no project-scoped ledger | `CF_PROXY_DAILY_REVIEW_THRESHOLD_USD`, `CF_PROXY_MONTHLY_BUDGET_AUD`, architect-led spend review tied to AT/OQ ledger |
| **Agent autonomy** | Hermes Agent / OpenClaw plugins (separate processes) | Built-in Agents + Skills + Subagents (in-turn) | Orchestrator runs autonomous step sequences; Cline handles interactive coding turns |
| **Notes / persistence** | Built-in notes, memories, knowledge bases | Built-in memories, conversation search, file upload | Odysseus Notes API (AT-1153); Skein OQ/task ledgers (`architecture-docs/`-style or Odysseus-native) |

**Finding:** For the AT/OQ project-management use case, Open WebUI and LibreChat are **chat
front-ends only**. They can display model output and call tools, but they do not replace
the governance layer, dispatch pipeline, or cost-accounting integration that Skein
provides. Odysseus + Skein MCP remains the only stack where the UI and the project
ledger are part of the same workflow.

---

## 4. LibreChat features worth contributing or porting to Odysseus (Q4)

LibreChat's MCP-in-turn implementation is the current open-source reference. Specific
features that would improve Odysseus's Skein-MCP client experience if ported upstream
or adapted:

1. **Dynamic MCP server registration (UI, no restart)**  
   LibreChat lets admins add/remove MCP servers via the UI; Odysseus requires a database
   registry edit or restart. A "Add SSE MCP Server" form in Odysseus settings would remove
   the last manual step from Skein-MCP onboarding.

2. **Per-user / per-role MCP access control**  
   LibreChat gates `PermissionTypes.MCP_SERVERS` behind role checks. Odysseus currently
   exposes all registered MCP tools to all users. Scoped access would matter in
   multi-user deployments.

3. **Request-scoped (ephemeral) MCP connections**  
   LibreChat's `requiresEphemeralUserConnection()` pattern opens an SSE connection per
   chat turn and tears it down afterward. Odysseus maintains a persistent connection.
   Ephemeral mode reduces stale-connection bugs when `local-mcp.py` restarts.

4. **Tool discovery without full auth**  
   LibreChat's `discoverServerTools()` lists MCP tools before OAuth completes, showing
   the user what would be available. Useful if Skein MCP ever adds auth layers.

5. **Artifact rendering for tool outputs**  
   LibreChat renders Code Interpreter outputs, file attachments, and structured tool
   results in rich cards. Odysseus tool output is plain text; rich rendering would make
   `run_shell` / `read_file` results more readable.

6. **Skills / reusable instruction bundles**  
   LibreChat Skills are `SKILL.md` files that can be attached to agents. A Skein "Skill"
   could bundle the standard AT/OQ prompt templates (e.g. "write a one-page evaluation
   note") as reusable agent context.

7. **Subagent delegation**  
   LibreChat Agents can delegate to child agents with isolated tool sets. Skein's
   orchestrator already does this procedurally; a UI-native subagent primitive would let
   the architect delegate spot-checks or validation runs without leaving the chat.

---

## 5. Bottom-line comparison

| Criterion | Open WebUI | LibreChat | Odysseus + Skein |
|---|---|---|---|
| **Stars / momentum** | ~142K, dominant | ~39.5K, fastest-growing agent stack | Fork, ~1K (contribution target per OQ-290) |
| **LiteLLM `localhost:4000`** | Yes | Yes | Yes |
| **Raw SSE MCP `localhost:3100/sse`** | No (needs MCPO/stdio bridge) | **Yes** (best-in-class) | Yes |
| **MCP in-turn tool-calling** | Basic (via proxy) | **Rich** (dynamic, OAuth, access control) | Functional (static registry) |
| **AT/OQ governance** | None | None | Unique |
| **Best fit for Skein today** | Chat-only front-end | Best reference for MCP UX improvements | Working integration + project layer |
| **Contribution target** | Low (UI not MCP-native) | **High** (MCP ecosystem, AAIF governance via ClickHouse) | Upstream Odysseus (issue-first, `dev` branch) |

**Recommendation:**

- **If the goal is a better chat UI for casual model access:** either Open WebUI or
  LibreChat works; LibreChat's MCP support makes it the safer long-term bet.
- **If the goal is deep Skein integration (AT/OQ ledger, dispatch pipeline, cost
  review):** Odysseus remains the only UI that sits inside the same workflow. The
  near-term win is to **port LibreChat's dynamic MCP registration, access control,
  and artifact rendering** into Odysseus, not to replace Odysseus with a generic
  chat UI.
- **If the goal is upstream MCP ecosystem contribution:** LibreChat (now ClickHouse-backed)
  is the stronger strategic target than Open WebUI, because its first-class MCP handling
  means new features land where they benefit the most users.

---

## References

- Open WebUI repo & docs: `github.com/open-webui/open-webui`, `docs.openwebui.com`
- LibreChat repo & docs: `github.com/danny-avila/LibreChat`, `docs.librechat.ai`
- Odysseus convergence (AT-1151): `docs/odysseus-convergence.md`
- Goose evaluation (AT-1196): `docs/goose-evaluation.md`
- Skein-Odysseus merge research (AT-1217): `docs/skein-odysseus-merge-research.md`
- LiteLLM proxy config: `mcp-server/litellm_config.yaml`
- Skein MCP server: `mcp-server/local-mcp.py` (SSE on `127.0.0.1:3100/sse`)
