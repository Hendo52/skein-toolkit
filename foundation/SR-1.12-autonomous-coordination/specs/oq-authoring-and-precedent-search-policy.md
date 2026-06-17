# OQ Authoring and Precedent-Search Policy — SR-1.12

| Field | Value |
|-------|-------|
| **Lifecycle** | Draft |
| **System Req (primary)** | SR-1.12 |
| **Issue** | — |
| **Owning files** | `architecture-docs/global/architect-open-questions.md`, `architecture-docs/governance/oq-decision-triage.md`, `scripts/local-mcp.py` (`_format_step_ambiguity_oq`, `_raise_step_ambiguity_oq`) |

---

## 1 — Purpose

The Open Question (OQ) ledger (`architecture-docs/global/architect-open-questions.md`) is the repo's primary mechanism for routing genuine architectural judgment calls to the System Architect without either (a) an agent guessing and silently committing the repo to a path the architect would not have chosen, or (b) an agent stalling indefinitely on every fork it meets. Over 500 OQs have been raised and resolved through this surface (see `architecture-docs/governance/oq-decision-triage.md` for the disposition of the first ~170).

That volume is itself the problem this spec addresses. Two failure modes have emerged at scale:

1. **Low-quality OQs** — questions raised about choices the architect doesn't actually care about (implementation order, naming, color schemes — anything cheap to change later), or questions that don't actually present a real tension (one option is obviously correct, but it's framed as a 50/50 choice anyway). These cost the architect attention without returning a decision worth making centrally.
2. **Redundant OQs** — questions that a *prior* OQ, somewhere in the 500+ already on record, already answered — sometimes on the *exact* same subject under a different name. Re-asking wastes the architect's time and, worse, risks getting a *different* answer the second time, silently forking the codebase's de-facto architecture into two contradictory precedents.

This spec defines (a) what makes an OQ worth raising at all, (b) the mandatory precedent-search step that must happen before raising one, and (c) the structural template a well-formed OQ follows. It governs both human-authored OQs and automated ones (e.g. the orchestrator's `_raise_step_ambiguity_oq` in `scripts/local-mcp.py`, and any future escalation paths built on the same pattern).

### Relationship to the Task and OQ Authoring Standard (ADR-011)

[`task-and-oq-authoring-standard.md`](../../../architecture-docs/governance/task-and-oq-authoring-standard.md)
(ADR-011) defines the portable, project-agnostic OQ **field schema** -- `ID`,
`Question`, `Options`, `Preemptive Answer`, `Reversibility`, `Context / Spec`,
`Unblocks`, `Date Added` / `Status` -- and the Decomposition Gate that routes
high-level requests into AT/OQ rows in the first place. This spec is the
content-authoring layer underneath that schema: §3-5 govern *whether* an OQ
should exist and *how it fits into the decision-routing loop*, and §6's
structure template is the recommended shape for what goes inside the
`Question` and `Context / Spec` cells. Where the two specs overlap on "what
makes an OQ well-formed", this spec is authoritative for OQ content in this
repository; ADR-011 is authoritative for the field list and table format.

---

## 2 — Design-Goal Linkage

- **Primary owner:** SR-1.12 in [architecture-docs/global/design-goals.md](../../../architecture-docs/global/design-goals.md)

SR-1.12 owns the queue/dashboard/open-question operating loop (`autonomous-execution-coordination.md`). This spec is a sibling to that one: where `autonomous-execution-coordination.md` defines *how the OQ ledger behaves as a coordination surface* (lane isolation, hot/cold temperature, reintegration), this spec defines *what makes an individual entry on that surface worth its place* — the authoring discipline that keeps the surface signal-dense rather than noisy. A coordination loop that is mechanically sound but flooded with low-value or duplicate entries is just as broken as one with no loop at all.

---

## 3 — The Materiality Filter: Is This Actually an OQ?

Before drafting anything, an agent must clear this filter. **An OQ is for decisions that matter — choices with lasting architectural consequence that are genuinely hard to reverse, or that ripple into many other decisions.** It is not a generic "I'm not 100% sure, better ask" outlet.

**Raise an OQ when:**
- Two or more paths are each individually defensible, and the choice will be expensive to unwind later (data model shape, ownership boundaries, public contracts, which subsystem is responsible for what, anything that other in-flight or planned work will build on top of).
- The "right" answer depends on information only the architect has — business priorities, commercial constraints, risk tolerance, prior verbal decisions not yet written down.
- Getting it wrong would not just require a revert, but would invalidate work built on top of the wrong choice in the meantime.

**Do not raise an OQ when:**
- The choice is cheap to change later (implementation order, variable/file naming within convention, which of two equally-valid libraries to prototype with first, color/cosmetic choices with no UX research backing either). The correct self-answer here is *"pick whichever is easier to build, and if it's wrong, it's a small, local fix"* — note that reasoning in the work log if it seems likely someone will wonder why you picked one over the other, but do not escalate it.
- One option is actually, on reflection, clearly better — and you can articulate *why* concretely. If you can write the recommendation section (§6.4) with total conviction and no real counter-argument, you don't have a question; you have a decision. Make it, document the reasoning where the work lands, and move on.
- The question is really "please do my analysis for me" — if grep, the spec index, `git log`, or fifteen minutes of reading would resolve it, that is research debt, not an architectural fork (see CLAUDE.md "Research First").

A bad OQ is recognizable by the architect shrugging and writing back "I don't care, your call" — if you can predict that response with confidence, don't ask; that confidence *is* your answer.

---

## 4 — Mandatory Precedent Search

**Before drafting a new OQ, search the existing record for a question that already covers this ground.** With 500+ entries on the live ledger plus the historical OQ-100-series triaged into `oq-decision-triage.md`, the probability that *something adjacent* has already been decided is high — often on the exact subject, sometimes on a structurally identical one from a different subsystem (e.g. "should X be user-configurable or auto-computed" has been answered more than once, in more than one domain, with a consistent architectural philosophy each time).

### 4.1 — Search procedure

1. **Grep the live ledger** (`architecture-docs/global/architect-open-questions.md`) for keywords describing the *subject* of your question (the noun, not the verb — "zone classification" not "should I"), and separately for keywords describing the *shape* of the decision ("user-configurable", "auto-computed", "feature flag", "Option A/B/C pattern" relevant to your fork).
2. **Grep `architecture-docs/governance/oq-decision-triage.md`** — this is where the historical OQ-100-series decisions were redistributed; many durable architecture calls (bucket 1) and spec/task-routed decisions (bucket 2) live here in summarized form, with pointers to where the full decision now lives.
3. **Check the owning spec** for your subsystem in `architecture-docs/specs/INDEX.md` — a "Notes" column entry referencing an OQ ID is a strong signal that this exact ground has been covered (e.g. INDEX.md row for `regression-testing-and-quality-gates.md` cites the architect-approval date directly; rows for design-goal-linked specs frequently cite "Architect directive: OQ-100-NN").
4. **Check `design-goals.md`** for "Architect directive: OQ-..." citations near the SR your question concerns — these mark settled precedent at the design-goal level, the most durable kind.

### 4.2 — What to do with what you find

| Finding | Action |
|---|---|
| **Exact precedent** — an existing OQ answers this question, on this subject, with no material difference in context | Do not raise a new OQ. Apply the existing answer directly, and cite the precedent OQ ID in your work log / commit message so the lineage is traceable (e.g. "per OQ-100-32: teal zone is the volume-consolidation target, applying that classification here"). |
| **Adjacent precedent, same philosophy, different subsystem** — a structurally identical question was answered elsewhere with a consistent architectural stance | Apply the same philosophy by analogy, and say so explicitly in your work log (e.g. "OQ-216 settled persistent-serialized-toggle as the pattern for GUI feature switches; applying the same shape here for consistency rather than re-litigating it"). If you are not confident the analogy holds, that uncertainty *is* a legitimate reason to raise a new OQ — but the OQ itself must name the precedent and explain precisely why this case might be the exception (§6.1). |
| **Partial precedent that conflicts with current circumstances** — an old OQ answered this, but something material has changed since (a later architectural pivot, a new constraint, a downstream consequence the original answer didn't anticipate) | Raise a new OQ. It must explicitly reference the prior OQ ID, state what it decided, and explain *why this case is different enough to warrant revisiting it* — this is the "course-correction" mode described in §7, and it is exactly the situation the OQ mechanism exists to handle gracefully rather than silently overriding or silently complying with stale guidance. |
| **No precedent found** | Proceed to draft a new OQ per §5/§6, noting in the OQ's context section that a search was performed and came up empty (this is itself useful signal to the architect — "nothing like this has been decided yet" is different from "I didn't look"). |

### 4.3 — Why this is not optional

Skipping precedent search has two failure costs, both expensive:
- **Architect fatigue** — re-answering the same question erodes trust in the OQ surface as a high-signal channel, making the architect less likely to engage promptly with *genuinely* novel questions.
- **Silent architectural forking** — if a re-asked question receives a *different* answer than its precedent (architects are human; context drifts; phrasing differs), the codebase now has two contradictory "official" answers to the same question, each defensible by citing a real OQ. This is far worse than either redundancy or an unanswered question — it actively corrupts the precedent record itself.

---

## 5 — The Dual Purpose of an OQ (read this before drafting)

A well-formed OQ serves two distinct modes, and should be written with both in mind:

1. **Rapid-fire approval of good defaults.** Most OQs should be answerable by the architect skimming the recommendation and options, and replying "yes, go with your recommendation" in seconds. This is the dominant case at scale — hundreds of OQs have been resolved this way. Optimize for *scannability*: a clear subject line, a tight options table, a recommendation that stands on its own.
2. **Steering correction when a guess went wrong.** When an agent has already committed to a path (by necessity, or by a prior OQ's recommendation) and that path turns out to create problems downstream, a *custom* architect answer to a follow-up OQ becomes the mechanism for course-correcting the architecture — not just this one decision, but potentially the chain of decisions built on top of it. **This is the load-bearing case.** A custom answer here often represents a genuine pivot, and pivots ripple: expect (and explicitly invite, in the OQ's "Unblocks" framing) the possibility that resolving this one correctly will surface *further* OQs as its implications propagate outward. Do not write an OQ in a way that forecloses this — leave room in the framing for "actually, the right fix is something none of these options describe" as a valid, expected kind of answer.

The mechanism, end to end, is what prevents two opposite failure modes simultaneously: an agent spinning through an unbounded space of micro-decisions alone (Option-B-style runaway), and an agent freezing every time it meets a fork (Option-A-style paralysis). The OQ ledger is the controlled middle path — and its value compounds over time *only if* each entry is worth the architect's attention and the record stays internally consistent (§4).

---

## 6 — OQ Structure Template

Every OQ — human-authored or automated — follows this shape. (The live ledger's table row uses the field schema from ADR-011's `task-and-oq-authoring-standard.md` Part 2 — `ID | Question | Options | Preemptive Answer | Reversibility | Context / Spec | Unblocks | Date Added / Status` — as the *index* row; the structure below is what the **Question**, **Options**, **Preemptive Answer**, and **Context / Spec** fields should actually contain, expanded inline or via a linked doc for anything non-trivial.)

### 6.1 — Problem statement (high detail, not a one-line snippet)

Explain **what is actually being encountered, and — critically — why it isn't a straightforward choice.** The architect needs enough detail to understand the *tension*: usually two (or more) genuinely valid possibilities where neither is clearly superior on the evidence available. State:
- What triggered this question (the concrete situation, file, decision point — link to it).
- What makes each candidate path *plausible* — not just "option A" and "option B" as labels, but the reasoning that makes each one a real contender.
- What's actually at stake if the wrong one is picked (§3's materiality test, made concrete for this specific case).

A terse "should X be A or B?" without this context forces the architect to reconstruct the tension from scratch — defeating the purpose of routing the decision to them in a pre-digested form.

### 6.2 — Precedent search note

One line confirming §4 was performed and what it found (exact precedent applied without escalation / adjacent precedent found and why this case may differ / no precedent found). This is mandatory — see §4.3.

### 6.3 — Options, each with real pros and cons

Present every path seriously considered (typically 2–4; lettered A/B/C/...). For each:
- **What it is** — concrete enough to picture the resulting architecture.
- **Pros** — what it genuinely buys you.
- **Cons** — what it genuinely costs, including second-order effects (maintenance burden, what it forecloses later, what other in-flight work it would conflict with).

Avoid strawmen. If one option is listed only to be dismissed in two words, it isn't a real option — either develop it honestly or drop it and explain in §6.1 why it didn't make the cut.

### 6.4 — Recommendation, held loosely

State which option you'd lean toward **and why** — but frame it as input to the architect's decision, not a fait accompli ("My inclination is **Option B**, because — but I'm not confident the {specific consideration} doesn't tip this toward A; that's exactly the part I can't judge from here"). The reasoning is the valuable part: it lets the architect either confirm quickly ("yes, B, as you said") or correct precisely ("no — and here's the consideration you're missing"), which is a far more useful reply than a bare "A" or "B" would be to give *or* to receive.

### 6.5 — Unblocks

What concretely becomes possible, or stops being blocked, once this is answered — and, per §5(2), an explicit acknowledgment when a "yes, but differently than any option above" answer would itself likely cascade into further questions. Naming that possibility up front normalizes it as a legitimate, expected outcome rather than a surprising detour.

---

## 7 — The Course-Correction Lifecycle

This is the pattern that makes the OQ mechanism more than a decision-routing inbox — it is how the architecture *self-corrects* over time:

1. An agent faces a fork, raises an OQ with a recommendation (§6.4), and — in the common case — receives a quick confirmation. Work proceeds on that basis.
2. Sometimes the chosen path later proves wrong: it creates friction, contradicts a fact discovered downstream, or simply doesn't survive contact with a more complex case than the one that prompted the original question.
3. When that happens, the *symptom* (the friction, the contradiction, the failure) is itself the trigger for a **new** OQ — one that does §4's precedent search, finds the prior OQ as the relevant precedent, and explicitly frames the question as "this earlier decision is creating {concrete problem}; here's what I think the options are now."
4. A **custom** architect answer here (one that doesn't match any of the original options) is not a failure of the OQ process — it is the process working as intended: surfacing exactly the kind of judgment call that couldn't have been made correctly without the benefit of what was learned by trying the original path. Expect — and explicitly invite via §6.5 — the possibility that this answer ripples into further OQs as its implications propagate through dependent decisions.

In short: the OQ ledger is not a one-shot gate at the start of a body of work. It is a **standing architectural-memory and steering mechanism** — it prevents an agent from spinning through an unbounded decision space alone, *and* it gives the architect a structured channel to revise course in light of what the work itself reveals, without that revision getting lost as an offhand verbal correction that the next agent never sees.

---

## 8 — Reference Examples

`architecture-docs/governance/oq-decision-triage.md` is the single richest source of worked examples — it classifies and summarizes the disposition of OQ-100-1 through OQ-100-170 plus AQ-13/AQ-14, spanning everything from durable architecture calls (bucket 1, e.g. OQ-100-28 "architectural ceiling angular threshold") to operational guidance (bucket 3) to settled-and-archived historical context (bucket 4). Reading a sample of bucket-1 and bucket-2 entries there, alongside their corresponding `design-goals.md` "Architect directive: OQ-..." citations, is the fastest way to internalize what a *durable, worth-asking* architectural question looks like in this repo versus one that was ultimately routed elsewhere as operational detail.

The live ledger (`architecture-docs/global/architect-open-questions.md`) carries the active and recently-resolved entries (OQ-2xx series and beyond at time of writing) and is the first place §4's search should look.
