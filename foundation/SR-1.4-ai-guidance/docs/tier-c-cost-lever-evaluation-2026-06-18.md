# Tier-C Cost Lever Evaluation: Advisor Tool, Batch API, Prompt Caching

**AT:** AT-1173
**Date:** 2026-06-18
**Trigger:** 2026-06-15 credit-balance exhaustion incidents on `claude/sonnet-4` during Lane 106 ledger work (AT-1166/AT-1167); architect interest in cost reduction for Tier-C (cloud Claude) usage.
**Scope:** Research only. No code changes in this AT -- go/no-go recommendation per lever, with follow-up ATs drafted for each "go".

---

## 1. Advisor tool (`advisor_20260301`)

**Verdict: GO.**

Confirmed real via web search (postdates this assistant's training cutoff, verified rather than assumed): Anthropic shipped the Advisor tool in beta on 2026-04-09. It is a server-side tool, not a client-side orchestration pattern -- a single Messages API call with `anthropic-beta: advisor-tool-2026-03-01` and a tool of `type: "advisor_20260301"` lets a cheap executor model (Sonnet 4.6 or Haiku 4.5) consult Opus 4.6 mid-call for hard sub-decisions, capped via `max_uses`. Benchmarks cited in the task description are accurate: Haiku+advisor 19.7% -> 41.2% on SWE-bench at 85% less cost than solo Sonnet; Sonnet+advisor 74.8% vs 72.1% solo Sonnet at lower cost than solo Opus.

**Billing:** no separate access fee for the tool itself; advisor tokens bill at Opus rates, executor tokens bill at Sonnet/Haiku rates. This means the cost benefit is real only when most of a task's tokens flow through the cheap executor and only a minority of sub-decisions trigger an advisor consult -- a task that consults the advisor on every turn would approach solo-Opus cost.

**Fit for this project's Tier-C usage:** the credit-exhaustion incidents this AT was triggered by (AT-1166/AT-1167, Lane 106 ledger work) were `claude/sonnet-4` solo calls on judgment-heavy but still largely mechanical tasks (spot-checking 29 ledger rows against commit evidence, bulk-correcting status fields). This is close to the Sonnet+advisor benchmark shape: mostly mechanical work with occasional "is this evidence actually sufficient" judgment calls -- exactly the kind of hard sub-decision the advisor pattern is designed to escalate, while the bulk of the token volume (reading rows, formatting commits) stays at Sonnet rates.

**Integration scope (follow-up AT, not yet staged):** `model-enablement-toolset-strategy.md` §7 currently defines two Support levels (Bare, Enabled/SQEP). Add a third: **Advised** -- a Tier-C model with the advisor tool wired in, escalating to Opus only for sub-decisions matching a to-be-defined "hard judgment call" signal (mirrors the existing OQ-escalation pattern already used elsewhere in this toolchain's orchestrator). `litellm_config.yaml` routing: LiteLLM would need to either (a) pass the `anthropic-beta` header and tool definition through transparently for any `claude/*` route the architect designates "Advised", or (b) require the caller (Cline, Claude Code) to set this per-request -- needs an actual LiteLLM compatibility check before committing to a design, since LiteLLM's tool-calling passthrough behavior for provider-specific beta tool types is not something this research pass verified.

---

## 2. Batch API

**Verdict: PARTIAL GO -- narrow but real eligibility window.**

Anthropic's Message Batches API: 50% discount on both input and output tokens for up to 24-hour async completion, available for every Claude model, up to 100,000 requests per batch. Critically, **the Batch API does not support tool use** -- confirmed via web search, not assumed. This is the single fact that determines eligibility for this project's AT-task categories.

**Eligible categories** (no tool calls required, output is the entire deliverable):
- Doc drafting from a fully-specified prompt (e.g. "write a one-page evaluation of X given these three source documents pasted into the prompt") -- if the source material is pasted into the prompt rather than fetched via a tool call mid-task.
- Classification/triage passes where the full input is already in the prompt (e.g. "classify each of these 40 file paths as Skein-canonical/ES-specific/Ambiguous given this one-line description of each" -- AT-1202's shape, *if* the file list and descriptions are pre-gathered into the prompt rather than the model reading each file itself).
- Bulk row-formatting where the transformation rule and all input rows fit in one prompt (e.g. AT-1167's spot-check, *if* the 29 rows' evidence had been pre-pasted rather than looked up live against `git log`).

**Ineligible categories** (the overwhelming majority of this project's AT tasks): anything in the iterative read-edit-test-commit loop shape -- which is most AT tasks, including every one completed in this session (AT-1170, AT-1174, AT-1164, AT-1168 all required reading files, running tests, and reacting to results mid-task). A batch request is submitted once with a fixed prompt and gets one response up to 24 hours later; it cannot pause to read a file, run a test, see the result, and adjust.

**Why this matters for the 2026-06-15 trigger incident specifically:** AT-1166/AT-1167 (the incidents that triggered this AT) were NOT batch-eligible as actually executed -- both involved looking up `git log` evidence live per row. They *could* have been restructured as batch-eligible if all 29 rows' commit evidence had been gathered into a single prompt first (a separate, tool-using step) and only the "spot-check and bulk-correct" judgment applied via batch. This is a real restructuring opportunity, not just a "doesn't apply" dismissal.

**Integration scope (follow-up AT, not yet staged):** define a "two-phase" pattern for the eligible category -- Phase 1 (tool-using, synchronous, Tier-C or cheaper) gathers all needed evidence into a single prompt; Phase 2 (no tools, batch-eligible) does the actual classification/drafting/spot-check judgment at 50% discount. This is a workflow-design AT, not a `litellm_config.yaml` change -- LiteLLM's batch support would need to be checked separately if routing through the existing proxy stack rather than calling Anthropic's Batch API directly.

---

## 3. Prompt caching (CF Workers AI)

**Verdict: GO, but the mechanism is different from what this task's premise assumed -- corrected below.**

This task's premise referred to "CF Workers AI `cache_control` support" -- modeled on Anthropic's `cache_control` content-block field. Verified via web search that **this is not the actual CF mechanism**. Cloudflare Workers AI has always done automatic prefix caching (caching input tensors from a previous request so only new tokens need prefill), and as of the kimi-k2.5/k2.6 rollout now surfaces this as a billed discount and an explicit opt-in lever: the **`x-session-affinity` request header**. Passing a unique string per session/agent routes follow-up requests to the same model instance, which is what makes the prefix cache hit. Confirmed pricing for the model this project already uses as its default cheap tier: `@cf/moonshotai/kimi-k2.5` cached input tokens are $0.100/M vs $0.600/M for regular input tokens (kimi-k2.6 pricing not separately listed in the page checked, but the mechanism is the same model family).

**Fit for this project:** every `_cf_proxy`-routed request in a Cline/Claude session against the same repo is, in practice, a "session" in CF's sense -- the orchestrator's per-step dispatch (`_dispatch_step` / `_build_step_dispatch_body`) and the plain interactive Cline-panel path both reuse the same conversational context repeatedly within one task. Adding a stable `x-session-affinity` value (e.g. derived from the orchestrator run key for orchestrated requests, or a per-VS-Code-session UUID for interactive requests) costs nothing to try and has a real, currently-unclaimed discount on the kimi-k2.x family already in default use.

**Claude Code's own ~5-minute ephemeral cache window** (the second half of this task's original framing) is a separate mechanism -- Anthropic's own prompt-cache TTL on `claude/*` calls, not something `_cf_proxy` controls. This project's own `CLAUDE.md`-adjacent tooling (this very session) already benefits from it automatically; there is no `_cf_proxy`-side lever for it since it applies only to direct Anthropic API calls, not the CF Workers AI proxy path. No action item here -- it already works as designed.

**Integration scope (follow-up AT, not yet staged):** add `x-session-affinity` header generation to `_cf_proxy`'s outbound request construction in `local-mcp.py` -- a small, mechanical change (derive a stable key per orchestrator run or per Cline session, attach the header on every forward). Verify the discount actually applies by comparing `cached input tokens` in CF's response usage block before/after, the same evidence-based verification pattern already used for CB-7/CB-11/etc. in the roadmap doc.

---

## Summary

| Lever | Verdict | Follow-up AT scope (not yet staged) |
|---|---|---|
| Advisor tool | **GO** | Third "Advised" Support level in `model-enablement-toolset-strategy.md` §7; LiteLLM passthrough compatibility check |
| Batch API | **PARTIAL GO** | Two-phase pattern (tool-using evidence-gathering + batch-eligible judgment) for the narrow eligible category; most AT tasks remain ineligible |
| Prompt caching (CF) | **GO** (mechanism corrected: `x-session-affinity` header, not `cache_control`) | Add session-affinity header generation to `_cf_proxy`; verify discount via CF usage response |

## Sources

- [Anthropic Advisor Strategy: Smarter AI Agents (2026)](https://www.buildfastwithai.com/blogs/anthropic-advisor-strategy-claude-api)
- [Feature Request: Support Anthropic Advisor Strategy (advisor_20260301) -- opencode#21789](https://github.com/anomalyco/opencode/issues/21789)
- [feat(@ai-sdk/anthropic): support advisor tool (advisor_20260301) -- vercel/ai#14285](https://github.com/vercel/ai/issues/14285)
- [Cloudflare Workers AI Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Moonshot AI Kimi K2.5 now available on Workers AI -- Cloudflare Changelog](https://developers.cloudflare.com/changelog/post/2026-03-19-kimi-k2-5-workers-ai/)
- [Powering the agents: Workers AI now runs large models, starting with Kimi K2.5 -- Cloudflare Blog](https://blog.cloudflare.com/workers-ai-large-models/)
- [When and How to Use the Anthropic Batch API in Your Agent](https://dev.to/mukundakatta/when-and-how-to-use-the-anthropic-batch-api-in-your-agent-5fgn)
- [Anthropic Message Batches API: 50% Off Async Jobs (2026)](https://www.respan.ai/articles/anthropic-message-batches-api)
