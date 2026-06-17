# Agent Harness Phase-0 Readiness Review

**Scope:** End-to-end migration plan, gap analysis, checkpoint validation, and OQ surfacing for the agent harness improvement initiative  
**Date:** 2026-06-13  
**Status:** BLOCKED on architect OQ resolution (see §5)  

---

## 1. Executive Summary

Before Phase 0 can begin, the project must resolve **three categories of blockers**:

1. **Strategic OQs** (2 open) — Determine whether Phase 0 is an in-place refactor or a step toward Odysseus convergence.
2. **Operational OQs** (1 open) — A live orchestrator run (`60d3aa7dece06114`) is paused at step 1/1 (OQ-268), leaving the harness in a dirty operational state.
3. **Chronic problems** (3 unfixed) — CB-18 (OQ ID reuse), CB-19 (step overshoot), and CB-15 (stale server process) will corrupt Phase 0 validation data if not fixed first.

**Verdict:** Phase 0 is **not ready to start**. A 1-day pre-flight sprint ("Phase -1") must close the chronic problems and obtain architect answers to the strategic OQs. Only then does Phase 0 begin.

---

## 2. Migration Strategy Options

The harness improvement review (`agent-harness-improvement-review.md`) proposed an **in-place decomposition** of `local-mcp.py` into domain-specific MCP servers (Phases 0–4). Separately, the Odysseus comparison (`odysseus-comparison-and-convergence-plan.md`) proposed a **10-week fork-and-port** to an Odysseus-based workspace.

These are not mutually exclusive, but they compete for the same engineering hours.

| Approach | Effort | Risk | When It Makes Sense |
|----------|--------|------|---------------------|
| **A — In-place only** | 2–3 weeks | Low; no external deps | Odysseus convergence deferred or rejected |
| **B — Odysseus fork first** | 10 weeks | High; large surface area | Architect commits to unified PWA workspace |
| **C — Hybrid (recommended in plan)** | 3 weeks in-place + 10 weeks fork | Medium; must not abandon in-place mid-flight | In-place Phase 0–2 delivers immediate safety wins; fork begins in parallel after Phase 2 |

**Gap:** No architect decision exists on which approach to pursue. The Odysseus plan introduced OQ-269 and OQ-270 for this purpose.

---

## 3. End-to-End Migration Plan with Checkpoints

Assuming **Approach C (Hybrid)** is adopted, the full migration spans **six phases**. Each phase has a **definition of done**, a **validation command**, and a **rollback trigger**.

### Phase -1: Pre-Flight (prerequisite — 1 day)

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| CB-18 fixed: `_next_oq_id` never reuses retired IDs | Unit test: simulate retirement then assert next ID > max ever assigned | If fix touches ledger format, run ledger syntax validator |
| CB-19 fixed: executor session bounded to single step | Integration test: step dispatch with multi-step prompt → orchestrator detects overshoot and halts | If heuristic false-positives, revert to manual review |
| CB-15 fixed: server auto-restarts when source file mtime changes | `touch local-mcp.py` → verify new PID within 5s | If restart loop on Windows, revert to manual `Stop-Process` + relaunch |
| OQ-268 answered: run `60d3aa7dece06114` dispositioned | State file archived or resumed per architect answer | n/a |
| OQ-269 answered: local-first vs cloud-first stance recorded | Answer codified in this doc | n/a |
| OQ-270 answered: MCP consumer vs producer identity recorded | Answer codified in this doc | n/a |
| Git status GREEN | `git status --short` returns empty (ignoring untracked build dirs) | Commit or restore any YELLOW/RED state first |

**Phase -1 Done Criteria:** All checkboxes above green; `agent-harness-phase0-readiness-review.md` updated with architect answers; commit `chore: phase -1 pre-flight complete`.

---

### Phase 0: Quick-Win Gates (1 day)

| Deliverable | Test / Validation | Rollback Trigger |
|-------------|-------------------|------------------|
| `ValidateCommitHygiene` skill in `.github/skills/` | Mocha test: skill execute → returns `{ passed: boolean, reasons: string[] }` on mock git repo | Skill malformed → remove skill folder, revert config.yaml |
| Size-guardrail gate in `local-mcp.py` | Unit test: `git_staged_stats` with 31 files → `guardrail_breach: true` | Breaks legitimate large refactor commits → widen threshold to 50 files temporarily |
| `as any` ESLint gate in `local-mcp.py` | Unit test: diff containing `as any` → gate returns `violation: true` with line numbers | False positive on string literal "as any" in comments → tighten regex |
| `no trailing commas in OpenSCAD` gate | Unit test: `.scad` file with trailing comma → gate catches it | n/a |

