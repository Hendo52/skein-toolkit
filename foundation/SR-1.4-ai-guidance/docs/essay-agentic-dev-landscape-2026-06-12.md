---
title: "The Agentic Development Landscape, June 2026"
date: 2026-06-12
author: Electron-Splines System Architect (SR-1.4 AI toolchain governance)
status: Working draft
context: |
  Written from the perspective of a project operating under a $100 AUD/month
  ceiling for ~36 hours/week of agentic programming. The project uses a
  three-tier inference strategy (A/B/C) documented in
  `agentic-budget-tiered-strategy-2026-06-11.md`.

  This essay surveys the major tools available as of mid-2026, classifies them
  by architecture and cost model, and explains why the project landed on its
  current toolchain rather than the alternatives.
---

# The Agentic Development Landscape, June 2026

## Introduction

Agentic development — the practice of delegating substantial, multi-step
programming tasks to AI systems that can read, write, test, and iterate on code
autonomously — has shifted from experiment to daily-driver reality in the first
half of 2026. The tools available today are no longer simple autocomplete
extensions; they are autonomous agents with tool use, planning, memory, and the
ability to interact with shells, version control, and test runners.

This essay surveys the seven most significant agentic development tools as of
June 2026: **Cline**, **Claude Code**, **Aider**, **Cursor**, **Windsurf**,
**Continue**, and **OpenHands/OpenDevin**. Each occupies a distinct position in
the design space, trading off model access, cost structure, integration depth,
openness, and the degree of human-in-the-loop control.

For context, the Electron-Splines project — a TypeScript/Electron + OpenSCAD
cross-disciplinary application with ~20 specialized agent roles — operates under
a tight budget ceiling of **$100 AUD/month**. This constraint shapes the
analysis. Frontier-class tools that cost thousands per month at 36 hours/week
are noted, but the project's practical interest lies in tools that can drive a
tier-A daily driver (Cloudflare Workers AI, ~$13-66 AUD/month) while reserving
frontier access for architect-invoked escalation (tier C, ~$20 AUD/month). The
tier definitions and budget figures are quoted verbatim from the source-of-truth
budget document dated 2026-06-11.

---

## Major Tools

### 1. Cline

**Architecture:** VS Code Extension + Model-Agnostic Orchestrator  
**Cost model:** Any model the user can reach (API keys, local Ollama, cloud
proxies)  
**Openness:** Fully open-source (MIT)  
**Best for:** Teams with existing VS Code workflows and non-trivial model
infrastructure; those who need to route different tasks to different models
based on cost or capability.

Cline is a VS Code extension that exposes an agentic interface inside the editor.
Unlike Cursor or Windsurf, which bundle their own IDE, Cline bolts onto an
existing VS Code installation and workspace. It reads the full codebase context,
can propose and execute shell commands, edits files, and runs terminal
instructions — all under human approval by default.

Cline's defining characteristic is **model agnosticism**. It does not prescribe a
model. It accepts Anthropic, OpenAI, Google, Azure, local Ollama, and arbitrary
OpenAI-compatible endpoints. For the Electron-Splines project, this is the
critical feature: Cline is the orchestrator that routes requests to the
custom-built Cloudflare Workers AI proxy (`gpt-oss-120b` / `kimi-k2.6`), making
tier-A daily-driver usage financially viable. Without Cline's open adapter
interface, the project would be locked into a model provider whose per-token
costs at 36 hours/week would exceed the $100 ceiling by an order of magnitude.

The trade-off is integration polish. Because Cline is an extension rather than a
first-class IDE, the experience is more "power user" than "batteries included."
Configuration is manual: API endpoints, system prompts, and approval workflows
must be set up by the user. For a project with 20+ specialized agent roles and a
stateless sub-agent delegation pipeline, this manual control is a feature, not a
bug — but for a developer who wants to open an IDE and immediately start
delegating, the friction is real.

### 2. Claude Code

