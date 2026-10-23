# Text Harness Brief Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Call Brief and ordinary handoff brief evidence-backed, BTC-schema-valid outputs of the text-to-text harness, then verify their effect on relevant harness behavior.

**Architecture:** Keep identity, memory and tool facts in the existing LangGraph state. Treat model-proposed handoff fields as candidates; harness code constructs the trusted brief and MCP order validates it before persistence. Call Brief continues to use persisted facts and dated tool refreshes, with an accurate session count and latency boundary.

**Tech Stack:** Python 3.12, Pydantic v2, jsonschema, unittest, LangGraph, PostgreSQL and the existing three MCP servers.

**Spec:** `docs/superpowers/specs/2026-10-21-brief-contract-design.md`; BTC `schemas/call_brief.schema.json`, `schemas/handoff_brief.schema.json`, `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md`, `eval/mock_tools.py`.

## Global Constraints

- Scope is **text-to-text harness**. Do not add ASR, UI or a new MCP server.
- BTC adjustments/mentor answers take precedence over the PDF; schemas define brief shapes; mock tools define tool results. Public sample is regression evidence, not runtime logic.
- Use verified `customer_id` and trusted channel identity; shared phone alone cannot select profile or order. Keep raw PII out of model prompt, logs and exported trace; the controlled handoff/order tool may receive the trusted phone.
- Historical quote, promotion and stock remain dated history. Refresh with `request.on` before a current claim. Unknown/failed refresh is `null` plus a warning, never an invented current value.
- No `scenario_id`, answer label, sample phrase, fixture customer or fixture SKU branch in runtime.
- Read relevant files and `git status` before edits. Preserve the user's current changes in `ai-services/app/agent/chat.py` and untracked `ai-services/report.json`; stage only this plan's files if committing.
- Existing memory, identity and erasure contract tests remain unchanged as evidence unless a demonstrably wrong assertion conflicts with BTC source. Report fake-model, BTC mock, MCP HTTP and real-LLM checks separately.

## File Map

| File | Responsibility in this plan |
|---|---|
| `ai-services/test/contract_briefs.py` | Explicitly run BTC-schema and evidence contract; starts red and becomes green. |
| `ai-services/test/test_mcp_business.py`, `test_deep_memory.py`, `test_scoped_context.py` | Service, harness and returning-customer regression controls. |
| `ai-services/app/agent/harness/handoff_brief.py` | Construct one safe handoff brief from state and a bounded model proposal. |
| `ai-services/app/agent/harness/policy.py`, `implementations/business_agent.py` | Apply handoff preconditions and accept a real queued ticket. |
| `ai-services/app/mcp_servers/mcp_order/services/order.py` | Validate handoff values before writing a ticket. |
| `ai-services/app/agent/harness/context.py`, `session_nodes.py`, `runtime.py` | Render returning-customer Call Brief and measure its latency. |
| `ai-services/app/mcp_servers/mcp_memory/services/memory.py`, `repos/postgres.py` | Supply all prior episode IDs separately from the capped episode display list. |
| `docs/brief-contract-evidence.md` | Baseline, final commands/results, limits and behavior decisions. |

## Review Focus

1. Two customers share a phone: neither brief may import the other's fact before verification (Tasks 1, 3, 4).
2. Two SKUs have the same quoted price: a handoff/Call Brief must keep SKU-specific provenance and avoid guessing the active SKU (Tasks 1, 3, 4).
3. Model supplies all required handoff keys with empty or wrong-typed values: no ticket may be created (Tasks 1, 2).
4. Tool returns a ticket without `status=queued`: the agent must not tell the customer transfer succeeded (Tasks 1, 3).
5. CRM lookup is slow and a promo refresh fails: Call Brief latency includes lookup and promo status stays unknown (Tasks 1, 4, 5).

---

### Task 1: Capture the brief contract and current red baseline

**Files:** Create `ai-services/test/contract_briefs.py`, `docs/brief-contract-evidence.md`.

**Interfaces:** Tests load BTC schemas by path at test time with `Draft202012Validator` and `FormatChecker`; runtime has no dependency on the BTC directory. The contract tests are run explicitly with `-p 'contract_briefs.py'` until green.

