# Memory & Brief Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LangMem-backed memory store carry everything a returning-customer brief needs (orders, open and resolved blockers, per-product advice, TTL), starting from the typed proposal schemas in `app/schemas/langmem.py`.

**Architecture:** Keep the current safety model: the LLM only *proposes*, deterministic admission verifies against committed turns and tool results, and the worker writes versioned records to `runtime.store`. Changes are additive (store records stay `schema_version: 1`, new fields optional), so no SQL migration is needed. Fields derivable from tool results (quoted prices, actions, tool facts) move from LLM output to deterministic code.

**Tech Stack:** Python, Pydantic, LangMem, LangGraph `AsyncPostgresStore`, PostgreSQL, unittest.

**Spec:** `MEMORY_IMPROVEMENT_PLAN.md` (findings 1-12), BTC `schemas/call_brief.schema.json`, `PB-01`, `KM-01/09`, `FAQ-16`.

## Review Focus

- The admission rule "literal customer evidence" stays. Only the *wiring* changes: the model supplies `text` plus a literal `evidence_quote`, and `evidence_supports(text, quote)` checks the pair.
- Tool facts keep the `reported_tool_candidates` rule (a quote/advice counts only if the agent actually said it). This is deliberate. It is **not** changed; the SAMPLE-01 failure there is agent behaviour (recommending the wrong SKU), not memory.
- Old store records and old `langmem_distillation_jobs.accepted_proposals` must still load (read new keys with `.get`).
- Brief latency must stay well under 5 s p95 (currently ~60-91 ms).

## Task 0: Baseline

**Files:** none (record results in the PR description).

- [x] Run `.venv/bin/python -m unittest discover -s test -v` from `ai-services/` and record failures.
- [x] Run the PostgreSQL integration tests with `MEMORY_INTEGRATION_ADMIN_DSN` set; record that `test_mixed_session_keeps_anonymous_turn_and_marks_unowned_pending` currently fails (`'completed' != 'partial'`).
- [x] Decide whether that failure is a test or a product bug (read `erasure_executor.py`, expected `partial` when pending facts of an unowned turn remain). Fix or document before changing memory code.
- [x] Re-run `eval_harness` on `SAMPLE-01..07` and keep the JSONL as the "before" snapshot (existing `enabled_public_full.jsonl` may predate the working tree).

## Task 1: Episode proposal schema (`app/schemas/langmem.py`)

**Files:** `app/schemas/langmem.py`, `test/test_langmem_extractor.py`, `test/test_langmem_primary.py`, `test/test_langmem_admission.py`.

- [x] Add `EvidencedText(SafeProposal)`: `text: str` (1-300), `evidence_quote: str` (8-200). A `mode="before"` validator coerces a plain `str` into `{text: s, evidence_quote: s}` so old callers and tests keep working.
- [x] Add `ResolvedItem(SafeProposal)`: `item_id: str`, `evidence_quote: str`.
- [x] Add `TopicProposal(SafeProposal)`: `scope_type: Literal["global","product","room"] = "global"`, `scope_id: str = ""`, optional `customer_goal`, `advice_given`, `next_step` (each `EvidencedText`), `open_items: list[OpenItemProposal]` (`kind: blocker|question` + `EvidencedText`), `resolved_items: list[ResolvedItem]`. Validate scope rules like `apply_episode_delta` (`product`/`room` need a non-empty safe `scope_id`).
- [x] In `CustomerCallEpisodeCandidate`: replace `topics: list[dict[str, Any]]` with `topics: list[TopicProposal]`; type `open_blockers` and `open_questions` as `list[EvidencedText]` (coerced from `str`); keep top-level `customer_goal` and fold it into an `unknown`-scope topic.
- [x] Remove `products_discussed`, `quoted_prices`, `actions_completed` from the LLM-facing model (they are computed deterministically in Task 3). Keep `QuotedPrice` as an internal type and retarget `test_price_in_episode_is_historical_and_sourced`.
- [x] `ProfileFactCandidate`: keep `valid_until` but document it as **set only by deterministic code**; add a validator `valid_until >= observed_on`.
- [x] Update asserts that compare `open_blockers` to plain strings (`test_langmem_extractor.py` line ~104, `test_langmem_primary.py` line ~199) to compare `.text`.
- [x] Run: `python -m unittest test.test_langmem_extractor test.test_langmem_primary test.test_langmem_admission`.

