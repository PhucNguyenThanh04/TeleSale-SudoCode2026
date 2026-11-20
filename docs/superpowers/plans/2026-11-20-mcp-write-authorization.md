# MCP Write Authorization Implementation Plan

> Execute inline using superpowers:executing-plans and TDD. Autonomous execution
> is already authorized. Current checkout, no subagents, no commits or worktrees.

**Goal:** Only execute the exact business write authorized by the current request.

**Architecture:** Keep semantic authorization in the agent, bind its decision to
a typed request context, sign the normalized MCP payload, and enforce that grant
before service execution. Retain business validation and transactional replay.

**Tech stack:** Existing Python/Pydantic/LangChain/FastMCP; stdlib HMAC/SHA256.

**Spec:** `docs/superpowers/specs/2026-11-20-mcp-write-authorization-design.md`

## Global constraints

- Preserve current dirty checkout and previous stages; surgical changes only.
- No comments/docstrings, new dependencies, live model/DB/evals or deployments.
- No phrase controllers, trace/scenario-driven repairs or remote prompt changes.
- Focused offline tests with dotenv disabled, placeholder credentials and blocked
  sockets. No full suite. Self-review under the explicit no-subagent rule.

## Review focus

- Correctly approved writes still execute for all four tools and short replies
  retain separate historical speaker context.
- Metadata cannot be supplied by model arguments or reused for another identity,
  request, date, target, quantity, price, time or operation key.
- Failed writes can retry; previous state receipts and context changes cannot
  bypass current authorization.
- Fresh signatures do not break durable idempotency after controller restart.
- Callback timezone and operating-hour handling never writes an unapproved time.

## Task 1: Review and grant contracts

Files: `app/agent/harness/authorization.py`, new
`app/mcp_servers/mcp_order/write_authorization.py`,
`app/mcp_servers/mcp_order/schemas.py`, new `test/test_write_authorization.py`.

Interfaces: `AuthorizedWriteContext`, `write_args_digest(name,args)`,
`write_operation_key(context,args)`, `sign_write_authorization(name,args,context,secret)`,
`verify_write_authorization(name,args,secret)`; review returns strict bool on a
valid decision or raises `WriteAuthorizationUnavailable` on contract/provider failure.

- [x] Add synthetic tests for current source/role preservation, strict decisions,
  literal current quote, policy handoff limits, unavailable review and deadline.
- [x] Add binding/signature tests for all four write payloads; missing/tampered/
  expired/cross-context inputs must fail. Observe RED before implementation.
- [x] Implement the minimal strict reviewer and typed context/signature helpers.
- [x] Verify the reviewer and grant tests GREEN.

## Task 2: Enforce the complete write path

Files: `app/agent/implementations/business_agent.py`, `app/agent/mcp/gateway.py`,
`app/agent/harness/policy.py`,
`app/mcp_servers/mcp_order/tools/handlers.py`,
`app/mcp_servers/mcp_order/services/order.py`, new independent integration tests
in `test/test_write_authorization.py`; update directly affected test fixtures.

Interfaces: `build_write_context(state,name,args)` at the agent boundary;
`MCPGateway.invoke_trusted(..., write_context=None)`; order handlers/service
`invoke(..., context_secret=None)`; server `create_server(..., context_secret=None)`.

- [x] Observe RED on unsigned MCP writes, failed/unbound receipt reuse, changed
  source during review and silent callback rescheduling.
- [x] Construct/bind context before review, protect arguments from mutation,
  enforce unchanged context, and pass the grant only after literal True.
- [x] Reuse only local successful bound results; retain bounded review cache.
- [x] Strip model metadata, require a matching typed grant and sign normalized
  payloads in the gateway. Wire grants through the four MCP tool signatures.
- [x] Verify before service transactions, compare re-resolved owner, and exclude
  the transient envelope from durable operation digests. Keep existing keys.
- [x] Return callback alternatives without a write; apply rules in business TZ.
- [x] Verify real in-process write flows, denials, read access, replay/restarts,
  identity boundaries, gateway stripping and callback behavior GREEN.

## Task 3: Focused regression and completion audit

- [x] Update affected offline fixtures to explicitly provide authorized context;
  do not restore obsolete controllers to satisfy their old conversation tests.
- [x] Run focused new tests plus business tool, gateway, logging, model tool,
  structured handoff and previous-stage boundary checks where directly relevant.
- [x] Check syntax/whitespace/new-file comment policy and self-review source.
- [x] Record requirement-by-requirement evidence, limits, any outside failures
  and upgrade contract in this plan and `docs/text-harness-contract.md`.

## Execution record

Spec and plan self-reviewed. The signed context is a trusted-process capability,
not independent proof of natural-language consent. The same normalization must
be used before signing and after MCP validation. Transient signatures must never
enter durable idempotency hashes. No external operation is needed for this repair.

### Rulings and self-review

- Ruling: a successful receipt is keyed by current source/request/identity and
  normalized arguments, excluding the interpretation-context hash. Completing
  that operation itself changes tool context; its receipt must remain reusable.
  Unused approvals still require unchanged interpretation context.
- Ruling: private address equality must survive masking. An offline test showed
  two different proposed addresses produced identical reviewer payloads because
  `safe_tool_result` removes address. Review now uses an opaque proposed-address
  marker in the full current utterance. Mask text segments separately so an
  address-introduction mask cannot erase that marker. Raw values stay private.
- Ruling: hash raw private context locally, not the masked model view. RED tests
  showed phone and tool-address changes during review were otherwise invisible.
  These hashes bind the grant without sending those values to the reviewer.
- Ruling: remove only the purchase-receipt shortcut in `policy.py`. A synthetic
  old receipt bypassed current quote/stock requirements and created a new order;
  cached state cannot substantiate missing commercial evidence.
