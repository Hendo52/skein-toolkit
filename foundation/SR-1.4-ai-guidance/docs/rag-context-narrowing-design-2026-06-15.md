# RAG-Based Context Narrowing for Tier A Orchestrator Sessions

**Date:** 2026-06-15
**Status:** Design note -- GO recommendation
**Owning SR:** SR-1.4 (AI toolchain governance)
**Task:** AT-1156
**Related:** `model-enablement-toolset-strategy.md` section 6,
            `cf-proxy-cheap-model-context-budget-roadmap.md` CB-1,
            `skein-toolkit/docs/odysseus-convergence.md` (AT-1152)

---

## 1. How Odysseus's RAG / Retrieval Approach Works

### 1.1 Infrastructure: ChromaDB + FastEmbed embedding lanes

Odysseus uses a persistent ChromaDB HTTP instance (default `localhost:8100`,
configured via `CHROMADB_HOST`/`CHROMADB_PORT`) as its vector store.
Source: `src/chroma_client.py` -- `get_chroma_client()` is a singleton factory
that TCP-probes the port with a 2s timeout before connecting, so startup does
not block if ChromaDB is absent.

Embedding is handled by the `EmbeddingLane` / `build_embedding_lanes()` machinery
in `src/embedding_lanes.py`. Two named lanes exist:

- `LANE_FASTEMBED` -- fastembed local model (no external call; always available
  as the baseline lane).
- `LANE_CUSTOM` -- user-configured HTTP embedding endpoint (`EMBEDDING_URL` /
  persisted via `src/embeddings.py`); preferred when reachable.

Each lane gets its own per-collection ChromaDB collection (`{base}_fastembed`,
`{base}_custom`) so different embedding dimensions never collide. Lane selection
is: custom first if healthy, fastembed as the unconditional fallback.
`build_embedding_lanes(base_name)` in `embedding_lanes.py` returns the live list.

### 1.2 Document RAG: `VectorRAG` / `RAGManager`

`src/rag_vector.py` -- `VectorRAG` is the core class. Key behaviors:

- **Chunking:** `_split_into_chunks(text, chunk_size=1000, overlap=200)` uses
  sentence-boundary splitting (`re.split(r'(?<=[.!?])\s+|\n{2,}', text)`) with
  hard fallback for long sentences. 1000-char chunks, 200-char overlap.
- **Indexing:** `add_document(text, metadata)` and `add_documents_batch(docs)`.
  Document ID is `doc_{sha256(owner + '\x00' + text)[:16]}`, owner-scoped.
- **Hybrid search:** `search(query, k=5, owner=None)` runs vector cosine
  similarity across all lanes via `query_lanes()`, then applies keyword overlap.
  Final hybrid score = `0.7 * vector_sim + 0.3 * keyword_score`. Results are
  de-duplicated across lanes, sorted by `similarity`, trimmed to `k`.
- `RAGManager` in `src/rag_manager.py` is a thin delegation wrapper; all real
  logic is in `VectorRAG`.

### 1.3 Tool surfacing: `ToolIndex` (the key component for this design)

`src/tool_index.py` -- `ToolIndex` is the RAG-based tool selection system.
This is the component directly analogous to what the orchestrator needs.

**Index construction:**
- `index_builtin_tools()` iterates `BUILTIN_TOOL_DESCRIPTIONS` (137 tool entries,
  each a name + several-sentence description). Upserts into a ChromaDB collection
  named `odysseus_tool_index`. Stale entries for removed tools are pruned first.
- `index_mcp_tools(mcp_mgr, disabled_map)` parses MCP tool descriptions from
  `mcp_mgr.get_tool_descriptions_for_prompt()` and adds them under
  `tool_type: "mcp"` metadata. Re-indexed only when the MCP generation counter
  changes.

**Retrieval at query time:**
`retrieve(query, k=8)` encodes the query with the first available lane, calls
`collection.query(query_embeddings=..., n_results=k)`, scores results by
`1.0 - distance`, deduplicates across lanes, returns the top-k tool names only
(not descriptions).

