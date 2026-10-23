# Structured Session Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store evidence-backed session state that reliably supplies unresolved issues to Call Brief and Handoff Brief across long, multichannel conversations.

**Architecture:** Extend the existing MCP memory episode record and atomic `commit_turn` with bounded structured topics/open items. The model proposes deltas; harness and memory service validate and apply them. Brief builders consume this state, while facts and live tool results remain authoritative for confirmed slots and freshness.

**Tech Stack:** Python 3.12, LangGraph, Pydantic, FastMCP, asyncpg/PostgreSQL, `unittest`, BTC JSON Schemas and mock tools.

**Spec:** [structured session memory design](../specs/2026-10-21-structured-session-memory-design.md); [existing brief contract design](../specs/2026-10-21-brief-contract-design.md).

## Global Constraints

- Preserve all user changes already present in the working tree; inspect the diff before editing a touched file.
- BTC amendments/mentor answers outrank the PDF; BTC tool schema/mock/reference evaluator define contracts. Do not alter BTC data.
- No runtime branching on `scenario_id`, sample labels, exact fixture text, fixture-only SKUs or dates.
- Use `request.on` for business validity; a prior price/promotion/stock value is historical until refreshed.
- PII stays outside prompts, checkpoints and traces except masked/ref forms; structured episode fields participate in verified erasure.
- Baseline removes prior-session memory only. Full and baseline use the same model, business tools, data and parameters.

## Review Focus

- A question answered later in the same session must disappear from `open_questions` without deleting its evidence: Task 2 tests it.
- A customer changes their mind about one product while discussing another: Task 2 tests independent scopes and replacement.
- A long session reaches the narrative limit before its final decision: Task 3 tests that the latest outcome remains represented.
- Two people share a phone or identity is ambiguous: Task 4 tests that no foreign episode enters a brief.
- Erasure starts while a turn is being committed: Task 1 tests that structured items cannot survive or be recreated by that write.

---

### Task 1: Durable episode contract and atomic storage

**Files:**
- Create: `ai-services/migrations/0009_structured_episodes.sql`
- Create: `ai-services/app/mcp_servers/mcp_memory/services/episode_state.py`
- Modify: `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py`
- Modify: `ai-services/app/mcp_servers/mcp_memory/services/memory.py`
- Modify: `ai-services/app/mcp_servers/mcp_memory/schemas.py`
- Test: `ai-services/test/test_structured_episode_memory.py`
- Test: `ai-services/test/test_memory_postgres_integration.py`
- Test: `ai-services/test/test_memory_erasure_workflow.py`

**Interfaces:**
- `apply_episode_delta(previous: dict, delta: dict, *, source_turn_id: str, customer_text: str, agent_text: str, prior_open_items: dict[str, tuple[str, str]] | None = None) -> dict` returns a validated, bounded episode state. A topic has `{scope_type, scope_id, customer_goal, advice_given, next_step, items}`. Each item has `{item_id, kind, text, status, source_turn_id, evidence_quote}`; `kind` is `blocker` or `question`, `status` is `open` or `resolved`. A resolution within this episode updates the item; a resolution of a prior episode adds an evidence-backed `resolved_prior_items` marker by item ID.
- `memory.write(action="commit_turn", data={..., "episode_delta": ...})` accepts an optional delta; `memory.read` returns `current_episode` and the `topics` of prior `episodes` without changing BTC tool names/arguments. `include_prior=false` returns only the current episode.

- [ ] **Step 1: Write failing tests** for atomic turn/fact/episode write, duplicate `operation_key`, owner mismatch, erasure block, read with `include_prior=false`, and purge of structured episode data. Assert no structured item is visible after a failed transaction or completed erasure.
- [ ] **Step 2: Run** `cd ai-services && .venv/bin/python -m unittest test.test_structured_episode_memory test.test_memory_erasure_workflow -v`; confirm the new contract tests fail for missing fields/storage.
- [ ] **Step 3: Add migration** with `topics jsonb NOT NULL DEFAULT '[]'::jsonb`, `resolved_prior_items jsonb NOT NULL DEFAULT '[]'::jsonb`, `status` (`active`/`closed`) and schema-version column on `ai_memory.episodes`; keep old `summary`/`outcome` rows readable as empty topics. Do not rewrite legacy summaries or synthesize open issues from them.
- [ ] **Step 4: Implement** `apply_episode_delta` and repository read/upsert support. Require bounded arrays/text, known status/kind, stable IDs, valid source turn, exact evidence within the committed masked turn, and valid scope; reject malformed/PII-bearing deltas rather than persisting them. Validate in the service even if MCP input was validated. Keep the turn, accepted facts and episode update in one DB transaction under the existing session/erasure locks.
- [ ] **Step 5: Run** the focused unit and PostgreSQL integration tests where a disposable DB is available; expect PASS and verify migration rollback/forward instructions in `ai-services/README.md` if that file documents migration application.
- [ ] **Step 6: Commit** only the task's files after review, if the execution workspace is a dedicated branch/worktree; do not commit unrelated existing changes.

