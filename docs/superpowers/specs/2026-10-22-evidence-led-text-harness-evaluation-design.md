# Evidence-led text harness evaluation design

## Intent

Find the highest-impact text-to-text harness failures before changing memory or agent behavior. The current memory report describes a newer `gemma4:31b` run, but no matching trace and BTC score artifact has been identified in the repository. Historical trace scores cannot stand in for that run.

## Outcome

Produce one reproducible `full` versus `baseline_no_memory` comparison on all seven BTC public scenarios. The comparison contains the exact trace JSONL, BTC reference-evaluator report, a safe run manifest, and a per-scenario failure matrix. The matrix identifies the first observed failure in the chain: identity/read, memory write, Call Brief/context, agent use, business-tool call, or task outcome. It records when trace evidence cannot distinguish stages.

Use that evidence to choose the first runtime repair. Do not prescribe a repair until the failure is reproduced. For each repair, use an independent wording/product variant and an unaffected control; keep the public sample as an acceptance check. Later expand development cases to the published hidden-test classes and measure latency on at least 100 turns.

## Boundaries and decisions

- Scope is M1 text-to-text harness. ASR, TTS, voice, UI, and project differentiation are later work.
- BTC `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md`, tool/schema/mock data and `reference_eval.py` define the contract. Sample labels are evidence to review, not runtime rules.
- Use the existing `eval/run_eval.py` and `reference_eval.py`; do not build a second scorer.
- Full and baseline use the same code, model and parameters, tools, catalog/policy data and initial DB seed. Baseline differs only in access to prior-session memory. Their mutable DB state is restored independently from the same seed before each run. `--isolated-db` alone does not perform this restore.
- The manifest contains a run ID, UTC time, source snapshot hash including dirty files, BTC data hash, model identifier and nonsecret parameters, tool mode, guardrail switches, database identity, seed identifier/hash, hardware description, trace hash, and evaluator report hash. It contains no DSN/password/token/raw PII.
- The trace remains BTC-schema-compatible. A separate masked diagnostic sidecar may record identity status, available prior fact keys/scopes, prior episode counts, Call Brief presence/field names, memory failure status, and tool success; it must not contain raw phone, address, name, prompt, or unsanitized tool result.
- `questions`, `claims`, and `facts_used` extraction is an estimate. Audit representative rows against actual agent text and tool arguments before treating RQR/CCR/HR as reliable.
- Seven public scenarios contain fewer than 100 turns. Report their observed latency descriptively, without claiming BTC p95 compliance. A later 100+ turn run follows the BTC warm-up and boundary rules.
- If live MCP/LLM or an isolated resettable DB are unavailable, finish the instrumentation and runbook, label any historical trace analysis as historical, and do not claim a new full/baseline result.

## Acceptance

The pair has complete, unique scenario/call/turn coverage; every row validates against BTC's trace schema; both manifests prove comparable configuration and starting state; the BTC evaluator runs on those exact files; and every failed scenario has evidence-linked stage findings with uncertainty marked. The next repair is chosen by lost Task Success and broad applicability, with guardrail and false-handoff regressions checked. No hidden-test score is claimed.
