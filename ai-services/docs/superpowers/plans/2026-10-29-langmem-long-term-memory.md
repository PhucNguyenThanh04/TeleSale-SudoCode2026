# LangMem Long-Term Memory Implementation Plan

> Historical implementation plan. The active long-term store design is in
> `../specs/2026-10-30-langmem-primary-design.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-checked LangMem profile and call-episode distillation, persistent PostgreSQL recall, and BTC-compatible evaluation without weakening the current memory contracts.

**Architecture:** `ai_memory` remains canonical. A durable job after each committed turn feeds a separate LangMem worker; accepted proposals update canonical records and a derived `AsyncPostgresStore` projection. Verified customer identity gates recall, and existing business tools refresh time-sensitive claims.

**Tech Stack:** Python 3.11+, LangMem 0.0.30, LangGraph and `langgraph-checkpoint-postgres` 3.1.2, Pydantic, asyncpg, psycopg 3, PostgreSQL, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-langmem-long-term-memory-design.md`

## Global Constraints

- `ai_memory` is the source of truth; LangMem proposals and the LangGraph store never bypass memory admission rules.
- Use the verified CRM `customer_id` for every namespace; no memory is shared on a phone number alone.
- Store masked content only; preserve source turn/tool, scope, quote date, and supersession.
- Call Brief p95 must stay at or below 5 seconds for M1; current prices, promotions, stock, and policies come from dated business tools.
- Compare full and no-memory runs using the same model, model parameters, tools, dates, seeds, and CRM identity.
- Keep existing MCP contracts and turn-write idempotency. Do not commit secrets or customer PII.
- LangMem availability is opt-in via settings until the shadow and enabled runs pass the adoption gate.

## Review Focus

- Shared phone with ambiguous CRM match: no cross-customer read or write (Task 6 test).
- A correction phrased as a question or hypothetical: do not supersede an active fact (Task 3 test).
- Worker crashes after canonical admission but before projection: retry without duplicate facts (Task 5 test).
- Erasure races with an in-flight worker: barrier prevents recreation in either store (Task 7 test).
- Promotion expires between calls: brief retains the historical quote but does not present it as current (Task 6 test).

---

### Task 1: Make BTC evaluation a reliable gate

**Files:**
- Modify: `eval_harness/benchmark_runner.py`
- Modify: `eval_harness/extractor.py`
- Create: `eval_harness/reference_adapter.py`
- Modify: `eval_harness/test_eval_harness.py`
- Modify: `eval_harness/README.md`

**Interfaces:**
- Produce `reference_adapter.trace_line(...) -> dict` matching `BTC-Data-Vong1-TEAMS/schemas/trace_log.schema.json`.
- Produce `reference_adapter.facts_used(agent_text: str, tool_calls: list[dict], prior_facts: dict) -> list[str]`; count only evidence of meaningful use, not loaded keys.
- Runner accepts `--config full|baseline|both` and writes separate JSONL files consumable by BTC `reference_eval.py`.

- [ ] **Step 1: Write failing tests** asserting a loaded but unused profile fact does not enter `facts_used`; an explicitly used prior fact does; baseline keeps the same channel identity/CRM lookup; `call_brief_latency_ms` is emitted from `CallBrief.latency_ms`; `customer_turns_asr`, channel and per-call date are honored; output validates against BTC trace schema.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest eval_harness/test_eval_harness.py -q` and confirm the new tests fail for the intended reasons.
- [ ] **Step 3: Implement** the adapter and runner changes. Use the existing runtime's `memory.include_prior=False` for baseline and an isolated memory namespace/database fixture to prevent full-run contamination; do not change the phone or CRM response. Keep the BTC script unmodified.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest eval_harness/test_eval_harness.py -q` and a small public-sample run through the BTC `reference_eval.py`; confirm non-null call-brief timing for returning calls and valid JSONL.
- [ ] **Step 5: Commit** `fix(eval): produce faithful BTC memory comparison traces`.