**Architecture:** Terminal-first CLI by Anthropic  
**Cost model:** Subscription or API-based; frontier pricing (Claude Sonnet / Opus)  
**Openness:** Proprietary; closed-source client  
**Best for:** High-trust delegation to frontier models on well-scoped tasks;
teams already invested in the Anthropic ecosystem.

Claude Code is Anthropic's official agentic CLI. It runs in the terminal,
operates within a working directory, reads files, runs shell commands, and
delegates multi-step tasks to Claude Sonnet or Claude Opus. It is the most
"mature" of the frontier-native tools: the model quality is high, the tool-use
reliability is excellent, and the context window handling (200k tokens) is
first-class.

The Electron-Splines project uses Claude Code directly — not through Cline — for
tier-C tasks: architect-invoked escalations, specification review, OQ
(Operational Question) resolution, and validation of content-fidelity fixes. The
reason is captured in the budget document:

> "Frontier-only usage is not" [viable as a daily-driver budget item]. At
> 36 hours/week of agentic usage, frontier API or subscription costs run to
> **thousands of AUD/month**.

Claude Code's model is locked to Anthropic's API. There is no path to routing
it to a cheap third-party endpoint. For a project with a $100/month ceiling,
this makes Claude Code a tier-C specialist, not a daily driver. The cost is,
however, justified for bounded, high-stakes tasks: a 15-minute architect
escalation that resolves a spec ambiguity is ~$1-3 AUD, not the hundreds it
would cost to run the same reasoning continuously.

### 3. Aider

**Architecture:** Terminal-based AI pair programming (git-centric)  
**Cost model:** Any OpenAI-compatible or Anthropic API  
**Openness:** Fully open-source (Apache 2.0)  
**Best for:** Developers comfortable in the terminal who want structured,
git-aware AI collaboration with minimal IDE dependency.

Aider is a terminal application that pairs with an editor of your choice (or
none at all). It reads the current git repository, uses `ctags` or tree-sitter
to understand code structure, and generates edits as unified-diff patches that
are applied to files. It supports multi-file editing, can run tests, and has a
strong mapping between git history and AI context — the model "sees" the repo's
structure and recent changes.

Aider's architecture is deliberately **git-native**: every AI edit is recorded
as a commit. This gives Aider the strongest audit trail of any tool surveyed
here. For teams that care about reproducibility and change attribution — a
concern for SR-1.4 governance, where "who decided what" matters for validation
and rollback — this is a genuine advantage.

Aider is less "agentic" than Cline or Claude Code in one respect: it does not
run arbitrary shell commands autonomously (though it can run linting and tests).
It is closer to a supercharged pair programmer that writes code for you to
review, rather than an autonomous agent that executes build pipelines. For the
Electron-Splines project, which needs agents that can run OpenSCAD headless
renders and mesh analysis tools, this limitation is why Aider was not selected
as the primary orchestrator. For a pure software project, however, Aider's
git-centric approach and low friction make it a strong contender.

### 4. Cursor

**Architecture:** Fork of VS Code with deep AI integration ("AI-native IDE")  
**Cost model:** Subscription tiers ($20-40 USD/month) + usage limits; uses Cursor's
own model routing  
**Openness:** Proprietary IDE; closed-source  
**Best for:** Developers who want the tightest possible integration between AI
and IDE — if the subscription cost is acceptable and the model routing is
trusted.

Cursor is a full IDE, a fork of VS Code, with AI deeply embedded at every layer:
inline completions, chat in the sidebar, composer mode for multi-file edits,
and agent mode for autonomous task execution. It is the most "productized" tool
in this survey. A developer opens Cursor, points it at a project, and can
immediately start delegating tasks that span files, tests, and terminal
commands. The onboarding friction is near zero.

