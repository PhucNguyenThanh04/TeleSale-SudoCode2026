# Agent and context repairs

Goal: Fix the eight findings in the agent/context audit while preserving the current model-led runtime and mandatory authorization/grounding boundaries.

Work in the current checkout. Preserve existing edits. Do not create worktrees, delegate, add code comments, invoke live models, run benchmarks, or migrate databases.

## Tasks

- [x] Preserve customer quantities, payment and conditions around masked address spans. Verify address extraction, multiple addresses, masking idempotence and authorization payloads.
- [x] Preserve committed customer requirements beyond the recent conversation window, including anonymous sessions and pending distillation. Reuse committed source text; do not infer selection or consent through language rules.
- [x] Keep public product attributes and safe quote-context bindings through persistence. Verify identical commercial evidence decisions before/after serialization and failed-refresh invalidation.
- [x] Distinguish list-price filtering from final-price affordability. Verify the model receives an explicit list-price argument and unsupported final-affordability conclusions are rejected.
- [x] Bound repeated proposals without new evidence and preserve precise precondition errors. Verify recovery after new evidence, duplicate reads/writes and budget exhaustion.
- [x] Compute latest-session metadata chronologically and retain scope in known-field guidance. Verify relevance ordering cannot change recency or forbid questions about another room/product.
- [x] Remove duplicated context while retaining authoritative customer requirements and evidence. Bound auxiliary history with explicit disclosure when omitted.
- [x] Check request fulfillment and unnecessary clarification in the existing grounding review. Verify rejection/repair and fail-closed structured output.

## Verification

Write regression tests and observe relevant failures before implementation. Run focused tests through `ai-services/.venv/bin/python -m eval_harness.offline_tests`; do not run the entire suite. Record baseline contract/fixture mismatches separately from regressions. Review the complete resulting change against these eight requirements before marking the goal complete.

## Progress

- Initial checkout inspected; existing changes retained. Audit remains the scope authority.
- Address and scope regressions observed failing, then passing. Further address tests cover legitimate Anh Son/Minh Khai/Chi Lang components and unpunctuated spoken quantities.
- Source-history regressions observed failing, then passing for both anonymous and identified customers with 17 pending turns. SQL replay verifies older sources and session isolation.
- Single/basket quote serialization regressions observed failing, then passing, including changed private context, failed refresh barriers, large public evidence and late receipts.
- Catalog argument verified through the actual SDK conversion. SDK alias loss was caught and fixed using a real model-facing field with canonical MCP normalization.
- Proposal budgets, repeated blocked reads, precise missing-quote errors, model-round exhaustion and model-facing recovery names verified. A price mismatch now reuses existing quote evidence.
- Recency tests cover both relevance truncation and stale projected dates while newer committed turns remain pending.
- Request fulfillment, unnecessary clarification and constraint violations use the existing grounding inference. Customer-source changes invalidate write review.
- In-process catalog/order MCP and real graph replay passed for text and delivered voice after restart and 14 filler turns. The explicitly proposed basket creates exactly once with correct per-unit prices and bank payment, without repeating commercial reads.
- Final focused offline command covered the two new regression files plus model-owned conversation, semantic grounding, write authorization, operational memory, model tool contract, readonly integration, policy product context, business completion, price grounding, reply boundaries and guarded streaming: 280 passed. Log: `/tmp/agent-context-final-focused.log`.
- One additional model-round boundary check passed without further production changes: `/tmp/agent-context-model-round-limit.log`. Total verified focused cases: 281.
- Existing controller-contract failures were rechecked separately: 14 failed, 9 deselected in `test_session_state.py` and `test_session_preparation.py`. They expect removed `SessionState.decision`, automatic pricing/purchase completion, or scripted recovery without model calls; the basket fixture also omits current catalog source data. Those test files and `runtime.py` are unchanged. Full names and output: `/tmp/agent-context-legacy-contracts.log`.
- Self-review completed against all eight requirements, connected callers, source/owner/date bindings, SDK schema, privacy, error recovery and persistence. `git diff --check` passed. No full-suite, live-model, real-database, benchmark or deployment run was performed.
- Decision: preserve literal committed customer sources instead of adding a semantic cart controller or another model inference. Only auxiliary summaries are budgeted; total prompt size can still grow with authoritative customer sources. Live semantic accuracy and latency remain unmeasured.