- Ruling: check exhausted write budget before invoking review. The existing
  per-turn review limit remains; no extra provider call is justified when no
  execution budget remains.
- Ruling: absence of an error is insufficient proof of a completed write. Four
  RED cases showed empty responses could be cached as successful operations.
  Require the tool's receipt identifier/status (and the update's target order)
  before accepting/caching a positive result; malformed results remain retryable
  through the same operation key.
- Self-review performed inline under the explicit no-subagent rule. Verified
  normalization at both boundaries, pre-transaction verification, source/owner
  binding, local result caching, failure/restart replay, secret configuration,
  strict model output and callback no-write alternatives. No independent reviewer.

### Verification

- Initial RED: inconsistent/extra review output had no failure contract, policy
  handoff admitted an unrelated reason, and the grant module was absent.
- Task 1 GREEN: **37 passed**.
- Task 2 RED: four unsigned domain writes and one direct MCP write executed;
  failed-result reuse blocked retry; changed source/context still reached the
  gateway; invalid callback times were inserted after automatic changes.
- Task 2 GREEN after enforcement: **63 passed**; later focused new/fixture and
  callback/concurrent-exchange checks: **85 passed**.
- Additional RED/GREEN cycles covered opaque-address masking, stale purchase
  receipt evidence, exhausted review budget, private-context changes and empty/
  incorrectly typed write receipts. The receipt check requires a string status
  before status membership, so malformed values return an error without crashing.
- Final focused command covered `test_write_authorization.py`,
  `test_business_completion.py`, `test_mcp_gateway.py`, `test_mcp_logging.py`,
  `test_structured_handoff.py`, `test_model_owned_conversation.py`,
  `test_model_tool_contract.py`, `test_mcp_business.py`,
  `test_november_pricing.py`, `test_semantic_grounding.py`,
  `test_memory_fact_review.py`, `test_tool_budget.py` and the two changed callback/
  concurrent-exchange cases in `test_tool_source_audit.py`.
  Final result after receipt validation: **256 passed, 1 failed**, one upstream trustcall/LangGraph deprecation
  warning. All new authorization cases and the existing four-write business,
  gateway, replay, logging, handoff, grounding and memory-review cases passed.
- The remaining failure is
  `test_tool_budget.py::test_quote_name_is_rejected_with_catalog_instruction_before_mcp_call`:
  it expects `sku_required` while the unchanged read precondition path returns
  `catalog_required` plus empty `missing_fields`. The new write gate is not
  reached. Left outside scope; this is not an all-suite green claim.
- Earlier focused failures were fixture incompatibilities: unsigned write setup,
  a fake operation store missing claimed-operation state, and a model-tool test
  without a scripted stage-1 answer review. Fixtures now supply explicit grants
  or isolate their unrelated review dependency; no runtime rule was added for
  those conversations.
- Tests disabled dotenv/provider credentials and Langfuse, blocked sockets, used
  in-process FastMCP and synthetic repositories. A real ChatOpenAI structured
  adapter parsed a scripted HTTP response offline. Existing business reference
  tests were regression checks, not implementation inputs. No saved trace,
  scenario conversation, held-out data or evaluation result drove a repair.
- Syntax passed for 15 Python files; scoped whitespace passed; three new Python
  files contain no comments/docstrings. No full suite, live model/DB, migration,
  remote prompt operation, commit or deployment was run.

### Completion audit

| Spec requirement | Authoritative evidence |
| --- | --- |
| 1 | All four tools execute through real controller/gateway/MCP/domain code after approval; denied/unsigned cases insert nothing. Reads without grants pass. Existing ownership, variant, stock/quote, basket and budget checks remain exercised. |
| 2 | Whole current utterance, separate customer/agent history and exact proposed arguments reach the reviewer. Independent scripted negation/condition/third-party/short-confirmation cases and private-address distinction tests pass. No new phrase classifier exists. |
| 3 | Strict extra-forbid Pydantic schema, allowed/basis/reason consistency, literal quote checks, policy reason/tool limits and deadline/provider tests pass; unavailable review yields a distinct error without gateway calls. |
| 4 | Frozen typed context and hashes bind IDs, text, identity, date, tool, normalized args and raw interpretation context. Source/phone/history/request/private-tool changes during review block; reviewer mutation cannot alter executed args. |
| 5 | Gateway strips supplied metadata, requires matching typed context and signs normalized payload. Service verifies before transaction. Unit tamper/wrong-secret/tool/args/expired/future tests pass; direct unsigned MCP writes never open a transaction. |
| 6 | Operation keys bind request/tool/order; service strips transient grant before durable digest and checks re-resolved owner before claim. Fresh-signature and controller-restart replays write once; owner change is denied. Unknown hotline handoff retains phone validation. |
| 7 | Local successful bound receipts reuse; empty or incorrectly typed responses are rejected and remain retryable. Old state receipts cannot authorize; transient failure retries; lost response after a real domain write replays once. Denials and review attempts remain bounded. |
| 8 | Hour, late-hour, Sunday, synthetic-holiday and UTC/business-TZ tests return alternatives with no insert. Valid aware timestamps keep the same instant. |
| 9 | New synthetic tests cross all four real boundaries with scripted review; focused existing regressions and syntax/whitespace checks ran offline. Limits and unsigned-client upgrade are documented. |

Previously identified promotion/Call Brief failures remain separate work and were
not rerun or repaired here. Real-model consent accuracy, prompt-injection
resistance, database concurrency under load, cost and latency remain unmeasured.
Order fulfilment/refund/address persistence remains outside this authorization
repair. Existing internal-token holders are trusted; signed grants are not a
defence against compromised signing credentials or malicious application code.
