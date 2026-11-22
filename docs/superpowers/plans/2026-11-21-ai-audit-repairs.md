# AI Audit Repairs Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline, task by task. The user prohibits subagents and worktrees and requested autonomous spec/plan/execution.

**Goal:** Repair all fourteen AI/MCP audit findings and verify the resulting contracts offline.

**Architecture:** Extend existing shared trust-boundary helpers, typed contracts, memory projection and guarded runtime. Preserve model-led conversation, signed writes and dated commercial evidence. Avoid changes to external BTC data.

**Tech Stack:** Existing Python, pytest, LangGraph, LangMem, FastMCP, PostgreSQL and Qdrant dependencies.

**Spec:** `docs/superpowers/specs/2026-11-21-ai-audit-repairs-design.md`

## Global Constraints

- Current checkout only; no subagents, worktrees, paid evaluations, dependency additions or unrelated refactors.
- Preserve all pre-existing uncommitted changes and external BTC files.
- No added code comments or explanatory docstrings.
- Focused offline regressions per behavior; at most one full offline integration run.
- Keep a durable task/evidence/ruling ledger in `docs/superpowers/plans/2026-11-21-ai-audit-repairs-progress.md`.
- No automatic commits of overlapping dirty files, deployment, database reset, or historical score replacement.

## Review Focus

- Spaced sensitive numbers versus prices, dates and product identifiers: Task 1.
- Backend verification on an unlinked channel versus a self-asserted phone: Task 2.
- Old-policy dates, missing receipt dates, unsealed hygiene goods and already expired returns: Task 3.
- Negated blockers and corrected addresses followed by confirmation on a later turn: Tasks 4–5.
- Erasure, provider outage, disconnect and retry after a successful business write: Tasks 6–7, 9, 11, 13.

## Tasks

### Task 1: Shared PII boundary

Files: `app/mcp_servers/mcp_shared/pii.py`, `test/test_audit_pii.py`, directly affected privacy fixtures.
Interface: retain `mask_pii(str) -> str` and `resolve_redacted_address(str) -> str | None`.
- [x] Add tests for spaced/dashed phones/CCCD/accounts, 16–19 digits, and retained prices/dates/SKUs; run and observe failures.
- [x] Fix the shared recognition once; run the new test and affected existing privacy tests.

### Task 2: Consistent verified identity

Files: `app/agent/harness/session_identity.py`, `runtime.py`, catalog/order identity services, `test/test_audit_identity.py`, identity tests.
Interface: a signed verified customer may resolve by that ID; unsigned source identity never gains that ability.
- [x] Reproduce self-asserted chat-phone memory access and failure of verified unlinked identity.
- [x] Remove implicit verification and make signed verified identity resolve through repository customer records; test tampered/ambiguous/unsigned cases.

### Task 3: Return eligibility and honest receipts

Files: `app/mcp_servers/mcp_order/services/order.py`, its schemas/tools, guardrails/write receipts, `test/test_audit_returns.py`, preview/update tests.
Interface: preview provides policy version, missing conditions and estimates; update returns an eligible receipt or explicit `review_pending`, and errors for verified ineligible requests.
- [x] Reproduce expired return acceptance and incorrect old-policy settlement.
- [x] Implement date/condition assessment and pending-review intake; preserve line/quantity/ownership checks and test old/new policies.

### Task 4: Semantically grounded episode resolutions

Files: memory fact/episode review, `distiller_worker.py`, `episode_state.py`, admission, episode tests.
Interface: only a resolution independently supported against the original item and current source may be applied.
- [x] Add negation/conditional/wrong-target and reviewer-unavailable regressions and observe failures.
- [x] Review and filter resolutions before projection; preserve retry digests and source IDs; test accepted resolutions too.

### Task 5: Private delivery reference across turns

Files: memory schemas/service/repository/migration/bootstrap, harness context/policy/authorization, new delivery tests.
Interface: private delivery record contains address, source turn ID and masked source statement; model-visible context contains only safe references.
- [x] Reproduce a supplied address followed by later confirmation and a restart; assert absence of raw PII in model messages.
- [x] Persist/resolve the private reference with current-turn corrections and authorization context; cover ambiguity and erasure.

