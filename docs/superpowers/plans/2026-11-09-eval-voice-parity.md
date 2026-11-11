# Eval voice lifecycle implementation plan

**Goal:** Run transcript eval through the deployed voice runtime lifecycle, with comparable response timing and durable memory before the next turn.

**Approved design:** The user approved the conversation proposal: prepare the session before inference, generate with voice delivery, acknowledge full playback, and finish memory outside response timing. Reuse the existing runtime methods used by the HTTP endpoints; do not create another agent implementation. ASR, TTS, browser playback duration, and network transport remain outside this transcript evaluation.

**Execution:** Implement inline in the current checkout. No agents, worktrees, live model calls, database resets, or deployment. Preserve existing user changes. Use focused offline tests.

## Task 1: Lifecycle parity

- [x] Add regression tests using the real `AgentHarnessRuntime` with offline model/memory/tool dependencies. Prove prepare precedes inference, full original reply is committed once after response, history is available next turn, and no playback timers remain.
- [x] Test preparation and playback failure behavior and diagnostics; never silently fall back to text delivery.
- [x] Change `eval_harness/benchmark_runner.py::run_scenario_call` to call `prepare_session` once per nonempty call, `run` with `delivery_mode='voice'`, and `record_playback` with the original response length and `interrupted=False` before worker waiting/capture. Keep dataset input mode unchanged.
- [x] Adapt offline runtime doubles to the production lifecycle contract, without production fallbacks for old test doubles.

## Task 2: Timing and compatibility

- [x] Add deterministic timing tests: prepare, response, playback persistence, and worker wait must not overlap response timing; only first turn carries preparation time. Preserve response timing on later bookkeeping errors.
- [x] Record `response_ms`, `prepare_ms`, `memory_finalize_ms`, plus existing `total_ms` as the response alias. `memory_finalize_ms` includes playback persistence and worker completion, excludes extraction/scoring/file writes.
- [x] BTC schema requires integer `ttft_ms`; retain it only as an explicitly marked response proxy (`ttft_is_proxy`) in the compatibility trace. Document this constraint instead of inventing a first-token measurement.
- [x] Record lifecycle/measurement metadata in single and paired reports, and document comparison limits in the harness README. Do not change BTC schemas or add dashboards.

## Verification and review

- [x] Watch new regression tests fail before implementation.
- [x] Run focused harness lifecycle, latency, entrypoint, diagnostics, schema/scoring compatibility tests and existing voice runtime tests. No full suite unless repository instructions require it.
- [x] Review the diff for memory-before-next-turn, first-call preparation failures, playback failure reporting, original-vs-redacted text length, empty calls, and diagnostics capture across persistence.

## Decisions / progress

- Existing user approval covers the design and execution; no further approval needed for local edits.
- Production already exposes one canonical lifecycle through `AgentHarnessRuntime`; eval should reuse it rather than refactor the deployed backend.
- BTC compatibility requires `ttft_ms` to be an integer, so deleting it or setting null would invalidate exported traces. The proxy marker and documentation make this explicit.


## Verification results

- Regression before implementation: four lifecycle/timing/failure tests failed as expected; the empty-call test already passed.
- Final lifecycle regressions: 8 passed, including both Deep and ReAct with the real production graph and offline dependencies; final_commit diagnostics remain captured.
- Core harness/entrypoint/content regressions: 153 passed, 1 skipped (isolated PostgreSQL integration). Two CLI environment failures were resolved by supplying PYTHONPATH and passed in the later focused CLI/report run.
- Reports/coordinator/root entrypoint/CLI checks: 36 passed.
- Existing runtime prepare/playback/API, harness diagnostics, warmup, trace extraction, BTC scoring/audit: 73 passed; the 6 chat API tests needed a separate process with an offline internal token and then all 6 passed.
- Backend voice flow/memory: 24 passed using backend/.venv (the AI virtualenv lacks pytest-asyncio).
- Additional real BTC publication check for extended latency fields and measurement metadata: 1 passed.
- git diff --check passed. No live model calls, service inference, database reset, deployment, or full suite run.
- Manual review: existing runtime methods are reused without a production fallback; preparation is once per nonempty call; receipt uses unredacted response length; failed playback preserves the response and stops the call; capture includes final persistence decisions; BTC schemas/scorer remain unchanged.
- Existing user changes in model configuration, frontend, compose, and other files were preserved. No commits were created.