**Set construction: `get_tools_for_query(query, k=8, always_include=None)`:**
1. Starts from `ALWAYS_AVAILABLE` = `{manage_memory, ask_user, update_plan}`.
2. Calls `retrieve(query, k=8)` to add the top-k vector-retrieved tool names.
3. Applies `_KEYWORD_HINTS` -- a dict of `frozenset(keyword_strings) -> set(tool_names)`.
   For each keyword set, checks for word-boundary regex match in the lowercased
   query; if any keyword matches, forces those tools in. Catches domain patterns
   (email, calendar, cookbook, research) that embedding alone may miss.
4. Applies `_SCHEDULE_RE` and `_WEB_RE` structural patterns.
5. Returns a `Set[str]` of tool names, not descriptions.

**How this is consumed in `agent_loop.py` (lines 1796-1893):**
1. `get_tool_index()` singleton (lazy init, 30s retry on failure).
2. `tool_idx.index_mcp_tools(mcp_mgr, ...)` refreshes if MCP gen changed.
3. `tool_idx.get_tools_for_query(_retrieval_query, 8)` runs via
   `asyncio.to_thread` with a timeout (slow ChromaDB never blocks a turn).
4. The resulting set `_relevant_tools` is passed to `_assemble_prompt()`, which
   builds the system prompt using only those tools' schemas and domain rules.
   The model never sees the irrelevant fraction of the tool catalog.
5. If ChromaDB is unavailable, a keyword-only fallback runs; if that also fails,
   `ALWAYS_AVAILABLE` only. The degradation path is explicit and logged.

The critical property: **the model's input context is bounded by retrieval, not
by catalog size.** A query about email yields ~10-15 tool schemas; a query about
shell scripting yields ~5-8 different ones.

---

## 2. Proposal: Retrieval-Based Context Narrowing for the Orchestrator

### 2.1 What to index

The orchestrator's per-step context assembly (in `_build_step_dispatch_body`,
`local-mcp.py` line 2499) currently includes:

1. A fixed system prompt (`_ORCHESTRATOR_STEP_SYSTEM_PROMPT`).
2. A user message: formatted findings block (prior step summaries) + step task.
3. `tail_messages` -- the tool-call/result turns from the current step only.

The CB-1 failure mode occurs when `tail_messages` accumulate large raw
tool-result payloads that push the total prompt past the ~12-20K token
degeneracy threshold for `cf/gpt-oss-*`.

What should be indexed for retrieval:

**A. Repository artifact index** -- index the project's documentation and spec
files. Candidates: `architecture-docs/` markdown files, `foundation/SR-*/` spec
and doc files, `engine/SR-*/docs/` files, source file summaries (first 30 lines
of key TypeScript files). Each chunk stored with metadata:
`{source: filepath, section: heading, type: "doc"|"code"}`.

**B. Tool description index** -- the 9 skein-toolkit MCP tools. A much smaller
set than Odysseus's 137, but the same principle: only show tools relevant to the
current step in the dispatch body's system prompt.

### 2.2 What triggers a retrieval query

Two query signals per orchestrator step:

1. **Step task text** -- the step's own sentence from the plan. The retrieval
   query is the step task itself, surfacing the relevant spec and source file.

2. **Step findings block** -- the accumulated `findings[]` from prior steps
   (in `_new_orchestrator_state`, populated by `_extract_step_finding`). The
   last 1-2 findings concatenated with the step task form a richer query.

### 2.3 Where in the existing per-step dispatch flow retrieval is inserted

The specific insertion point is `_build_step_dispatch_body` (line 2499):

