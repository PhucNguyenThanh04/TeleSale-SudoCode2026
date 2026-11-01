# Text Conversation Evaluation Harness — Design

## Intent

Make each text-to-text evaluation run reproducible, traceable to the current
code and BTC data, and scored by BTC's unmodified `reference_eval.py`. Show
one selected run in a readable chart dashboard. The harness should reveal
which conversations failed and why without presenting incomplete runs as
valid scores.

## Decisions from the discussion

- Scope: text-to-text conversations and every metric with an observable text
  input and a defined scoring method. Audio, ASR, TTS, diarization and TTFA are
  outside this spec.
- Clear test data in schema `runtime` at the start of each `full` or
  `baseline_no_memory` run. Keep `btc_source`, schema definitions and
  `runtime.store_migrations`. Reset runtime sequences. The user confirmed the
  current runtime data is test data and authorized this reset.
- Dashboard: show charts for a single selected run. Do not make agent or
  configuration comparisons the main presentation.

## Existing components to reuse

- `ai-services/eval_harness/benchmark_runner.py` runs current Deep/ReAct
  harness turns, waits for LangMem distillation, and exports BTC trace rows.
- Root `eval/trace_audit.py` checks BTC JSON Schema, exact turn coverage and
  provenance; `eval/score_pair.py` calls BTC's scorer and records hashes of its
  inputs and report. The new flow must use these components rather than
  reimplementing their contracts. Both currently derive the BTC scorer/schema
  location from the scenario directory, so they need an explicit BTC source
  path for the local `ai-services/eval_harness/scenarios` dataset. The root
  manifest currently requires a `telesale_eval*` database name, while the
  authorized local test database is `telesale`; the new preflight must use
  explicit expected DB identity and non-production mode instead of a name
  prefix alone.
- BTC `schemas/trace_log.schema.json` and `eval/reference_eval.py` define the
  authoritative trace format and conversation scores. The reference scorer
  itself remains unmodified.
- The `runtime` reset already added to `eval_harness/` runs before each
  configuration, checks all MCP database identities, rejects production mode,
  preserves store migration metadata, and resets the order sequence.

## Evaluation flow

1. Select a scenario directory and agent. Record a run ID, source revision,
   dataset digest, BTC scorer digest, model and sampling parameters, runtime
   settings relevant to answers, DB identity, seed identity, and hardware
   description without secrets or raw customer PII. Compute the seed digest
   from canonical `btc_source` table contents before each configuration; the
   two digests must match. A file hash of the BTC release alone is insufficient
   to prove what the live database contains.
2. Verify that the configured database and all three MCP servers point to the
   same test database. Reset `runtime` before `full`; run every customer turn
   in scenario order and wait for the corresponding LangMem job to reach a
   terminal state before the next turn. Require exactly one job for an
   identified committed turn; allow zero for an anonymous turn. A failed or
   missing expected job invalidates the run. Preserve partial traces for
   debugging.
3. Reset `runtime` again before `baseline_no_memory`. Run the same scenarios,
   model, business tools, and CRM identity with only prior long-term memory
   hidden. A failed reset or incomplete run cannot become a scored run.
4. Validate each trace with BTC JSON Schema and exact scenario/call/turn
   coverage. Reject duplicated, missing, out-of-order, or invalid rows;
   failed memory jobs; missing or mismatched DB/model/dataset metadata; and
   changed scorer or trace bytes during scoring. Locate BTC schema and scorer
   through an explicit source directory, independent of scenario location.
   The runner must not calculate or publish an official score after any turn
   exception, missing job or failed reset, even if it retained partial trace
   rows.
5. Call BTC's `reference_eval.py` on the validated full/baseline pair. Store
   its original report, input hashes, run manifests, redacted diagnostic
   events and traces under ignored `eval_harness/results/<run-id>/`.
6. Produce optional diagnostics from the internal scorer and stage evidence.
   Label them as diagnostics. If an overlapping metric differs from BTC,
   display the discrepancy and use the BTC value for the published score.

