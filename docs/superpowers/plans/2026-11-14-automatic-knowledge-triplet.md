# Automatic knowledge experiment

Approved scope: run No memory K0, Full memory K0, automatically review eligible
worker proposals, publish K1 and run Full memory K1. No advance review-plan file,
no frontend dependency, no fourth conversation run. Existing explicit pre-reviewed
plans remain optional. This is experimental automatic approval, not human review.

1. Generate scoped feedback from actual K0 policy lookups, use the real worker,
   review its drafts against current public source hashes, applicability,
   unambiguous lexical relevance and offline regression checks. FAQ answers must
   copy source text exactly; dynamic commerce topics are excluded. Log skips.
2. Wire automatic review into the existing checkpoint/publication/K1 pipeline and
   managed launcher. Persist the review mode and catalog fingerprint, preserve
   idempotency, original boot, dataset/model, source and existing revision checks.
3. Report unchanged BTC metrics for three arms and new-revision retrieval evidence.
   Do not treat generated answers/tests as independent correctness ground truth;
   automatic mode has no literal answer accuracy claim. Log all decisions.
4. Verify focused offline services, orchestration/resume, CLI/startup argument
   handling and real in-memory hybrid publication/search. Do not run live LLM eval
   or modify the user's database. Document one-command operation and limitations.

Completion evidence:
- 91 focused offline tests passed across automatic review, optional pre-reviewed
  review, triplet orchestration, official pair ordering, managed startup and
  publication/search. Real lifecycle/worker services and Qdrant in-memory hybrid
  indexing/search are exercised; model/embedding backends are offline fixtures.
- Tests cover source hashes, expired/missing order dates, ambiguous relevance,
  dynamic topics, unsupported content, permissions, regression failure, scoped
  jobs, idempotency and release capacity. Review/publication interruptions resume
  without another K0; changed source/catalog/review/trace/boot are rejected.
- Both modes run pair then Full-only K1; automatic mode needs no plan file and
  reports no generated answer accuracy. Independent BTC scoring is exercised.
- CLI help and diff whitespace checks passed. No live LLM evaluation, Cloudflare
  call, database reset or BTC source edit was performed for this goal.
- The automatic gate is lexical/source-bound, not a semantic verifier; no eligible
  proposals stops before K1 with exit code 2 instead of fabricating improvement.