- [ ] Add tests using synthetic names/SKUs/wordings outside public sample: (a) returning customer with two rooms and two priced products, (b) ordinary medical/out-of-scope handoff with an unresolved question, (c) invalid model brief, (d) ambiguous shared phone, (e) ticket with wrong status, (f) slow identity plus failed refresh. Validate emitted brief objects against BTC schemas and assert provenance, `must_not_ask`, ticket status, PII boundary and no over-escalation.
- [ ] Run `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_briefs.py' -v`; record each expected red assertion and its owning layer in `docs/brief-contract-evidence.md`. Keep existing green safety tests green; do not weaken the contract to fit current output.
- [ ] Review test inputs against `schemas/tools.schema.json` and `eval/mock_tools.py`; add one unaffected control for an ordinary answer without handoff. Do not make test assertions depend on one exact model phrase or public-sample score.
- [ ] Stage only the new contract/evidence files if committing this baseline; mark red tests as planned work in the evidence document.

### Task 2: Reject invalid handoff briefs at the MCP order boundary

**Files:** Modify `ai-services/app/mcp_servers/mcp_order/services/order.py`, `ai-services/app/schemas/brief.py` only if its BTC-compatible field validation needs strengthening, `ai-services/test/test_mcp_business.py`.

**Interfaces:** `handoff(repo, session, args, customer_id, phone) -> dict` keeps its existing signature. Successful result remains `{ticket_id, status: "queued", brief_ok: true}`. Invalid brief returns `{"error": "brief_invalid"}` with a bounded reason and makes no `insert_handoff` call.

- [ ] Add failing service tests for required keys present but `conversation_summary` shorter than 20, illegal `escalation_reason`, wrong `product_advised`/price type, malformed phone and empty `next_action`; assert `repo.handoffs == 0`. Keep the existing valid retry test, updating its synthetic brief to satisfy the BTC schema.
- [ ] Run `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'test_mcp_business.py' -v`; confirm the new malformed-value tests fail.
- [ ] Validate `brief` with `HandoffBrief.model_validate` before identity checks or insert. Convert `ValidationError` to a sanitized `brief_invalid`, preserve trusted-phone/owner checks, and store `model_dump(mode="json")` so `generated_at` is a JSON date-time. Do not load the BTC package at runtime.
- [ ] Rerun focused service tests and the BTC-schema contract for valid and invalid handoffs; confirm no ticket on invalid content. Commit only this slice after review.

### Task 3: Build ordinary handoff briefs from verified state

**Files:** Create `ai-services/app/agent/harness/handoff_brief.py`; modify `ai-services/app/agent/harness/policy.py`, `ai-services/app/agent/implementations/business_agent.py`, `ai-services/test/test_deep_memory.py`, `ai-services/test/contract_briefs.py`.

**Interfaces:** `build_handoff_brief(state: TurnState, proposal: dict, clock: Callable[[], datetime]) -> HandoffBrief | None`. `None` means no trusted phone or insufficient supported content, so `prepare_tool_call` returns `None`. The model still decides whether to request transfer; code owns the final brief.

- [ ] Add failing tests: the model's fake customer phone/name/price is replaced by trusted state; two equal-price SKUs stay distinct and `product_advised`/price are `null` when current SKU is ambiguous; recent customer question survives in `open_questions`; a no-phone chat does not call handoff; a normal sales question does not get forced into handoff; an error or ticket without `queued` does not set `needs_handoff`.
- [ ] Run explicit contract and focused harness tests; confirm red assertions are about brief assembly/result handling, not model wording.
- [ ] Construct a 20–800 character, masked `conversation_summary` from current turn plus relevant confirmed history. Copy only supported product/quote/promo from matching SKU facts or successful tool observations; keep prior prices labeled as history. Bound `facts_confirmed` and `history_refs`; include the unresolved customer question and a concrete next action for the proposed reason. Inject trusted identity, channel and `generated_at` in code. Keep the existing erasure-specific handoff path and its qualified customer wording.
- [ ] Have `prepare_tool_call` pass the resulting model dump to `handoff.transfer`. In `BusinessTools.invoke`, set `needs_handoff` only for `status == "queued"` with a nonempty string ticket ID and no error. Rerun contract, `test_deep_memory.py`, `test_memory_erasure_contract.py`, `test_memory_erasure_workflow.py` and `test_mcp_business.py`; commit this slice after review.

### Task 4: Complete returning-customer Call Brief content

**Files:** Modify `ai-services/app/agent/harness/context.py`, `ai-services/test/test_scoped_context.py`, `ai-services/test/test_memory_freshness_contract.py`, `ai-services/test/contract_briefs.py`.

