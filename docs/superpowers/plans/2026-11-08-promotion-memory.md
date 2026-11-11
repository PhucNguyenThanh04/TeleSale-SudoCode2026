# Promotion fact recall without requiring spoken technical codes

Goal: derive promo_code/promo_expiry from communicated, verified benefits using
existing quote observations. No new model calls, network or database reads.

1. Add offline regressions for percentage/fixed discount/shipping without codes,
   current literal-code/gift behavior, ambiguity, negatives, questions, wrong
   product/deadline, expired offers and confirmed voice text.
2. Extend deterministic reported-promotion matching against applied_promos only.
   Match numeric percentages to verified discount/list-price, monetary savings
   to discount_vnd and shipping to a real freeship promotion. Require unique
   benefit attribution; preserve explicit code disambiguation. Do not infer an
   offer from the sale price alone or a general unverified promotion statement.
3. Bind promotion and expiry checks to the same quote/product and communicated
   benefit; do not cross-borrow another benefit's code/deadline. Keep the existing
   scalar memory schema and admission conflict handling for multiple promotions.
4. Test through observation allowlisting, verified candidates, admission and the
   worker's projection boundary using offline doubles. Verify existing promo,
   memory, guardrail and voice behavior; update docs and inspect the diff.

No sample/campaign constants in implementation, no subagents/worktrees, no live
evaluation/benchmark or service restarts. Preserve existing brief changes.

Completed verification:
- 30 promotion-memory regressions pass, including observation filtering,
  admission, worker projection with empty model extraction, and unspoken text.
- 55 existing focused checks pass for memory refinements, primary/worker,
  promotion grounding/recovery/second-item, fact evidence, freshness and playback.
- 25 admission, projection and promotion-refresh checks pass.
- No live evaluations, external model requests or service restarts performed.
- Runtime edit is limited to reported_facts.py; it consumes existing observations.

Limits: descriptive matching supports numeric ordinary percentages, money savings,
unique gifts and verified freeship campaigns. Ambiguous identical benefits require
an explicit code. Existing scalar admission conflict rules remain in force when
multiple different codes are communicated for the same product; no schema change.
Historical stored facts are not backfilled by this change.
