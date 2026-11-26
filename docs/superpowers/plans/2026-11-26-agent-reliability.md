# Agent Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task inline. User instructions prohibit delegation and worktrees.

**Goal:** Improve safe task completion, memory accuracy and grounded responses using general contracts rather than public-scenario shortcuts.

**Architecture:** Preserve the existing harness and MCP services. Repair identity, authorization and evidence boundaries, then connect bounded recovery and verify with unfamiliar offline fixtures and authorized live measurement.

**Tech Stack:** Python, pytest, FastAPI, LangGraph, MCP, PostgreSQL, Qdrant.

**Spec:** `docs/superpowers/specs/2026-11-26-agent-reliability-design.md`

## Global Constraints

- Work in the current checkout, with no sub-agents or worktrees.
- Preserve existing user artifacts and leave the changes uncommitted for review.
- No code comments or explanatory docstrings; no new dependencies or dashboards.
- No live model calls, deployment or database reset without explicit authorization.
- No runtime scenario IDs, fixed catalog products, private labels or test-trace lookups.
- Focused tests per task; full suite only if required and at most once.

## Review Focus

- Numeric social IDs and typed phone numbers must not expose another customer's memory.
- Swapped target, changed quantity and old/conflicting evidence must not grant a write.
- Checking an unavailable variant must not replace the customer's selected variant.
- Paraphrased completion, policy exceptions and repaired streaming must preserve actual facts.
- Already executed writes must survive bounded recovery without duplicate execution.

### Task 1: Trusted identity

**Files:** `app/agent/harness/session_identity.py`, `app/agent/harness/runtime.py`, identity regression tests under `ai-services/test/`.

**Interfaces:** Preserve `initialize_identity(turn, tools)` and signed backend verification. Remove unauthenticated phone fallback; do not reinterpret a social ID as a phone.

- [x] Add or extend parameterized unlinked-channel regressions and run them red alongside the existing failing audit test.
- [x] Remove fallback and unnecessary self-declared-phone refresh; update obsolete tests to assert the trusted boundary.
- [x] Run identity and signed authorization integration tests; expected all pass.

### Task 2: Exact deterministic authorization

**Files:** `app/agent/harness/authorization.py`, `test_p2_latency_optimizations.py`, `test_write_authorization.py`, a focused generalization regression file.

**Interfaces:** Preserve `deterministic_fast_authorize(name, args, state) -> bool | None`; `None` delegates to review. Use existing commerce evidence and owner/date/quote bindings.

- [x] Write red tests for wrong product, quantity, payment, variant, negation, stale evidence and explicit clear valid approvals using unfamiliar catalogs.
- [x] Constrain the fast path to a closed, fully matched request and exact evidence; defer unsupported language.
- [x] Run fast-path, parallel-read and write-authorization tests; expected all pass.

### Task 3: Memory selection and freshness

**Files:** `agent/memory/deterministic_tool_facts.py`, `mcp_memory/distiller_worker.py`, `mcp_memory/services/memory.py`, `harness/context.py`, memory tests.

**Interfaces:** Keep fact schemas and confirmed order details. Reads may enrich evidence but cannot create selected size/color facts. Carry the configured fact TTL to all prompt/brief projections.

- [x] Write red tests for multiple queried variants, unavailable variants, customer correction and nondefault TTL.
- [x] Correct worker and operational replay together; preserve order receipt and customer-sourced facts.
- [x] Run focused memory admission, replay, projection and freshness checks.

### Task 4: Grounded answers and policy conditions

**Files:** `guardrails/checks.py`, `guardrails/policy_grounding.py`, `harness/agent_nodes.py`, `configs.py`, relevant grounding tests.

**Interfaces:** Preserve existing rejection codes and semantic-review schema. Receipt validation must work for natural paraphrases and reject wrong or missing actions. Policy conditions stay attached to their entitlements.

- [x] Write red cases for phantom completion and blanket exceptions with synthetic sources; retain positive and conditional explanations.
- [x] Repair deterministic action checks and semantic-review activation without bypassing infrastructure failures.
- [x] Verify price, gift, policy, transaction and semantic grounding with focused tests.

### Task 5: Consistent delivery and fallback

**Files:** `harness/streaming.py`, `harness/agent_nodes.py`, streaming and recovery tests.

**Interfaces:** `finish()` returns the delivered verified answer; unverified drafts cannot be appended to repaired answers. Product fallback excludes gift-only SKUs.

- [x] Write red tests for a safe-looking prefix followed by a rejected draft, a changed repair and a gift-only catalog read.
- [x] Hold unsafe publication until final review; preserve disconnect, retry and persistence semantics.
- [x] Run focused stream/runtime/repair tests, recording latency tradeoffs explicitly.

### Task 6: Bounded completion recovery

**Files:** `harness/agent_nodes.py`, `implementations/business_agent.py` only if required, model-loop integration tests.

**Interfaces:** One model-authored continuation with the same `BusinessTools`, current context and existing budgets. Never execute writes from a text trigger alone.

- [x] Write red fake-model integration cases: extra confirmation, unanswered action, rejected authorization, completed write and negative request.
- [x] Add bounded recovery using tool-enabled model generation before final answer-only repair.
- [x] Prove successful completion and no duplicate or unauthorized write offline.

### Task 7: Complete retrieval and honest scoring

**Files:** `mcp_knowledge/services/knowledge.py`, `rag_eval/scoring.py`, focused retrieval/scoring tests.

**Interfaces:** Preserve `hard_limit`, applicability and missing dependency markers. Separate model self-report from observed/judged abstention and unmeasured answer accuracy.

- [x] Write red tests for transitive/cyclic/missing required links and answer/action inconsistencies.
- [x] Implement bounded dependency closure and conservative observed refusal handling using existing scoring structures.
- [x] Run retrieval/dependency/scoring checks without embeddings or model calls.

### Task 8: Integration, review and metric evidence

**Files:** this plan, spec, execution ledger; regression fixtures and minimal caller repairs as evidence requires.

- [x] Review the connected diff against all eight spec requirements and anti-overfitting constraints.
- [x] Run focused cross-component offline integration checks once connected; resolve failures by root cause.
- [ ] If authorized and access permits, verify service provenance and run one limited live eval; record comparable quality, latency and actual failures without hiding excluded costs. Pending explicit permission; no live model calls run.
- [x] Report exact checks, changes and remaining limitations. Mark the goal complete only when the requested end state has authoritative evidence.