**Phase 0 Done Criteria:** All four gates exist and have passing tests; no regression in existing `create_test` / `run_shell` skills; commit `feat: phase 0 commit-hygiene gates`.

---

### Phase 1: MCP Server Extraction — Git & Npm (2 days)

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| `mcp-git-server` runs as standalone stdio process | `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python mcp_git_server.py` returns git tools in JSON | Falls back to `HARNESS_LEGACY=1` |
| `mcp-npm-server` runs as standalone stdio process | Same pattern; returns npm tools | Falls back to legacy |
| Continue.dev discovers both servers | `.continue/config.yaml` `mcpServers` block lists both; VS Code reload shows tools in chat | If Continue format incompatible, keep legacy as secondary transport |
| `local-mcp.py` shrinks by ≥30 % (≈900 lines removed) | `wc -l scripts/local-mcp.py` before/after | If orchestrator breaks, revert commit and retry with smaller slice |
| Orchestrator still routes correctly | End-to-end test: one orchestrated step using git tool via new server → YES verdict | Revert to legacy mode |

**Phase 1 Done Criteria:** Both servers unit-tested; orchestrator integration tested; `local-mcp.py` reduced; commit `refactor: extract mcp-git-server and mcp-npm-server`.

---

### Phase 2: MCP Server Extraction — OpenSCAD & Specs (2 days)

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| `mcp-openscad-server` renders a test `.scad` via tool call | Integration test: `openscad_render` tool on `engine/SR-3.1-data-representation/code/sweep_primitives.scad` → STL file exists with non-zero size | If OpenSCAD CLI path resolution broken on Windows, embed path fallback |
| `mcp-spec-server` can read and append OQs | Unit test: `append_oq` with mocked ledger → mock file contains new row with correct next ID | If ledger locking/atomicity issues, revert to direct file-write skills |
| `modelcontextprotocol/` package has `package.json` or `pyproject.toml` | `npm install` or `pip install -e .` succeeds in that directory | n/a |

**Phase 2 Done Criteria:** All four domain servers (git, npm, openscad, specs) operational; `local-mcp.py` reduced to orchestrator + proxy only; commit `feat: mcp-openscad-server and mcp-spec-server`.

---

### Phase 3: Agent Persona & Config Overhaul (1 day)

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| `.continue/config.yaml` uses `mcpServers` block, not monolithic prompts | Config reloads without error; agents spawn with tool discovery | Revert to static `systemMessage` if MCP dynamic loading fails |
| Persona yaml validated against schema | `yamllint` or custom validator passes | n/a |
| Smoke test: `agent architect` persona can list specs via `mcp-spec-server` | One manual chat session: `/agent architect` → `list_specs` tool call succeeds | n/a |

**Phase 3 Done Criteria:** Config clean; personas documented; commit `refactor: agent personas via MCP tool binding`.

---

### Phase 4: Observability & Packaging (2 days)

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| JSONL span file written on every orchestrator step | `cat .cf_proxy_orchestrator/spans/<trace_id>.jsonl` contains step_start, tool_call, step_end events | If log rotation fills disk, cap file at 10 MB |
| `modelcontextprotocol/` packages publishable | `npm pack` or `python -m build` produces valid artifact | n/a |
| Docker Compose includes MCP servers | `docker compose up mcp-git mcp-npm` starts both; health endpoint 200 OK | Revert to direct process spawning |

**Phase 4 Done Criteria:** Spans logging live; packages buildable; commit `feat: observability spans and mcp packaging`.

---

### Phase 5: Odysseus Convergence (parallel track, 10 weeks)

Only begins after Phase 2 is Done and architect confirms Odysseus fork.

| Checkpoint | Validation | Rollback Trigger |
|------------|------------|------------------|
| Odysseus fork builds with `CLOUD_MODE=true` | `docker compose up` in fork directory returns 0 | Revert to in-place harness |
| CF proxy registers as Odysseus model provider | Provider appears in Odysseus model dropdown; test call via CF returns text | n/a |
| Phase-3 orchestrator runs as Odysseus extension | One end-to-end task: plan → step → validator → YES via Odysseus UI | If opencode conflicts with orchestrator, disable opencode native loop |
| Deep Research engine callable from our tasks | Research task produces structured report with source table | n/a |

**Phase 5 Done Criteria:** Odysseus-based workspace exceeds current harness capability; legacy harness deprecated; final convergence commit.

---

