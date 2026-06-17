# Agent Harness Improvement Review

**Scope:** Skills, specialised agents, MCP protocols, CLI commands  
**Date:** 2026-06-13  
**Author:** Self-review (Cline / Continue orchestrator)

---

## 1. Executive Summary

The current harness works—`scripts/local-mcp.py` successfully bridges the Electron-Splines codebase to Continue.dev/Cline—but it is a **monolithic 3 000-line script** that mixes orchestration, proxying, git operations, lint orchestration, and OpenSCAD decision logic. This creates a single point of failure, makes testing hard, and wastes context-window tokens loading irrelevant code paths.

**Primary recommendation:** Decompose `local-mcp.py` into a **federation of small, single-responsibility MCP servers** and **specialised skill modules**, connected through a thin orchestrator that only knows how to route, never how to implement.

---

## 2. Current State

| Component | What it does | Lines | Pain point |
|---|---|---|---|
| `scripts/local-mcp.py` | MCP proxy, git wrapper, npm/bash runner, lint scheduler, orchestrator state machine, OpenSCAD decision logic | ~3 000 | Too large; any edit risks unrelated regressions |
| `.continue/config.yaml` | Slash commands (`agent architect`, `agent engineer`, `orchestrator`), model routing, validation templates | ~120 | Commands are big static strings; no composition |
| `.github/skills/` | `create_test`, `run_shell` | 2 | Far too few; missing domain-specific skills (OpenSCAD, Three.js, npm, git hygiene) |
| `.clinerules` | Commit hygiene, naming, file-placement, TS/SCAD watch-outs | ~150 | Excellent content, but **not machine-verifiable** at hook time |
| `modelcontextprotocol/` | Empty or unused | 0 | Directory exists but serves no purpose |

### 2.1 Token-waste analysis
Every invocation of `local-mcp.py` loads the entire script into the tool-call payload. Rough token counts:
- Full file read: ~4 500–5 000 tokens
- Orchestrator state-machine + prompt templates: ~3 500 tokens
- Git/npm/lint implementations: ~1 500 tokens
- **Result:** ~40 % of every tool context is code that will not execute on that call.

---

## 3. Improvement Recommendations

### 3.1 Decompose `local-mcp.py` into scoped MCP servers

Instead of one proxy, run a **local MCP hub** (e.g. `npx @anthropic-ai/mcp-hub` or a tiny Python starlette app) that mounts the following **micro-servers**:

| Server | Responsibility | Tools exposed | Language |
|---|---|---|---|
| `mcp-git-server` | All git operations + commit-hygiene validation | `git_status`, `git_diff`, `git_commit`, `git_log`, `lint_staged_check` | Python |
| `mcp-npm-server` | npm / node / TypeScript tooling | `npm_run`, `npm_test`, `npm_lint`, `typecheck`, `webpack_build` | Node/TS |
| `mcp-openscad-server` | OpenSCAD rendering, BOSL2 validation, STL QA | `openscad_render`, `bosl2_lint`, `stl_analyse`, `mesh_qa` | Python + OpenSCAD CLI |
| `mcp-spec-server` | Spec/OQ/decision-log CRUD | `list_specs`, `read_spec`, `append_oq`, `update_dashboard` | Python |
| `mcp-orchestrator-server` | State machine, step routing, pause/resume **only** | `start_run`, `step_next`, `pause_ambiguity`, `resume_run` | Python |

**Benefits:**
- **Fail isolation:** A crash in the OpenSCAD server does not kill the orchestrator.
- **Token efficiency:** The LLM only loads the server relevant to the current step.
- **Testability:** Each server is independently unit-testable (`pytest` or `mocha`).
- **Parallel execution:** The orchestrator can call `npm_test` and `openscad_render` concurrently.

### 3.2 Standardise on JSON-RPC 2.0 MCP transport

The current script uses ad-hoc HTTP POST with custom headers. Switch to the **official MCP transport**:

1. **stdio transport** for local sub-process servers (fastest, easiest on Windows).
2. **Server-Sent Events (SSE)** transport if you later need remote execution on a build agent.

This gives you:
- Automatic schema validation via MCP’s `tool` descriptors (`inputSchema`, `outputSchema`).
- Built-in progress, cancellation, and pagination primitives.
- Client-side tool-discovery: Cline/Continue lists tools dynamically instead of hard-coding them in `config.yaml`.

