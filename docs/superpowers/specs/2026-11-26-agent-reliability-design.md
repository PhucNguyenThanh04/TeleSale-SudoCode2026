# Agent reliability and task completion

## Intent

Strengthen the existing telesales service after the source and trace audit. Improve correct task completion, memory carryover, grounded answers and useful response latency without weakening customer authorization or tuning runtime behavior to public scenarios.

The user delegated specification, planning and execution. Implement inline in the current checkout. Do not create worktrees or delegate to agents. Leave changes reviewable in the working tree. Existing untracked `eval_results/` belongs to the user and must remain intact.

## Evidence and targets

The saved full run has 7 scenarios and 39 turns: TSR 57.1%, CCR 52.4%, RQR 0%, price/promotion HR 0%, TTFT p95 3799 ms. These are a small historical sample, not a controlled current baseline. RAG has any-hit recall@5 91.5% and multi-source full recall@5 50%, with no independent answer judgments.

Correctness gates take priority over apparent metric gains. Target the existing acceptance thresholds of TSR >=70%, price/promotion HR <=5%, RQR reduction >=40%, TTFT p95 <=3 seconds and total p95 <=8 seconds. Do not claim that offline tests establish these live thresholds. Live evaluation requires explicit permission, an isolated evaluation database and matching deployed worker code. A private-test score cannot be certified without private evidence.

## Required behavior

1. Identity: an unlinked chat account and a self-declared phone number never authenticate a CRM customer. Linked channel identity and backend-verified identity continue to work, including shared-phone ambiguity checks.
2. Authorization: deterministic approval is limited to a fully understood current request with the exact target, quantity, payment and current valid evidence. Unrecognized language uses independent review. A known contradiction never gets a fast approval. No catalog names, SKU prefixes, customer IDs, dates or scenario IDs are hardcoded to pass examples.
3. Memory: a read of price or stock is not a customer selection. Only supported customer statements and confirmed order receipts establish selected variants. Worker and operational replay use the same rule. Current fact freshness must reach its configured callers.
4. Answer evidence: completed actions require actual compatible successful receipts. Policy support must preserve scope and conditions, not merely contain the same number of days. Use existing semantic review at the appropriate boundary; deterministic checks remain a fast first line. Fix cases where the checker rejects an evidenced price or gift because it binds the wrong product.
5. Delivery and recovery: the delivered answer must agree with the final verified answer. Rejected drafts cannot survive by being concatenated with a repair. Fallbacks cannot select a gift as the purchased product or ask for information already supplied. Errors must preserve actual write receipts and retry protection.
6. Completion: when the model offers an unnecessary extra confirmation or promises an action without executing it, permit a bounded model/tool continuation under unchanged authorization and tool budgets. Never create a business write directly from a regex. Handle abstention, ambiguity and explicit constraints without forcing a purchase.
7. Retrieval and measurement: preserve mandatory linked evidence through bounded dependency traversal. Do not turn missing evidence into a confident answer. Score abstention from observed behavior when labels are available and distinguish unmeasured quality from success. Reuse existing evaluation facilities; do not add dashboards.
8. Verification: each risky change has a failing regression and focused green tests. Include synthetic unfamiliar products, shifted dates, quantities, variants, negation, conditions and third parties. Run relevant offline integration checks after the components are connected. Do not rewrite expected results merely to hide regressions.

## Chosen approach

Keep FastAPI, LangGraph, MCP, PostgreSQL and Qdrant and the existing service boundaries. Repair the narrow trust and evidence boundaries first, then improve completion and retrieval. Prefer removing an unsafe shortcut to expanding language heuristics without proof. Preserve independent authorization and semantic review for language that cannot be safely resolved without a model.

Bound recovery by the existing total turn deadline, call budget and one continuation. Measure substantive response delivery; do not improve TTFT by emitting meaningless acknowledgments. Compare live latency and quality only when the evaluation is authorized and deployment provenance is verified.

## Non-goals

No new frontend, dashboard, framework, model training, unrelated refactoring, production deployment or stock-management integration. Multi-replica session coordination and a real external order fulfillment system are separate projects.

## Execution decisions

The user explicitly requested autonomous spec -> plan -> execution, so approval checkpoints in the skill workflow are replaced by this recorded scope and continuous implementation. Repository rules override worktree, delegation and automatic-commit suggestions. Do not add code comments or explanatory docstrings.

## Completion evidence

Record changed files, red/green test commands, integration outcomes, evidence of generalization, and any live metric comparison in the execution ledger. If live access or permission is unavailable, report that limitation and do not label the historical metrics improved. Audit all eight required behaviors before marking the goal achieved.
