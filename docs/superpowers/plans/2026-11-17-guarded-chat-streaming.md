# Guarded chat streaming implementation plan

**Goal:** Deliver actual incremental chat output behind existing guardrails, with correct persistence and honest streaming latency measurement.

**Architecture:** A turn-local stream context buffers model message chunks and publishes only verified answer units. The existing agent graph still verifies the final answer; runtime defers persistence until it knows the emitted prefix. NDJSON connects AI runtime to the existing backend WebSocket and text UI.

**Tech stack:** Existing Python asyncio, LangGraph/LangChain, FastAPI/httpx and browser WebSocket; no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-17-guarded-chat-streaming-design.md` implements the approach the user approved in chat. Builder review and execution are inline under the user's no-subagent rule; no commit/worktree/full-suite workflow is imposed.

## Review focus

- A price, phone number or tool JSON split across chunks must not bypass checks.
- Policy conditions can occur after an apparent complete sentence: hold the whole policy answer.
- A final recovery must not erase or contradict already emitted text.
- Disconnect during a side effect must not trigger a second write or store unspoken draft.
- Both evaluator arms and their manifests must use the same real stream lifecycle; headers/empty events do not count as tokens.

## Tasks

- [x] 1. Add `app/agent/harness/streaming.py` and focused tests for buffered verified units, withheld policy/sensitive content, raw-tool suppression, reconciliation and backpressure/disconnect. Watch RED then GREEN.
- [x] 2. Integrate agent streaming invocation, freeze later business tools, defer graph persistence, and add `AgentHarnessRuntime.stream(turn)` with disconnect/retry/identity coverage. Existing `run()` and voice retain their contracts. Watch real graph/model barrier tests RED then GREEN.
- [x] 3. Add authenticated NDJSON endpoint, backend relay and progressive frontend bubble; test IDs, malformed/truncated streams, safe errors and browser rendering before done. Keep preparation, memory updates and session binding.
- [x] 4. Add opt-in `--streaming` through canonical paired runner and saved provenance. Test first answer delta vs total/persistence, both arms, unsupported voice+streaming, and missing done. Keep nonstreaming rule 7 and existing thresholds.
- [x] 5. Self-review connected changes, run a focused combined regression after final edits, record results and exact live measurement command. No live model call, benchmark, DB reset or publishing until separately authorized. Do not call latency/M1 passing based on offline tests.
- [ ] 6. After explicit authorization, run the one paired streaming measurement, inspect actual gates and quality regressions, and continue fixing if the latency target remains unmet. Do not mark the goal complete before actual verification.

## Ledger

- Scope is the approved streaming/guardrail implementation. The 3-second gate remains a measurement target, not a promised outcome of buffering. User preferences authorize implementation choices and override repeated design-approval/subagent/worktree skill steps.
- Task 1/2 initial verification: 12 publication-unit tests and 5 real-graph runtime tests passed (17 total), including before-completion barriers, interruption prefixes, retry and refusing later tools. `run()`/voice regressions and final adversarial review remain pending.
- Task 3 initial verification: 7 AI API/auth tests passed; 19 backend WebSocket/session/timeline tests passed. NDJSON relay forwards the first frame before done and rejects mismatched IDs/sequence/text or truncation without retries. Browser rendering still requires verification.
- Task 4 in progress: opt-in streaming flag reaches both pair arms and warmup; runner records the first nonempty checked delta separately from completion/persistence. Broken streams fail rather than fabricate TTFT. BTC scorer and thresholds unchanged; saved-evidence checks extended to require streaming provenance in traces/reports/manifests.
- Final review: inline self-review, no subagent per user instruction. A complete price-objection block may stream after existing task/grounding checks; policy/PII/action blocks remain held. Machine JSON and disabled guardrails are refused. A zero-delivery interrupted retry returns `turn_interrupted` rather than publishing a response absent from saved history. Cost: the caller must ask for current status in a new turn; no silent write retry.
- Read-only preflight passed with the same model parameters, BTC source and knowledge release as `20261117T080357Z-d1f6f8e2`; no model request/reset performed. Reviewable implementation and exact one-pair command are in `docs/guarded-chat-streaming-20261117.md`. Live authorization is the remaining dependency.
- Final focused verification: 267 passed, 2 PostgreSQL integration tests skipped (11.46 s); backend/WebSocket/Chrome: 24 passed (6.25 s). Logs and source-bound offline verification saved under `ai-services/eval_harness/results/measurement-audit/20261117-guarded-streaming-*`. No full suite, model/embedding/ASR call, DB reset, publishing or commit performed.
- User supplied live run `20261117T092200Z-17b3f18d` after running the CLI themselves. Full TSR 100%, RQR 4.5%, price/promo HR 0%, TTFT p95 3807 ms; baseline TTFT p95 3207 ms. Execution degraded in both arms only at SC-T11/call_1/turn2: 12 model calls and GraphRecursionError after the tracking prefix was published while the redelivery-rule request was still unmet. Knowledge detection correctly rejects the unhealthy pair before creating a checkpoint; the advertised `.knowledge/experiment.json` does not exist.
- Follow-up repairs in progress: classify the entire tracking+redelivery request before publication; terminate redundant post-publication tool loops once an answer actually is complete; avoid model-only restatement of prepared price objections; recognize named shoe stock/variant reads; distinguish reported packaging condition from an actual policy question. Five exact offline regressions were observed RED then GREEN; the complete tracking+policy graph reply still needs a regression/fix before final validation. No additional live eval authorized or started.
- Follow-up repair validation completed offline: eight new live-trace/boundary regressions RED→GREEN; final focused batch 274 passed in 8.72 s. Complete shipping reply, trusted source order `date`, opt-out and short action acknowledgements are covered. `git diff --check` passed. See `docs/streaming-live-repairs-20261117.md`. Actual post-repair TTFT remains unmeasured; goal is not complete, and no new live model call/reset was started by the assistant.
