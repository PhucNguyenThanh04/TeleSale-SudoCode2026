# Brief contract evidence

Date: 2026-10-21. Scope: text-to-text harness; BTC schemas loaded only by tests.

## Red baseline

`cd ai-services && .venv/bin/python -m unittest discover -s test -p contract_briefs.py -v`: 3 red cases. Handoff accepted a model summary below BTC minimum and a hotline identity of `unknown`; Call Brief emitted `quoted_on: null`, which BTC schema does not permit, and counted only its capped episode list. These are harness construction and context defects, respectively.

`cd ai-services && .venv/bin/python -m unittest discover -s test -p test_mcp_business.py -v`: new malformed-value test failed in six subcases before service validation. Existing replay and commerce controls passed. The service only checked presence of required keys.

The synthetic SKU and rooms are outside the public sample; no runtime branch depends on them.

## Final verification

- `cd ai-services && .venv/bin/python -m unittest discover -s test -p contract_briefs.py -v`: 8/8 passed. Synthetic cases cover two equal-price SKUs, two rooms, seven prior sessions with five displayed episodes, failed/malformed quote, active/expired promo, invalid hotline identity, nonqueued ticket, a current-turn quote and an ordinary catalog control. Both emitted brief objects pass BTC Draft 2020-12 schemas with format checking.
- `cd ai-services && .venv/bin/python -m unittest discover -s test -v`: 182 tests, passed, 7 skipped. This includes the earlier memory, erasure and fake-model graph checks.
- `cd ai-services && .venv/bin/python -m unittest discover -s test -p test_mcp_business.py -v`: 4/4 passed. Invalid content creates no ticket; valid stored brief passes BTC JSON Schema and replay writes once. Commerce comparison uses BTC mock tools.
- `ai-services/.venv/bin/python -m unittest discover -s eval -v`: 9/9 passed, including the text eval runner's business-date and label-exclusion checks.
- `cd backend && python3.12 -m unittest discover -s test -v`: 9 tests run, 6 passed, 3 PostgreSQL integration tests skipped because `BACKEND_INTEGRATION_ADMIN_DSN` was not set.
- `git diff --check`: passed. Runtime files in this change have no `scenario_id`, `expected_outcome` or `public_sample` branch.

The tests use synthetic state, a fake model, fake gateway and BTC mock commerce functions. PostgreSQL listens locally, but an isolated integration database and credentials were not configured for this run, so the new `prior_session_ids` SQL was not executed against PostgreSQL. MCP HTTP and real LLM were not exercised. Full versus `baseline_no_memory` public-sample runs require an isolated resettable eval database plus running MCP/model endpoints; no reliable p95 latency or false-handoff rate is claimed from the eight synthetic contract cases. Hidden-test performance remains unknown.

A fresh read-only review identified four defects: success wording after failed transfer, an omitted current-turn quote, overwritten erasure verification instructions and a timezone-free `generated_at`. Each was reproduced by a failing test and fixed; the AI suite and explicit contract were rerun after the fixes.

## Structured session memory extension (2026-10-21)

The new `0009_structured_episodes.sql` migration adds topic state and
cross-session resolution markers. `commit_turn` applies evidence-checked
episode deltas atomically with turns/facts; a late resolution suppresses the
earlier open item without rewriting its evidence. The rolling summary reserves
room for the latest turn while retaining earlier product references when the
character budget allows. Call Brief is emitted at the first recognized turn
of a returning session; later turns refresh business data only for a relevant
request. Handoff Brief includes still-open questions.

- AI service: `cd ai-services && .venv/bin/python -m unittest discover -s test -q`: 202 tests, passed, 8 skipped.
- Additional memory contract suite: `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_memory*.py' -q`: 11/11 passed, including the public multi-product conversation and synthetic cross-channel/correction cases.
- BTC brief contract: 8/8 passed; eval runner tests: 9/9 passed; backend unit suite: 9 tests, 3 skipped.
- Disposable PostgreSQL database, created and dropped by `test_memory_postgres_integration.py`: 5/5 passed with migrations through `0009`, including cross-session resolution and erasure. Credentials were loaded locally from existing ignored secrets and were not printed.
- `git diff --check` and Python `compileall` passed. These are whitespace and syntax checks, not a lint run.

The original full-vs-`baseline_no_memory` public-sample trace evaluation was
not run: it requires three MCP endpoints connected to one isolated eval DB and
the same configured LLM. MCP HTTP and live-model latency remain unmeasured;
the PostgreSQL integration above verifies storage behavior directly.

### Follow-up review and regression check

Read-only review reproduced four edge cases, then focused RED→GREEN tests drove
the fixes: topic-scoped questions are retained separately; an episode at its
item/topic/resolution limit now commits the verified turn and facts with a
`capacity_reached` warning; proposals require lexical support in their exact
current-turn quote; an explicitly resolved issue can be filtered during the
same-turn handoff; and an overlong latest utterance is truncated rather than
silently replaced by older text. This evidence check is deliberately
conservative but cannot prove semantic entailment, so proposal quality still
needs real-model evaluation.

- AI service `unittest discover -s test -q`: 209 tests run, 8 skipped.
- Explicit `contract_*.py` suite: 19/19 passed. Root `eval/` tests: 9/9 passed.
- Backend tests: 9 run, 3 skipped. Disposable PostgreSQL integration with
  migrations through `0009`: 5/5 passed after the review fixes.
- `git diff --check` passed. The full/baseline live MCP and LLM comparison
  remains unrun, so hidden benchmark performance is unmeasured.