The trade-offs are two-fold. First, **cost and lock-in**: Cursor requires a
subscription ($20-40 USD/month at the time of writing, ~$28-57 AUD), and the
agentic features are metered with usage limits. At 36 hours/week of agentic
usage, a user could exhaust the tier limits and face overage or throttling.
Second, **model opacity**: Cursor routes requests through its own model
infrastructure. The user cannot substitute a cheap third-party endpoint (like
CF Workers AI) or a local model. The model is whatever Cursor's backend serves.

For a project with a $100 AUD/month ceiling and a requirement to route cheap
models through a custom proxy, Cursor is structurally incompatible. Its value
proposition is "pay us to handle the model infrastructure" — which is a
reasonable proposition for teams with budget, but not for this one.

### 5. Windsurf

**Architecture:** AI-native IDE by Codeium (formerly Exafunction)  
**Cost model:** Subscription tiers with usage-based agentic credits  
**Openness:** Proprietary; closed-source  
**Best for:** Teams wanting an "agentic-first" IDE experience with stronger
planning/memory features than Cursor at the time of its release.

Windsurf (formerly Codeium Chat / Cascade) is Codeium's entry in the AI-native
IDE market. Like Cursor, it is a full IDE. Its distinctive feature is a
**planning-oriented agent mode**: the AI first writes a plan of action, presents
it for approval, and then executes it step by step, with memory of intermediate
results. This "plan-then-act" pattern reduces the rate of hallucinated edits
and gives the developer higher-level control.

Windsurf's model routing is similarly opaque to Cursor's, with subscriptions and
credit systems that scale with usage. As of mid-2026, it is positioned as a
direct competitor to Cursor, with similar cost structures and similar
proprietary lock-in.

The Electron-Splines project evaluated both Cursor and Windsurf during its 2025
toolchain selection phase and rejected both for the same reason: neither
supports custom model endpoints, and neither's pricing model fits within the
$100/month ceiling at 36 hours/week. The "agentic IDE" category is the right
abstraction for developers who want zero-configuration AI coding, but it is the
wrong cost model for budget-constrained agentic programming.

### 6. Continue

**Architecture:** Open-source IDE extension (VS Code, JetBrains) + model-agnostic
backend  
**Cost model:** Any model the user configures (free if using local or cheap
cloud models)  
**Openness:** Fully open-source (Apache 2.0)  
**Best for:** Teams that want Cline-like model agnosticism with a larger
community and broader IDE support; those who need JetBrains compatibility.

Continue is an open-source AI coding assistant that installs as an IDE extension
(for VS Code, JetBrains, and others). It is the closest conceptual peer to
Cline: model-agnostic, open-source, and extensible. It supports any
OpenAI-compatible API, local models via Ollama/LM Studio, and major cloud
providers. It offers chat, inline edits, and autocomplete.

Where Continue differs from Cline is in **orchestration depth**. Continue is
primarily a chat-and-edit assistant; its agentic capabilities (autonomous
multi-step execution, tool use, terminal integration) are less mature than
Cline's as of mid-2026. It is excellent for "ask a question about the code, get
an answer, apply an edit" workflows, but less suited to "run a 9-step plan that
involves editing files, running tests, and validating mesh output" — the kind
of workflow the Electron-Splines project requires.

Continue is a strong candidate for teams that need JetBrains support (Cline is
VS Code-only) or prefer a more lightweight, community-driven extension. For a
project that needs full agentic orchestration with custom cheap-model routing,
Cline's more advanced task-execution features made it the better fit.

### 7. OpenHands / OpenDevin

**Architecture:** Containerized autonomous software engineering agent  
**Cost model:** Self-hosted (compute for the agent container) + model API costs  
**Openness:** Fully open-source (MIT)  
**Best for:** Research, experimentation, and scenarios where a fully autonomous
"AI software engineer" running in an isolated sandbox is desirable.

OpenHands (formerly OpenDevin) is the most architecturally distinct tool in this
survey. It is not an IDE extension or a CLI copilot; it is a **containerized
agent** that runs inside a Docker environment with a full Unix shell, file
system, web browser, and code editor. The agent receives a task description and
autonomously writes code, runs commands, browses documentation, and debugs — all
inside its sandbox.