### 3.3 Expand the skills library

Current: 2 skills (`create_test`, `run_shell`).

Target: **One skill per domain verb**, following the pattern `DomainVerb` (PascalCase, no suffix):

```
.github/skills/
  CreateTypeScriptTest/       # (existing, rename from create_test)
  RunShellCommand/            # (existing, rename from run_shell)
  ValidateCommitHygiene/      # runs git diff --cached --stat, size/count guardrails
  RenderOpenScadProfile/      # wraps openscad CLI with BOSL2 path injection
  AnalyseStlMesh/             # wraps engine/SR-3.8-mesh-qa/code/
  UpdateSpecIndex/            # validates spec markdown, updates INDEX.md
  GenerateOpenQuestion/       # appends to architect-open-questions.md with next-id logic
  CheckNamingViolations/      # scans touched files, appends to NAMING_VIOLATIONS.md
```

Each skill should be:
1. **A TypeScript file** or **Python module** with a typed `execute(args)` entry point.
2. **Self-documenting:** A `README.md` inside the skill folder explaining inputs, outputs, side effects, and rollback behaviour.
3. **Unit-tested:** A `test/` subfolder with fixtures.

### 3.4 Introduce specialised agent personas (not just more prompts)

The current `config.yaml` defines agents via large `systemMessage` strings. Instead, define **lightweight personas that bind to a subset of MCP tools**:

```yaml
agent_personas:
  architect:
    description: "System-level design, spec review, OQ arbitration"
    tools:
      - mcp-spec-server:*
      - mcp-git-server:git_log,git_diff
      - mcp-orchestrator-server:pause_ambiguity
    model: claude-sonnet-4

  ts_engineer:
    description: "TypeScript / Electron / Three.js implementation"
    tools:
      - mcp-npm-server:*
      - mcp-git-server:*
      - Builtin:read_file,replace_in_file
    model: claude-sonnet-4

  scad_geometer:
    description: "OpenSCAD geometry, BOSL2 profiles, STL validation"
    tools:
      - mcp-openscad-server:*
      - Builtin:read_file,replace_in_file
    model: claude-sonnet-4

  qa_runner:
    description: "Test execution, lint, commit-hygiene gating"
    tools:
      - mcp-npm-server:*
      - mcp-git-server:*
      - Builtin:execute_command  # limited to npm/git
    model: claude-haiku
```

**Key difference:** The agent does not carry the implementation in its prompt; it discovers tools at runtime. This keeps prompts short and ensures tool improvements automatically propagate to every agent.

### 3.5 Replace raw bash with typed CLI abstractions

Currently, `execute_command` passes raw strings like `git diff --cached --stat`. Create a **CLI façade layer** so the LLM calls semantically-named tools rather than constructing shell strings:

| Current (raw) | Improved (typed tool) |
|---|---|
| `execute_command("git diff --cached --stat")` | `git_staged_stats()` → `{ files_changed: number, insertions: number, too_large: boolean }` |
| `execute_command("npm run test")` | `npm_run_script({ script: "test", reporter: "mocha" })` → parsed JSON with pass/fail/test list |
| `execute_command("openscad -o render.stl model.scad")` | `openscad_render({ input: "model.scad", output: "render.stl", quality: "draft" })` |

Implement this façade as **thin wrappers inside each MCP server**. The LLM never sees shell syntax; it sees JSON arguments and JSON results.

### 3.6 Add pre-flight and post-flight validation gates

The `.clinerules` are excellent, but they are **passive text**. Convert the highest-leverage rules into **automated gates**:

| Rule | Gate implementation |
|---|---|
| "One commit per task" | MCP tool `git_commit` rejects if working tree contains unstaged changes from multiple `--stat` groups |
| "Size guardrail: >30 files or >500 insertions" | `git_staged_stats` returns `guardrail_breach: true`; orchestrator auto-splits |
| "Conventional prefixes" | `git_commit` validates message regex `^(feat\|fix\|docs\|refactor\|test\|chore):` |
| "Clean exit: GREEN state" | `orchestrator_finish` runs `git_status_check` before allowing `attempt_completion` |
| "No `as any`" | `eslint_mcp` rule specifically greps for `as any\|as unknown as\|!` at diff boundaries |
| "No trailing commas in OpenSCAD" | `openscad_lint` parses `.scad` files for trailing commas in list literals |

