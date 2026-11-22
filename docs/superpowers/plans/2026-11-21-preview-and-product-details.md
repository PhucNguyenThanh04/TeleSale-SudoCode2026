# Preview and Product Details Implementation Plan

> Execute inline using superpowers:executing-plans. The user approved both tools
> and autonomous execution. Current-checkout/no-subagent rules override skill defaults.

**Goal:** Ship order.preview_update and catalog.get_details as read-only agent tools.

**Architecture:** Share order update calculations with a side-effect-free preview;
extend the existing catalog evidence parser and reviewed source bindings. Keep
canonical tool names throughout the gateway, agent, evidence and memory.

**Tech Stack:** Existing Python/Pydantic/FastMCP/SQLAlchemy/pytest; no dependencies.

**Spec:** docs/superpowers/specs/2026-11-21-preview-and-product-details-design.md

## Global constraints

Current checkout; preserve existing uncommitted repairs. No subagents, worktrees,
commits, code comments/docstrings, live models, saved traces/eval inputs, external
writes or deployment. Focused offline tests only, sockets blocked, dotenv disabled.

## Review focus

- Preview performs zero writes even if caller supplies an operation key.
- Shared phones/foreign orders cannot expose another member's paid amounts.
- Preview cannot grant write consent or preserve stale prices/stock on execution.
- Technical rows/section bindings keep exact model/variant scope and source priority.
- Actual model tool output survives grounding and detail evidence survives memory.

## Task 1: Order preview

Files: order schemas/services/handlers; shared identity; gateway; new
ai-services/test/test_order_preview.py.

Interface: PreviewUpdateInput; preview_update(repo, session, args, customer_id);
shared _update_plan; preview status and estimate flags with net amount fields.

- [x] Write RED synthetic full/partial return, exchange price/fee/stock, invalid
  selection, zero-write, shared-phone/foreign/tampered identity cases.
- [x] Extract existing update calculation, add strict read schema/MCP route and
  signed scoped read. Restrict operation journal calls to WRITE_TOOLS.
- [x] Verify parity with execution, changed stock/price revalidation and unsigned
  writes still denied. No preview result constitutes customer authorization.

## Task 2: Product details

Files: catalog schemas/service/handlers; shared catalog_evidence.py and reviewed
catalog-evidence.json; new ai-services/test/test_catalog_details.py.

Interface: DetailsInput(sku); get_details(repo, session, args); product_details
returns search-compatible items plus specifications/technical_evidence/availability.

- [x] Write RED exact SKU/variant, full table properties, section scope, missing
  data, private/malformed/contradictory sources and catalog priority tests.
- [x] Reuse table parsing and source resolution, add reviewed section bindings for
  public prose/size data, register exact-SKU MCP lookup.
- [x] Verify synthetic evidence and actual BTC public source coverage offline.

## Task 3: Agent and evidence integration

Files: model tool_names/business_agent; harness preparation; shared commerce
evidence/entities/memory observations; policy provenance/grounding consumers;
new focused integration tests and directly affected contract fixtures.

- [x] Observe RED for real model-tool → gateway → MCP calls, preview without
  consent, details → pricing/policy evidence and safe output/observation retention.
- [x] Register fields/descriptions, shared catalog source recognition and typed
  preview preparation; preserve write authorization and policy requirements.
- [x] Extend answer evidence for preview estimates and technical sources without
  permitting a preview to prove fulfilment or policy entitlement.

## Task 4: Verification and documentation

- [x] Run new and directly related offline regression tests; reconcile fixtures
  only for the two new tool contracts. No broad unrelated repairs.
- [x] Check syntax/JSON/whitespace and self-review each spec requirement.
- [x] Update runtime docs with usage, limits and coordinated process restart needs.
- [x] Record evidence and mark the user goal complete only after all requirements.

## Execution record

Initial state: previous data-contract repair remains uncommitted and must be kept.
No graph exists; targeted source search used instead of generating one. Tests will
use synthetic fixtures plus BTC catalog and approved public specification documents.
Plan self-review: all five requirements covered; no external side effect needed.

- Task 1: 8 initial RED failures confirmed missing preview implementation/route.
  Shared pure calculation, signed read and read-only operation guards then passed
  126 preview/update/identity/authorization tests. Added proof tampering, raw
  operation-key, changed stock and changed price cases, all passing.
- Task 2: 8 initial RED failures confirmed absent details service. Shared table
  parsing plus reviewed public section bindings passed 25 details/evidence tests.
  Additional RED caught unparseable technical cells misattributed as catalog
  provenance, a technical price column overriding catalog priority, and raw variant
  stock being exposed as details context. Sources and the variant projection were
  corrected; actual BTC size/prose/exact SKU tables and all bindings are checked.
