# Goose Evaluation (AT-1196)

**Date:** 2026-06-20
**Scope:** Research-only evaluation of Block/AAIF Goose as a general agentic layer
for the skein-toolkit stack. No code changes.
**Sources:** Goose docs (goose-docs.ai), GitHub source (`aaif-goose/goose` main
branch), and skein-toolkit existing configuration files.

---

## 1. LiteLLM proxy compatibility (Q1)

**Verdict: YES — direct support via both a first-class LiteLLM provider and the
OpenAI-compatible fallback.**

Goose has a dedicated **LiteLLM provider** (`crates/goose/src/providers/litellm.rs`)
that reads `LITELLM_HOST` (default `https://api.litellm.ai`),
`LITELLM_BASE_PATH` (default `v1/chat/completions`), `LITELLM_API_KEY`,
`LITELLM_CUSTOM_HEADERS`, and `LITELLM_TIMEOUT`. Pointing it at the local proxy
is straightforward:

```bash
export LITELLM_HOST="http://localhost:4000"
export LITELLM_BASE_PATH="v1/chat/completions"
```

Alternatively, Goose's **OpenAI provider** (`openai.rs`) accepts `OPENAI_BASE_URL`
(or the deprecated `OPENAI_HOST`). The parser auto-adds `http://` for `localhost`
hosts (line 92, `ensure_url_scheme`), so `OPENAI_BASE_URL=http://localhost:4000/v1`
works without manual scheme configuration. `OPENAI_BASE_PATH` can be set to
override the path segment if needed.

Goose also has built-in **Ollama** and **OpenRouter** providers, so the entire
local→mid→frontier model tier stack defined in `litellm_config.yaml` is reachable.
The only friction is that Goose's model picker is provider-centric (choose provider,
then model), whereas LiteLLM exposes a flat namespace (`local/qwen3.6`, `cf/kimi-k2.6`,
etc.). This is UX-level, not a protocol block.

---

## 2. Skein MCP SSE tool-calling (Q2)

**Verdict: NOT DIRECTLY — transport mismatch (SSE vs. Streamable HTTP).**

Goose's MCP client (`crates/goose/src/agents/extension_manager.rs`) is built on
the `rmcp` Rust SDK. It supports two transports:

1. **Stdio** (`TokioChildProcess`) — for local subprocess extensions.
2. **Streamable HTTP** (`StreamableHttpClientTransport`) — for remote HTTP
   extensions.

The `ExtensionConfig` enum (`extension.rs`) lists `Stdio`, `Builtin`, `Platform`,
`Frontend`, and `StreamableHttp`. **There is no `Sse` variant.** The CLI flag for
remote extensions is:

```bash
goose session --with-streamable-http-extension "https://example.com/streamable"
```

There is no `--with-sse-extension` equivalent.

Skein MCP (`local-mcp.py` / `devserver-mcp.py`) currently exposes **SSE transport**
at `http://127.0.0.1:3100/sse` via `FastMCP(..., port=3100)` + `mcp.sse_app()`.
This is the "classic" MCP SSE transport. Goose expects the newer **streamable
HTTP** transport, which uses POST for client→server and server-side events for
responses over a different endpoint shape.

**Implications:**

- Goose cannot register Skein MCP as-is without either (a) adding a streamable
  HTTP endpoint to Skein MCP, (b) running an SSE→streamable-HTTP bridge, or
  (c) adding SSE transport support to Goose (a non-trivial upstream change).
- Odysseus, by contrast, already has first-class `transport="sse"` + `url`
  registry support (confirmed in AT-1151).

---

## 3. UX comparison vs Odysseus (Q3)

| Dimension | Goose | Odysseus |
|---|---|---|
| **Scope** | General-purpose agent (code, research, automation, data analysis) | Coding- and project-management-focused |
| **Interfaces** | Desktop app (macOS/Linux/Windows), CLI, embeddable API | CLI + web dashboard |
| **MCP support** | First-class; 70+ documented extensions; marketplace | First-class; registry with `stdio`/`sse`; auto-registration for Skein built-in |
| **Project awareness** | Single working directory via MCP Roots; recipes (YAML workflows); subagents | Task queue (AT/OQ ledger), notes, milestones, per-project context |
| **Multi-model** | Planning mode + subagents with different providers/models | Single model per session (today) |
| **Permissions** | Tool permission levels, sandbox mode, adversary inspector, `.gooseignore` | Tool-enable toggles, manual approval prompts |
| **Session mgmt** | Persistent sessions, conversation search, resume | Session persistence via notes + task state |

