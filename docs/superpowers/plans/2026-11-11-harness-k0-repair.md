# Harness repair from K0 20261111T082822Z-116126a9

Objective: resolve reproducible harness/measurement problems evidenced by saved K0
traces before working on Knowledge Gap Loop. Use the production shared runtime,
not a separate eval-only solver. Preserve BTC sources and original run/score artifacts.
No paid inference/evaluation, DB reset/import/mutation, deployment, agents, worktrees
or automatic commits in this goal. Preserve unrelated existing user changes.

## Implemented changes and evidence

- [x] Catalog word/model tokens replace arbitrary substring matching; explicit brand,
  model qualifiers and product-type prefixes constrain discovery. Features rank within
  the type. Comparison queries keep both brands. Tests reproduce Windbreak (29 noisy
  hits), Sunhouse, Lock 4 and Xiaomi 4 Pro. Exact-SKU output still matches BTC mock.
- [x] Short-name resolution uses unique proper-name tokens from sourced catalog names;
  no brand/result-schema or memory allowlist extension. It recognizes Windbreak/Spectra
  while a standalone product choice cannot authorize its similarly named combo.
- [x] Lock&Lock parsing, letter clothing sizes and navy/be claim binding preserve the
  actually selected variant instead of losing it between offer and consent.
- [x] Purchase permission recognizes tao don/len order and polite duoc roi, cam on em
  only after a real presented offer plus confirmation question. Negated/hypothetical
  orders and past-purchase status lookups do not grant a new purchase.
- [x] Presented-offer validation includes the latest same-date inventory evidence.
  A valid price+stock sentence previously failed stock_sku_mismatch when constructing
  consent; failed/stale inventory still cannot support that sentence.
- [x] Quote/order binding recognizes giao ve/ship ve with literal customer-matched region
  evidence, retaining unknown state for mismatched addresses. No raw addresses added
  to long-term memory persistence.
- [x] Order-status requests prepare an owner-bound read; one known order is normalized
  to its ID and duplicate same-turn reads are reused. Unknown identity and foreign
  IDs remain denied. A real AgentNodes fake-model replay answers sourced shipping
  status even when the model asks unnecessarily for the already known order ID.
- [x] Answer completion/recovery treats stock, app, child lock and order status as
  their own requested information, rather than replacing them with a price. Missing
  app data remains unknown. Accessory model suffixes require an accessory cue, so
  AirPure Pro alone does not identify a replacement filter for that model.
- [x] Human handoff retains an immediately unanswered question after an explicit refusal
  when episode extraction omitted it; resolved questions are not resurrected. This
  fixes the actual T05 open_questions omission without loosening the test matcher.
- [x] Question extractor excludes no-order-found statements from RQR requests while
  retaining actual ID requests, including requests without '?'. Frozen language labels,
  extraction contracts and report verification pass; unresolved claims stay unresolved.
- [x] T15 data precondition repaired: no assumed RO10 advice from call_1; customer names
  RO10 in call_2, which tests its quote. Unsupported product carry-over labels removed.
  This was the stated least-assumptive choice after asking the user; it changes future
  dataset identity, never the K0 snapshot or old score.

## Verification

- Final connected commerce/harness/worker/brief selection: 269 passed,
  /tmp/harness-k0-focused-final.log (20 focused test files, not the full suite).
- Presented-offer and guardrail false-positive suites: 54 passed.
- Extractor language labels/contracts/report suites: 26 passed.
- Total across these disjoint selections: 349 passed. One dependency deprecation warning.
- New test_k0_harness_replay.py uses original BTC products/promos/inventory with actual
  BusinessTools, persistence allowlist, consent and AgentNodes; model/transport are fake.
  Covers correct-once Windbreak/Lock orders, wrong-combo and unrelated-price rejection,
  and known-owner order lookup/answer. No expected-answer labels enter runtime.
- Dataset canonical preflight: 29 scenarios / 67 calls / 231 turns; acceptance labels
  available for all 38 returning calls; dataset_ready=true. This is data readiness only.
- K0 load_pair validates original artifact hashes; original BTC source hash comparison
  reports zero changed files. git diff --check passes. Original K0 metrics not rewritten.
- Offline fixtures now supply received_at_monotonic as the real runtime does. Tests use
  KNOWLEDGE_ENABLED=false so local live feedback configuration cannot activate a mock
  repo's absent async feedback method. No service .env files were changed.

## Interpretation and limits

K0's full pass count is six: one team case and five public cases. The scorer caps its
failure examples at 40, so subtracting that list from IDs incorrectly suggests eight.
Old trace addresses are masked: never use the masked literal to claim a quote mismatch
in the original runtime. The address defect was independently reproduced with literal,
customer-matched region fixtures.

Catalog search intentionally improves relevance while retaining output format and
inventory/pricing rules; it does not change source data or BTC scorer. Specific tool-arg
matchers (e.g. max_price_vnd versus a direct SKU lookup) remain as authored. A valid
alternative recommendation can still fail an exact matcher; review semantics instead
of silently relaxing it. Medical/unknown specifications still need correct refusal,
not invented facts. These repairs do not prove new model TSR/CCR/HR or latency.

Because code/extractor and T15 input changed, the next authorized live pair is a NEW
baseline K0. Do not attribute any change against the old K0 to knowledge release alone.
No API evaluation was run or claimed as passing in this repair goal.
