# Text harness contract repair

## Authorized scope and evidence boundary

Review and repair the complete ai-services text-to-text path against BTC
business requirements and the responsibilities of a telesales harness.
Work in the current checkout, without subagents, live evaluations, model calls,
database changes, or reading public/held-out scenarios, QA labels or saved traces.
Existing held-out files are prior user work and remain untouched.

Authority: BTC DIEU-CHINH-DE.md, GIAI-DAP-MENTOR.md, tool/brief schemas,
catalog/policy contracts; application source and isolated component tests.
Tests must use independent small domain fixtures, not benchmark cases.
No evidence here will claim a new quality score or live deployment validation.

## Intended lifecycle

Authenticate/bind identity -> load owned, current memory and session evidence ->
model chooses tools or clarification -> validate each proposed tool call ->
execute MCP and return observed result to model -> check the final answer ->
commit the actually delivered customer/assistant turn and successful tool
evidence durably -> background LangMem enrichment with evidence admission.

Commercial facts require the matching product, quantity, date, delivery context
and owner. Past recommendations, tool reads, hypothetical speech and old
consent are not authority for a new write. Failed/uncertain writes are not
silently repeated. Memory is historical evidence, never a source of current
prices, inventory or permission. Recovery must answer the current request or
ask a specific clarification, not switch to an unrelated cached product.

## Execution plan and ledger

- [x] Map and inspect API/runtime, agent loop, gateway/MCP, memory/LangMem,
  guardrails/streaming, call brief/handoff, persistence and failure paths.
- [x] Repair agent orchestration: one model-led business-tool loop; remove
  proactive write execution and off-topic answer substitution. Prove contracts
  with fake model messages and recorded in-memory business tools.
- [x] Repair tool boundaries: schema/identity, explicit current authorization,
  exact commercial evidence, retry/idempotency and bounded execution.
- [x] Repair answer verification and streaming: source/product relevance,
  error handling and final delivery before persistence; no built-in tools or
  unverified data treated as model instructions.
- [x] Audit and fix memory/LangMem: ownership, TTL, per-turn persistence,
  read-your-writes, background admission/order, erasure and cross-channel state.
- [x] Review BTC MCP parity for time-dependent quotes, stock, orders and
  callback/handoff. Fix proven contract defects, preserving source data.
- [x] Run focused offline checks for changed components, inspect the whole
  change, and record remaining deployment/model-quality limitations.

Ruling: user already authorized implementation and prohibits worktrees and
delegation; do not introduce skill approval handoffs, agents or new checkouts.
Ruling: full-suite skill defaults yield to repository focused-test instruction;
do not execute benchmark/scenario/eval tests or costly operations.

## Findings from source (before changes)

- AgentNodes.run_agent invokes automatic commercial preparation and
  complete_purchase_if_ready before and after model invocation. It can return
  deterministic commercial answers before giving the model the current turn.
- verify_agent tries several broad fallback answer builders, including catalog
  recommendations, even when their topics do not match the rejected answer.
- Tool writes use trusted identity/date and MCP operation keys, but authorization
  is distributed among regex-based consultation and basket state. Review all
  write types, not only creation.
- MCP order service validates identity/ownership, transactional operation
  deduplication, live quote and stock. These are required boundaries to retain.
- Runtime serializes sessions, checks conflicting retries and persists text
  after guarded delivery; memory reads and enrichment use owner/revision gates.
  Inspect their failure and cross-session behavior before deciding changes.

## Verification record

2026-11-18, first repair batch:

- `test_text_harness_contract.py`: initially 6 contract failures (after fixing
  the fake model setup), then 7 passed after orchestration/context changes.
- Model receives current utterance for normal requests; proactive commercial
  reads/writes and pre/post-model answer replacement removed from run_agent.
  Privacy-erasure routing retains its explicit safety workflow.
- Prompt no longer presents a heuristic consultation decision as authority.
  Remembered order IDs no longer fabricate `created` status or borrow a variant
  from an unrelated product fact.
- Added turn-local structured semantic write authorization with full current
  customer utterance and verified context, exact quote provenance, fail-closed
  handling and a 5s deadline. No real model request executed during this work.
- Added stable write retry keys independent of the number/order of read tools.
  API and MCP signatures remain compatible; MCP still checks ownership/price.
- Before write gate change: 5 new failures; after change: 12 passed. Before
  reviewer wiring: 2 new failures; after wiring: 14 passed.
- Before removing the legacy language-specific purchase decision and implicit
  lookup: 2 new failures, 16 passed. Mechanical evidence gate and obsolete
  commercial preparation/continuation methods now replaced; verification pending.

Ruling: semantic authorization is an additional bounded model inference only
when a write is proposed, not an eval judge or a knowledge-learning loop.
Mechanical stock/quote/owner checks remain mandatory even after permission.
It adds latency/cost on write turns and must be reported; offline tests cannot
prove a provider model's semantic accuracy or production latency.

Final source review and offline verification completed:

- Owner/date/SKU/variant/quantity/address and basket physical-unit price checks
  are covered by independent fixtures. Quotes before a prior successful purchase
  are invalidated; bound observation indices remain aligned after filtering.
- Active tool normalization respects explicit model arguments. Historical
  language interpretation remains available to memory annotations, without
  authorizing tool actions.
- Guarded streaming waits for final message stop. Updated focused tests retain
  disconnect, persistence, late tool-call and retry guarantees.
- API authentication now fails closed; MCP connection+call deadlines cover
  business tools, policy search and release pinning.
- Memory filters expiry/status/future facts. Customer goals cannot be sourced
  from assistant speech. Anonymous evidence is persisted with each turn rather
  than kept only in a process dictionary; migration 0005 and the managed fresh
  schema include the new columns.
- Completed create/update/callback/handoff receipts remain available on model
  failure. PII masking is idempotent and brackets cannot bypass address masking.
  A privacy marker cannot become a physical delivery address in tool arguments.
- Obsolete expectations in the selected business/stream/policy component tests
  were migrated to the model-led lifecycle. Dataset/replay files and old private
  controller tests outside this selection were not used to tune production.
- Final focused run: **278 passed, 1 existing LangGraph deprecation warning,
  4.98 seconds**, across 27 component modules. The offline runner removes
  provider credentials, disables dotenv and blocks network access. This is not
  a full-suite or live quality evaluation.
- `git diff --check` passed. Modified application files parsed successfully;
  newly unused imports/constants were removed. Existing unrelated unused code
  was left alone. No database migration, model request, live evaluation,
  publication, deployment or commit was performed.

Operational notes and audit mapping:
`ai-services/docs/text-harness-contract.md`, linked from the service README.
Existing databases need migration 0005 before this memory service revision.
Provider structured-call support, semantic authorization accuracy, production
latency/cost and PostgreSQL integration remain unmeasured offline. Default tool
budget is now 8; explicit environment configuration still takes precedence.
Process-local session coordination and legacy tests for retired controllers are
explicitly documented compatibility limits, not claims of a green full suite.
Existing published knowledge and pre-existing held-out files remain untouched.
