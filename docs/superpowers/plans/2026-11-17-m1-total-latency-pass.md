# M1 Total latency pass

**Goal:** Execute the user's approved bounded pass: repair policy/callback/TDS routing, reduce evidenced model round trips, and measure one fresh Full/baseline pair before deciding whether streaming is needed.

**Spec:** The approved three-step proposal in the conversation; starting evidence is run `20261117T070242Z-849d1e51`.

**Execution:** Inline in the current dirty checkout; no worktrees, subagents, commits, model changes or BTC threshold/scorer changes. Use focused offline regressions. The user approved the proposed single paired measurement on this goal turn, including the existing eval runtime reset; do not ask for that authorization again.

## Task 1 — Routing regressions

Files: existing callback parser, consultation followup, session/agent nodes and focused tests.

- [x] Reproduce an affirmative callback request after “chưa trao đổi kỹ”, while preserving negated/hypothetical callback rejection.
- [x] Reproduce exchange/packaging policy questions being answered with price; route to sourced policy and preserve order-date/ownership requirements.
- [x] Reproduce natural TDS abstention wording and the UF-to-RO followup falling back despite a valid quote; normalize missing specifications without discarding valid price clauses or asserting unsupported suitability.
- [x] Run the focused regressions RED then GREEN.

## Task 2 — Model round trips

Files: existing bounded catalog/commerce preparation and verified reply orchestration, plus focused runtime tests.

- [x] Trace the slow read-only price/stock/policy requests and identify avoidable model-mediated reads.
- [x] Prepare only literal product/category requests that the current source metadata can resolve; never turn metadata into purchase consent.
- [x] Reuse complete verified replies for those reads and for prepared policy; preserve ambiguous variants, missing stock/quotes, conditional policy and transaction idempotency checks.
- [x] Test the exact slow utterances, mixed-product requests and scope/consent edge cases offline.

## Task 3 — Validation and one live pair

- [x] Self-review the changes inline and run one final combined focused regression batch after the last production edits. No full suite unless required by repo instructions.
- [x] Read-only preflight: verify model/settings, pinned BTC/data identity and available eval services without exposing credentials.
- [x] Run the approved one paired evaluation using the canonical `run_pair`, same frozen scenarios/BTC package, model/parameters, seed 7, warmup 3 and text lifecycle. Measure both arms; keep knowledge retrieval enabled. This measurement does not publish knowledge or run a separate K1 experiment.
- [x] Inspect saved acceptance, new failures, model-call timings and source-bound extraction review. Do not infer live latency from fake inference tests.
- [x] Compare against Full p95 3396 ms / baseline p95 3627 ms, both against the existing 3000 ms TTFT limit; Total limit remains 8000 ms.
- [x] Record whether this pass meets latency or whether streaming design is the next justified step. Do not certify all M1 from this latency pass; ASR, extraction, demo and cost evidence remain explicit.

## Progress / rulings

- User approved the proposal and activated this new goal after clearing the previous goal. “Duyệt đề xuất” refers to the immediately preceding Total/streaming recommendation, not publishing K1 proposals.
- Starting runtime already contains earlier basket/TDS/continuation changes; preserve them and existing user changes. Current snapshot path consumers assume `run/btc-release` in some followup code; for the approved measurement pass the actual recorded BTC root explicitly to read-only reporting rather than restarting an evaluation to repair a display issue.
- Final focused batch: 335 passed in 8.27 s, log `/tmp/m1-total-round3-final.txt`. Includes 22 new exact utterance/scope tests, callback, policy, consent, variant/offer ambiguity, model contract, runtime and latency regressions. No full suite run. Scoped `git diff --check` passed.
- Read-only preflight passed: four MCP services and runner resolve `telesale`, server start `2026-11-17T04:16:16.501978+00:00`, knowledge release `policy-79dd0a921214cb762c5e4514232d9522`. Model `gemma4:31b`, provider `ollama.com`, temperature 0.2, max_tokens 256, history 6, tool budget 5; runner applies seed 7. No concurrent eval process found.
- Approved live pair completed: `20261117T080357Z-d1f6f8e2`, validated/healthy, 170 turns each. Full p95 3410 ms (fail), Baseline p95 2921 ms (pass). Full TSR 28/29, RQR 0/28, HR price/promo 0/35. Both Total p95 pass. Decision: streaming design is the next justified step; this bounded pass did not achieve the Full TTFT gate or full M1.
- Post-measurement corrections preserve policy order bindings across the early-return graph boundary, omit chunking instructions, and require an answer to product stock alongside policy. Final offline batch 117 passed in 6.41 s. No new live measurement after these corrections; recorded scores remain historical measured output. See `docs/m1-total-latency-pass-20261117.md` for comparison, source-bound partial review and remaining evidence.
