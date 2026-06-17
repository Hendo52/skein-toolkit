# Toolchain Comparison: CF Proxy Orchestrator vs Odysseus, Aider, and OpenHands

**Date:** 2026-06-12
**Status:** Draft
**Owning SR:** SR-1.4 (AI toolchain governance)
**Tags:** toolchain, mcp, orchestrator, comparison, odysseus, aider, openhands

---

## Introduction: The Electron-Splines Toolchain

Agentic development on the Electron-Splines repository currently relies on a three-layer toolchain designed to make cheap AI models operationally viable for sustained engineering work. At the lowest layer sits a Cloudflare Workers AI proxy that routes requests to low-cost inference endpoints, primarily `cf/kimi-k2.6` at roughly two to four cents per call. Above that proxy runs `scripts/local-mcp.py`, a Python-based Model Context Protocol (MCP) orchestrator that supervises Cline, the AI coding agent, through multi-step tasks. The orchestrator performs planning passes to break large requests into discrete steps, dispatches each step with a narrowed context frame, runs validation passes against git snapshots to confirm real work occurred, and carries forward accumulated findings so later steps need not re-read large source documents.

This architecture exists because cheap models suffer from a chronic "context budget" problem: once a single prompt exceeds roughly twelve to twenty thousand tokens of dense tool-result text, models like `cf/gpt-oss-20b` reliably degenerate into empty completions, burning their entire token budget in an internal reasoning channel. The orchestrator fights this through per-step context isolation, oversized-tool-result truncation, a findings-carry-forward mechanism, and explicit architect intervention via "open question" (OQ) pause-and-resume semantics. Every change is experiment-driven, validated with before/after comparisons, and committed independently. The goal is not merely to make cheap models work occasionally, but to prove they can work reliably enough to seed a standalone community toolchain.

---

## The Odysseus Architecture

Odysseus is a self-hosted AI workspace built on a FastAPI server with SQLite for structured persistence and ChromaDB for vector search. It is licensed under AGPL-3.0, meaning any network deployment must share source modifications, a constraint that shapes its community dynamics differently from our repo-centric toolchain. Odysseus integrates multiple built-in MCP servers for memory, retrieval-augmented generation (RAG), email, and browser automation, exposing them through a unified server that handles client connections, tool discovery, and argument bridging.

A notable implementation detail in Odysseus is its correct MCP argument-bridge pattern, which uses `json.loads` to deserialize arguments passed from the MCP client into native Python structures before forwarding them to tool handlers. This seems trivial, but many MCP implementations fail at this boundary, passing raw strings or partially parsed objects that confuse downstream tools. Odysseus gets this right consistently across its server ecosystem. Its RAG-based tool surfacing uses ChromaDB embeddings to retrieve relevant documentation, prior conversations, or indexed web pages before invoking a tool, effectively pre-loading context rather than flooding the model with raw search dumps.

Odysseus also implements admin-controlled tool access, allowing an administrator to gate which MCP servers individual users or sessions may invoke. This is a multi-tenant concern our single-user orchestrator does not currently address. Most practically, Odysseus provides auto-reconnect logic for crashed MCP servers: if a tool server disconnects or panics, the workspace detects the failure, retries with backoff, and either re-establishes the connection or surfaces a graceful degradation message. Our toolchain has no equivalent resilience layer; if Cline crashes or the CF proxy returns a transport error, the orchestrator logs the failure and halts.
