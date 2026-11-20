# Customer Fact Admission Implementation Plan

> Execute inline with superpowers:executing-plans and TDD. The user delegated
> spec/plan/execution and prohibits worktrees, subagents and case-based repairs.

**Goal:** Prevent unsupported customer profile facts from reaching durable memory.

**Architecture:** Preserve mechanical admission, review customer facts once per
job, freeze the reviewed proposals, and safely replay them through revision fencing.

**Tech stack:** Existing Python, Pydantic, LangChain, LangMem and pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-memory-fact-admission-design.md`

## Global constraints

- Current checkout; preserve user changes and stage 1 guardrails.
- No code comments/docstrings, new dependencies, migrations, live model/database
  calls, evaluations, remote prompt publication or scenario/trace-driven implementation.
- General source, type, ownership, scope, time and revision contracts only.
- Focused offline checks; no full suite.

## Review focus

- Mixed approved/rejected facts cannot corrupt unrelated scopes or types.
- Negative facts and explicit corrections must remain admissible.
- Assistant/history context cannot become a new customer source.
- Reviewer failure cannot complete a job or change the store.
- Legacy partial writes and crashes between cache save and cleanup cannot revive
  rejected facts under a completed revision.

## Task 1: Batch reviewer and mechanical date boundary

Files: create `app/agent/memory/fact_review.py` and `test/test_memory_fact_review.py`;
modify `app/mcp_servers/mcp_memory/services/langmem_admission.py`.

- [x] Write independent tests for strict indexed decisions, literal-source
  consistency, role/PII preservation, arbitrary scopes, dates, timeout and failures.
- [x] Observe RED on missing review and mismatched-date admission.
- [x] Implement `review_profile_facts(model, facts, turn, history, existing, tools)`
  returning an unchanged subset or raising `FactReviewUnavailable`; implement an
  exact-input review digest and the committed-date check.
- [x] Verify focused reviewer and admission cases GREEN.

## Task 2: Worker gate, retry integrity and revision cleanup

Files: modify `distiller_worker.py`, `repos/langmem_projection.py` and add worker
integration cases to the new test file; update focused worker test doubles.

- [x] Observe RED for unsupported customer projection, missing reviewer, cached
  bypass and legacy partial-row promotion.
- [x] Add a `fact_reviewer` callback to `process_one`, wired to the configured model
  in `run`. Review after every customer-fact-producing path and before cache save.
- [x] Share the existing bounded history with extraction and review as context.
- [x] Bind cached review to exact facts and sources. Revalidate legacy/changed
  caches, persist the reset flag, and discard only that job's fact revision before
  publishing the reviewed set under the existing locks.
- [x] Verify frozen retries, explicit corrections, scope isolation, erasure and
  lease fences, source dates and tool-only jobs with focused offline tests.

## Task 3: Verification and self-review

- [x] Run focused reviewer, worker, extractor, admission, projection and erasure
  tests with dotenv/provider credentials disabled and sockets blocked.
- [x] Check syntax, whitespace and changed-file scope.
- [x] Audit each spec requirement against real code/tests; record results and
  remaining semantic-model limitations here and in the runtime contract.

## Execution record

Spec and plan self-reviewed before implementation. Tasks share the exact admitted
fact records, the review-failure exception and the cache digest. Worker must save
the reset flag before any legacy revision cleanup; projector must delete only
fact rows with that exact customer namespace and job revision. No new approval
gate is needed because autonomous design and execution were explicitly requested.


### Results

- RED observed before implementation: a mismatched observed date was admitted;
  the worker projected customer proposals without review; legacy partial rows
  became active when their cached job completed. The reviewer module was absent.
- A later self-review added a cache-removal retry case. It failed because an
  empty changed cache bypassed cleanup, promoting the partial row. Cache receipt
  validation now runs even when no customer facts remain. The case is GREEN.
- Final focused run: **107 passed, 1 deselected**, one upstream trustcall/LangGraph
  deprecation warning. Files: `test_memory_fact_review.py`,
  `test_langmem_primary.py`, `test_langmem_worker.py`, `test_langmem_projection.py`,
  `test_langmem_admission.py`, `test_langmem_extractor.py`,
  `test_langmem_erasure.py`, `test_operational_memory.py`. The existing
  `sample_01` case was deselected to avoid reading its saved input.
- Tests disabled dotenv loading, used placeholder credentials, disabled Langfuse
  and blocked socket connections. Store tests used the real projection class
  over an in-memory transport; no PostgreSQL integration test was executed.
  Existing worker fixtures now supply explicit review decisions and valid saved
  proposals. The PostgreSQL customer-write fixture was updated but not run.
- An earlier broader run found three failures outside this stage:
  `test_promotion_memory.py::test_single_quote_cannot_describe_another_catalog_product`,
  `test_memory_freshness_contract.py::MemoryFreshnessContract::test_early_return_keeps_preference_but_rechecks_price`,
  and `test_memory_freshness_contract.py::MemoryFreshnessContract::test_eight_month_return_refreshes_stock_and_quote_on_call_date`.
  They concern the unchanged reported-tool product association and Call Brief
  refresh paths. They remain unresolved; this is not an all-suite pass claim.
- Syntax and scoped whitespace checks passed. New Python files contain no comments
  or explanatory docstrings. No unrelated runtime code was changed for those
  broader failures, and no phrase controller was restored.

### Requirement audit

| Requirement | Implementation and offline evidence |
| --- | --- |
| 1 | Existing mechanical checks retained; committed-date mismatch rejected; tool-only test bypasses semantic review. |
| 2 | Strict Pydantic decisions, complete index coverage, boolean/reason consistency and unchanged subset tests. |
| 3 | Review instructions cover whole-utterance meaning, scope, corrections and deletion; scripted independent cases exercise the interface. Valid negative boolean reaches active memory. |
| 4 | Separate speaker fields and the bounded session window reach extraction/review; PII is masked and source IDs remain intact. |
| 5 | Real projection tests preserve the other room and other customer's records; existing revision and erasure tests pass. |
| 6 | Timeout cancellation, malformed output, missing reviewer and retry-exhaustion tests prevent publication/completion and preserve the source turn. |
| 7 | Gate follows blocker supplementation; cache binds exact facts/source/context; unchanged partial-write retries reuse extraction/review once. |
| 8 | Reset flag persists before exact customer/revision cleanup; legacy, altered-value, removed-fact and interrupted-cleanup cases pass. |
| 9 | New fixtures use independent values and general boundary failures; no saved trace/evaluation drove a repair or live operation ran. |

Self-review performed inline under the no-subagent rule. Semantic decisions in
these tests are scripted; real model entailment, adversarial robustness, cost and
latency remain unmeasured. Previously completed facts, episode narratives and
historical backfill are not recertified. Runtime details are recorded in
`ai-services/docs/text-harness-contract.md`.