The vision is "an AI software engineer that works in its own environment." For
researchers studying autonomous agent behavior, OpenHands is invaluable: the
sandboxed execution allows safe experimentation with arbitrary code execution,
and the open-source codebase permits deep instrumentation of the agent's
planning and reasoning.

For practical daily-driver use, the friction is higher. The container must be
provisioned, the model must be configured, and the agent's output must be
extracted back into the developer's real workspace. OpenHands does not integrate
into an existing IDE workflow; it is a parallel environment. The compute cost
of running the container plus the model inference costs add up.

The Electron-Splines project did not adopt OpenHands for two reasons. First, the
sandboxed model does not match the project's workflow, where agents need to work
directly in the real workspace (editing OpenSCAD files that feed into the real
build pipeline). Second, the project's agent team model — with 20+ specialized
roles orchestrated by a teamlead agent — is a higher-level architecture than
OpenHands' single autonomous agent. OpenHands is a research platform and a
powerful proof of concept; Cline plus custom orchestration is a production
workflow.

---

## Underlying Tech Stacks

The agentic tools surveyed above do not operate in a vacuum. Each depends on a
plumbing layer that handles model access, routing, authentication, and
context-window management. Four technologies in this layer have become
foundational as of mid-2026: **Model Context Protocol (MCP) servers**, unified
API proxies in the **LiteLLM** tradition, **Ollama** for local orchestration, and
serverless cloud inference via **Cloudflare Workers AI**.

### Model Context Protocol Servers