## 4. Gap Analysis

### 4.1 Testing Infrastructure Gaps

| Gap | Severity | Mitigation in Plan |
|-----|----------|-------------------|
| Zero unit tests for `local-mcp.py` | **Critical** | Every Phase 0–2 deliverable must include a test before the code lands |
| No integration test for Continue.dev MCP discovery | **High** | Phase 1 checkpoint: manual smoke test + automated JSON-RPC validation |
| No mock git repository for CI | **Medium** | Create `fixtures/mock-repo/` with known dirty/clean/staged states |
| No performance benchmark for token burn | **Low** | Phase 4: measure `local-mcp.py` context size before/after each extraction |

### 4.2 Operational Gaps

| Gap | Severity | Mitigation in Plan |
|-----|----------|-------------------|
| No staging environment; all changes hit live orchestrator | **Critical** | Phase -1: establish `HARNESS_LEGACY=1` env fallback; never remove legacy path until new server proven |
| Windows process spawning untested for MCP stdio | **High** | Phase 1: test exclusively on Windows first; use stdio not sockets |
| No health check for stale server (CB-15) | **High** | Phase -1: auto-restart on file change; heartbeat/ping endpoint optional for Phase 2 |
| No automated ledger syntax validation (CB-18) | **Medium** | Phase -1: unit test for `_next_oq_id`; add CI check that linting passes |
| No step-overshoot protection (CB-19) | **Medium** | Phase -1: executor prompt injection + validator heuristic |

### 4.3 Skills / Agent Gaps

| Gap | Severity | Mitigation in Plan |
|-----|----------|-------------------|
| Only 2 skills exist; domain coverage severely incomplete | **High** | Phase 0 adds `ValidateCommitHygiene`; Phase 2 adds OpenSCAD and spec skills |
| Skills are not parameterised or composable | **Medium** | Phase 3: skill schema supports `{{params}}` substitution; meta-skills deferred to Phase 4 |
| Agent personas exist only as prompt strings | **High** | Phase 3: rebind to MCP tool subsets with dynamic discovery |
| No MCP Prompts protocol (`prompts/list`) | **Low** | Phase 4: register prompts as first-class resources |

### 4.4 Documentation Gaps

| Gap | Severity | Mitigation in Plan |
|-----|----------|-------------------|
| No migration runbook for `.continue/config.yaml` changes | **Medium** | This document serves as runbook; add "Config Migration" section to Phase 3 |
| No operator playbook for MCP server restart | **Low** | Phase 2: `README.md` in `modelcontextprotocol/` with restart commands |

---

## 5. Outstanding OQs Requiring Architect Answer Before Phase 0

### 5.1 Strategic OQs (must answer — block entire direction)

| ID | Question | Context | Options | Consequence of no answer |
|----|----------|---------|---------|------------------------|
| **OQ-269** | Local-first vs cloud-first stance for the harness | Odysseus comparison §2.3 | (A) Fork Odysseus, strip local-model UI; (B) Upstream contribution (slow); (C) Plugin layer with UI friction | Phase 0 scope unknown: in-place only, or in-place + fork prep? |
| **OQ-270** | MCP consumer vs producer identity | Odysseus comparison §2.3 | (A) Become pure consumer (lose safety); (B) Keep producer identity alongside Odysseus (complex); (C) Orchestrator as privileged extension (hybrid) | Determines whether `local-mcp.py` is retired or promoted to extension |

### 5.2 Operational OQs (must answer — block clean start)

| ID | Question | Context | Status | Recommended disposition |
|----|----------|---------|--------|------------------------|
| **OQ-268** | Orchestrator run `60d3aa7dece06114` step 1/1 ambiguous | Run paused 2026-06-13; diff empty on "provide task to break down" | **Open** | **Option B (treat as incomplete, halt)** — the step had no actionable task string; abandon run rather than guess |

### 5.3 Stalled OQs (from stopped runs — recommend bulk close)

| ID | Question | Context | Recommendation |
|----|----------|---------|----------------|
| OQ-267 | Run `90c2dbb2a162a15b` step 3/12 ambiguous | Essay run stopped by architect after CB-19 detected; file already contains steps 3–5 content | **Close as abandoned** — run will not be resumed per architect note |
| OQ-266 | Run `90c2dbb2a162a15b` step 2/12 ambiguous | Same run; untracked-new-file diff blindness | **Close as abandoned** — same run as OQ-267 |
| OQ-260 | Run `a731f317e9507669` step 7/9 ambiguous | File-creation step wrote to wrong absolute path; content manually copied to correct path | **Option A (treat as complete)** — the file exists at correct path with correct content; AMBIGUOUS was false positive from wrong-path write (CB-13) |
| OQ-259 | Run `a731f317e9507669` step 5/9 ambiguous | Read-only copy step; empty diff is correct by design | **Option A (treat as complete)** — precedented by earlier OQ-259 resolutions |

