# Connected repairs from K0 b5ed4233

Authorized scope: fix observed payment aliases/repeated failed writes, unsupported
side-effect acknowledgements, offer/variant binding, basket preparation, policy
answer verification and source-inconsistent team scenario/metric expectations.
Preserve BTC originals and frozen runs. Current checkout, no subagents or worktree,
no paid API evaluation, live DB writes, deployment or automatic commits.

Work incrementally: reproduce each failure offline, fix shared boundary, run focused
regressions including previously passing cases. Final claims require connected tests;
no new TSR/HR claims without a separately authorized live run.

Checklist:
- [x] Canonical payment at model-to-tool boundary, invalid write acknowledgement.
- [x] Callback action/acknowledgement and handoff unresolved question.
- [x] Variant offers T06/T17; basket discovery/preparation T10/T18.
- [x] Policy evidence/verification T18/T19/T22.
- [x] Team T10 product naming; T13 matcher and T14 multi-product HR interpretation.
- [x] Connected regression and immutable-source/run checks.

## Progress

- Payment spellings canonicalized at model-tool preparation boundary (MOMO,
  Bank Transfer, BANK_TRANSFER, cod); strict MCP schema stays unchanged. Red/green
  alias checks and purchase/basket regression selection: 68 passed.
- Guardrail now rejects unsupported order-recorded/processing acknowledgements
  and callback-created acknowledgements without successful receipts. Focused
  acknowledgement/payment/purchase selection: 37 passed. This does not yet solve
  deterministic callback execution or repeated failed write recovery.
- Remaining checklist items are still open; no model-quality/eval gain claimed.
- Added narrow current-speech callback parser (explicit full date or today/tomorrow,
  one time; rejects negated/hypothetical/ambiguous/inconsistent dates). Agent invokes
  existing trusted callback tool once before model and renders actual receipt/failure.
  Callback + acknowledgement + business completion selection: 25 passed.
- Handoff now retains an immediately unanswered question after medical expertise
  refusal wording from T05; regression reproduced missing open_questions first.
- T06 reproduced using actual HikePro catalog/variant data, split stock and price
  sentences and deictic purchase speech. Claim-SKU resolution lacked the unique
  proper-name aliases already understood by consultation. Added bounded unique
  proper-name aliases (excluding generic Pro/Lite/etc and bundles/accessory-only
  model mentions); replay creates correct 41/XAM. Offer/entity/variant/fact-use
  regression selection: 123 passed. T17 and remaining groups not yet closed.
- T22 refund recovery replay now selects directly relevant refund sections instead
  of collecting every section from a document with refund in its title. Fixed
  accent-fold collision biểu mẫu -> biếu being mistaken for a promotional gift.
  Frozen evidence recovery passes both grounding and answer verifier, includes
  form instructions and 3–5-day conditions. Connected followup/response: 41 passed.
- Basket preparation now uses pricing.quote_order for an explicit total request
  naming two known nonvariant products, each one. Does not infer a basket from
  comparison/alternatives or larger/unclear quantities. Real source Pigeon+Fatz
  replay prepares 779,000 total before customer confirms and then creates order;
  basket/shortlist/replay selection: 60 passed. T10 unknown brand mapping and
  broader quantity/variant basket discovery remain separate open issues.
- T17 expired-discount confirmation replay now passes with both explicitly named
  size/color and parent-only spoken quote, using customer's prior size/color and
  real RunLite catalog/price/stock. No extra permission relaxation was added.
  This is session-bound offline replay, not full original worker/model execution.
- T18 seal question now has a bounded pre-purchase explanation from the one
  current retrieved bottle/seal business rule, with explicit unverified-order-date
  qualification. Does not borrow expired DT-OLD, unrelated HEPA rules, incomplete
  dependencies or rules requiring additional context. Checks use real frozen policy
  evidence and both production verifiers; broader T19 warranty recovery remains open.
