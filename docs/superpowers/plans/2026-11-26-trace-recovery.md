# Trace Recovery Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; user instructions prohibit delegation and worktrees.

**Goal:** Repair the trace-backed product-role, completion, identity-transport and duplicate-review failures.

**Architecture:** Preserve the existing BusinessTools/authorization and final-publication boundaries. Extend the already edited repair paths, propagate explicit verified identity, and deduplicate semantic review only inside one verifier invocation.

**Tech Stack:** Python, pytest, LangGraph, existing MCP services.

**Spec:** docs/superpowers/specs/2026-11-26-trace-recovery-design.md

## Global Constraints

- Current checkout only; preserve existing uncommitted changes.
- No agents, worktrees, code comments/docstrings, commits or live inference.
- No changes to BTC data, labels or saved traces.
- Focused offline tests only; no full-suite requirement or repeated successful checks without new changes.
- Keep authorization, receipt validation, idempotency, budgets and whole-answer verification.

## Review Focus

- Failed writes mentioning a gift must not turn it into a selected product.
- Colloquial consent and exchange requests must reach bounded recovery; questions and negation must remain safe.
- Explicit verified identity must survive preparation, text/voice execution and playback.
- Unlinked social IDs must remain unknown; descriptive phone fields must not authenticate them.
- Same answer with changed evidence must invalidate semantic review reuse.

### Task 1: Product roles and bounded task completion

**Files:** app/agent/memory/reported_facts.py, app/agent/harness/agent_nodes.py and their existing boundary tests under ai-services/.

**Interfaces:** `_gift_only_skus(calls)` and `_requested_write_missing(state)` retain their current signatures; BusinessTools retains all write decisions.

- [x] Add and run regressions for failed gift receipts and natural current requests missed despite an accepting reviewer; observe failures.
- [x] Make the smallest role-admission and recovery-signal fixes.
- [x] Run memory selection, bounded completion, answer-contract and verified-delivery boundary tests.

### Task 2: Explicit trusted identity through evaluation transport

**Files:** ai-services/eval_harness/benchmark_runner.py, ai-services/eval_harness/test_voice_lifecycle.py, ai-services/docs/text-harness-contract.md.

**Interfaces:** `run_scenario_call` consumes optional explicit call-spec `verified_customer_id` and `verified_phone`; existing request models carry them. Missing social `channel_identity` stays None; hotline retains its phone default.

- [x] Add failing text/voice propagation, incomplete-pair and missing-social-ID tests.
- [x] Propagate identity through prepare, turns and playback; align history preparation with the channel-specific default.
- [x] Run focused runner lifecycle and real identity-boundary checks; document the trusted-input contract and external mapping limitation.

### Task 3: Remove duplicate semantic review requests

**Files:** ai-services/app/agent/harness/agent_nodes.py, ai-services/test/test_semantic_grounding.py.

**Interfaces:** `verify_agent(state)` retains its return contract; `review_answer` remains the external semantic boundary.

- [x] Add failing checks for repeated identical rejected drafts, changed evidence, retry after unavailable review, and separate-turn isolation.
- [x] Reuse supported/unsupported semantic verdicts only for identical answer plus review context in this invocation.
- [x] Run semantic, repair and verified-publication tests.

### Task 4: Integration and completion audit

**Files:** this plan and its progress ledger; existing connected tests.

- [x] Run one connected focused selection spanning real graph continuation, worker memory, identity, runner transport and delivery.
- [x] Replay saved gift/update/missing-write rows without inference or artifact mutations.
- [x] Review the diff inline and audit every spec requirement. Record actual output and any external limits; run git diff --check.

No automatic commits. The user has already delegated spec, plan and execution, so no approval checkpoint is inserted.