```python
# Current signature:
def _build_step_dispatch_body(original_body, tail_messages, step_task,
                               step_index, total, findings=None):

# Proposed change -- add retrieval_context=None parameter:
def _build_step_dispatch_body(original_body, tail_messages, step_task,
                               step_index, total, findings=None,
                               retrieval_context=None):
    narrowed = dict(original_body)
    system_content = _ORCHESTRATOR_STEP_SYSTEM_PROMPT
    if retrieval_context:
        system_content = retrieval_context + "\n\n" + system_content
    narrowed["messages"] = [
        {"role": "system", "content": system_content},
        {"role": "user",
         "content": f"{_format_findings_block(findings or [])}Step {step_index} of {total} -- do ONLY this step: {step_task}"},
    ] + tail_messages
    narrowed["stream"] = False
    return narrowed
```

`retrieval_context` is a pre-formatted block of the top-3 to top-5 retrieved
chunks, each capped at ~500 chars. Total addition: ~2000 tokens at most. This
is additive but bounded -- unlike `tail_messages` which can grow unbounded.

The call site (in `_finish_step` or `_handle_orchestrated_request` where
`_build_step_dispatch_body` is called) adds one retrieval call per step:

```python
# Pseudocode for the new pre-step retrieval at the dispatch call site:
query = step_task
if findings:
    query = (findings[-1]["text"] + " " + step_task)[:512]
retrieval_context = await _retrieve_context_for_step(query, k=4, max_chars=2000)
dispatch_body = _build_step_dispatch_body(
    original_body, tail_messages, step_task, step_index, total,
    findings=findings, retrieval_context=retrieval_context
)
```

If ChromaDB is unavailable, `_retrieve_context_for_step` returns `None` and
`_build_step_dispatch_body` falls back to current behavior -- no regression.

**The `tail_messages` content is NOT changed.** Retrieval adds pre-hoc relevant
context; it does not compress or filter what the model has already gathered.

### 2.4 Where the Odysseus SSE bridge fits

AT-1152 verified that Odysseus's MCP manager can reach `local-mcp.py` via
`McpManager.connect_server(transport="sse", url="http://127.0.0.1:3100/sse")`.

However, for this proposal, the relevant Odysseus component is not the MCP tool
surface -- it is the **ChromaDB + fastembed infrastructure**. Two options:

**Option A -- Share Odysseus's ChromaDB instance.** The orchestrator calls
ChromaDB directly (same `localhost:8100`) using a separate collection name
(`skein_step_context`). No MCP calls needed; the orchestrator imports
`chromadb-client` and `fastembed` directly.

**Option B -- Call Odysseus's RAG as an MCP tool via the SSE bridge.** Add a
retrieval tool to Odysseus's MCP registration that accepts a query and returns
the top-k chunks from `VectorRAG.search()`.

**Recommendation: Option A.** Fewer moving parts: no new Odysseus-side code, no
dependency on the MCP bridge being up at dispatch time, no extra network hop.

---

## 3. How This Addresses CB-1

CB-1's failure mode (from `cf-proxy-cheap-model-context-budget-roadmap.md`):

> `cf/gpt-oss-20b` (and `-120b`) reliably returns an empty completion -- all
> token budget spent in the Harmony `analysis` (reasoning) channel, never
> reaching the `final` channel -- once a turn's prompt context reaches roughly
> 12-20K tokens, particularly when that context is dense raw tool-result text.

The degeneracy is content-shape-sensitive, not purely size-driven (roadmap section 3):

> The degeneracy at 15-20K (12-16% full) is NOT a hard context-window limit.
> It correlates with content density/shape (raw tool dumps), consistent with
> Chroma's "Context Rot" research.

RAG-based context narrowing addresses CB-1 in two ways:

**1. Pre-hoc reduction of irrelevant tool calls.**
If the model has a concise, pre-retrieved summary of the 3-4 most relevant
spec/code chunks in its system prompt, it has less need to call `read_file` or
`search_code` to recover that background. Fewer tool calls -> fewer large
tool-result turns in `tail_messages` -> smaller total context per step.

The Odysseus tool-surfacing data point is instructive: showing only relevant
tool schemas (5-15 tools out of 137) reduces the model's propensity to issue
spurious tool calls for irrelevant domains. The same mechanism applies to
context chunks: showing the model the 3-4 relevant spec paragraphs pre-emptively
should reduce the "read everything, then reason" pattern that produces large
`tail_messages`.