### Task 2: Add typed LangMem proposals and model capability check

**Files:**
- Modify: `requirements.txt`
- Modify: `app/configs.py`
- Create: `app/schemas/langmem.py`
- Create: `app/agent/memory/langmem_extractor.py`
- Create: `test/test_langmem_extractor.py`

**Interfaces:**
- `ProfileFactCandidate` and `CustomerCallEpisodeCandidate` live in `app.schemas.langmem`; both carry `schema_version=1` and source references.
- `extract_candidates(model: BaseChatModel, turns: list[dict], existing: list[dict]) -> tuple[list[ProfileFactCandidate], CustomerCallEpisodeCandidate | None]` uses LangMem's `create_memory_manager` but performs no database writes.
- Settings: `langmem_mode: Literal['off','shadow','enabled']='off'`, `langmem_model: str | None=None`; default to configured `llm_model`.

- [ ] **Step 1: Write failing tests** for a profile correction, quoted price with date/tool source, blocker retained as open, empty/noisy model response returning no proposals, and rejection of unmasked PII at the schema boundary.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_extractor.py -q`; confirm the intended failures.
- [ ] **Step 3: Pin** `langmem==0.0.30`, define schemas, and implement the extraction adapter. Keep customer-call episode separate from LangMem's example experience-replay schema. Add a controlled smoke test using the configured model to confirm structured tool-calling support before enabling the feature.
- [ ] **Step 4: Run** the tests and dependency resolver; record the tested model and extraction failures without raw prompts or PII.
- [ ] **Step 5: Commit** `feat(memory): add typed LangMem proposal extraction`.

### Task 3: Admit proposals through canonical memory rules

**Files:**
- Create: `app/mcp_servers/mcp_memory/services/langmem_admission.py`
- Modify: `app/mcp_servers/mcp_memory/services/memory.py`
- Modify: `app/mcp_servers/mcp_memory/services/episode_state.py`
- Create: `test/test_langmem_admission.py`

**Interfaces:**
- `admit_profile_candidates(customer_id: str, session_id: str, candidates: list[ProfileFactCandidate], committed_turns: list[dict], tool_calls: list[dict]) -> tuple[list[dict], list[dict]]` returns accepted writes and bounded rejection codes.
- `admit_episode_candidate(customer_id: str, session_id: str, candidate: CustomerCallEpisodeCandidate, committed_turns: list[dict], tool_calls: list[dict]) -> dict | None` returns a delta compatible with existing episode state.
- Reuse `_write_fact` supersession and `apply_episode_delta`; never insert an unvalidated model document directly.

- [ ] **Step 1: Write failing tests** for exact customer/tool evidence, wrong customer/session, shared phone, hypothetical/negated correction, conflicting same-turn values, old quote versus current price, resolved blocker, and PII rejection.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_admission.py -q`; confirm failures.
- [ ] **Step 3: Implement** admission with a stable slot/scope mapping to the existing registry. A candidate outside the supported contract is rejected with a reason, not silently saved as arbitrary free text.
- [ ] **Step 4: Run** the new tests plus `.venv/bin/python -m pytest test/test_memory_refinements.py test/test_structured_episode_memory.py -q`.
- [ ] **Step 5: Commit** `feat(memory): validate LangMem proposals before persistence`.

### Task 4: Queue and process distillation outside the response path

**Files:**
- Create: `migrations/0010_langmem_distillation_jobs.sql`
- Modify: `app/mcp_servers/mcp_memory/repos/postgres.py`
- Modify: `app/mcp_servers/mcp_memory/services/memory.py`
- Modify: `app/agent/memory/store.py`
- Modify: `app/agent/harness/agent_nodes.py`
- Create: `app/mcp_servers/mcp_memory/distiller_worker.py`
- Create: `test/test_langmem_worker.py`
- Modify: `README.md`

