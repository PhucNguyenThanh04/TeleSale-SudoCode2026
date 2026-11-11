# M1 readiness implementation plan

**Goal:** Complete the six M1 work groups approved in conversation, excluding
dataset generation, and distinguish implementation checks from measured acceptance.

**Architecture:** Reuse the production runtime, memory and knowledge services.
Keep the existing voice evaluation lifecycle; add explicit text evaluation instead
of silently changing prior measurements. Verify saved evidence without inference.

**Spec:** Official final-project PDF beside this checkout, BTC DIEU-CHINH-DE.md
and GIAI-DAP-MENTOR.md, and the six work groups in the conversation.

**Execution:** Inline under executing-plans and TDD. Current checkout; no worktrees,
subagents, commits, new dashboards, dataset generation, live inference or resets.
Preserve all pre-existing changes. Focused tests only. Live model/ASR measurements
and reset targets require explicit authorization before execution.

## Review focus

- Historical memory/quotes never become customer consent or fresh evidence.
- Failed tool/model/memory work cannot masquerade as an accepted evaluation.
- Text and voice timings cannot be merged or relabelled as measured TTFT.
- Feedback improvements need reviewed sources and fixed before/after tests.
- Missing dataset/ASR/cost/demo evidence stays missing, never an assumed pass.

## Tasks and completion evidence

### 1. M1 evaluation lifecycle
- [ ] Add failing tests for text delivery through real runtime: no voice playback,
  durable turn capture before the next turn, same identity/history/tool boundary.
- [ ] Add delivery_mode to runner/coordinator CLI and metadata, default voice for
  compatibility; explicit text mode follows production chat persistence.
- [ ] Verify lifecycle/coordinator/report tests, including error and empty calls.
- [ ] Pin honest latency semantics; use BTC rule 7 (nonstreaming TTFT = Total) for
  M1 text and retain the explicit proxy label for voice.

### 2. Memory and transaction acceptance
- [ ] Verify four offline stories: returning purchase, changed variant, cross-channel
  identity, changed price/promotion. Assert no repeated known slots, no stale offer
  acceptance, ownership isolation and exactly-once writes; repair proven gaps.
- [ ] Verify timeout/malformed output fallback and handoff brief contracts.

### 3. Reproducible M1 acceptance and dataset handoff
- [ ] Add offline acceptance CLI for saved audited runs. Report evidence for paired
  model parameters, guardrails, extraction, coverage, BTC thresholds and latency.
  Missing/insufficient/proxy evidence must not pass a gate.
- [ ] Validate dataset handoff contracts without generating new data or using labels
  at runtime. List missing scale and binding information with actionable reasons.
- [ ] Document one-command paired run and one-command evidence check.

### 4. Knowledge Gap Loop evidence
- [ ] Exercise runtime feedback -> gap -> reviewed revision/regression -> release
  using existing services and offline dependencies; preserve review/rollback gates.
- [ ] Add before/after comparison of audited runs: identical dataset/model settings,
  allowed knowledge change, explicit source/run hashes, metric deltas and regressions.
- [ ] Prepare repeatable two-round instructions; actual runtime improvement remains
  unproven until authorized measurements on the fixed dataset exist.

### 5. ASR and latency evidence integration
- [ ] Verify customer-only ASR replay -> same harness, preserve provenance and dates.
- [ ] Consume saved ASR scores with scope/source hashes; require BTC audio + at least
  20 team files and money/phone entity evidence. Never substitute template labels.
- [ ] Correct measurement gaps needed for M1 or record them explicitly. Live ASR,
  >=100 measured turns and runtime threshold passes require real evidence.

### 6. Demo and handover
- [ ] Verify existing chat/brief/memory UI and offline startup contracts; fix only
  demonstrated M1 gaps. Provide exact demo steps, dependency/setup and failure paths.
- [ ] Provide cost-per-call calculation from actual usage/prices when available;
  otherwise report unknown, with explicit inputs needed (no invented API pricing).
- [ ] Review changed code and focused tests, publish evidence ledger and outstanding
  external requirements. Do not mark the full goal complete on software tests alone.

## Progress / rulings

### Evidence ledger (software checks, not M1 acceptance)

- Text lifecycle, coordinator and latency-report tests: 22 passed. Text uses
  BTC nonstreaming rule 7; voice remains labelled as proxy.
- Focused core/runner/memory/knowledge/speech run: 293 passed, one isolated
  PostgreSQL test skipped, and one obsolete identity fixture failed. That fixture
  was updated to use the admission contract; the focused identity/admission/worker
  checks then passed (21 tests). This is not a live database integration result.
- Acceptance, round comparison and evaluation-feedback checks: 24 passed;
  subsequent feedback hash/knowledge ingestion/worker checks: 15 passed.
- ASR evidence/adapter/evaluation checks: 19 passed. Speech dependency-isolated
  checks covered 62 cases across the main run and the dependency follow-up.
  No audio transcription or model inference was performed.
- Gateway/UI/voice focused checks: 42 passed; text gateway/browser checks after
  session-preparation alignment: seven passed using offline upstream responses.
- Current review: `git diff --check` passes. Standalone `node --check` could not
  run because Node is absent; the browser check above exercises the chat script.
- No live evaluation, database reset, ASR inference, knowledge publication or
  service deployment has been executed for this plan. The live smoke request is
  pending explicit authorization. Actual KPI, latency, two-round improvement,
  cost and real-service demo evidence remain outstanding.

The task checkboxes below describe the full intended outcomes. They remain open
where runtime evidence is missing, even when the supporting software exists.

- Initial audit: existing checkout contains prior model/backend/voice work and the
  previous harness fixes. None will be reverted. Dataset generation belongs to the
  user's teammate; integration/validation remains in scope.
- User approved the proposed six groups and requested autonomous execution. No
  additional design approval is needed for the reversible changes described here.
- Current voice runner deliberately uses TTFT proxy. Add text mode rather than
  breaking the earlier approved voice parity. Do not fake a first-token timestamp.
- Ruling from the authoritative latency guide: rule 7 explicitly permits
  nonstreaming TTFT = Total. Text uses that measured completion boundary and records
  its basis, not an invented token timestamp. Voice remains a proxy. A streaming
  implementation is not an additional M1 prerequisite.
- Ruling after inspecting the real frontend: old text-backend modules are absent.
  Added connection-bound chat to the existing gateway. Both chat and voice prepare
  identity/brief when the session starts; text then persists inside runtime.run and
  never uses voice playback. This supersedes the initial assumption that text had
  no pre-session preparation. The runner and tests follow this actual M1 lifecycle.