**2. Improved signal-to-noise ratio.**
The roadmap notes the failure is "prompt-content-correlated, not just
size-correlated." Retrieved context is dense and domain-relevant. Raw
tool-result text is often sparse and full of file-path boilerplate. Replacing N
tokens of low-density tool output with N tokens of high-density retrieved context
may shift the prompt below the degeneracy threshold even at the same token count.

**What RAG-based narrowing does NOT fix:**
- `tail_messages` growth during a step's own exploration. A step that issues 4
  `read_file` calls still accumulates 4 file dumps in `tail_messages`.
- First-turn degeneracy before any tool calls (the "4174-token first-turn prompt
  degenerated 6/6 attempts" finding in CB-1's row). For those, CB-2 or CB-3
  remain the appropriate levers.
- The CF proxy's current default cheap-tier model is `cf/kimi-k2.6` (OQ-264,
  2026-06-12), which does NOT exhibit the CB-1 degeneracy that `cf/gpt-oss-*`
  did. The immediate, urgent version of CB-1 is mitigated by model substitution.

This last point is material to the GO/NO-GO decision; see section 5.

---

## 4. Integration Cost and Complexity Assessment

### 4.1 What needs to be built

1. **Indexer for the repo artifact corpus.** A script or
   `_rebuild_step_context_index()` function in `local-mcp.py` that walks the
   repo's doc and spec directories, chunks content with sentence-boundary
   splitting (same algorithm as `VectorRAG._split_into_chunks`), and upserts
   the chunks into a `skein_step_context` ChromaDB collection.

2. **Retrieval helper.** `_retrieve_context_for_step(query, k, max_chars)` --
   a ChromaDB query function returning a formatted string. ~50 lines,
   structurally identical to Odysseus's `VectorRAG.search()`.

3. **Insertion point in `_build_step_dispatch_body` and its call site.** As
   described in section 2.3: add `retrieval_context=None` parameter, prepend
   to system prompt if non-None. The call site adds one
   `await _retrieve_context_for_step()` call per step before the dispatch.

4. **Graceful degradation guard.** If `get_chroma_client()` raises, catch and
   set `retrieval_context = None`. Log to stderr. No regression.

5. **Unit tests.** `_build_step_dispatch_body` with `retrieval_context=None`
   produces identical output to current behavior; non-None `retrieval_context`
   is prepended correctly; retrieval fallback returns None without exception.

### 4.2 Dependencies