### Task 2: Evidence-checked model proposals and state transitions

**Files:**
- Create: `ai-services/app/agent/memory/episode_candidates.py`
- Modify: `ai-services/app/agent/implementations/business_agent.py`
- Modify: `ai-services/app/agent/harness/agent_nodes.py`
- Modify: `ai-services/app/agent/harness/context.py`
- Modify: `ai-services/app/agent/harness/state.py`
- Modify: `ai-services/app/agent/memory/store.py`
- Test: `ai-services/test/test_episode_candidates.py`
- Test: `ai-services/test/test_deep_memory.py`

**Interfaces:**
- `accepted_episode_delta(customer_text: str, agent_text: str, proposal: object, current_episode: dict, tool_calls: list[dict]) -> dict` returns only accepted additions/resolutions/narrative. Every new open item has an exact masked evidence substring from this turn; a resolution cites an existing item and current-turn evidence. Scope is `unknown`, `global`, `product` or `room`; product/room association requires current-turn or verified-state support. Unknown association stays `unknown`.
- Extend `MemoryStore.commit_turn(..., orders=None, episode_delta=None) -> dict`; preserve old callers and idempotency key.

- [ ] **Step 1: Write failing tests** using non-sample paraphrases/products for opening a question/blocker, resolving it later, changing a decision, two product scopes, and an unaffected control. Also test fabricated quote, unsupported scope, PII, duplicate item and absent/malformed model proposal; assert accepted facts remain untouched by the proposal.
- [ ] **Step 2: Run** `cd ai-services && .venv/bin/python -m unittest test.test_episode_candidates test.test_deep_memory -v`; confirm expected failures.
- [ ] **Step 3: Extend the existing final-answer JSON prompt** with an optional `episode_delta` proposal; carry `memory.read.current_episode` into turn state, parse the proposal in the agent node and run `accepted_episode_delta` after answer verification. Do not add a mandatory second LLM call to every turn. Feed the accepted delta to `commit_turn`; if proposal validation fails, commit the turn/facts with an empty delta and record a bounded validation reason.
- [ ] **Step 4: Run** focused tests and existing memory contract tests; expect PASS. Inspect generated prompts/traces to confirm raw identity/PII and proposed text do not leak.
- [ ] **Step 5: Commit** only task files after review in the isolated execution workspace.

### Task 3: Long-session rolling summary and episode finalization

**Files:**
- Modify: `ai-services/app/mcp_servers/mcp_memory/services/episode_summary.py`
- Modify: `ai-services/app/mcp_servers/mcp_memory/services/memory.py`
- Test: `ai-services/test/test_structured_episode_memory.py`
- Test: `ai-services/test/test_mcp_memory.py`

**Interfaces:**
- `build_episode_summary(confirmed_facts: list[dict], recent_turns: list[dict], max_chars: int, *, episode_state: dict | None = None) -> str` keeps the existing caller working and returns a masked, bounded summary emphasizing current outcome/open items and relevant scoped facts. A malformed/absent delta still yields a conservative summary.

- [ ] **Step 1: Write failing tests** for a 30+ turn session where a late answer resolves an early question, a late preference supersedes an old one, and multiple products exceed the character budget. Assert the final summary includes the latest state or a pointer to structured facts, never a misleading partial list; replay leaves it unchanged.
- [ ] **Step 2: Run** `cd ai-services && .venv/bin/python -m unittest test.test_structured_episode_memory test.test_mcp_memory -v`; confirm the long-session regression fails.
- [ ] **Step 3: Implement rolling summary** from current structured state plus bounded recent turns/facts. Preserve evidence in turns and references rather than expanding the narrative. Keep per-turn snapshot usable without an explicit close event; leave `status=active` until the system has a verified close signal. Derive `outcome` from verified customer/tool events rather than model prose.
- [ ] **Step 4: Run** focused tests; expect PASS and inspect a masked long-session snapshot.
- [ ] **Step 5: Commit** task files after review in the isolated execution workspace.

