# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-06-12

Initial spin-off of the Electron-Splines AI development toolchain into a
standalone, Apache-2.0-licensed repository.

### Added

- Local agentic MCP server (`mcp-server/local-mcp.py`) and GPU-devserver
  variant (`mcp-server/devserver-mcp.py`), including the Cloudflare Workers
  AI proxy and multi-step task orchestrator with bounded-ambiguity
  escalation.
- LiteLLM unified proxy config routing local/CF/Groq/DeepSeek/Anthropic/OpenAI
  models.
- Docker Compose stack for `mcp-server` + `litellm`.
- Windows launcher/diagnostic scripts (`run-cline.ps1`,
  `resume-orchestrator-run.ps1`, `toolchain-doctor.ps1`, `start-litellm.ps1`).
- Ported unit test suite (57 cases across 5 files covering orchestrator
  resume, findings carry-forward, validator, CB-14 dispatch routing, and
  dispatch timeout) and a GitHub Actions CI workflow.
- PEP 517/518 packaging (`pyproject.toml`) for `mcp-server/` as the
  `mcp_server` distribution package.

### Licensing

- Relicensed under Apache License 2.0 (`LICENSE`, `NOTICE`) -- a deliberate
  relaxation from the source repository's proprietary license, scoped only to
  this standalone toolkit.

### Known limitations

- The orchestrator's "open questions" / "actionable tasks" governance
  integration (`CF_PROXY_OQ_LEDGER_PATH` and friends) still assumes an
  Electron-Splines-style `architecture-docs/` layout when enabled.
- PyPI package and Docker registry image have not yet been published.
