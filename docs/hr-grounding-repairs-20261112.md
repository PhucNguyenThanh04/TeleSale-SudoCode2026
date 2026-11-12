# HR grounding repairs — 2026-11-12

## Scope and invariants

Fix the causes identified in the frozen K0/K1 traces without scenario IDs,
BTC SKU/price constants, expected answers, or edits to BTC/scenario data.
Runtime and extractor remain independent. No model API calls, database changes,
knowledge publication, or rewrites of saved scores were performed.

1. A new explicitly identified model can trigger a bounded catalog lookup for
   an inquiry, not just a purchase. Existing admitted scope metadata is hydrated
   first so a two-item basket can still be resolved. Reads grant no consent.
2. An unresolved new model cannot inherit the old product's consultation scope.
   An empty/failed lookup must not authorize the previous product's price.
3. Customer product focus outranks an erroneous prior agent recommendation.
   Explicit requests for alternatives and comparisons still allow other models.
4. Verification binds price/promotion statements to the requested product, or
   the established focus for a generic price/promotion follow-up. A valid quote
   for another product is insufficient, even if both prices happen to match.
   Existing quote-date, variant, quantity, owner and purchase gates still apply.
5. Eval extraction distinguishes an attributed budget from a selling price in
   the same clause, understands spoken half-units, and preserves digit-written
   currency units. It does not consult tool truth to erase incorrect claims.

## General regression coverage

`test_product_switch_grounding.py` uses invented model names and prices, covering:

- New-model inquiry, same-price/different-price products, generic follow-ups,
  and incorrect prior agent speech.
- Empty lookup, unavailable lookup/quote and a previous-day quote.
- Whole shared runtime preparation → stub model → postprocessing → verifier.
- Correct recovery when evidence exists; no old-product price when it does not.
- Explicit comparisons, historical prices and requested alternatives.
- Coupon/address identifiers versus model identifiers.
- No order/callback/handoff side effects and no inferred purchase acceptance.

`test_price_budget_extraction.py` checks the public extraction API against
mixed budget/price clauses, digit/word forms and spoken half-units.
The existing explicit-model price-inquiry test was updated to require a bounded
read rather than forbid all preparation reads; its no-consent assertions remain.

## Verification results

- 336 focused tests passed across product resolution, catalog query, consultation,
  memory/commerce evidence, prices/promotions, grounding, K0 runtime replay and
  extractor/re-extraction contracts. One existing warning remained.
- Two `test_btc_context_replays_keep_brief_on_all_returning_turns` SAMPLE-01
  variants (text and voice) fail on missing `profile.room_area_m2`.
  Both were reproduced with the pre-change HEAD implementations loaded into
  an isolated Python process; files in the checkout were not rolled back.
  They are pre-existing and were deselected from the final focused command.
  No claim is made that every repository test passes.
- Offline speech re-extraction covered 680 rows: Full and Baseline in both runs.
  Only K1 Full SC06/call_1/turn 3 changed: the incorrect extracted 5,000,000
  selling-price claim disappeared; the real 5,490,000 claim remained.
- Offline verifier replay of the original K1 SC-T15 call 2, with observed catalog
  metadata and original within-call history, rejected the old UF price at turn 1
  when a current RO10 quote was missing. At turn 2 it recovered RO10 6,890,000
  and the RO10 quote's shipping/COD benefits. This replay does not regenerate
  model answers or prove the next live run's aggregate HR.
- The K0/K1 scenario snapshot digests match:
  `6270de45fbe5607316af7857f1ffa33d9e39f4a04774f86dcb12ab6808f7f5dc`.
  The four source traces retained their hashes during replay.

Frozen inputs:

- `ai-services/eval_harness/results/knowledge-k0-final/20261112T093027Z-f42a59c5`
- `ai-services/eval_harness/results/knowledge-k1-final/20261112T095815Z-369b9c88`

## Limits

These checks prove the identified failure classes offline, not HR=0 on unseen
conversations. Literal model discovery still uses the existing identifier parser;
unrecognized natural-language product names may require model-driven lookup.
Comparisons and historical prices intentionally retain their separate semantics.
The answer checks require the existing `AGENT_GUARDRAILS_ENABLED=true` setting.
Any new live metric must come from a newly authorized eval, not rewriting K0/K1.