**Interfaces:** `load_context(state, memory, tools, clock) -> dict` keeps its signature and returns `call_brief: dict | None`. Existing `CallBrief` response shape remains compatible with BTC schema.

- [ ] Add failing tests for a Fanpage → hotline return, two rooms and two products with equal historical prices, a different current quote, a failed promo refresh, a changed blocker, and an ambiguous identity control. Assert `profile_facts` retains room IDs/source, `must_not_ask` includes confirmed scoped slots, `quoted_on` comes from the fact's `on`, `promo_still_active` is `true`/`false` only from the dated quote and otherwise `null`, and no customer PII enters `prompt_context`.
- [ ] Run focused tests to confirm present omissions. Update Call Brief rendering to keep scoped constraints and per-SKU history separate; build a short suggested opening that confirms one relevant prior point, and a grounded `suggested_next_action`. Preserve old quote as historical even when current price changes. Do not refresh all four old SKUs unless the current turn names them; an unrefreshed SKU has unknown current promo status.
- [ ] Rerun focused tests, `test_deep_memory.py` and the explicit brief contract. Check at least one phrasing/product variant and one ordinary single-product control; commit this slice after review.

### Task 5: Make session count and Call Brief latency honest

**Files:** Modify `ai-services/app/mcp_servers/mcp_memory/repos/postgres.py`, `services/memory.py`, `ai-services/app/agent/harness/runtime.py`, `session_nodes.py`, `context.py`, `ai-services/test/test_mcp_memory.py`, `test_deep_memory.py`, `contract_briefs.py`.

**Interfaces:** `MemoryRepo.prior_session_ids(conn, customer_id: str, session_id: str) -> list[str]` returns distinct prior episode IDs independent of `max_episodes`; `memory.read` adds optional `prior_session_ids`. `load_context` counts the union of these IDs and CRM session IDs, excluding the active session. The existing `episodes` list remains capped for prompt size.

- [ ] Add failing tests where seven prior sessions are stored but only five summaries loaded, and one CRM session duplicates a memory episode; assert `n_previous_sessions == 7`, not 5 or 8. Add a timing test with an injected slow identity/tool boundary and assert `latency_ms` includes it, while a failed refresh leaves `promo_still_active == null`.
- [ ] Run focused tests and confirm current capped count and post-identity timer are the causes. Add the separate ID query/read field; do not send all IDs to the model prompt. Start the monotonic timing before `initialize_identity` in `AgentHarnessRuntime.run`, preserve it through `SessionNodes.accept`, and compute brief latency after all freshness checks. Keep `precomputed_parts` limited to parts actually produced before this turn.
- [ ] Rerun focused tests and memory service tests, then one PostgreSQL test on an isolated DB for distinct count if local DB setup permits. Commit this slice after review.

### Task 6: Verify the text-to-text harness and document limits

**Files:** Modify `docs/brief-contract-evidence.md`; add tests only for a concrete uncovered failure.

**Interfaces:** No new runtime API.

- [ ] Run `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_briefs.py' -v`, then the default AI test suite, `test_mcp_business.py`, relevant backend tests and `git diff --check`. Explicit brief contract must be green without changing previous memory/erasure evidence tests.
- [ ] Run text-to-text scenario variants with BTC mock tools, including handoff and returning-customer cases; compare tool calls, brief schema and source facts. If isolated DB and current LLM/MCP endpoints are available, run the public sample as text input with the same model/tools under `full` and `baseline_no_memory`, reset mutable eval state between runs, validate JSONL against `schemas/trace_log.schema.json`, and score with BTC `reference_eval.py`. Do not connect ASR.
- [ ] Record exact commands, result counts and limitations by fake model/BTC mock/MCP HTTP/real LLM. Report Call Brief p95 from measured fields and false handoff rate alongside BTC metrics; do not infer hidden-test score from public sample. Review the diff for sample-specific branches and accidental changes to the user's `chat.py` or `report.json` before committing docs.

## Self-review and execution gate

Tasks 1–5 cover both BTC brief shapes, evidence selection, identity/PII, freshness, success status, session count and latency. Task 6 checks the text harness only. The five Review Focus cases are pinned to named tests above. No task edits ASR, BTC data or evaluation labels. The current checkout has user changes, so an executor must preserve them and stage narrowly; no implementation or commit is authorized merely by writing this plan.