**Interfaces:**
- `MemoryRepo.enqueue_distillation(conn, session_id: str, customer_id: str, source_turn_id: str, tool_observations: list[dict]) -> None` uses a unique `(session_id, source_turn_id)` key; observations are bounded, masked, and limited to successful business tools.
- `MemoryRepo.claim_distillation(conn, lease_seconds: int) -> dict | None` claims with `FOR UPDATE SKIP LOCKED` and a retryable lease.
- `process_one(repo: MemoryRepo, extractor, projector) -> bool` reads committed data, admits proposals, marks complete only after canonical write and projection result are recorded; jobs have bounded attempts and an error code.

- [ ] **Step 1: Write failing tests** for duplicate turn commit creating one job, job lease/reclaim after crash, per-session turn ordering, tool evidence available after restart, model timeout preserving the committed turn, and a repeated proposal producing no duplicate canonical fact.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_worker.py -q`; confirm failures.
- [ ] **Step 3: Add** the migration, repository methods, and opt-in worker entrypoint using the `mcp_memory` role. Capture bounded successful tool observations with the committed turn; process jobs in turn order per session. Hold the per-customer erasure advisory lock through admission and projection. The existing synchronous fact/episode path remains available until its replacement is proven; no response waits for the worker.
- [ ] **Step 4: Run** worker tests and the isolated PostgreSQL integration tests with dedicated test DB variables. Document one worker process, graceful shutdown, retry limits, and sanitized failure logs.
- [ ] **Step 5: Commit** `feat(memory): queue durable LangMem distillation`.

### Task 5: Add a derived AsyncPostgresStore projection

**Files:**
- Create: `migrations/0011_langmem_store.sql`
- Modify: `scripts/provision_mcp_roles.sh`
- Create: `scripts/setup_langmem_store.py`
- Create: `app/mcp_servers/mcp_memory/repos/langmem_projection.py`
- Create: `test/test_langmem_projection.py`
- Modify: `README.md`

**Interfaces:**
- `LangMemProjection.put_episode(customer_id: str, session_id: str, canonical: dict) -> None` upserts `('customers', customer_id, 'episodes')/session_id` with `schema_version=1`.
- `LangMemProjection.list_episodes(customer_id: str, limit: int) -> list[dict]` returns only that verified namespace; `delete_customer(customer_id: str) -> int` removes all of its namespace keys.
- Use `AsyncPostgresStore` with a dedicated `langmem_store` `search_path`; no `index`/pgvector in V1. Store DDL is applied once under admin/migration privileges, not at request startup.

- [ ] **Step 1: Write failing tests** for persistence across store instances, one customer never reading another's namespace, safe repeated upsert, idempotent delete, and retry after canonical admission but before projection.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_projection.py -q`; confirm failures.
- [ ] **Step 3: Implement** schema setup/role grants and projection. `0011` creates the schema and grants; a one-time admin command calls `AsyncPostgresStore.setup()` with a fixed `search_path` outside startup and outside a wrapping DDL transaction. Verify the installed 3.1.2 store SQL resolves only to `langmem_store`; keep database credentials out of the AI API.
- [ ] **Step 4: Run** projection tests on an isolated PostgreSQL DB and inspect created schemas/tables and grants; then run existing `test/test_memory_postgres_integration.py`.
- [ ] **Step 5: Commit** `feat(memory): persist validated recall projection`.

### Task 6: Use accepted memories in Call Brief and agent context

**Files:**
- Modify: `app/mcp_servers/mcp_memory/services/memory.py`
- Modify: `app/agent/memory/store.py`
- Modify: `app/agent/harness/context.py`
- Create: `test/test_langmem_recall.py`

**Interfaces:**
- `memory.read` adds `accepted_episodes` only when `langmem_mode='enabled'`; `shadow` records diagnostics but serves canonical memory.
- `load_context` ranks by current product/scope and open blocker, then date; it accepts only active canonical references. Missing/stale projection falls back to existing `episodes`.

