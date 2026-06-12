# LLM Toolkit (standalone)

A repo-agnostic clone of the AI development toolchain originally built inside
Electron-Splines: a Cloudflare Workers AI proxy, a multi-step task orchestrator,
and a local agentic MCP server, fronted by a unified LiteLLM proxy.

This repo is the result of the "LLM Tech Stack Standalone Repository" spin-off
(see `architecture-docs/global/ai-task-queue.md`, AT-1116-1139, in the
Electron-Splines repo for the full task history and rationale). Further
refinement of this agentic system happens here, not in Electron-Splines.

## What's in here

| Path | Purpose |
|------|---------|
| `mcp-server/local-mcp.py` | The core: a local MCP SSE server (port 3100) that also proxies/instruments Cloudflare Workers AI requests at `/cfproxy/{account_id}/...`, including a multi-step task orchestrator with bounded-ambiguity escalation. |
| `mcp-server/devserver-mcp.py` | A lighter MCP server variant for a remote GPU devserver. |
| `mcp-server/litellm_config.yaml` + `litellm.env.example` | LiteLLM unified proxy config routing local/CF/Groq/DeepSeek/Anthropic/OpenAI models. |
| `mcp-server/run-cline.ps1`, `resume-orchestrator-run.ps1`, `toolchain-doctor.ps1`, `start-litellm.ps1` | Launcher/diagnostic scripts for running Cline against this stack on Windows. |
| `cloudflare/README.md` | Cloudflare Workers AI configuration (env-var only -- no zone/firewall config). |
| `docker-compose.yml`, `docker-compose.override.yml`, `docker/` | Containerized mcp-server + LiteLLM stack. |

## Quick start (local, Windows)

1. Create a Python virtualenv at the repo root and install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\pip install -r mcp-server\requirements.txt
   ```
2. Copy `mcp-server\litellm.env.example` to `mcp-server\litellm.env` and fill
   in your API keys (see `cloudflare/README.md` for the Cloudflare token).
3. Run `mcp-server\toolchain-doctor.ps1` to diagnose and (where possible)
   auto-start LiteLLM and local-mcp.py.
4. Run `mcp-server\run-cline.ps1 -Task "..."` to launch Cline against the
   configured model.

By default, `local-mcp.py` operates on the parent of the `mcp-server/`
directory (i.e. this repo's checkout). Set `WORKSPACE_ROOT` to point it at a
different project checkout instead.

## Quick start (Docker)

```bash
cp docker/.env.example docker/.env   # fill in API keys
docker compose up --build
```

This starts `mcp-server` (port 3100) and `litellm` (port 4000, dashboard at
`/ui`). By default `mcp-server` operates on `./workspace` -- use
`docker-compose.override.yml` to mount a different project checkout.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKSPACE_ROOT` | parent of `mcp-server/` | Project checkout local-mcp.py reads/writes/runs commands in. |
| `CF_API_BASE` / `CF_API_KEY` | -- | Cloudflare Workers AI proxy target + token. See `cloudflare/README.md`. |
| `CF_PROXY_OQ_LEDGER_PATH` | `architecture-docs/global/architect-open-questions.md` | Path (relative to `WORKSPACE_ROOT`) to an "open questions" ledger the orchestrator appends bounded-ambiguity rows to. If the consuming project has no such ledger, leave the default -- failures to read/write it are logged and degrade to "ambiguity surfaced inline", not a crash. |
| `CF_PROXY_USD_TO_AUD_RATE`, `CF_PROXY_MONTHLY_BUDGET_AUD`, `CF_PROXY_DAILY_REVIEW_THRESHOLD_USD` | `1.42`, `100.00`, derived | CF spend-review accounting (optional). |

## Status

This is an early-stage clone (Phase 1 of the migration plan in
`planning_document.md`): the toolchain runs standalone, but the orchestrator's
"open questions" / "actionable tasks" governance integration
(`CF_PROXY_OQ_LEDGER_PATH` and friends) still assumes an Electron-Splines-style
`architecture-docs/` layout when enabled. Generalizing that integration into
reusable `create_open_question` / `create_actionable_task` MCP tools is tracked
as AT-1137-1139 in the source repo.

Full mirroring of the consuming project's `app/`, `engine/`, and `scripts/`
directories (AT-1117/1118/1119) has not been done here -- this clone currently
contains only the AI-toolchain pieces (MCP server, orchestrator, LiteLLM,
Cloudflare/Docker config). If the original AT-1117/1118 scope (mirroring the
entire Electron-Splines app and engine source trees into this repo) is still
wanted, that is a separate, much larger effort and should be re-scoped with
the architect first.