- `chromadb-client` Python package (already in Odysseus's environment; needs
  confirmation for the orchestrator's Python environment).
- `fastembed` Python package (same situation).
- A running ChromaDB instance (already required by Odysseus; shared).
- An initial index build (one-time, then incremental on doc changes).

### 4.3 Complexity risks

- **Index staleness.** If a spec file is updated between the index build and a
  step dispatch, retrieved context may be stale. Low-risk: the model still calls
  `read_file` for authoritative text per the verbatim-quoting requirement in
  `_ORCHESTRATOR_STEP_SYSTEM_PROMPT`. Retrieved context is a hint, not ground truth.
- **ChromaDB service dependency.** The graceful degradation guard keeps this a
  soft dependency -- an absent ChromaDB is a logged warning, not a hard failure.
- **Embedding startup latency.** FastEmbed downloads the model on first use
  (~10-30s cold start). Subsequent queries are fast (<100ms on CPU). One-time
  per-process cost, already present in Odysseus.
- **Effort.** Medium: 3-5 engineering days. Most code is a structural copy of
  Odysseus's existing `rag_vector.py`; the non-trivial part is choosing which
  artifacts to index, tuning chunk size and k, and measuring `tail_messages`
  reduction empirically.

---

## 5. GO / NO-GO Recommendation

### Verdict: GO -- with a deferred priority note

**Reasoning for GO:**

1. The infrastructure work is low-risk and bounded. Odysseus has already solved
   the hard parts (ChromaDB client, fastembed lane management, hybrid search,
   graceful degradation). The orchestrator reuses a well-exercised pattern.

2. The AT-1152 SSE bridge is verified. The Option A integration (shared ChromaDB)
   requires only `pip install chromadb-client fastembed` in the orchestrator
   environment plus ~150 lines adapted from `rag_vector.py`.

3. CB-1's degenerate-empty-response failure mode is real and documented with
   reproducible test results. `cf/kimi-k2.6` substitution mitigated the immediate
   pain, but CB-1 was explicitly carried forward to the standalone toolchain repo.
   This proposal directly implements the pre-hoc attack on CB-1 described in
   `model-enablement-toolset-strategy.md` section 6.

4. The `_build_step_dispatch_body` insertion point is clean, additive, and
   backward-compatible. One function signature change, one call site change.

**Caveats:**

- **Priority is Medium, not High.** `cf/kimi-k2.6` is the current default and
  does not exhibit CB-1. This should not displace tasks targeting active regressions.
- **The experiment must measure what it claims to fix.** Exit evidence for the
  follow-up AT must require before/after token counts and a concrete pass/fail
  on a task that previously triggered CB-1 degeneracy with `cf/gpt-oss-120b`.
- **NO-GO condition for the prototype:** if `cf/kimi-k2.6` remains the only
  deployed cheap-tier model and never exhibits CB-1, the prototype has no live
  failure mode to test against. Implementing it fully without a live degeneracy
  trigger would be gold-plating; shelve at the measurement step if so.

---

## 6. Summary of Call Sites That Would Change

| Function | File | Change |
|---|---|---|
| `_build_step_dispatch_body` | `skein-toolkit/mcp-server/local-mcp.py` ~line 2499 | Add `retrieval_context=None`; prepend to `_ORCHESTRATOR_STEP_SYSTEM_PROMPT` if non-None |
| `_finish_step` (dispatch call site) | `skein-toolkit/mcp-server/local-mcp.py` ~line 2620 | Add `await _retrieve_context_for_step(query)` before dispatch; pass result as `retrieval_context` |
| (new) `_retrieve_context_for_step` | `skein-toolkit/mcp-server/local-mcp.py` | ChromaDB query + result formatting; returns `str` or `None` |
| (new) `_get_step_context_index` | `skein-toolkit/mcp-server/local-mcp.py` | Singleton ChromaDB collection handle; returns `None` if ChromaDB unreachable |

No changes to Odysseus or any file under `odysseus-local/` are required.
No changes to the AT-1152 SSE bridge are required.

---

## 7. Appendix: Key Source References

- Odysseus RAG infrastructure:
  - `c:/Users/jakeh/source/repos/odysseus-local/src/rag_vector.py` -- `VectorRAG` class (hybrid search, chunking)
  - `c:/Users/jakeh/source/repos/odysseus-local/src/embedding_lanes.py` -- `build_embedding_lanes`, `EmbeddingLane`
  - `c:/Users/jakeh/source/repos/odysseus-local/src/chroma_client.py` -- `get_chroma_client` singleton
- Odysseus tool surfacing:
  - `c:/Users/jakeh/source/repos/odysseus-local/src/tool_index.py` -- `ToolIndex`, `get_tool_index`, `get_tools_for_query`
  - `c:/Users/jakeh/source/repos/odysseus-local/src/agent_loop.py` lines 1796-1893 -- per-request RAG tool selection flow
- Orchestrator context assembly:
  - `skein-toolkit/mcp-server/local-mcp.py` lines 2499-2515 -- `_build_step_dispatch_body`
  - `skein-toolkit/mcp-server/local-mcp.py` lines 1638-1661 -- `_new_orchestrator_state`
- CB-1 documentation:
  - `foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-roadmap.md` section 5, CB-1 row
- AT-1152 SSE bridge verification:
  - `foundation/SR-1.4-ai-guidance/specs/model-enablement-toolset-strategy.md` section 5.1
