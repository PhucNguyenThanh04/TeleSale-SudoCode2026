# Erasure, Scoped Memory and Long Episodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fulfil a verified customer's erasure request within an explicitly approved data scope, then retain distinct facts for each product and room across long conversations.

**Architecture:** Keep the customer-facing request as a handoff; execute erasure only through an authenticated internal workflow keyed by verified `customer_id`. Use PostgreSQL as the structured fact source, add explicit fact scope rather than packing multiple values into one slot, and build episode summaries from validated persisted facts plus a bounded recent-turn tail. Treat external traces, immutable BTC seed data and backups as separate inventory items with their own completion evidence.

**Tech Stack:** Python 3.12, LangGraph, MCP memory, PostgreSQL, backend PostgreSQL, unittest; existing Langfuse 4.x only where enabled. No new memory store.

**Spec:** `docs/superpowers/specs/2026-10-20-multisession-memory-contract-design.md`, `docs/memory-contract-v1.md`, `docs/memory-policy.md`; BTC `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md`, `schemas/tools.schema.json` and `eval/mock_tools.py`.

## Global Constraints

- Read `git status` and relevant files before edits; preserve the current uncommitted work. Create an isolated worktree at execution time only if it does not strand these changes.
- Do not treat a phone number, channel identity or handoff ticket as proof of customer ownership. A human verifies identity and authorizes scope before the internal erasure job starts.
- A fact's `op=delete` retracts one fact; it never means whole-customer erasure. Do not expose a purge action to the sales agent or expand the BTC `memory.write` contract to do so.
- Do not mutate the original BTC package. Avoid fixture IDs, `scenario_id`, answer labels and sample phrases in runtime branches.
- Keep quote, promotion and stock facts as dated history. Recheck them with business `on` from the call before making current claims.
- Keep PII out of prompt, episode, checkpoint and trace; do not log credentials or raw erasure payloads.
- Report unit/mock, PostgreSQL, MCP HTTP, public sample and real LLM evidence separately. Use an isolated seeded eval DB for full versus baseline.
- An erasure job may report `completed` only for the approved scope after every required store reports completion; otherwise report `pending`, `partial` or `failed` with a sanitized reason.

## Review Focus

- Shared phone with two customer IDs: an erasure request must not affect either record until one owner is verified (Task 2 test).
- Concurrent `commit_turn` during erasure: after the erasure barrier, no new fact or episode may reappear (Task 3 test).
- A backup restore or BTC reimport must not resurrect a suppressed customer profile (Task 4 test).
- Two SKUs with the same quoted price or stock value must keep separate provenance and current-state refreshes (Tasks 6 and 7 tests).
- Two rooms in one utterance, an ordinal room reference, and a hypothetical comparison must produce only the justified scoped facts (Task 6 test).

---

## Phase A — Erasure contract and authorized execution

**Proposed scope for Task 1 review:** Delete customer-owned rows from `ai_memory` and verified customer sessions/messages in the backend. Delete or deidentify runtime callbacks, handoffs, orders and operation payloads only when an ownership link is proven and the approved retention rule permits it; otherwise mark that store pending for an operator. Leave the original BTC files intact and suppress any retained BTC seed rows from runtime reads and future imports. Check JSONL files, Langfuse and backups by deployment: absence of a configured sink is a verified `not_applicable` result, while an unreachable or unknown sink remains `pending`. Redis currently appears to hold a connection only, but Task 1 must verify whether deployment uses it for customer state. These are proposed choices, not an approved deletion policy.

### Task 1: Approve the erasure matrix before destructive implementation

**Files:** Create `docs/erasure-contract.md`; modify `docs/memory-policy.md`.

**Interfaces:** Produces the approved matrix consumed by Tasks 2–4. No runtime changes.

- [ ] Inventory `ai_memory` (`turns`, `episodes`, `facts`, `pending_facts`, `order_links`, `write_operations`), backend chats, `app_runtime` orders/updates/callbacks/handoffs/promo uses/operations, `btc_source` CRM and orders, JSONL traces, Langfuse if enabled, Redis and backups. Record owner, selector, whether the store has customer content, and deletion/retention capability.
- [ ] Write the proposed decision for each store: delete, deidentify, suppress from runtime, retain under a documented rule, or outside team control. For every retained copy record owner, reason and end condition. Do not infer a legal retention period from this plan.
- [ ] Specify identity evidence, who may approve the request, scope (`customer_id` and separately identified sessions), shared-phone treatment, retry/idempotency, failure states, and the exact wording permitted at `queued`, `partial` and `completed`.
- [ ] Obtain user approval of that matrix before implementing or running physical erasure. If BTC seed data, external traces or backups cannot be removed, prohibit an unqualified “all data deleted” claim and document the remaining copies.
- [ ] Check the document against the six-case contract and the actual table inventory; record any store that cannot be addressed by an automated executor.

### Task 2: Internal erasure request and read barrier

**Files:** Create `ai-services/migrations/0007_erasure_requests.sql`, `ai-services/app/mcp_servers/mcp_memory/services/erasure.py`, `ai-services/test/test_memory_erasure_workflow.py`; modify `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py`, `ai-services/app/mcp_servers/mcp_memory/services/memory.py`, `ai-services/app/agent/harness/context.py`.