- T19 extended-warranty topic selects its specific section. Verbatim applicable
  policy thresholds/formulas can pass the monetary guard without pretending to be
  a SKU quote; altered percentage/threshold is rejected. Monetary/policy/guardrail
  selection: 60 passed; specific recovery + followup: 27 passed. Combined shipping
  response still requires separately bound commercial evidence and remains open.
- Identical same-turn side-effect requests reuse the first result, including
  failure, instead of generating a new operation key and repeating a potentially
  committed write. Applies create/update/callback/handoff only; failed read refresh
  remains possible. Regression reproduced two creates before fix; 79 connected
  payment/purchase/basket/callback tests passed afterward.
- T10 working scenario now names Joie Pact in both customer turns, matching
  existing SKU-MB-STR1. SKU, price and scoring requirements unchanged. Added
  source-catalog replay of its actual total request: two correct items, 8,480,000
  total, no order before consent. All 13 K0 harness replay cases passed. Original
  BTC data and frozen eval artifacts were not edited. T13/T14 remain open.

## Final offline verification

- T13: reproduced missing filtered search and recovery stuck on old product.
  An explicit alternative search now discovers within the sourced category using
  current budget/room filters. Product-feature recovery defers to the shortlist
  for that request. Repeated preparation does not repeat the search; selected
  products, negated/hypothetical requests and product-specific questions retain
  their behavior. Actual T13 speech + source catalog recommends AirPure Y.
  Existing scenario matcher was retained, not loosened.
- T19: recovery preserves both complete extended-warranty and shipping-fee
  sections already retrieved. Full attributed policy quotations may explain
  monetary conditions without inventing a SKU quote. Both monetary and promotion
  checks still reject altered formulas or an appended unsupported product price /
  customer-specific free-shipping promise. Completeness rejects warranty-only
  answers to the compound question. This explains a tariff, not a final fee.
- T10: full two-item purchase replay exposed redundant budget-basis gate after
  preparing the total. When basket total <= limit, both unit/total interpretations
  fit; the gate is retained when total exceeds the unknown-basis limit. Real
  8,480,000 basket succeeds with 9m; 7m remains blocked. Existing budget test
  now covers both cases. No budget basis is fabricated or stored.
- T09: added current-price replay proving a previous-day quote is refreshed on
  the current business date, with no order creation. Callback execution and
  acknowledgement have separate production-node tests.
- T14: report no longer infers wrong selection solely from the final-order SKU
  when the current customer explicitly asks about both products. Frozen HR stays
  unchanged. Working team scenario now names the actual standing Senko fan;
  removed its ambiguous call-wide price label, preserving Panasonic order-price
  args_match. README/notes disclose reduced HR price-label scope for this call;
  no model-quality gain is attributed to that label correction.
- Connected focused regression: **381 passed in 12.31s** across payment,
  acknowledgements, callback, handoff, K0 replays, policy recovery, purchase,
  basket, variants, offers, consultation, grounding, promotions, evidence,
  delivery and report/claim tests. A pre-existing stale second-item promotion
  test reason was aligned with the unchanged HEAD runtime reason; monetary
  assertions remain unchanged. No full suite or model/API eval was run.
- Working dataset validates: 29 scenarios, 67 calls, 170 turns; 28 multi-session
  scenarios, 15 hard cases, 29 distinct customer phones; all four dataset gates
  pass. Frozen run integrity validated via load_pair: both traces remain 170
  rows, saved Full TSR remains 18/29. All **69** base/patch/effective source
  file hashes match the frozen BTC release manifest. git diff --check passes.

These checks establish the repaired offline paths and focused regression scope.
They do not establish a new TSR/HR, live worker reliability, deployment health,
or deterministic model behavior on a fresh 29-scenario run. The unrelated
return-request/order-status lifecycle observation remains a separate follow-up;
no order-state contract or BTC fixture was changed as part of this repair.
