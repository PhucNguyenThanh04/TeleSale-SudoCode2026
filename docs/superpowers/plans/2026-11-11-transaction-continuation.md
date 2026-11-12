# Transaction continuation optimization

User authorized continuing the proposed optimization: product/variant binding,
purchase completion and receipt-backed later order lookup, then measurement review.
Use current shared runtime. No paid inference, live eval, DB mutation, BTC data
changes, original K0 rewrites, worktree, agents or automatic commits.

1. Replay K0 SC-T01 / SC-T02 / SC06 customer turns across calls with real graph,
   MCP, commerce rules and memory services; only storage/model replaced.
2. Reproduce remaining failures, fix the shared cause with focused regression tests.
3. Verify receipt owner lookup, no duplicate/unconsented orders, product switches,
   price changes, baseline isolation and extractor evidence boundaries.
4. Run focused connected checks; report offline evidence separately from model
   quality and end-to-end eval scores.

Tests must not feed scenario expected facts/answers into runtime. Prepared model
responses exercise orchestration, not actual model performance. Preserve old repairs.

## Completed changes

- Combined stock/price request: safe_product_reply previously returned stock alone,
  discarding an already sourced price. SC-T02's next purchase therefore had no
  presented offer to accept. Recovery now adds the matching current quote when the
  customer asks for price, and includes the actual size/color in the stock label.
  Stock-only/feature-only questions still do not receive an unsolicited price.
- Receipt lookup: order_status_requested did not recognize “kiểm lại đơn”, including
  SC-T01's actual first call_3 message. It now recognizes that wording while keeping
  negation, hypothetical requests and new purchase intent separate. Existing owner
  checks, tool budget, consent and current-price requirements remain in force.

## Evidence

- New test_transaction_continuation.py replays original K0 customer speech and the
  first turn's actual model discovery/read proposals through the shared graph/MCP.
  Later model responses are generic; completion must come from orchestration.
  Trace-masked identity/address/date fields are removed from proposals and supplied
  by the trusted runtime. Scenario success labels are used only in test assertions.
- SC-T01: one Xiaomi order, then receipt-bound order.status and sourced reply in
  call_3. SC-T02: first call creates exactly one M/navy Windbreak. SC06: one Xiaomi
  order; recorded unrelated mother/baby quote proposals do not reach the gateway.
  All three run with deep/react × text/voice (12 sequence checks). SC-T02 later
  exchange/policy conversations are not claimed as covered by this new replay.
- Six language checks include positive lookup, negation, hypothetical lookup and
  ordinary create-order wording. The sequence tests failed before the two fixes;
  the expanded 18-test replay passed afterward.
- Final focused connected selection: 235 passed in 33.91s across 15 files. Includes
  variant/evidence, consent, changed prices, duplicate-write prevention, baseline
  isolation, voice interruption, prior K0 replay, and extractor/report contracts.
  No full suite or live model evaluation was run.
- K0 load_pair verifies original scenarios/traces/score/manifests; hashes valid.
  Original BTC and November patch file list/SHA256 unchanged (55 files).
  git diff --check passed.

## Limits / next measurement

The fake model does not prove new-model tool selection, generated-answer quality,
TSR/HR/CCR or latency. Generic replies without the recorded initial discovery reads
are not asserted to solve these cases: initial model discovery still matters.
These runtime repairs apply to both eval and deployed flow. A future authorized
API run should be a new baseline/full pair on the current code/data, not a rewrite
of old K0 or a knowledge-loop-only comparison. No API calls or deployment performed.
