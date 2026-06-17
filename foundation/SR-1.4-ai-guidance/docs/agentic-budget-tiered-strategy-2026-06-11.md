# AI Toolchain Budget & Tiered Inference Strategy -- Working Notes (2026-06-11)

**Status:** Working notes -- source-of-truth for a formal spec (not yet written)
**Owning SR:** SR-1.4 (AI toolchain governance)
**Date:** 2026-06-11
**Currency:** All dollar amounts are AUD. Where source pricing is in USD, the conversion
rate used is 1 USD = 1.42 AUD (June 2026).
**Budget ceiling:** $100 AUD/month, for approximately 36 hours/week of agentic programming.

This document is the literal source of record for the budget figures and tier
definitions below. A formal spec derived from this document MUST quote the
figures in section 2 and the tier definitions in section 3 verbatim --
do not recompute or re-derive them.

---

## 1. Why this document exists

Agentic development on Electron-Splines has paused except for the effort of getting
a cheap-model toolchain (Cline + Cloudflare Workers AI) to a daily-driver standard.
This document records the 2026-06-11 budget analysis and the resulting three-tier
inference strategy (A/B/C), so that this analysis can be carried into a formal spec
and into the agentic-server spinoff project's own documentation.

---

## 2. Budget findings (2026-06-11 session)

### 2.1 Tier A -- Cloudflare Workers AI (cf/gpt-oss-120b, cf/kimi-k2.6)

- Estimated cost at 36 hours/week of usage: **$13-66 AUD/month**, depending on
  usage intensity (light to heavy).
- This range is comfortably inside the $100 AUD/month ceiling even at the heavy
  end.
- Remaining headroom after Tier A alone: **$35-85 AUD/month**.

### 2.2 Frontier cloud options (Claude API direct, Claude Code subscriptions)

- At 36 hours/week of agentic usage, frontier API or subscription costs run to
  **thousands of AUD/month** -- not viable as a daily-driver budget item.

### 2.3 Tier C -- pay-as-you-go Claude Sonnet (architect-invoked only)

- Estimated cost: **~$20 AUD/month**, based on the naturally low, bounded
  frequency of architect-invoked tasks (escalations, spec review, OQ resolution).

### 2.4 Conclusion

CF Workers AI (`gpt-oss-120b` / `kimi-k2.6`) is financially viable as a daily
driver at 36 hours/week, within the $100 AUD/month ceiling. Frontier-only usage
is not. **The constraint currently blocking Tier A from being usable is
reliability (the CB-7 content-fidelity problem in
`foundation/SR-1.4-ai-guidance/docs/cf-proxy-cheap-model-context-budget-roadmap.md`),
not cost.**

---

## 3. The three-tier strategy (A/B/C)

### Tier A -- Cloudflare Workers AI daily driver

- **Models:** `cf/gpt-oss-120b` for most daily tasks; `cf/kimi-k2.6` for harder
  tasks.
- **Role:** Primary daily driver for routine and complex agentic programming
  tasks.
- **Cost:** $13-66 AUD/month (see 2.1).
- **Status (2026-06-11):** Mechanically working end-to-end for the first time
  (the orchestrator ran a full 9-step plan, exit 0 in 42s) after the
  `run-cline.ps1` stdin-truncation fix (commit `8d2fb468`). The remaining
  blocker is content fidelity (CB-7): "exit 0" did not mean "correct" -- a
  test run inverted the actual System Architect decisions it was asked to
  transcribe. A scoped fix for CB-7 (verbatim-quote instruction in the
  per-step executor system prompt) was applied 2026-06-11, commit `cfa3a2d4`,
  and is being validated.

### Tier B -- vast.ai dev server for escalation / batch complex tasks

- **Role:** Escalation target for tasks Tier A cannot handle reliably, and for
  batches of complex tasks where amortizing provisioning overhead makes sense.
- **Models:** The best available open model on rented GPU hardware (see
  `architecture-docs/research_into_prior_work/gpu-batch-cost-optimization.md`
  for prior Vast.ai + Ollama cost research).
- **Status (2026-06-11):** Does not exist yet. `electron-splines-dev-server/`
  is an empty stub repository (a fresh `master` branch with no commits, no
  remote, and a one-line `README.md`). `DEV_TOOLKIT_PLAN.md` describes the
  intended standalone, Docker-based toolkit repo but no provisioning has been
  done.
- **Open question:** there is likely a minimum viable batch size below which
  Vast.ai provisioning overhead is not worth it relative to running the same
  tasks on Tier A or Tier C.

### Tier C -- pay-as-you-go Claude Sonnet, architect-invoked

- **Role:** Specific tasks invoked directly by the System Architect -- not a
  daily-driver tier.
- **Cost:** ~$20 AUD/month (see 2.3).
- **Status (2026-06-11):** Already in use (this session is an example). Usage
  is naturally low-frequency and bounded.

---

## 4. Per-tier budget allocation (within the $100 AUD/month ceiling)

| Tier | Role | Estimated cost (AUD/month) |
|------|------|------------------------------|
| A -- CF Workers AI | Daily driver | $13-66 |
| B -- Vast.ai dev server | Escalation / batch | Not yet provisioned -- no cost data |
| C -- Claude Sonnet (pay-as-you-go) | Architect-invoked | ~$20 |

A, B, and C compete for the same $100 AUD/month budget. Tier B's cost is
currently unknown because the dev server has not been provisioned. Once Tier A
is reliable (CB-7 resolved), the ~$35-85 AUD/month headroom is available for
Tier B provisioning experiments and/or further Tier C usage, subject to
explicit per-tier caps to be set once Tier B has real cost data.

---

## 5. Status as of 2026-06-11

- Tier A: mechanically functional, content-fidelity fix (CB-7) applied and
  pending validation.
- Tier B: not provisioned; only prior-art research exists.
- Tier C: working, low-frequency, in use.
- This document is the source-of-truth for a formal spec to be authored under
  SR-1.4 (`foundation/SR-1.4-ai-guidance/specs/`), and for documentation carried
  into the agentic-server spinoff project described in `DEV_TOOLKIT_PLAN.md`.