### Task 6: Completed erasure and cache invalidation

Files: memory erasure/read contracts and runtime/session context; erasure tests.
Interface: distinguish pending erasure from completed erased identity; return fresh anonymous context without resurrecting old data.
- [x] Reproduce permanently blocked post-erasure contact and retained runtime state.
- [x] Preserve tombstone protection, clear owner caches/playback/private delivery, and test fresh contact plus delayed-worker protection.

### Task 7: Knowledge lookup availability and bounded verification

Files: harness runtime/gateway, knowledge release service/repository/index, policy integration tests.
Interface: resolve/pin policy at the tool boundary; release-reference lookup avoids complete vector verification; serving still checks revocation and source integrity.
- [x] Reproduce knowledge failure blocking a greeting and repeated full verification.
- [x] Remove the unrelated-turn dependency, cache validated immutable serving data safely, and test revocation and failure behavior.

### Task 8: Current episode summaries

Files: `distiller_worker.py`, `episode_summary.py`, worker/summary tests.
Interface: summaries derive from current canonical topics/actions and prioritize latest source-backed changes.
- [x] Reproduce a full old summary hiding new state.
- [x] Rebuild bounded summary and test correction/resolution visibility in the next brief.

### Task 9: Bounded context and runtime resources

Files: harness context/runtime/session state, memory read/projection/repository, long-context/retry tests.
Interface: explicit context completeness and source references; writes cannot proceed if relevant constraints were dropped; cache expiry retains durable replay/idempotency.
- [x] Reproduce unbounded raw-history/tool context and repeated completed-session reconstruction.
- [x] Bound context and retained runtime data, use committed/pending evidence appropriately, and test long conversations and retry after eviction.

### Task 10: Durable tool evidence and provenance

Files: `memory_observations.py`, deterministic tool facts, projection/turn status, memory contract tests.
Interface: safe durable tool receipts keep exact source/status/IDs; callback fact and episode agree; memory change source reflects actual provenance.
- [x] Reproduce dropped order-update receipts, missing callback fact and source misattribution.
- [x] Align allowlists/receipt adapters and test round trips without PII or stale-policy rights.

### Task 11: Guarded request deadline and truthful publication

Files: runtime/streaming/agent nodes/config, deadline/stream tests.
Interface: a total turn deadline includes verification and repair; no unchecked token is published; completed writes remain recoverable after timeout/disconnect.
- [x] Test slow model/reviewer/tool and timeout following a successful write.
- [x] Add deadline propagation and bounded repair while retaining honest full-answer first-delta measurement.

### Task 12: BTC prompt invariants and prompt reuse

Files: business prompt, agent nodes/state, authorization, prompt contract tests.
Interface: selected compiled prompt is reused throughout the turn; explicit medical handoff and pre-order offer presentation rules preserve privacy.
- [x] Test main/repair prompt consistency and required PB-06/PB-09/opening instructions.
- [x] Add the minimal prompt changes and ensure existing grounding/consent tests remain valid.

### Task 13: Split-order contract and tool budget

Files: model tool schema, signed-write operation keys, order evidence/creation, config/example, basket/authorization tests.
Interface: distinct fully authorized creates have stable independent keys; identical retries remain idempotent; split pricing context is visible and verified.
- [x] Reproduce omitted `basket_skus`, same-turn create collision and insufficient four-product budget.
- [x] Implement complete split context and stable keys with justified budget; test unchanged signatures, authorization, prices and quantities.

### Task 14: Integration, replay and evaluation evidence

Files: preparation/outage/erasure tests, offline replay/extraction review and documentation in existing locations.
Interface: current-source offline evidence stays separate from historical model/human evaluation results.
- [x] Update stale tests only after deriving their intended behavior from the spec and runtime contracts.
- [x] Add pending-worker cross-channel replay and audit unresolved historical extraction candidates without inventing human labels.
- [x] Run the final focused integration gate; if required, run the full offline suite once, record all outcomes and remaining external evidence.
- [x] Review every numbered spec requirement against actual code/test evidence, fix remaining defects, and only then report completion.
