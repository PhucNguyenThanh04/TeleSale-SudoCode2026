# General Answer Grounding Implementation Plan

> Execute inline using superpowers:executing-plans. User instructions prohibit
> subagents and worktrees and authorize autonomous spec, plan and execution.

**Goal:** Require source-grounded semantic approval before any answer is published.

**Architecture:** Keep mechanical checks, add one bounded structured review,
reuse the existing answer-only repair, and bind publication to the approved text.

**Tech Stack:** Existing Python, Pydantic, LangChain and pytest dependencies.

**Spec:** `docs/superpowers/specs/2026-11-20-answer-grounding-design.md`

## Global constraints

- Work in the current checkout and preserve existing user changes.
- No subagents, worktrees, code comments, explanatory docstrings or dependencies.
- No live provider calls, evaluations, database changes or prompt publication.
- No trace, public/hidden scenario, QA-label or saved evaluation inputs.
- Model chooses meaning and actions; code enforces typed source/publication boundaries.
- Use focused offline checks; do not run the full suite.

## Review focus

- Mixed supported and unsupported clauses must reject the entire draft.
- Conditional/conflicting policy and failed tools must not authorize claims.
- Customer/assistant history and instructions in sources must retain their roles.
- Structured output errors and timeouts must never approve an answer.
- Provider stop, repair, retry and disconnection must not publish rejected speech.

## Task 1: Structured grounding boundary

Files: create `ai-services/app/agent/guardrails/semantic_grounding.py` and
`ai-services/test/test_semantic_grounding.py`.

- [x] Write independent synthetic source/review fixtures and tests for approval,
  rejection, strict types, contradictory results, invalid sources and deadlines.
- [x] Run the new tests offline; expect failure because the reviewer is absent.
- [x] Implement `review_answer(model, answer, context) -> str | None`, a strict
  verdict, a general source-entailment prompt and safe source preparation.
- [x] Run the tests; expect all task tests to pass.

## Task 2: Verification and publication integration

Files: modify `agent_nodes.py`, `state.py`, `session_nodes.py`, `streaming.py` and focused test doubles
and streaming tests; add integration cases to `test_semantic_grounding.py`.

- [x] Add tests proving rejection before publication, one repair, revalidation,
  mandatory grounding with optional checks disabled, retry and delivered history.
- [x] Run the new integration cases; expect failure on the current publication path.
- [x] Invoke semantic review after deterministic validation for both original and
  repaired answers. Return `verified_answer` only on success.
- [x] Buffer provider events until verification. `finish` publishes only the exact
  `verified_answer`, once. Keep disconnect and persistence behavior.
- [x] Update focused test doubles for the structured review boundary and tests
  whose former contract allowed provider-stop publication.

## Task 3: Focused verification and final review

- [x] Run offline tests for semantic grounding, grounding-always, guarded
  streaming, model-owned conversation, text harness and reply boundaries.
- [x] Run deterministic price/promotion/policy evidence component checks where
  relevant; inspect every failure and distinguish pre-existing assertions.
- [x] Review the actual change against each spec requirement, including rejected
  repair, unsupported structured output, source filtering and persisted speech.
- [x] Record results and limitations here; report no live accuracy/latency claim.

## Execution record

Specification and plan self-reviewed before implementation. The user explicitly
delegated design choices and execution, so no additional approval gate is needed.
Tasks 1 and 2 share the reviewer return contract and the exact approved answer;
Task 2 owns both graph and stream consumers. No branch integration is requested.


RED: the reviewer test failed with the expected missing module. Three integration
cases then failed because an unsupported draft was accepted with both flag values
and a provider-stop chunk published before verification. The first reviewer-only
run passed 18 cases, and the first complete new-file run passed 24 cases.

The first integration group passed 169 cases and exposed one outdated HTTP double
that supported streaming generation only. It now handles a real LangChain/OpenAI
structured tool response and holds publication while that response is pending.
Its focused check passed.

Final focused verification: 255 passed, one upstream trustcall/LangGraph deprecation
warning, exit 0. Files: test_semantic_grounding.py, test_grounding_always.py,
test_guardrail_false_positives.py, test_guarded_streaming.py,
test_text_harness_contract.py, test_model_owned_conversation.py,
test_llm_reply_boundary.py, test_chat_stream_runtime.py, test_price_grounding.py,
test_promotion_grounding.py, test_policy_agent_evidence.py, test_policy_lookup.py.
Runs disabled dotenv loading, supplied dummy provider settings, disabled pytest
plugin autoload/cache writes, and prohibited socket connections. No full suite ran.
Syntax checks passed for the 14 changed Python files; git diff --check passed for
the changed tracked files. New Python files contain no code comments.

Self-review removed the now-unused deterministic publication helper and its unused
test import. No conversational controller was restored. Requirements 1 and 8 are
covered by deterministic and optional-flag checks; requirements 2 through 5 by
reviewer, source-boundary, strict-verdict, PII/role and deadline tests; requirements
6 and 7 by repair, real graph, HTTP parser, exact-publication, disconnect, delivered
history and retry checks. Requirement 9 is reflected in generic production logic
and independent fixtures retaining unfamiliar attributes across unrelated domains.

The semantic provider is scripted in offline tests. These checks establish the
protocol and publication boundary, not model accuracy, prompt-injection resistance,
public/hidden task scores, live latency or cost. No live calls, database mutation,
remote prompt publication, new dependency, worktree, subagent or commit was used.