- Task 3: initial RED showed absent model aliases and preview amounts rejected as
  missing quotes. Added both canonical/model tools, trusted catalog source handling,
  policy provenance, memory evidence and mandatory semantic review scope. Offline
  framework roundtrips caught the old fixed 10-tool fixture; it now expects all 12.
- Source-scoping ruling: prose/size sources remain contextual evidence with their
  model names/conditions intact; they are not flattened into product attributes.
  The exact-SKU table path provides structured properties, while approved JSON
  binds other sections. Missing technical information stays explicitly unavailable.
- Read-scope ruling: preview estimates do not enter durable memory observations.
  Current-turn refreshed estimates replace older equivalents and failed refreshes
  invalidate them. Distinct line/action options can be explained together; numeric
  grounding checks source amounts and semantic review still checks role/subject,
  policy conditions and any completed-action claim.
- Broad focused regression before the final preview refresh correction: 302 passed,
  one pre-existing failure. Replaying HEAD commerce-evidence/checks in memory
  reproduced test_prior_turn_quote_reused_by_real_verifier: its AgentNodes(None)
  has no mandatory semantic reviewer. No runtime gate was weakened to pass it.
- Follow-up through real MCP/model schemas, details/source/preview and evidence
  consumers: 83 passed, 1 baseline case deselected. No live model or network calls.

- Final refresh/option tests were RED for stale duplicate estimates and comparing
  two distinct options; preview now participates in the existing evidence view with
  argument-bound latest-read/failure barriers, while monetary validation accepts
  source amounts from distinct options. Semantic review retains subject/role scope.
- Final focused verification: 306 passed, 1 pre-existing case deselected in 5.58s.
  Includes all three new test modules; actual fake-provider Deep/ReAct tool payload
  roundtrips across six framework/provider combinations; existing update, signed
  authorization/identity, policy, catalog, evidence, feature grounding, pricing,
  journal/replay and concurrent exchange fee checks. Sockets blocked and dotenv,
  Langfuse content/prompts disabled. No full suite/live eval/benchmark was run.
- Static verification: changed/new Python parsed, JSON parsed, new Python contains
  no comments/docstrings, and git diff --check passes. Existing unrelated changes
  from the preceding goal remain intact. Runtime docs describe both tool contracts.

## Completion audit

| Requirement | Current implementation | Direct evidence |
|---|---|---|
| 1. Read-only owned preview with shared amounts/fees/stock | PreviewUpdateInput, signed identity route, shared _update_plan, explicit estimates/net fields; operation claims restricted to writes | test_order_preview: SQL journal unchanged, zero operations/locks, foreign/shared owner, tampered selection/date, full/partial amounts and fees |
| 2. Preview does not grant consent or freeze execution | Existing write review/signature gates retained; update recomputes plan | test_readonly_tool_integration: preview bypasses write reviewer, subsequent denied write inserts nothing; price/stock change and unsigned-write tests |
| 3. Exact parent/variant product details with provenance | DetailsInput/get_details, shared public table parser and source resolution | test_catalog_details and test_catalog_evidence: exact rows, variant identity, source hashes, protected values, contradictory/private/malformed sources |
| 4. Contextual prose/size support and honest missing data | Reviewed section_bindings, scope=section_context, technical_data_status | Independent bindings test and actual BTC approved-document/table/prose/size checks; legacy model does not borrow current table; absent source stays unavailable |
| 5. Complete agent/MCP/evidence integration | Both model aliases, gateway/MCP registration, scoped preparation, catalog source recognition, policy provenance, durable details and mandatory review scope | test_readonly_tool_integration and test_model_tool_contract: 12 model tools, actual in-process MCP reads, details→quote/policy/memory candidate, supported/unsupported amounts and scoped stock, refresh barriers |

All five approved requirements are implemented and verified in the current
checkout. No required local implementation remains. The pre-existing reviewer-less
verifier test is documented, not repaired by weakening mandatory review. No live
semantic-accuracy, latency or deployment claim is made. Catalog details depend on
loaded public source rows; prose remains contextual and missing facts stay unknown.
Preview still requires separate policy verification and an authorized update.

Deployment: rebuild/restart the harness and catalog/order/knowledge MCP together
with the existing shared context secret and the reviewed catalog-evidence JSON.
Existing tables/grants suffice; no migration, source import, embedding call or
index rebuild is needed. Deployment was not performed during this goal.
