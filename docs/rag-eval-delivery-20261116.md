# RAG eval code delivery — 16/11/2026

Codebase delivery is complete; live quality acceptance is pending the user's run.

| Requirement | Evidence |
|---|---|
| Independent RAG CLI, no conversation harness | `ai-services/rag_eval/__main__.py`, no eval_harness dependency |
| All 60 QA, labels isolated from generation | `test_btc_cases_keep_labels_out_of_runtime_inputs`, runner generation boundary test |
| Explicit dates with synthetic provenance | contexts fixture + context validation test + real signed MCP handler test |
| Safe read-tool facts for numeric/catalog questions | frozen BTC tools, allowlist, recursive internal-field removal, reference fixture tests |
| One pinned release and preserved evidence order | runner pin/mismatch tests + known multi-hop/link-order scoring test |
| Exact BTC scorer and honest denominators | actual frozen scorer; known Recall 2/59 and full-recall 1/12, 2/12 assertions |
| Offline replay, integrity and exact coverage | missing/duplicate/unknown/input-binding/hash/nested-output regression tests |
| Optional Ragas + independent business judge | partial-metric/refusal tests; actual pinned Ragas with HTTP MockTransport, 7 calls |
| Comparison and human calibration | incompatible-dataset comparison, answer delta, trace binding, kappa and unjudged-case tests |
| Fail-closed live commands, durable interrupted traces | CLI opt-in tests and interruption regression test |
| Run instructions and artifacts to return | `ai-services/rag_eval/README.md` |

Verification: focused package **29 passed, 1 skipped**; optional Ragas API test in
an isolated temporary environment **1 passed**. The optional dependency emitted
one upstream langchain-community deprecation warning. CLI help and diff whitespace
checks passed. No full repository suite, live embedding/model call, database reset,
release activation, commit, worktree or subagent was used.

Boundaries: isolated generator uses its own saved prompt; current-order dates and
read-tool inputs are component fixtures, not evidence of agent verification or
tool routing. Server release reference does not independently attest that its
whole corpus/config matches the local BTC snapshot. Real Vietnamese judge quality
requires human calibration. Artifact hashes detect accidental edits, not an actor
rewriting both artifacts and manifests.

User acceptance inputs: collection directory, scored/judged directory, comparison
if available, and reviewed human labels. Report/trace evidence must precede any
claim about actual quality or improvement.
