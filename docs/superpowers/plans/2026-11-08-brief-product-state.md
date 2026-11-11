# Consistent returning-customer product state

Goal: correct a brief listing X while accepted consultation history recommends Y,
without adding model calls, reads or refreshes to the live voice/text path.

1. Reproduce X→Y with stale product facts and an admitted recommended_sku=Y.
   Pin call counts, selected versus recommended state and missing/untrusted
   evidence in offline tests.
2. Reuse the single derive_consultation result already calculated by load_context.
   Keep products_advised as historical discussed products; add nullable
   recommended_sku and selected_sku from its provenance-backed snapshot. Include
   the admitted recommendation in history even if the separate fact projection
   has not caught up. Do not treat catalog candidates or a quote as advice.
3. Make the suggested opening and browser brief distinguish historical products,
   latest recommendation and confirmed customer selection. Keep existing refresh
   selection/count unchanged. Never copy X's price/promotion onto Y.
4. Verify focused harness, brief, memory and browser tests. Update protocol docs.

Ruling: the scalar product_advised fact is historical evidence, not the canonical
latest recommendation. Reconcile the brief from the already-admitted consultation
snapshot instead of rewriting historical facts or replaying old tool results as
current evidence. This fixes the missing-fact symptom without new memory I/O.

Constraints: current checkout; no subagents/worktrees/live inference/benchmarks.
Do not promise wall-clock latency improvement from offline checks; verify no
additional model/read/refresh calls and report that actual demo latency is unmeasured.

## Completion evidence

- Implemented the brief reconciliation, nullable recommendation/selection fields,
  provenance checks, opening and browser labels. Kept historical prices attached
  to their original SKU; did not modify the worker, storage or refresh selection.
- Reused-catalog regression derives the real committed consultation snapshot:
  delivered Y advice supersedes X, but unplayed Y text leaves X as the latest
  recommendation. Neither agent advice nor tool evidence creates customer selection.
- The X→Y fixture asserts exactly one memory read, one existing consultation
  derivation and the same two refresh calls for Y. No model or storage I/O was
  added. No historical fact rewrite/backfill is necessary.
- Verification: 87 focused AI/brief/consent/freshness/voice tests passed; a further
  26 chat/memory regression checks passed (includes the brief tests again); three
  Chrome cases passed for the new labels, missing selection and legacy briefs.
- BTC Call Brief schema permits additive fields; legacy opening/brief tests pass.
  Final diff whitespace check passed. No live call, benchmark or service restart
  was initiated, so real demo wall-clock latency has not been remeasured.
