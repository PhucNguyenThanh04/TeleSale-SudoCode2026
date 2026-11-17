# Independent RAG evaluation

## Intent and scope

Build an independent `ai-services/rag_eval` CLI for the deployed MCP Knowledge
retriever and an explicitly isolated RAG generator. It does not run the agent
harness, reset databases, write knowledge, or claim to measure agent quality.
The user will run live evaluation and send artifacts for acceptance. Development
verification uses offline fixtures and mocked network boundaries only.

Technology: Python, the unmodified BTC `rag_eval` scorer, deterministic checks,
and optional Ragas 0.4.4 collections metrics (Faithfulness, FactualCorrectness F1).
No new dashboard, Langfuse integration, retriever changes, or paid experiment.

## Dataset and context

Read all questions and labels from the supplied BTC root. Validate unique qids,
known types, nonempty questions/answers, and source IDs. Preserve every question,
including restricted and unanswerable. Require exact result coverage before scoring.
Inputs and evaluator-owned labels remain separate. Generation receives no qid,
type, relevant IDs, reference answer, or assertions.

Ship a versioned component-context file. Default business date and synthetic
verified order date are 2026-10-15; mark provenance `eval_fixture`, not an actual
CRM verification. Override Q32 to July 2026, Q42 to September, Q43 to order
2026-09-28 and call 2026-10-09. These are documented component fixtures, not a
measurement of agent date extraction/verification. Custom context files are
supported for independent team datasets, with dates and fields validated.

Optional per-case reference read-tool fixtures supply missing catalog/pricing/
inventory facts. Allowlist only read tools in BTC mock_tools; redact private
fields before model input and artifact storage. Never pass raw CRM or internal
price floors. No labels may drive runtime search or tool selection. Record
fixture inputs, tool observations and their frozen source hashes explicitly.

## Modes and artifacts

`run --mode retrieval|end-to-end --allow-live --out NEW_DIR` performs live work.
Without the explicit flag it must fail before settings/client/network access.
`score --run DIR --out NEW_DIR` replays deterministic scoring with no settings,
model, database, or network. `judge --run DIR --out NEW_DIR --allow-live` adds
Ragas and business-rubric results to saved generation outputs without rerunning
retrieval/generation. `compare` compares compatible scored artifacts offline.

Each run snapshots the BTC QA, policy, catalog, scorer and read-tool source, plus
context fixtures, before calls; hashes bind inputs, trace, config and implementation.
Pin one authenticated Knowledge release for the whole run. Verify returned
release IDs. Persist JSONL after every case, even failed ones; record sanitized
error codes, not raw exceptions/credentials. Interrupted runs keep partial traces
and an incomplete manifest; no implicit restart/resume or overwrite.

Trace includes query, trusted business context, top_k, ordered evidence including
linked sections/applicability, retrieval status/latency, fixture observations,
answer/action (when generated), generation latency/usage, and status/error.
Keep all returned evidence; BTC scoring uses its ordered prefix at k=3 and 5.
The generation action is self-reported, not an independently judged decision.

## Scoring and integrity

Load BTC's exact `rag_eval` function from the frozen scorer, record its hash, and
export its native qid-keyed `rag_results.json`. Retrieval-only reports hide all
answer/abstention metrics as unmeasured. End-to-end pre-judge reports mark BTC
abstention as self-reported; judged reports use independently classified actions.
Failed cases remain in the denominator; coverage and execution health are separate
from quality. No missing/duplicate/unknown qids, nonfinite scores, or tampered
artifacts may silently improve a report.

Supplement with per-case hit/full-recall/MRR, by-type results and p50/p95 latency.
Deterministic checks use explicit, versioned assertion fixtures for critical
numbers, forbidden facts and required alternatives; label literal checks as
diagnostics, not complete semantic correctness.

Business judge returns correctness, observed action (answer/clarify/refuse/handoff),
version/numeric correctness where applicable, internal leakage, and a reason.
Keep this separate from Ragas faithfulness/correctness. Skip faithfulness on
refusal/clarification/handoff; report null with a reason. Judge errors are visible
and excluded only from that metric's measured denominator, with coverage shown.
Model and prompt identities and Ragas version are recorded. Judge uses explicitly
configured OpenAI-compatible credentials; generation uses existing AI settings.
No assertion/expected answer is supplied to generation.

Reports include JSON, Markdown and per-case trace, plus a human-label template
bound to the trace hash. Optional completed labels report agreement and Cohen's
kappa on correctness; fewer than 20 labels are marked insufficient calibration.
Comparison rejects changed dataset/context/scorer or generation/judge settings;
retriever release may differ, and is shown explicitly. Return per-qid improvements
and regressions, not statistical significance claims.

## Acceptance

- Focused offline tests prove the real BTC metric formula and exact coverage.
- Fake MCP/model boundaries prove pinning, no label leakage, safe reference tools,
  per-case errors, replay integrity, and no-network default behavior.
- Ragas API smoke check uses the pinned package without paid calls.
- Vietnamese runbook documents installation, environment, retrieval, generation,
  judge, replay, comparison, human calibration and the artifacts to return.
- No claims of live quality until the user runs the system.

## Decisions delegated by the user

The user requested spec → plan → execution autonomously. Continue without another
approval gate. Work in the current checkout, no subagents/worktrees/commits, and
focused tests only, in accordance with repository instructions.
