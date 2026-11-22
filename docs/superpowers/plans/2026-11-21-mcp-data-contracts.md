# MCP Data Contracts Implementation Plan

> Execute inline using superpowers:executing-plans and TDD. The user already
> delegated design/plan/execution and forbids worktrees, subagents and live evals.

**Goal:** Repair all eight tool/data findings and safe source refresh handling.

**Architecture:** Preserve authorization/source boundaries, extend the existing
typed tool contracts, and share pure normalization/evidence logic across callers.

**Tech stack:** Existing Python, Pydantic, FastMCP, SQLAlchemy, asyncpg and pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-mcp-data-contracts-design.md`

## Global constraints

- Current checkout; no commits, new dependencies, comments or docstrings.
- No saved traces, scenario dialogues, QA labels or evaluation outputs as inputs.
- No live model/DB write/index build/activation/deployment; offline focused tests.
- Preserve unsigned-write denial, exact grant binding and durable idempotency.

## Review focus

- Shared phone never grants another profile's discounts or order access.
- Selected lines/units determine amounts; missing/ambiguous targets do not write.
- Address changes survive subsequent reads and retries without mutating BTC seed.
- Requested and effective callback times stay visible and authorized.
- Source priority is data-driven; no SKU-specific correction or policy bypass.

## Task 1: Trusted identity across MCP

Files: new `app/mcp_servers/mcp_shared/identity.py`; catalog/order schemas,
handlers, services and gateway; new `test/test_mcp_data_identity.py`.

Interfaces: signed identity envelope helpers; `select_identity(matches, customer_id)`;
`MCPGateway.invoke_trusted` supplies identity proof for scoped reads. Writes use
the existing verified `AuthorizedWriteContext.customer_id`.

- [x] Write synthetic shared-phone read/write, tamper, foreign-owner and unsigned
  ambiguity cases; observe RED.
- [x] Implement proof propagation/verification and exact CRM member selection.
- [x] Verify all four writes, pricing and status scope, replay and denial GREEN.

## Task 2: Order-line updates and durable addresses

Files: order schemas/handlers/service/repo, business model tool fields,
preparation/authorization, relevant observation allowlists;
new `test/test_order_update_lines.py`.

Interfaces: optional update `line_index`, `qty`, `address`;
`OrderRepo.order_updates(session, order_id)`; update result includes selection
and amounts; status overlays the latest journaled address.

- [x] Observe RED for whole/partial multi-line refunds, ambiguous exchanges,
  quantity stock/price differences, absent addresses and read-after-update.
- [x] Implement stored-line normalization and selected-unit arithmetic, validate
  args and journal actual address changes. Keep fees/idempotency and ownership.
- [x] Verify real service/controller/MCP paths and SQL journal projection GREEN.

## Task 3: Calendar-normalized callback contract

Files: new shared calendar module and reviewed JSON; callback schema,
normalization/preparation, authorization prompt/service; calendar and callback tests.

Interface: pure callback normalizer produces effective time plus original time;
`normalized_write` and controller review consume the same canonical arguments.

- [x] Observe RED for dated opening exceptions, Sunday/holiday/late-hour times,
  timezone behavior and effective-time grant binding.
- [x] Normalize before review/signing; store only the reviewed effective time;
  return `moved_from`. Preserve fail-closed semantic authorization.
- [x] Update previous reschedule fixtures to the reconciled contract and verify.

## Task 4: Attribute search and catalog source conflicts

Files: catalog schema/handler/service/repo, shared commerce search, model fields;
new technical evidence parser/reviewed mappings and tests.

Interfaces: typed attribute filters; generic evidence enrichment accepts product
records and public policy table rows and returns attributes plus provenance/conflicts.

- [x] Observe RED for attribute queries, bool/numeric filters and conflicting
  technical values with unrelated fixtures.
- [x] Implement search/filter propagation and source priority with visible
  conflict metadata; preserve raw source JSON, pricing and stock/warranty authority.
- [x] Verify missing/ambiguous source handling and catalog-to-model output GREEN.

## Task 5: Product policy context and promotion validity

Files: policy schemas/auth/rules, gateway and business preparation; catalog quote
service and memory evidence helpers if required; focused independent tests.

Interfaces: verified product context with source provenance; applied promotions
consistently include `valid_until` from loaded source in both quote forms.

- [x] Observe RED for a verified product remaining conditional, spoofed/mismatched
  products, and missing basket promotion dates.
- [x] Propagate only source-verified product metadata and discharge corresponding
  applicability context; retain dates/links and strict signed schema.
- [x] Enrich unit/order promotion metadata without changing calculated prices.
- [x] Verify model arguments, in-process MCP, applicability and memory consumers.

## Task 6: Atomic source refresh, regression and completion audit

Files: dataloader import/verification, source-refresh tests; runtime/loader docs.

- [x] Observe RED for a removed source record remaining live after upsert.
- [x] Verify the transactional source snapshot and reject stale extras without
  deleting source or runtime records; retain policy workflow and dry-run behavior.
- [x] Run focused new and directly related regressions with dotenv/provider
  credentials disabled and sockets blocked; no full suite unless required.
- [x] Check syntax/whitespace, perform self-review, document deployment/import
  requirements and audit all nine spec requirements against current evidence.

## Execution record

Initial checkout was clean. Earlier stage fixes are present in committed source.
Spec/plan self-reviewed before implementation. Tasks share normalized schemas and
trusted source metadata; controller fields and server signatures must advance
together. No task requires applying changes to external services during execution.


### Progress

- Task 1: eight synthetic cases were RED on the actual shared-phone failures and
  absent read proof. All four writes, scoped status, member-specific pricing,
  forgery and expiry pass. Existing authorization regression: 106 passed, one
  gateway fixture needed matching catalog secret; focused follow-up: 18 passed.
- Task 2: initial RED showed 15 failures (refund amount/selection, exchange
  quantity and missing address); 113 focused identity/update/authorization cases
  then passed. Additional RED caught a multi-unit exchange omitting basket
  discounts and a read projection mutating a source dict. Both were fixed.
  Core update/identity follow-up: 26 passed. Added controller/model-tool → signed
  MCP → SQL journal/read-after-update/replay cases.
- Ruling: exchange replacement prices use a basket quote for the selected
  quantity; multiplying a single-unit quote would omit quantity promotions.
- Ruling: address changes use the existing append-only update journal as the
  authoritative overlay for owned-order reads. Raw seed records remain unchanged;
  this needs no new DB schema or external mutation during implementation.
- Task 3: initial missing-module/time-window cases were RED; an additional
  whole-day closure test caught loss of the requested clock time. Reviewed calendar,
  source hours, moved_from receipts and effective-time signature checks pass.
  Combined calendar/authorization/identity/update check: 131 passed.
- Ruling: reviewed opening-hours policy takes priority over simplified reference
  hours. Sunday and the dated sales opening are calendar data, with no date-specific
  controller branches. Whole-day closures preserve a valid requested clock time.
- Task 4: 15 initial RED cases covered text attributes, typed filters, provenance,
  private/unapproved/unparseable technical sources and unresolved conflicts.
  Follow-up RED cases caught equal int/float values creating false conflicts,
  conflicting technical warranty rows overriding catalog authority, and numeric
  segments in source hashes being masked in model output. All are corrected;
  catalog/memory evidence tests pass, with all 13 BTC attribute keys retained.
- Actual-source offline inspection: 40 catalog products and 99 source chunks read.
  The generic parser found one conflicting field: SKU-WF-RO10 stages=0 versus 10 in
  SP-WF-01. Output uses 10 with document/chunk/hash and original value recorded;
  source JSON was not modified. No per-SKU correction exists in application code.
- Task 5: six initial RED cases covered absent product schemas/context binding,
  spoofed products and missing unit/order basket promotion dates. Focused catalog,
  policy rules/service/MCP/integration check: 46 passed. Additional RED detected
  repeated order reads mixing/denying provenance and stale fallback after an empty
  latest status; the latest authoritative order read now supplies both date and
  product, with failed/empty reads invalidating earlier evidence.
- Ruling: a verified product clears only required_context=product. Order dates,
  receipt/registration conditions, rule scopes and required policy links remain
  independent. Multiple distinct order products require a selection. Raw gateway
  arguments cannot forge the signed product provenance.
- Ruling: quote metadata comes from loaded promotion ends. Unit and order promotion
  expiry survives durable memory observations; price formulas and existing profile
  fact schemas are preserved.
- Task 6: nine stale-table cases plus source-customer removal were RED, then pass
  with full transactional snapshot comparison. All nine source tables are locked
  for the import; missing/extra/changed rows reject and roll back without deletion.
  A further RED case caught CLI hiding the useful mismatch reason; typed safe errors
  now report the table/counts and source_commit_confirmed=False without customer data.
- Regression fixtures were advanced only for the changed contracts: public technical
  chunk reads, journal reads, source-expiry metadata and actual callback receipts.
  BTC per-unit stored lines omit qty; an independent RED case now verifies missing
  qty means one while explicit null/invalid qty still fails closed.
- Focused combined offline check: 326 passed in 5.07s. Dotenv and telemetry/provider
  configuration disabled; network sockets blocked. No full suite, live model,
  external import, migration, index build/activation or deployment was run.
- Six older catalog conversation tests failed in the broader targeted investigation.
  Loading the HEAD harness policy in memory reproduced the same six failures:
  one implicit carry-forward filter case and five phrase-derived variant/claim
  inference cases. They are pre-existing; obsolete phrase controllers were not
  restored. These tests were not represented as passing in the 326-test check.
- Syntax parsed for all 39 changed/new Python files; new JSON parsed, new Python
  has no comments/docstrings, and git diff --check passed. Docker copies app and
  therefore includes both reviewed JSON files; existing role grants already cover
  public policy chunks and the order update journal. No new DB schema is needed.

- Final policy/status barrier follow-up after the last controller correction:
  126 passed in 3.41s (product context, policy rules/search/MCP/integration/contracts
  and write authorization). Changed-file syntax/JSON and whitespace checks pass.

## Completion self-review

| Spec requirement | Implemented evidence | Offline verification |
|---|---|---|
| 1. Shared-phone identity | Signed scoped reads and write-context owner re-resolution | test_mcp_data_identity; test_write_authorization; test_mcp_gateway |
| 2. Lines/units/paid amounts | Full/partial selection, quantity stock checks and replacement basket quote | test_order_update_lines; concurrent exchange fee regression |
| 3. Actual address updates | Validated address, existing SQL journal, latest owned-read projection | Schema denial, SQL read-after-update, MCP replay and raw seed immutability cases |
| 4. Callback calendar | Reviewed calendar JSON, pre-review canonical arguments and moved_from | test_business_calendar; source-hours/receipt regressions; grant tamper/denial cases |
| 5. Attribute search | Attribute text, typed filters, model schema and MCP handler | test_catalog_evidence; test_catalog_ranked |
| 6. Verified policy product | Catalog/owned-order provenance, signed binding and latest-read barrier | test_policy_product_context plus existing policy/date/dependency tests |
| 7. Promotion validity | Loaded expiry on unit/order applied promos, retained durable observations | test_quote_promotion_validity; pricing/MCP regressions; existing memory admission |
| 8. Conflicting product sources | Generic public-table parser, reviewed source/field authority and visible conflicts/hashes | Independent synthetic sources, ambiguous/private/malformed cases, actual-source inspection |
| 9. Safe source refresh | Nine-table lock, full comparison before commit, safe typed mismatch report | test_dataloader_postgres; test_dataloader_offline; test_ingestion_verification |

All nine requirements are implemented in the current checkout. No required local
implementation remains. The observed six older conversation-inference failures
remain outside this repair. Model semantic accuracy, retrieval relevance, latency
and physical fulfilment were not measured or claimed. Returns/exchanges still
represent pickup requests; financial receipts are not proof of completed payment.

Deployment is separate: upgrade/restart the harness and catalog/order/knowledge
MCP together, carrying both reviewed JSON files and the same context secret. The
code uses existing source/journal tables and existing role grants. No new source
import, index rebuild, activation or schema change is required for these local
repairs against the previously verified BTC snapshot. Future imports with stale
extras deliberately require reviewed source cleanup before retrying.
