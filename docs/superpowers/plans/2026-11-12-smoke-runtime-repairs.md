# Repairs from smoke 20261112T060044Z-17ffa366

Authorized: repair observed smoke failures in current checkout. No live model
eval, source BTC edits, frozen artifact edits, subagents, DB reset or deployment.

Success requires production-path offline reproductions including actual preceding
sales observations, preparation evidence and session continuation; focused tests
alone without those inputs cannot establish the entire fix.

- [x] T10/T18 basket discovery before metadata, quantity semantics, presented
      basket recognition and consent continuation through runtime persistence.
- [x] T17 identify the actual blocking gate using cross-session state and worker
      facts; retain price/variant/stock/consent requirements.
- [x] T09 distinguish preparation quote from missing trace evidence; preserve
      current-date/identity/address matching and truthful tool accounting.
- [x] T19/T22 policy recovery with prior product quote, compound questions and
      verifier recovery completeness; prevent price-only recovery on policy tasks.
- [x] Connected focused regressions, unchanged source/run integrity, review of
      complete scope before claiming completion. No new model-quality scores.

## Verified progress

Policy replay with actual smoke call_1 turn_1 sales observations reproduced both
T19 and T22 failures. Accent-folded `gia han` / `gia dung` was treated as a product
price request, causing unsolicited product quote prefix, monetary verification
failure and price-only fallback. Shared product_price_requested now excludes
these non-price phrases (also gia dinh) in preparation, recovery and task-complete
checks. Tests exercise real verify_agent fallback with actual preceding quotes.
Policy-context / K0 policy / followup selection: **29 passed in 2.35s**.

Policy recovery completeness on other rejection paths and all remaining groups
are still unverified; goal remains active.

T18 discovery order reproduced with actual call_2 speech, no catalog cache and
two previously admitted SKU candidates. Basket recognition ran before bounded
metadata reads; it missed both products and fell through to quantity-2 individual
quotes. Moved recognition after metadata discovery, retaining all existing
quantity/alternative/nonvariant guards. Replay now produces one quote_order,
one unit of each product, total 779,000, and no individual quote. Focused K0
replay / shortlist / basket harness selection: **74 passed in 2.84s**. This
does not yet verify the worker-derived cross-session candidate shape or actual
persisted basket consent; those remain open.

T10 actual delivered basket sentence is recognized when replayed with its
catalog/quote observations. Adding actual model read calls exposed the missing
test dimension: configured agent_max_tool_calls is **5**, previous replay used
8, and the smoke model spent all five reads before continuation. Ready baskets
now attempt the existing permission boundary before model/preparation reads.
Successful basket completion returns the real order receipt without a model;
incomplete baskets can still finish after later reads (completion latch is set
only after passing readiness gates). Single-product orchestration unchanged.
Production AgentNodes replay at limit 5 creates once from exact T10 delivered
speech; no model configured. K0 replay / purchase continuation / business
completion / basket selection: **90 passed in 3.01s**. Full memory/runtime
roundtrip and other open checklist items remain unverified.

T17 actual smoke call_2 speech/current stock+quote and reconstructed prior
variant facts pass the existing purchase gate at tool budget 5. Added this
cross-session-input replay to preserve that evidence. It does not reproduce
the live failure yet: prior episodes/preparation inputs remain the uncertainty;
no permission gate was weakened to force a fix.

Policy verifier had an independent omission: a factually sourced price-only
draft answered a policy question and was accepted. Added failing tests using
actual prior quote (not an invented wrong price). Verification now requires
policy task completeness for initial draft and each recovery candidate, using
the existing task checker. Stable rejection label policy_question_unanswered.
Policy-context / K0 policy / followup / policy evidence / consultation response
selection: **52 passed in 2.70s**. Other goal items remain open.

## Connected production-path findings and repairs

T17 was finally reproduced through real graph, prepare_session, MCP catalog/order
handlers and production memory read/write with fake storage/inference only.
Two distinct issues:

- The pending operational memory view did not recover parent/variant/size/color
  from the exact catalog variant and successful variant reads, unlike the worker.
  It now uses the existing verified_variant_details helper, restricted to catalog
  observations in that owned session. No customer purchase authority is inferred.
- A parent-SKU quote from preparation survived alongside the exact variant quote.
  Explicit price acceptance used the parent quote first, then the variant gate
  rejected that consent (offer_confirmation_required). Consent price lookup now
  resolves the selection first and reads the exact selected SKU's quote. Gate
  requirements and current price/stock checks remain intact.

The production-path T17 replay creates the 41/DEN bank-payment order; explicit
purchase refusal and a different accepted price remain blocked. Real memory
roundtrips also cover T10 8,480,000 and T18 779,000: total delivered before consent,
no initial order, then one correctly priced two-line order, budget five tools.

T09 preparation actually performs a current-day quote. The runner omitted
prepared_tool_calls from published rows, so the official tool_called matcher
could not see it. Rows now include the runtime-attributed preparation reads on
their first real consumer only. Historical session calls are never copied into
later turns; latency accounting and per-turn tool budget remain unchanged.
Production prepare/runtime/runner replay verifies exactly one AP-PRO quote dated
2026-10-22 at 7,690,000 and no order. Frozen scores were not rescored.

The first connected regression exposed two regressions, repaired before closing:
early basket continuation bypassed model discovery on product changes; it is now
limited to deictic confirmation without a new explicit model or change request.
Other basket requests follow normal discovery. Policy completeness rejected
legitimate non-assertive lookup/clarification; the existing assertion/refusal
checker now preserves those while rejecting price-only policy answers.

**414 connected focused tests passed in 29.97s**, including actual deep/react
basket changes with text/voice, operational memory, offers, permission boundaries,
policy grounding, runner lifecycles and offline real-scorer end-to-end tests.
Additional deep/react parametrization of the new smoke runtime replays:
**12 passed in 9.33s** (overlaps the connected selection; counts are not additive).
No full suite or live model evaluation was run.

Integrity: load_pair validates old K0 (170 rows/config, saved Full TSR 62.1) and
the smoke (62 rows/config, saved Full TSR 60.0). For each frozen release, all 69
base/November-patch/effective file hashes match its stored manifest. No BTC or
frozen run files were changed. git diff --check passes.

## Completion boundary

All listed fixes have an offline reproduction and focused regression evidence,
including the production runtime/memory/prepare paths missing from the first
repair round. This completes the authorized code repair; live model outcome,
deployment/container state and fresh TSR/HR are unmeasured. A new user-run smoke
after rebuilding services is the next validation step. The runner trace change
corrects evidence coverage; a future TSR change alone must not be attributed
entirely to model improvement.