**Interfaces:** `ErasureRequest(customer_id, verified_by, scope, request_key)` is an internal service input, never an agent tool argument. Persist `request_key`, status and sanitized per-store results. `MemoryRepo.is_erasure_blocked(conn, customer_id: str) -> bool` gates reads and writes.

- [ ] Add failing tests: unverified/shared-phone inputs cannot enqueue; the same request key is idempotent; a blocked customer returns no prior profile/episode/Call Brief; another customer sharing the phone remains readable.
- [ ] Run the focused tests and confirm they fail for absent workflow/barrier.
- [ ] Add the migration and an authenticated operator entrypoint or CLI using the approved identity evidence; use `customer_id`, never phone alone. Block memory read/write as soon as a verified request enters processing.
- [ ] Run focused unit and PostgreSQL transaction tests; verify the barrier survives process restart and two workers.
- [ ] Commit only the files for this task after review.

### Task 3: Delete runtime-owned records with a resumable executor

**Files:** Create `ai-services/app/mcp_servers/mcp_memory/repos/erasure.py`, `ai-services/app/mcp_servers/mcp_memory/services/erasure_executor.py`, `backend/app/services/erasure.py`, `ai-services/test/test_erasure_postgres.py`, `backend/test/test_erasure.py`; modify migrations only as required by the approved matrix.

**Interfaces:** `execute_erasure(request_key: str) -> ErasureResult` returns per-store counts/status without PII. Each store handler is retry-safe. Cross-database progress is recorded per store; no false all-or-nothing transaction claim.

- [ ] Add failing seeded-DB tests for every runtime-owned table in the approved matrix. Include a customer with two channels, another customer with the same phone, and anonymous or mixed-owner turns. Assert that only verified ownership is selected and legacy `write_operations.result` cannot restore a deleted fact.
- [ ] Run those tests and confirm the expected failure. Add an interleaving test for a concurrent `commit_turn` and a worker retry after one store succeeds.
- [ ] Implement one store at a time, using stable customer/session/order selectors and transactions within each database. Avoid deleting by phone across all customers. Use the existing backend service boundary for backend chats and the owning MCP repo for each AI runtime store.
- [ ] Run focused unit and PostgreSQL tests, then retry the same job and confirm no records reappear or duplicate side effects occur.
- [ ] Commit the reviewed slice.

### Task 4: External copies, replay protection and completion proof

**Files:** Modify `dataloader_offline/` import path and its tests if the approved matrix requires suppression; create `docs/erasure-operations.md`; add focused tests in `ai-services/test/` and `backend/test/`.

**Interfaces:** The erasure executor consumes per-store completion evidence. A sanitized receipt lists completed, retained and pending stores; it contains no raw customer text or phone.

- [ ] Add failing tests for BTC reimport and backup restore rehearsal: a suppressed customer must not become readable again. Verify JSONL/trace and Langfuse behavior according to the approved matrix; read current Langfuse documentation before any API implementation.
- [ ] Implement the approved suppression/trace/backup procedure and an operator verification command that re-queries each store without printing PII. Keep the BTC source package untouched.
- [ ] Confirm `completed` is impossible while any required store is pending, unreachable or restored. Confirm the agent still says only that the request was transferred until the authorized workflow reports completion.
- [ ] Run the erasure contract, backend and PostgreSQL integration tests; document manual dependencies and retention limits in `docs/erasure-operations.md`.
- [ ] Commit the reviewed slice.

## Phase B — Scoped product and room memory

### Task 5: Add a scoped fact schema without losing existing facts

**Files:** Create `ai-services/migrations/0008_scoped_facts.sql`; modify `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py`, `ai-services/app/mcp_servers/mcp_memory/services/memory.py`, `ai-services/test/test_mcp_memory.py`, `ai-services/test/test_scoped_fact_migration.py`.

**Interfaces:** Each fact has `scope_type` in `global|product|room` and `scope_id` (`''` for global, verified SKU for product, stable room identifier for room). Active uniqueness and supersession use `(customer_id, scope_type, scope_id, key)`; `memory.read` exposes global profile plus scoped facts in a stable, backward-compatible shape. Existing facts remain global unless their original provenance proves a narrower scope.

- [ ] Add failing tests for two active SKU quotes and two active room areas, superseding only one scope, and legacy single-slot reads. Test migration against a temporary PostgreSQL schema and assert no guessed backfill of ambiguous legacy rows.
- [ ] Run tests to confirm the current `(customer_id,key)` uniqueness and profile dict lose scoped values.
- [ ] Add columns/checks/indexes and repository lookups keyed by scope. Reject a product scope without a catalog-confirmed SKU and a room scope without an evidence-backed room identifier; preserve source turn, `on_date` and status.
- [ ] Run focused service and migration tests, including retry/idempotency and deletion of one scoped fact without touching another.
- [ ] Commit the reviewed slice.

### Task 6: Bind candidates and reports to the right scope