### 5.4 New OQs Surfaced by This Readiness Review

| ID | Question | Trigger | Preemptive Answer | Reversibility |
|----|----------|---------|-------------------|---------------|
| **OQ-271** | Should Phase 0 proceed before Odysseus fork decision, or must OQ-269/OQ-270 be resolved first? | Uncertainty between in-place and fork timelines | **Resolve OQ-269/270 first** — Phase 0 is architecturally different if the target is "clean in-place" vs "migration scaffolding toward Odysseus" | Reversible — in-place Phase 0 gates are useful regardless |
| **OQ-272** | What is the rollback policy if an extracted MCP server corrupts an ongoing orchestrator run? | No staging environment exists | **HARNESS_LEGACY=1 env var** forces monolith mode; new servers are opt-in per `.continue/config.yaml` | Reversible — env var toggle |
| **OQ-273** | Should the three chronic problems (CB-15, CB-18, CB-19) be fixed in a single pre-flight commit or separate commits? | Commit hygiene rule: one commit per task | **Single commit acceptable** — all three are "harness reliability fixes" for the same operational incident class; collectively <100 lines | Reversible — single revert |
| **OQ-274** | Should new OQs raised during the migration be appended to the existing `architect-open-questions.md` ledger or tracked in a separate `harness-migration-oqs.md`? | Existing ledger is 506 KB and slow to parse | **Existing ledger** — the OQ ledger is the single source of truth; migrate to `harness-migration-oqs.md` only if ledger size exceeds 1 MB or parser performance degrades | Reversible — file move is trivial |

---

## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Continue.dev `.continue/config.yaml` format changes, breaking MCP server registration | Medium | High | Keep legacy prompt-based agents as fallback; monitor Continue changelog |
| Windows stdio transport flaky for Python MCP servers | High (known) | High | Test Phase 1 exclusively on Windows; use `subprocess.Popen` with `bufsize=1`; fall back to SSE loopback if stdio fails |
| Odysseus upstream restructures, invalidating fork investment | Low | High | Phase 0–2 in-place improvements are valuable regardless; fork only after Phase 2 proves decomposition pattern |
| Token savings from decomposition offset by schema bloat | Medium | Low | Generate schemas from Zod types; use terse keys; measure before/after |
| Phase 0 gates produce false positives, breaking developer velocity | Medium | Medium | Gates start as warnings-only for 1 week; promote to hard failures after calibration |

---

## 7. Recommended Sequence of Actions

1. **Architect answers OQ-269, OQ-270, OQ-268** (this session or next).
2. **Architect confirms OQ-271** (proceed with Phase -1 regardless of Odysseus decision).
3. **Execute Phase -1** (1 day): fix CB-15, CB-18, CB-19; close stalled OQs; commit.
4. **Begin Phase 0** (1 day): deliver gates and skill; commit.
5. **Review Phase 0 evidence**; architect sign-off.
6. **Begin Phase 1** (2 days): extract git/npm servers.

---

## 8. Appendices

### A. Validation Commands Quick Reference

```bash
# Git status check
git status --short

# Legacy fallback test
HARNESS_LEGACY=1 python scripts/local-mcp.py

# New server health check (Phase 1+)
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python modelcontextprotocol/mcp_git_server.py

# Span file inspection (Phase 4+)
cat .cf_proxy_orchestrator/spans/$(ls -t .cf_proxy_orchestrator/spans/ | head -1)

# Skill unit test
npx mocha .github/skills/ValidateCommitHygiene/test/*.ts
```

### B. File Placement Reference

- This plan: `foundation/SR-1.4-ai-guidance/docs/agent-harness-phase0-readiness-review.md`
- Phase 0 gates: `.github/skills/ValidateCommitHygiene/`
- Phase 1–2 servers: `modelcontextprotocol/mcp_*_server.py`
- Phase 3 config: `.continue/config.yaml` (updated in-place)
- Phase 4 spans: `.cf_proxy_orchestrator/spans/` or `logs/orchestrator-spans/`

---

*Document status: AWAITING ARCHITECT OQ ANSWERS — do not proceed to Phase -1 until OQ-269, OQ-270, and OQ-268 are resolved.*
