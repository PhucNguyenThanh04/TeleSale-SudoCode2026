# Structured session memory for Call Brief and Handoff Brief

Approved in conversation on 2026-10-21. This design extends the existing
text-to-text harness and the previously approved brief contract design.

## Intent and boundaries

Persist a useful, evidence-backed account of each session so a returning
customer's Call Brief and a live Handoff Brief can explain what remains to be
done. BTC specifies the brief outputs, not the internal episode format. Preserve
the existing CRM identity boundary, PostgreSQL as source of truth, per-turn
memory commit, fact provenance, PII masking, erasure workflow, and BTC tool
names/arguments. No ASR, UI, new MCP server, or sample-specific routing.

## Session record

An episode has session/customer identity, channel, business date, outcome,
updated time, short masked narrative, and structured topics. Each topic is
scoped to a product or room when known and contains the customer's goal,
advice given, outstanding blockers/questions, and next step. Every open item
has a stable ID, status (`open` or `resolved`), a source turn, and evidence.
Unknown scope stays explicit; it must not be attached to an arbitrary SKU or
room. A later session can record an evidence-backed resolution by the earlier
item ID; readers suppress that item without rewriting the earlier episode.
Fact and order IDs remain references to their authoritative records;
quote provenance stays in existing dated tool/fact records when no quote ID is
available. Empty topic/open-item lists are valid.

Persist a usable snapshot after each successful turn; an explicit close event
may mark the episode closed but is not required to produce a summary. A late
change or resolution must update the snapshot even after a long call. Bound
the narrative without dropping the latest state or early product references,
and retain the underlying
turns/facts as evidence. Use request business date, never wall-clock date, for
business validity.

## Model and service responsibilities

The LLM may propose narrative and open-item changes, with cited text from the
current customer or agent turn. The harness validates the proposal's shape,
source text, scope and PII, and the memory service applies valid changes in
the same idempotent transaction as the turn and accepted facts. A proposal
cannot directly alter confirmed profile facts, tool results, identity, order
IDs, or ownership. Unsupported or failed extraction degrades to a conservative
snapshot from verified facts/turns; it must not invent a blocker or question.
Resolved items stay available as history but are excluded from brief open lists.

## Brief lifecycle

At the first turn of a newly recognized returning session, read the latest
cross-channel episodes/facts, filter open items, and refresh time-sensitive
price, promotion and stock information for relevant products. Emit one Call
Brief for that session; subsequent turns use working memory and on-demand
business tools without rebuilding the brief. `must_not_ask` comes from valid,
appropriately scoped facts. `stale_warnings` is computed at recognition and
never stored as a permanent episode conclusion. Latency includes identity,
memory read and refresh as required by BTC; `precomputed_parts` reports only
the episode narrative/structure actually prepared before the session.

Handoff Brief uses the current turn and verified tool results alongside open
items from the current session and relevant prior episodes. It retains the
existing trusted-phone and handoff-result checks. It must not claim an old
price is current or imply that an erasure request has already been fulfilled.

## Verification

Exercise status transitions, paraphrases and products outside public sample,
cross-channel return, shared phone/ambiguous identity, long sessions, replay,
erasure, missing/failing model proposals, and a non-returning control. Validate
both briefs against BTC schemas and tool evidence. Run isolated PostgreSQL/MCP
and full/baseline text-to-text evaluation when available, reporting these
separately from unit/mock results. Public sample is regression evidence, not
the specification.