**Files:** Modify `ai-services/app/agent/memory/fact_candidates.py`, `ai-services/app/agent/memory/reported_facts.py`, `ai-services/app/agent/guardrails/checks.py`, `ai-services/app/agent/harness/agent_nodes.py`; extend `ai-services/test/contract_memory_updates.py` and focused `test_*.py` tests.

**Interfaces:** Candidate and committed fact dictionaries carry `scope_type`/`scope_id`; room IDs are resolved from an explicit room mention or a previously unambiguous room reference. Tool observations bind `sku` from tool arguments/results before report validation; identical values alone cannot associate a claim with a SKU.

- [ ] Add failing tests for two products quoted in one answer, equal prices across two SKUs, two stock results, two named rooms in one utterance, an ordinal room correction, a hypothetical room, and a single-product/single-room control using different wording and products from the public sample.
- [ ] Run focused tests to confirm the present key-only conflict and diacritic-folded hypothetical cue errors.
- [ ] Pass and validate scope through model proposals, tool candidates, evidence checks, accepted candidates and `commit_turn`. When the reference is ambiguous, reject or defer that fact with a reason; do not assign it to the most recent SKU or room by guess.
- [ ] Run focused tests and the existing memory/guardrail suite. Update the extraction prompt only to propose scope; code remains the final authority.
- [ ] Commit the reviewed slice.

### Task 7: Render scoped context and refresh dated product facts

**Files:** Modify `ai-services/app/agent/harness/context.py`, `ai-services/app/schemas/brief.py` if its shape must change, and focused context/freshness tests.

**Interfaces:** Prompt context and Call Brief expose separate room constraints and per-SKU sales history. Each old SKU that may be discussed has an independent current quote/stock lookup using `request.on`; historical observations remain marked historical.

- [ ] Add failing tests for two room areas in `customer_facts`, four SKU histories without cross-assigned quote/KM/stock, same customer across channels, a return after eight months, and a control where no stale SKU is discussed.
- [ ] Run tests to confirm the current single `product_advised` refresh path loses association.
- [ ] Render scoped facts with provenance, mask PII, and refresh only the product set needed for the current turn within tool-call/latency limits. When refresh cannot complete, mark that product unverified and block a current price/stock claim.
- [ ] Run focused tests, BTC mock tests with `on` from each call, and the AI unit suite.
- [ ] Commit the reviewed slice.

## Phase C — Long episode and end-to-end evidence

### Task 8: Build a bounded, evidence-based episode summary

**Files:** Create `ai-services/app/mcp_servers/mcp_memory/services/episode_summary.py`; modify `ai-services/app/mcp_servers/mcp_memory/services/memory.py` and episode tests.

**Interfaces:** `build_episode_summary(confirmed_facts, recent_turns, max_chars: int) -> str` emits a masked summary that preserves each distinct advised SKU, each active room constraint, the latest explicit correction and outcome before optional recent dialogue. It never turns historical quote/stock into a current claim.

- [ ] Add failing tests for the 16-turn/four-product case, two rooms, superseded facts, PII in legacy turns, and one ordinary short call. Assert stable ordering and the configured size bound.
- [ ] Run the tests to confirm the current last-three-turn summary drops early products.
- [ ] Build the summary from persisted validated facts after the turn transaction writes them; allocate space to required structured items before the optional recent-turn tail. If the bound cannot hold all required items, store structured episode items separately and render a bounded view rather than silently dropping an item.
- [ ] Run focused tests, including cross-session retrieval and Call Brief consumption.
- [ ] Commit the reviewed slice.

### Task 9: Verify the full contract and record the remaining limits

**Files:** Modify `docs/memory-contract-v1.md`, `docs/memory-policy.md`; add integration tests only for uncovered behavior.

**Interfaces:** No new runtime API.

- [ ] Run `ai-services/.venv/bin/python -m unittest discover -s ai-services/test -p 'contract_*.py' -v` from repo root and the default AI/backend/eval suites. The known long-conversation red cases must pass without weakening their assertions; preserve the original evidence tests.
- [ ] Run PostgreSQL migrations 0006–0008 and MCP HTTP tests on an isolated database; verify the six scenarios, including erasure receipt and no cross-customer disclosure. Do not apply erasure to BTC source or a production DB.
- [ ] Restore or confirm the `eval/` package, then run full and `baseline_no_memory` with the same model/data/tool settings on separately reset eval state. Validate JSONL against `schemas/trace_log.schema.json` and score with BTC `reference_eval.py`; report RQR, CCR, TSR, HR and latency.
- [ ] Run `git diff --check`. Record exact commands/results and unresolved limits, especially any external trace or backup operation that was only rehearsed.
- [ ] Commit docs and final reviewed changes.

## Execution order and decision gate

Task 1 is a policy gate. Tasks 2–4 implement only its approved matrix; a partial matrix produces a qualified receipt, never a blanket deletion claim. Tasks 5–8 can proceed on an isolated development DB after that gate even if an external store requires a manual operation. Task 9 is the final acceptance gate. Existing dirty changes must be reviewed and preserved before any commit or worktree operation.
