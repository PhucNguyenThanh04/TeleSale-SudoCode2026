# Measurement audit: RQR / CCR / HR

Optimize the agreed measurement scope, with offline evidence only. Preserve BTC
scoring rules, source data, scenario expectations and original K0 artifacts. No API,
DB changes, agents or worktrees. Existing question fixes are preserved.

1. Replay current extraction on the frozen pair to a separate output directory.
2. Fix reproducible measurement defects with focused positive/negative checks.
3. Record observable prior-fact use separately from mere context availability.
4. Validate question/claim labels, conservative claim-source explanations, CCR
   provenance/scope, baseline isolation, replay hashes and original artifacts.

Old traces lack call-start fact snapshots: never fabricate a retrospective CCR.
HR mismatch explanations cannot remove BTC errors or infer missing quote evidence.

## Changes and proof

- CCR now recognizes an unambiguous catalog-backed spoken product name as use of
  a prior product_advised SKU. Scope, prior-session source, negation/hypothetical
  language, failed catalog and current customer repetition still constrain credit.
- Inactive/superseded/expired/deleted facts cannot receive recall credit. Tests
  reproduced the prior false credits and missing named-product credit before fixes.
- Future runner rows carry facts_used_evidence: field, scope type and matching
  method (speech/tool_args). No raw fact values, source text or extra PII is added.
  Merely having a fact/context present produces no evidence. This records observable
  use, not causal proof that the model relied on memory.
- HR diagnostic explanations can inspect earlier tools within the same scenario,
  call and date. They cannot borrow future turns/other calls/other scenarios, accept
  failed/stale/conflicting quotes, or change BTC claims/scores. Expected product
  labels may come from args_match or that call's facts_established, only for display.
- Existing RQR narrative exclusions were verified using the frozen K0 pair; no
  new question rule or BTC scoring rule was required in this goal.
- CLI integration test now uses its fixed repair fixture instead of assuming the
  mutable working scenario directory still contains the former seven samples.
  Working scenarios are preserved. At verification time some of its calls are lists;
  the canonical loader requires a call_1/call_2/... dictionary. Therefore current
  working-dataset readiness is NOT established by these measurement checks.

## Offline K0 comparison

Replay artifact: ai-services/eval_harness/results/measurement-audit/k0-extraction-20261111
contains separate scores, sidecars and replay_manifest.json. It is explicitly an
annotation replay, not a new agent evaluation. No source run.json is replaced.

| Metric | Original Full | Annotation replay Full | Original baseline | Replay baseline |
|---|---|---|---|---|
| RQR | 32.9% (24/73) | 26.9% (18/67) | 57.1% (40/70) | 56.5% (39/69) |
| CCR | 15.2% | 15.2%, preserved | 1.3% | 1.3%, preserved |
| HR | 17.1% | 17.1% | 27.3% | 27.3% |

Lower RQR here is measurement correction, not improved conversation behavior.
Old public traces lack the sourced call-start fact snapshots needed to rerun CCR;
the new CCR fixes/evidence apply to future executions only. Full HR remains 7/41.
Same-call context now identifies the wrong-product quote behind SC06 call_1 turns
2/3; cross-call or absent evidence remains unresolved. Source-consistent price is
not necessarily the price of the customer-requested product.

## Validation and limits

- 96 focused fact-usage / claim-source / report tests passed after final changes.
- 35 focused CLI, offline-end-to-end, report and trace-redaction checks passed;
  selections overlap and must not be added as unique test counts.
- The connected selection also passed extraction contracts/report/replay integrity,
  official pipeline and the 18 transaction sequence/language checks. Its initial
  mutable-dataset CLI failure was fixed and rerun above. No full suite or model call.
- Frozen self-reviewed speech labels: 18/18 detected/matched, no classification
  errors. This small label set is not independent human/hidden-test calibration.
- K0 entire source file hashes match replay_manifest.source_hashes; load_pair
  verifies original score/trace/scenario/manifests. Original BTC and November patch
  list/SHA256 also unchanged. git diff --check passed.
- No new model TSR/CCR/HR/latency claim. Before any API run, preflight the actual
  working dataset; this task intentionally did not rewrite that dataset.