**Model Context Protocol (MCP)** is an open standard — originally introduced by
Anthropic and now widely adopted — that defines how an agent (the "client")
discovers and invokes tools exposed by a server. An MCP server is a lightweight
process that exposes a schema describing the functions it offers (e.g., "read
file", "run shell command", "query database"), along with type-safe request and
response formats. The client, whether it is Claude Code, Cline, or a custom
orchestrator, connects to the server and calls those functions as part of its
planning loop.

The significance for agentic development is **composability**. Instead of every
tool (Cline, Claude Code, Cursor) hard-coding its own file-system access,
terminal execution, or browser automation, each can speak MCP and consume the
same standardized tool servers. A project that builds a custom MCP server for
its OpenSCAD rendering pipeline can plug that server into any MCP-compatible
orchestrator without rewriting integrations. This decouples the "what the agent
can do" from the "which IDE hosts the agent."

For the Electron-Splines project, MCP is the integration strategy for
specialized sub-agents. A dedicated MCP server exposes the OpenSCAD CLI, the
mesh-analysis toolchain, and the project's validation scripts. Cline connects to
this server as an MCP client, so the tier-A daily-driver agent can invoke
CAD-level operations without Cline needing to know anything about OpenSCAD
syntax. This is a cleaner architecture than embedding shell commands inline in
agent prompts.

### LiteLLM-Style Unified Proxies

**LiteLLM** is an open-source proxy layer that presents a single,
OpenAI-compatible API surface while routing requests to dozens of backend
providers (Anthropic, OpenAI, Azure, Google Vertex, Cohere, local models, and
more). It handles load balancing, fallbacks, retries, cost tracking, and rate
limiting in one place. As of mid-2026, "LiteLLM-style" has become a generic term
for this pattern: a unified gateway that abstracts provider diversity behind a
single client-facing contract.

The practical impact on agentic development is enormous. Without a unified
proxy, every tool in the stack would need native adapter code for every model
provider. Cline would need one code path for Anthropic, another for OpenAI,
another for Google, and so on — and every new provider would require a client
update. With a LiteLLM-style proxy, the tool speaks one protocol (OpenAI
Compatible), and the proxy handles the translation.

For budget-constrained projects, the proxy is also the **cost-control layer**.
LiteLLM can route low-priority summarization tasks to the cheapest endpoint,
critical reasoning tasks to the frontier model, and everything else to a middle
tier — all transparently to the client. The Electron-Splines project's custom
Cloudflare Workers AI proxy is architecturally a LiteLLM-style unified gateway:
it speaks OpenAI-compatible JSON to Cline, but routes to `gpt-oss-120b` or
`kimi-k2.6` on the Cloudflare backend. If the project later adds an
Ollama-local tier-B fallback, the same proxy can route there without a single
line of change in Cline.

### Local Model Orchestration via Ollama

**Ollama** is the dominant local model runner for developer workstations as of
mid-2026. It packages large language models into downloadable "model files" that
include weights, tokenizer configuration, and system prompts, then serves them
via a local HTTP API that is wire-compatible with OpenAI's chat completions
endpoint. A developer runs `ollama pull <model>` and then points any
OpenAI-compatible client to `http://localhost:11434`.

For agentic development, Ollama serves two roles. The first is **offline
capability**: developers can iterate on agent workflows without any API cost or
network dependency. The second is **privacy and control**: sensitive codebases
can be processed entirely on-local-hardware, with no tokens leaving the machine.

The constraint is hardware. Running a 120-billion-parameter model (the class of
`gpt-oss-120b`) locally requires GPU resources that few workstations possess.
Ollama excels at smaller models — the 7B-to-70B parameter range — where a modern
desktop GPU or Apple Silicon Mac can deliver usable token throughput. For the
Electron-Splines project, Ollama is the designated **tier-B fallback**: when
network connectivity to Cloudflare Workers AI is unavailable or when the budget
proxy is at quota, the orchestrator falls back to a local model (e.g., a
fine-tuned 14B or 32B parameter model) served by Ollama. The degradation in
capability is acceptable because the fallback is bounded: short
maintenance tasks, not full architecture sessions.

Architecturally, Ollama integrates seamlessly with the LiteLLM-style proxy
layer. The proxy treats the Ollama endpoint as just another backend provider.
Cline, in turn, treats the proxy as just another OpenAI-compatible API. The
abstraction chains are clean.

### Cloud Inference via Cloudflare Workers AI

**Cloudflare Workers AI** is a serverless GPU inference platform that exposes
popular open-weights models (including Meta's Llama family, Mistral, and DeepSeek
variants, and as of 2026, models like `gpt-oss-120b` and `kimi-k2.6`) through a
REST API located at the edge of Cloudflare's CDN. Requests are routed to the
nearest data center, keeping latency low, and billing is usage-based with no
minimum spend.

For agentic development, Cloudflare Workers AI occupies a unique position in the
cost-capability matrix. It is not frontier-class (it does not host Claude Opus
or GPT-4o-level proprietary models), but the models it hosts are competent
generalists — good enough for code generation, refactoring, documentation, and
test writing. The pricing, at the volume of ~36 hours/week of agentic usage, is
an order of magnitude cheaper than frontier API providers. The Electron-Splines
project's budget document estimates this tier at approximately **$13-66
AUD/month** depending on the mix of models and task complexity.

The project's custom proxy is built on Cloudflare Workers (the serverless
compute platform, distinct from Workers AI the inference platform). The Worker
receives OpenAI-compatible requests from Cline, translates them to the Cloudflare
Workers AI REST format, forwards them, and streams the response back. This
indirection is necessary because Cline natively speaks OpenAI-compatible JSON,
not Cloudflare's native schema. The same Worker also handles authentication
(bearer tokens for sub-agent isolation) and basic rate-limiting to prevent runaway
agents from exhausting the daily budget.

The trade-off for this cheap tier is **ceiling**: there are tasks that
`gpt-oss-120b` simply cannot do reliably — deep architectural reasoning,
specification validation across 10,000 lines of context, reasoning about
non-local code interactions. This is why the project retains tier-C (frontier)
access via Claude Code for bounded high-stakes tasks. The architecture is not
"cheap model for everything"; it is "cheap model for the 80% that does not need
frontier reasoning, frontier model for the 20% that does."

---