### Task 4: Call Brief at session recognition

**Files:**
- Modify: `ai-services/app/agent/harness/context.py`
- Modify: `ai-services/app/agent/harness/session_nodes.py`
- Modify: `ai-services/app/agent/harness/runtime.py` only if needed to keep response/trace emission consistent
- Test: `ai-services/test/test_scoped_context.py`
- Test: `ai-services/test/contract_briefs.py`
- Test: `ai-services/test/test_deep_memory.py`

**Interfaces:**
- `load_context(...)` consumes `current_episode` and prior `episodes[*].topics`. A new-session predicate uses durable `memory.read.turn_count == 0`, not process-local cache, so workers agree on first-turn emission. Brief output stays `CallBrief`/BTC schema.

- [ ] **Step 1: Write failing tests** for first returning turn with open blocker/question, second turn returning `call_brief=None` and no repeat refresh, new/ambiguous identity, Fanpage-to-hotline same customer, shared-phone different customer, baseline `include_prior=false`, and a current product different from the most recent episode. Assert `must_not_ask` derives from valid scoped facts and `stale_warnings` only from current-date tool checks.
- [ ] **Step 2: Run** `cd ai-services && .venv/bin/python -m unittest test.test_scoped_context test.contract_briefs test.test_deep_memory -v`; confirm failures before changes.
- [ ] **Step 3: Build Call Brief** at the recognized session's first turn from current customer identity, latest prior episode and unresolved items across relevant prior episodes. Filter resolved items; do not convert legacy prose into open items. Use the existing freshness path on `request.on` only for relevant products. Include identity/read/refresh time in `latency_ms`; set `precomputed_parts` only for parts already stored before this session.
- [ ] **Step 4: Run** focused tests and BTC Call Brief JSON Schema validation; expect PASS. Check response/trace emits the object once while subsequent turns still receive current working memory.
- [ ] **Step 5: Commit** task files after review in the isolated execution workspace.

### Task 5: Handoff consumption, erasure, and evaluation evidence

**Files:**
- Modify: `ai-services/app/agent/harness/handoff_brief.py`
- Modify: `ai-services/app/agent/harness/context.py` only for state plumbing
- Modify: `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py` only if erasure test exposes a gap
- Test: `ai-services/test/contract_briefs.py`
- Test: `ai-services/test/test_memory_erasure_contract.py`
- Test: `ai-services/test/test_memory_erasure_workflow.py`
- Modify: `docs/brief-contract-evidence.md`

**Interfaces:**
- `build_handoff_brief(state: TurnState, proposal: dict, clock: Callable[[], datetime]) -> HandoffBrief | None` keeps its signature and consumes current-session open items plus relevant prior open items; current-turn question and verified tool output take precedence. A resolved prior question never appears as open.

- [ ] **Step 1: Write failing tests** for unresolved prior question carried to handoff, question resolved during current session, multiple products with uncertain focus, failed/stale quote, erasure handoff and missing trusted phone. Validate final object against BTC Handoff Brief schema and underlying tool evidence.
- [ ] **Step 2: Run** `cd ai-services && .venv/bin/python -m unittest test.contract_briefs test.test_memory_erasure_contract test.test_memory_erasure_workflow -v`; confirm new tests fail as expected.
- [ ] **Step 3: Integrate** structured open items into handoff construction and keep current-turn evidence first. Ensure the existing special erasure path says the request was escalated, not that data was deleted. Purge the new episode fields with the existing customer episode deletion; do not add untracked copies to trace/vector/checkpoint.
- [ ] **Step 4: Run** all AI service tests, BTC brief/tool contracts, backend tests and `git diff --check`; expect PASS. If a disposable DB and real MCP/LLM are configured, run full and `baseline_no_memory` on the same text cases with clean isolated state, validate JSONL against `trace_log.schema.json`, and report RQR/CCR/TSR/HR plus latency with `reference_eval.py`. Record exact commands, environment and limits in `docs/brief-contract-evidence.md`.
- [ ] **Step 5: Commit** task files after review in the isolated execution workspace; report any unrun PostgreSQL/MCP HTTP/LLM checks separately from mock/unit results.