These gates run inside the MCP servers, not in the LLM prompt, so they are **fast, deterministic, and fail-safe**.

### 3.7 Improve observability with structured spans

The current orchestrator logs to plain text files. Adopt **OpenTelemetry-style spans** (even if just JSONL) so you can later feed runs into a trace viewer:

```jsonl
{"t":"2026-06-13T04:55:00Z","trace_id":"30555b381ccd787d","span_id":"step_3","parent_id":"run_1","event":"step_start","step_idx":3,"task":"Refactor spline evaluator"}
{"t":"2026-06-13T04:55:12Z","trace_id":"30555b381ccd787d","span_id":"tool_call_a1","parent_id":"step_3","event":"tool_call","tool":"replace_in_file","file":"app/src/splines/eval.ts","duration_ms":1200}
{"t":"2026-06-13T04:55:15Z","trace_id":"30555b381ccd787d","span_id":"step_3","parent_id":"run_1","event":"step_end","verdict":"YES","finding":"Extracted cubic evaluator into CubicBezierSegment class"}
```

This makes it trivial to:
- Calculate per-step latency and token burn.
- Replay a failed run deterministically.
- Train/evaluate agent performance offline.

### 3.8 Create a `modelcontextprotocol/` package

The empty `modelcontextprotocol/` directory should become a **proper Node.js or Python package** that exports:

- `@electron-splines/mcp-core` – shared types, transport helpers, span logging
- `@electron-splines/mcp-git` – git server implementation
- `@electron-splines/mcp-npm` – npm server implementation
- `@electron-splines/mcp-openscad` – OpenSCAD server implementation
- `@electron-splines/mcp-specs` – spec/OQ server implementation
- `@electron-splines/mcp-orchestrator` – state-machine server

Start with one server (`mcp-git`) as a prototype. Once the pattern is proven, replicate.

---

## 4. Priority & Sequencing

| Phase | Work | Effort | Impact |
|---|---|---|---|
| 0 – Quick wins | Add `ValidateCommitHygiene` skill; add ESLint gate for `as any`; add size-guardrail gate to `local-mcp.py` | 1 day | High (prevents most common violations today) |
| 1 – Decomposition | Extract `mcp-git-server` and `mcp-npm-server` from `local-mcp.py`; keep orchestrator in main script | 2 days | High (testability, token efficiency) |
| 2 – New domains | Build `mcp-openscad-server` and `mcp-spec-server`; retire OpenSCAD logic from monolith | 2 days | Medium (isolates SCAD expertise) |
| 3 – Agent overhaul | Re-write `.continue/config.yaml` to use persona → tool bindings instead of monolith prompts | 1 day | Medium (maintainability) |
| 4 – Observability | Add JSONL spans; build a tiny HTML trace viewer or adopt Jaeger | 2 days | Low (future ROI for training/eval) |

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Decomposition creates network-of-failure | Keep the monolith as a **fallback mode** (env var `HARNESS_LEGACY=1`) until new servers are battle-tested |
| Windows process spawning is flaky | Use `stdio` MCP transport exclusively on Windows; avoid socket files |
| Token savings are offset by JSON schema bloat | Use terse schema keys (`a` not `argument`); generate schemas from TypeScript `zod` types to keep them tight |
| `.continue/config.yaml` format may not support dynamic tool discovery | Continue.dev already supports MCP servers natively; move away from static `systemMessage` lists toward `mcpServers` block |

---

## 6. Conclusion

The harness is **functionally sound** but architecturally **over-centralised**. The highest-leverage change is to **split `local-mcp.py` into domain-specific MCP servers**, expose them through typed skill modules, and let the orchestrator focus solely on routing and state management. This reduces token burn, increases test coverage, and creates clearer boundaries between TypeScript, OpenSCAD, and git concerns.

**Recommended next action:** Begin Phase 0 (quick-win gates and a new skill) to prove the tooling pipeline, then proceed to Phase 1 with `mcp-git-server`.

---

*File placement per `.clinerules`: `foundation/SR-1.4-ai-guidance/docs/agent-harness-improvement-review.md`*