## Task 2: Extractor prompt and inputs (`app/agent/memory/langmem_extractor.py`)

**Files:** `langmem_extractor.py`, `distiller_worker.py`, `test/test_langmem_extractor.py`.

- [x] Add an `open_items` argument to `extract_candidates` and include `{item_id, text, scope_type, scope_id}` of open blockers/questions from **earlier sessions of the same customer** in the latest turn payload (masked, `item_id` added to `_OPAQUE_FIELDS`).
- [x] Rewrite `_INSTRUCTIONS`: give `text` (normalised, e.g. "cần hỏi chồng") and a *literal* `evidence_quote`; propose `resolved_items` only when the customer or agent states the dependency is settled; use `advice_given` / `next_step` per product topic; do not emit prices or tool facts.
- [x] Worker: build `open_items` from `projector.list_episode_versions` (exclude the current session, skip ids already in `resolved_prior_items`).
- [x] Test: payload passed to the manager contains the prior open items and no unmasked PII.

## Task 3: Admission and deterministic episode data (`langmem_admission.py`, `distiller_worker.py`)

**Files:** `app/mcp_servers/mcp_memory/services/langmem_admission.py`, `distiller_worker.py`, `episode_state.py` (read-only check), new tests.

- [x] Rewrite `admit_episode_candidate` to emit one `topic_update` per `TopicProposal` with real `scope_type`/`scope_id`. Product scope is accepted only if the SKU appears in the turn's tool calls or the customer text; otherwise downgrade to `global`.
- [x] Gate each item with `evidence_quote in customer_text` (literal, case-insensitive) **and** `evidence_supports(text, quote)`. This replaces `blocker.casefold() in source.casefold()` and keeps the existing literal-evidence guarantee.
- [x] Emit `advice_given` / `next_step` / `customer_goal` using `narrative_evidence_quote` (quote may come from customer **or** agent text, as `apply_episode_delta` already allows for narrative fields).
- [x] Emit `resolve_items` only for ids in the supplied `prior_open_items`; pass `prior_open_items` to `apply_episode_delta` (today it is never passed, so cross-session resolution always raises).
- [x] Compute deterministically from `tool_observations` (no LLM): `actions_completed` (`order.create`, `schedule.callback`, `handoff.transfer`) and per-product quoted price/date. Store them in the stored proposal under new optional keys.
- [x] Worker line ~124: take blocker text/quote from the new objects; keep the "promote first blocker to the `blocker` slot" behaviour, now with `text` as value and `evidence_quote` as proof.
- [x] Read stored `accepted_proposals` with `.get()` so retries of old jobs still work.
- [x] Tests: SAMPLE-01-style flow (call_1 blocker "để chị hỏi ông xã", call_2 "ông xã đồng ý rồi") ends with the blocker `resolved`; a normalised-but-supported blocker is admitted; an unsupported one is rejected; topic scope is `product` when a quoted SKU exists.

## Task 4: Fact persistence and key limits

**Files:** `langmem_projection.py`, `services/memory.py`, `app/constants.py`, `context.py` (`_split_facts`), tests.

- [x] `put_facts`: persist `valid_until` (ISO string) when present; `read` returns it in the public fact; `_split_facts` copies it.
- [x] `_valid_fact`: validate `valid_until` as an ISO date.
- [x] Set `valid_until` deterministically: `promo_expiry` fact → the promo `valid_until`; no TTL for other slots yet.
- [x] Widen scoped keys: `_PRODUCT_KEYS` += `size`, `color`, `preferred_size`, `preferred_color`, `blocker`, `objection`; `_ROOM_KEYS` += `has_children`, `product_advised`. Keep `_valid_scope` strict for everything else.
- [x] `constants.py`: set `brief_must_not_ask=True` for `price_quoted_vnd`, `competitor_price_vnd`, `order_id`, `size`, `preferred_size`, `color`, `preferred_color`, `payment` (the slots BTC lists in `must_not_ask`). Do **not** add `blocker`, `objection`, `in_stock`.
- [x] Add slots that real BTC scenarios use: `owned_sku` (source: `crm.get_customer` orders; needs `fact_evidence` support), `callback_scheduled` (source: `schedule.callback`), `alt_suggested` (tool/agent). Defer `region` until we decide whether to read it from CRM or from the address (address is PII, masked).
- [x] **Do not add `phone_provided`.** Phones are masked in memory (PB-08); a phone given in chat belongs to identity linking, not to a stored fact.
- [x] Tests: facts round-trip with `valid_until`; scoped `size`/`color` per product; `must_not_ask` in a brief contains the expected slots when known.