**Assessment:** Goose has a richer *agent framework* (subagents, recipes,
multi-model orchestration, security sandbox) and a real desktop GUI. Odysseus
has deeper *project-management* semantics (the AT/OQ ledger, task queue, notes
linked to code changes). For a "project-aware agentic session" that tracks
open questions, actionable tasks, and their resolution against a codebase,
Odysseus's data model is the better fit today. Goose's model is "run the agent
in a directory and call tools" — powerful, but without the built-in
project-management layer that the OQ/AT system provides.

---

## 4. Windows support (Q4)

**Verdict: NATIVE DESKTOP YES; CLI REQUIRES GIT BASH/MSYS2 (NO WSL2 REQUIRED).**

- **Desktop:** A native Windows `.zip` is available from the download page.
  Runs as a standard Windows executable — no WSL2 needed.
- **CLI:** The install script (`download_cli.sh`) and binary expect a POSIX
  shell. The docs explicitly state: *"To install goose natively on Windows, you
  need one of the following environments: Git Bash (recommended): Comes with
  Git for Windows; MSYS2".*
- **PowerShell/cmd:** Not natively supported for the CLI install. The `curl | bash`
  workflow and the `goose` binary's shell assumptions require a bash-compatible
  environment. The Desktop app does not have this restriction.
- **Config path on Windows:** `%APPDATA%\Block\goose\config\config.yaml`
  (YAML format, shared between Desktop and CLI).

So Goose is **usable on Windows natively via the Desktop app**, but scripted or
CI-driven CLI use requires Git Bash or MSYS2. This is similar to aider's
`PYTHONIOENCODING` issue — a platform quirk, not a hard blocker.

---

## 5. Contribution target recommendation vs Odysseus (Q5)

**Recommendation: Goose is the stronger strategic target for *general
agentic-layer* contributions, but it is not a drop-in replacement for Skein's
current MCP integration due to the SSE transport gap.**

### Why Goose wins on strategic fit

1. **Governance:** Goose is now part of the **Agentic AI Foundation (AAIF) at the
   Linux Foundation** — the same standards body that stewards MCP itself.
   Contributing MCP extensions or agent behavior upstream has a real path to
   becoming part of the reference implementation.
2. **Ecosystem scale:** 70+ documented MCP extensions, a marketplace, recipes,
   and subagent primitives. Skein's tools would plug into a much larger user
   base than Odysseus's.
3. **Architecture:** Built in Rust for performance, with a clear separation
   between providers, extensions, and the agent loop. The code is production-grade
   (49k+ GitHub stars, 500+ contributors).

### Why Odysseus remains the better near-term fit

1. **SSE transport:** Odysseus already consumes Skein MCP at
   `http://127.0.0.1:3100/sse` with zero code changes (AT-1151 verified). Goose
   cannot do this today.
2. **Project model:** The AT/OQ ledger and notes system map directly to
   Odysseus's built-in concepts. Porting them to Goose would require new
   extensions or recipes, not just a registry entry.
3. **Depth B convergence:** The current Skein-Odysseus integration is already
   proven at Depth B (MCP-remote) and preserves upstream-contribution posture
   (AT-1217 finding). Moving to Goose would introduce new architectural work
   before any contribution could happen.

### Bottom line

- **If the goal is general tool-calling work and upstream contribution to the
  MCP ecosystem:** Goose is the better contribution target. The AAIF governance
  and first-class MCP support make it the natural home for new extensions.
- **If the goal is immediate Skein-toolkit integration with the existing
  SSE-based MCP server and the AT/OQ project layer:** Odysseus remains the
  working choice. Close the SSE→streamable-HTTP gap (either in Skein MCP or
  in Goose) before revisiting a switch.

---

## References

- AAIF Goose repo: `https://github.com/aaif-goose/goose`
- Goose docs: `https://goose-docs.ai/`
- LiteLLM provider source: `crates/goose/src/providers/litellm.rs`
- OpenAI provider source: `crates/goose/src/providers/openai.rs`
- Extension config source: `crates/goose/src/agents/extension.rs`
- Extension manager source: `crates/goose/src/agents/extension_manager.rs`
- Skein LiteLLM config: `../skein-toolkit/mcp-server/litellm_config.yaml`
- Prior Odysseus convergence analysis: `docs/odysseus-convergence.md` (AT-1151)
- Skein-Odysseus merge research: `docs/skein-odysseus-merge-research.md` (AT-1217)