- [ ] **Step 1: Write failing tests** for cross-channel same verified customer, ambiguous/shared-phone isolation, correction and supersession, multiple products without cross-wiring quoted prices, promotion expiry, and projection outage fallback.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_recall.py -q`; confirm failures.
- [ ] **Step 3: Implement** the opt-in read path and bounded brief/context selection. Keep existing dated `inventory.check` and `pricing.get_quote` refresh; `must_not_ask` includes only active non-expired facts.
- [ ] **Step 4: Run** the tests plus `.venv/bin/python -m pytest test/test_memory_freshness_contract.py test/test_memory_recovery.py -q` and verify Call Brief p95 in a sample run.
- [ ] **Step 5: Commit** `feat(memory): recall validated episodes in call brief`.

### Task 7: Make erasure cover canonical and projected memory

**Files:**
- Modify: `app/mcp_servers/mcp_memory/services/erasure_executor.py`
- Modify: `app/mcp_servers/mcp_memory/repos/postgres.py`
- Modify: `app/mcp_servers/mcp_memory/repos/langmem_projection.py`
- Create: `test/test_langmem_erasure.py`

**Interfaces:**
- `execute_erasure(repo, request_key: str, projector: LangMemProjection | None = None) -> dict` retains the existing shape and reports both canonical and projection results.
- A pending erasure barrier blocks worker admission and recall. Projection failure leaves status `partial`; retry finishes it without recreating canonical records.

- [ ] **Step 1: Write failing tests** for customer deletion, in-flight worker race, partial projection failure, retry, and no surviving namespace after completed erasure.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest test/test_langmem_erasure.py -q`; confirm failures.
- [ ] **Step 3: Implement** the barrier and both-store purge in the internal workflow; do not expose erasure as a sales-agent tool. Keep status truthful if another store in the requested scope is still pending.
- [ ] **Step 4: Run** new tests and `.venv/bin/python -m pytest test/test_memory_erasure_workflow.py test/test_memory_erasure_contract.py -q`.
- [ ] **Step 5: Commit** `fix(memory): erase LangMem projection with customer data`.

### Task 8: Measure the variant and set the release gate

**Files:**
- Modify: `eval_harness/benchmark_runner.py`
- Create: `eval_harness/compare_langmem.py`
- Create: `eval_harness/test_langmem_comparison.py`
- Modify: `eval_harness/README.md`
- Modify: `README.md`

**Interfaces:**
- `compare_langmem.compare(reference_reports: dict[str, dict]) -> dict` reports current, shadow, enabled, relative RQR reduction, CCR/TSR/hard TSR, HR, guardrails, Call Brief/total/TTFT p95, and cost per call.
- Keep raw BTC traces in ignored run artifacts; store only sanitized aggregate results in the repo.

- [ ] **Step 1: Write failing tests** for missing metric denominator, zero price/promo claims (report `null`, not 0%), no Call Brief samples, mismatched model/seed/date, and a regression in isolation/guardrails failing the release gate.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest eval_harness/test_langmem_comparison.py -q`; confirm failures.
- [ ] **Step 3: Implement** the comparison CLI and runbook. Run current, shadow, and enabled on the same 7 public samples and 19 local scenarios, exporting BTC JSONL and evaluating each with BTC `reference_eval.py` without changing it. Include a categorized failure report for each TSR miss.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest test eval_harness/test_eval_harness.py eval_harness/test_langmem_comparison.py -q`; validate the generated traces with BTC schema; inspect the full versus baseline table. Enable `langmem_mode='enabled'` for demo only if the spec's adoption gate passes.
- [ ] **Step 5: Commit** `test(memory): report LangMem ablation with BTC metrics`.

## Self-Review Checklist

- [x] Each spec requirement maps to a task: evaluation (1, 8), schemas (2), admission (3), durable formation (4), same-DB store (5), recall/freshness (6), erasure (7).
- [x] The plan pins LangMem 0.0.30, uses the inspected `AsyncPostgresStore` 3.1.2 API, and requires a model capability check and identical setup/runtime `search_path`.
- [x] No existing working-tree deletions or unrelated edits were staged or overwritten.