## Task 5: Brief assembly (`context.py`, `brief.py`, new `brief_opening.py`)

**Files:** `app/agent/harness/context.py`, new `app/agent/harness/brief_opening.py`, `app/schemas/brief.py`, `session_nodes.py`/`prompt_context`, tests.

- [x] Fill `CallBrief.orders` from `owned_order_ids` plus CRM orders (`order_id`, `variant_sku` if known, `status`); add `orders` / `remembered_order_ids` to `prompt_context`.
- [x] Open blockers/questions: show only `status == "open"` and not in `resolved_prior_items` (already supported by `_open_episode_items`; assert it with a test).
- [x] Refresh: cap at the 3 most recent advised SKUs, run `inventory.check` and `pricing.get_quote` with `asyncio.gather`, and drop the "only when ≤1 product" restriction. Keep the warning when a SKU was not refreshed.
- [x] Stale warnings: add (a) last session older than 180 days → "xác nhận lại địa chỉ giao hàng"; (b) fact with `valid_until < call date`; (c) discontinued SKU with `successor_sku`. For (c) first check which MCP tool exposes `attributes.discontinued/successor_sku`; if none does, extend the catalog service rather than reading the DB from the agent.
- [x] Move opening generation to `build_suggested_opening(brief_state)`: greet by honorific/name, confirm at most two items (product + blocker) as a confirmation question, never restate an old price when its promo expired, vary by `last_session.outcome`.
- [x] Tests: multi-product brief (SC11 shape) refreshes up to 3 SKUs; refresh latency does not grow linearly (mock tools with delay); stale warnings for the three cases; opening mentions ≤2 facts.

## Task 6: Measure memory directly

**Files:** new `eval_harness/memory_recall.py`, `eval_harness/benchmark_runner.py`, tests.

- [x] After each `call_n`, wait for distillation, then compare the store with that call's `facts_established`: per-slot presence, exact match for numeric/SKU slots, `evidence_supports` for free-text slots (`blocker`).
- [x] Report recall/precision per slot and per scenario next to CCR/RQR so "not written" and "not used" can be told apart.
- [x] Known data issue: SAMPLE-01 `facts_established.budget_vnd` is `5700000` while the customer says "tầm 5 triệu". Treat budget as a tolerance match (±15%) or exclude it, and note it in the report.
- [x] Out-of-scope dependency to note: `catalog.search` hard-filtering `budget_vnd` hides `SKU-AP-Y` (5.2M) for a "tầm 5 triệu" budget. This is catalog/agent behaviour and must be handled separately for TSR.

## Task 7 (decision needed): Synchronous floor and store hygiene

- [x] Decide whether to write deterministic facts (reported tool facts, `customer_slot_cues`) synchronously at `commit_turn`, with LangMem enriching later. Today a callback before the worker finishes sees an empty profile. This reverses part of the "LangMem only, no sync writes" decision, so it needs explicit approval. *(Kept LangMem-only async architecture per `2026-10-31-langmem-only-runtime.md`; `eval_harness` waits for job completion between turns.)*
- [x] Add compaction of superseded fact/episode revisions in `runtime.store`; today every read scans all versions and opens a new store connection (`list_fact_versions`, `list_episode_versions`).

## Task 8: Verify

- [x] Full unit suite and PostgreSQL integration tests green (or the known failure documented).
- [x] Re-run `eval_harness` on `SAMPLE-01..07` and `SC01..SC19`; compare with the Task 0 snapshot on CCR, RQR, TSR, brief `orders`/`open_blockers`/`stale_warnings`, and `memory_recall`.
- [x] Measure `call_brief_latency_ms` with 1, 3 and 4 advised SKUs; p95 must stay under 5000 ms.
- [x] Update `ai-services/README.md` memory section and `docs/memory` notes; no SQL migration is expected, confirm `git status` shows none.

## Risks

- Changing the schema changes the tool schema shown to the LLM, so extraction quality can shift; keep temperature/seed fixed and compare before/after.
- Backward compatibility of `open_blockers` (str → object) is handled by the coercing validator, but any external caller constructing the model with positional data must be checked with `grep`.
- Relaxing evidence from "substring" to "quote + `evidence_supports`" is a deliberate loosening; keep the quote-in-customer-text requirement so a model cannot invent blockers.