## Metric contract

The dashboard must show numerator, denominator, value, threshold if BTC
defines one, and measurement status for each applicable metric. A missing
denominator is `not measured`, never zero or pass.

| Metric group | Source of truth | Display |
| --- | --- | --- |
| TSR overall and hard cases; RQR and relative reduction; CCR; hallucination overall and price/promotion; guardrail violations | BTC paired reference report | Score cards and per-scenario charts |
| Total latency, TTFT, Call Brief latency | BTC paired reference report and trace | Distribution and p50/p95; nonstreaming TTFT equals total latency |
| Average turns per call, calls to close, memory checks | BTC paired reference report | Charts or review list when denominator exists |
| Memory recall/precision, tool counts, tool retries, job failures, verifier rejection reasons | Existing harness trace and diagnostic sidecars | Diagnostic charts, clearly separate from BTC score |
| Policy retrieval Recall@3/@5, multi-hop full recall, abstain and false-abstain | Fresh ranked retrieval run on BTC's 60 labeled text questions, scored with BTC's `--rag` path | Separate text retrieval section; no invented values |
| Cost per call, calibrated LLM-judge rubric | Billing source or human-labeled calibration set not yet established | `Not measured` until a source and method are recorded |

Question and claim extraction, plus `facts_used`, are part of the measurement
boundary. Keep an annotated synthetic fixture with Vietnamese paraphrases,
boolean facts, confirmation questions, prices and promotions. Measure
extraction misses and false positives against those labels before trusting
RQR, CCR or hallucination rates. The current `reference_adapter.facts_used`
ignores booleans, and the internal scorer skips structured forbidden claims;
these are known sources of metric drift.

For latency, the 7-scenario public sample has only 39 turns; display BTC's
sample-size warning. The 19-scenario local set has 116 turns. Record the
measurement boundary and warm-up rule; show BTC's raw result as official and
any warm-up-adjusted diagnostic separately if it differs. Do not call a
nonstreaming total-time value a measured first-token timestamp.

## Dashboard behavior

Use the selected run's validated manifest and BTC report rather than fixed
filenames or hard-coded scenario counts. Show: overall score cards; a bar chart
for measured rates against BTC targets; pass/fail by scenario or category;
failure-reason counts; latency distribution and p95 marker; memory carryover
and repeated-question counts; and a drill-down to redacted per-scenario
diagnostics. Filters select the run, scenario group, and metric. Charts label
their units, denominator and unavailable state. Do not display raw PII from
trace files or stale historical runs as current results.

## Acceptance criteria

- A complete pair produces the same authoritative values when BTC's
  `reference_eval.py` is rerun directly on the emitted traces.
- Reset clears all mutable `runtime` rows and resets runtime sequences before
  each configuration, while preserving `btc_source` and `store_migrations`.
  A database mismatch, production mode, missing reset privilege, or lock
  timeout stops the run before customer turns or scoring.
- Missing/duplicate/invalid trace rows, failed LangMem jobs, changed inputs,
  or incompatible pair metadata prevent publication of a BTC score. Partial
  traces remain available for diagnosis.
- Dashboard selects a valid run and derives scenario/turn counts from its
  manifest. Every chart handles missing denominators without coercing them
  to zero. It renders only aggregate or redacted data.
- Tests cover reset behavior on an isolated PostgreSQL database, the paired
  run lifecycle, trace/schema audit, BTC score parity, extractor fixtures,
  and dashboard data loading with missing and invalid metrics.

## Implementation calls to review

- Treat the BTC conversation report as the score authority; retain internal
  scoring only for diagnostics.
- Keep policy retrieval as a separate text-only section because it has a
  different labeled dataset from the conversation scenarios. Generate a fresh
  result file for every complete evaluation run; display `Not measured` only
  if the retrieval service or BTC QA dataset is unavailable, and record why.
- Show cost and LLM-judge metrics as unavailable until their input data is
  supplied and validated.
