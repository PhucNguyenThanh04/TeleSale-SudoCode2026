# M1 acceptance repairs implementation plan

> Execute inline in the current checkout. No subagents, worktrees, automatic commits or live model runs.

**Goal:** Repair the failures found in run `20261117T050609Z-2042b75f`, and establish honest evidence against the existing M1 conversation gates.

**Architecture:** Keep the existing runtime, MCP boundaries, consent checks and BTC scorer. Add focused regressions using saved speech/tool observations and fake inference. Preserve the historical run; extraction changes use a separate offline replay. A measured new run is required to establish latency or task-score improvements.

**Tech stack:** Existing Python, pytest, Pydantic and LangGraph.

**Spec:** User-approved four repair areas in the conversation and repository AGENTS.md.

## Constraints and review focus

- Preserve existing uncommitted work. Every edit must address a traced failure.
- Keep BTC thresholds/scorer, Full/baseline separation and measurement boundaries unchanged.
- A quote fetched by tools is not an offer delivered to the customer or consent to buy.
- Two distinct products are not quantity two of one product.
- Missing specifications must produce a truthful abstention, never a guessed measurement.
- Review evidence must bind exact extraction candidates and trace bytes; unresolved or unsupported claims cannot silently become correct.
- Model-call savings in offline tests do not establish live p95. ASR/demo/cost evidence remains separately required.

## Task 1: Basket reporting and confirmation

Files: `app/agent/guardrails/checks.py`, `app/agent/harness/agent_nodes.py`, `app/agent/harness/session_nodes.py`, `app/agent/implementations/business_agent.py`, and focused basket/runtime tests under `ai-services/test/`.

- [x] Reproduce a sourced 779000 VND two-product basket rejected with single-SKU focus.
- [x] Reproduce first-turn two-product quote/stock request and later COD confirmation through the runtime.
- [x] Repair quote preparation and basket-aware answer checks without weakening product/price/consent boundaries.
- [x] Verify missing/changed offers, incorrect totals, wrong products and absent consent still fail.

## Task 2: Missing product specifications

Files: `app/agent/harness/session_nodes.py`, `app/agent/harness/agent_nodes.py`, and focused runtime tests.

- [x] Reproduce the TDS question receiving price advice instead of missing-information disclosure.
- [x] Recognize and answer requested missing specifications from source metadata; keep the abstention compatible with BTC wording.
- [x] Verify unsupported numerical TDS cannot escape verification or be replaced by unrelated sales advice.

## Task 3: Extraction and bound review

Files: `eval_harness/extractor.py`, extraction report/replay/acceptance modules, focused tests, review evidence and short documentation.

- [x] Reproduce fragment/narrative candidates and ambiguous question classification from saved speech.
- [x] Repair safe extraction errors; preserve qualifiers and unsupported projections explicitly.
- [x] Provide a verifiable per-candidate review path for cases the BTC flat schema cannot represent. Review is a recorded judgment, never an automatic assumption of truth.
- [x] Test missing/tampered/wrong-run/partial review rejection and remaining uncertain claims.
- [x] Replay annotations offline into a new artifact directory; report score deltas and unresolved evidence honestly.

## Task 4: Model round trips and final evidence

Files: existing agent orchestration/business preparation and focused latency/purchase tests.

- [x] Reproduce repeated inference when a confirmed, fully evidenced purchase can already continue.
- [x] Use the existing deterministic continuation before unnecessary inference; keep verification and persistence.
- [x] Verify stale prices, changed benefits, missing stock, ambiguous selection and missing consent still block writes.
- [x] Run one combined focused regression batch after the final edits; no full suite unless required by the repo.
- [x] Record exact offline evidence, remaining M1 gates and a concrete proposed live-eval command for approval.
- [ ] Obtain authorization for one live paired run, execute it, review its extraction and verify the unchanged acceptance gates. Offline tasks being checked does not complete the goal.

## Progress / rulings

- Started from an already dirty checkout; existing changes belong to the user. Implementation and review run inline, following the explicit user constraints over conflicting skill workflow defaults.
- Historical latency/behavior cannot be repaired by rewriting trace bytes. Goal completion requires authoritative fresh evidence for those gates; do not mark complete from offline tests alone.
- Task 1: complete offline. Initial regressions failed with `price_product_mismatch` and missing basket total; now pass with wrong-total/product/consent protections intact.
- Task 2: complete offline. Initial TDS tests returned price advice or accepted unsupported ppm; now disclose missing information and reject mismatching ppm. Explicitly sourced ppm also passes.
- Task 3: complete offline tooling/replay. Replay source integrity has no issues, RQR annotation changes 1/27 to 0/27, and speech/tool/memory/latency remain unchanged. Assistant source review records 71 supported, 7 fragments and 58 unverifiable candidates; `complete=false` is preserved.
- Task 4: complete offline changes. Confirmed purchases can skip inference; complete price/stock answers can also skip inference in both Full/baseline. No live p95 claim.
- Ruling: an initial latency-test fixture used AirPure Pro on October 19, when BTC inventory is out of stock. Corrected the assertion to require “hết hàng”; also repaired the real omission of the requested price for out-of-stock products. Currency wording is recognized separately from TDS units.
- Ruling: safety regression testing found a shared-brand alias could let early continuation inherit an old basket. Required literal model/SKU metadata matching before skipping lookup; all 12 changed-basket text/voice/deep/react regressions pass.
- Final focused validation: 540 passed in 20.14 seconds; no full suite, network/model/ASR/DB evaluation. Durable log: `ai-services/eval_harness/results/measurement-audit/20261117-m1-acceptance-repairs-tests.txt`.
- Self-review and `git diff --check` completed inline; existing user modifications preserved, no commits/worktrees/subagents created. Live-eval approval requested through the async user-input tool, with the exact command and runtime reset scope in `docs/m1-acceptance-repairs-20261117.md`.
- Continuation: reviewed the remaining source paraphrases rather than waiting idly. Six remaining question uncertainties reproduced RED and repaired; parser/review/replay focused batch 113 passed. New v2 replay preserves v1 and the historical run, and has zero uncertain emitted questions in both arms.
- Continuation: source adjudication now records 130 candidates: 106 supported, 9 fragments/abstentions, 15 unverifiable. Review remains incomplete; no historical failure or latency is overwritten.
- Continuation: unsupported physical shipping details inferred from `created` reproduced RED and repaired through the existing verifier/recovery. Final affected-area batch: 261 passed in 8.26 seconds. These overlap the earlier 540-test batch and are not an additive unique-test count.
- Live-eval approval is still absent. No inference/reset/ASR/benchmark has been started. Goal remains active and unverified rather than being reduced to the completed offline changes.
- Blocking audit, third goal turn: explicit live-eval approval is still absent; the latest saved paired run remains `20261117T050609Z-2042b75f`. Revalidated source/replay hashes and saved focused-test results without repeating tests. The remaining historical uncertainty cannot be repaired by rewriting source artifacts, and fresh p95/behavior cannot be established offline. Mark the goal blocked pending authorization for the concrete paired-eval command, not complete or paused.
