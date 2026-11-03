# Progress — 2026-11-02-agent-correctness-eval-fidelity

Plan: `2026-11-02-agent-correctness-eval-fidelity.md`; spec and plan approved.
HEAD at start: `9da1c07`. Existing Knowledge Gap Loop changes and deleted
SC08–SC19 scenarios are preserved. No live eval, DB reset, commit or sub-agent.

Task 0: complete — Python/pytest and original run artifacts present; relevant
pre-existing diffs inspected. Ledger lives here per approved plan rather than
skill scratch worktree/commit machinery.

Pre-flight: Task 1 selection consumed by Task 2 recovery; same interface.
Tasks 3/6 extractor consumed by Task 9 replay; preserve output schema.
Task 4 snapshot requires original pre-write retrieved state, not later writes.
Task 5 verifier must recheck Task 2 recovery after its behavior changes.
Ruling: self-review inline, no fresh agent; explicit user constraints prevail.

Task 1: complete — new variant contracts RED (missing resolver) → GREEN;
`pytest test/test_variant_contracts.py test/test_business_completion.py test/test_mcp_business.py -q`: 18 passed.
Ruling: put independent synthetic catalog tests in test_variant_contracts.py
rather than mixing more BTC-backed fixtures. Existing cache test now supplies
non-variant metadata, as the revised create contract requires.
Task 2: complete — transaction helpers RED → GREEN;
`pytest test/test_transaction_reply.py test/test_business_completion.py test/test_grounding_always.py -q`: 38 passed.
Ruling: recovery acknowledges order ID without adding price; no quote is needed
for the acknowledgment, avoiding a new unsupported price claim. Existing
always-on feature rejection remains mandatory; optional-check logging retained.

Task 3: complete — semantic question tests RED (6 failures) → GREEN;
question_semantics + trace_extraction: 17 passed.
Task 4: complete — provenance tests RED → GREEN; snapshot regression additionally
verified by replacing only our snapshot logic with per-turn state: expected
failure, then restored: 10 passed. Combined adapter/harness preservation: 44 passed.
Ruling: unknown/ambiguous scope is excluded conservatively; public trace cannot
prove every paraphrase. Snapshot provenance is retained for use later in a call.
Task 5: complete — 7 benefit-check failures reproduced; focused promotion and
transaction checks: 26 passed. Percent discounts verified against actual amount.
Task 6: complete — 5 semantic claim failures reproduced; claim/question/trace
checks: 23 passed. Historical offers use historical fields with original text;
generic gifts remain promo_active and still expose ground-truth conflicts.
Task 7: complete — opening tests RED (3 failures) → GREEN; 11 focused tests passed.
Removed SKU-specific recommendation and unconditional budget override from local
prompt. Remote production prompt was not fetched/published; its deployment is
not claimed. Existing Langfuse loader tests mock both production/fallback paths.

Task 8: complete offline — 8 RED failures for supplement suppression, conflict
revival and blocker semantic matching → 71 focused tests passed (one upstream
deprecation warning). No production data read or DB/model invocation. Historical
SC02 proposal/rejection artifacts are absent; its exact historical loss is still
unattributed. The independently reproduced failure class is fixed; no claim that
all historical missing facts are recovered. No TTL/compaction/store changes.
Task 9: CLI RED missing module → 3 focused tests passed; original pair replayed
with exact coverage/schema audit (39 rows per config) and unchanged input hashes.
Replay preserves facts_used, text, tools, writes, latency; only extraction fields
change. README records field mapping, zero-baseline and incomplete-label limits.

Final review (self-review per user instruction, no sub-agent):
- Added RED→GREEN regressions for gift deadline borrowed from freecod, negative
  gift/shipping claims, latest quote/stock superseding older evidence, explicit
  variant beating old preference, customer color conflicting with model SKU,
  unknown identity, and known wrong SKU despite a superficially valid draft.
- Catalog matching is driven by metadata; no benchmark SKU or price branch.
  Latest explicit size/color cues use catalog values, not a fixed value table.
- MCP synthetic tests verify surcharge, size exclusion, valid non-variant orders,
  and failed catalog/budget without writes; independent of BTC scenarios.
- Existing deep-memory test updated to allow the newly specified catalog read,
  while still asserting that no order write occurs without stock/quote.
- Existing structured/always-on grounding and disabled-check logging preserved.
Ruling: a singular gift_sku represents one item in the existing tool contract;
explicit larger quantities require gift_qty evidence, rather than trusting any
promo. Wrong gift name/expiry remains rejected.
Ruling: conservative scope/unknown-language cases may undercount or reject a
paraphrase; no LLM judge added to the response path. Live behavior/latency remains
unmeasured after changes, and remote production prompts remain unpublished.

Latest replay after stock-polarity correction: `eval_harness/results/20261101T174223Z-c43720a3/offline-reextract-20261101T193039Z`.

Task 10: complete — full regression run exactly once:
`.venv/bin/python -m pytest test eval_harness/test_eval_harness.py -q`
→ 418 passed, 14 skipped, 1 upstream LangGraph deprecation warning in 8.41s.
Full log: `/tmp/telesale-correctness-regression.log`.
`git diff --check` passed. Focused eval extraction/replay and provenance tests
were run separately in their tasks (full command only collects the named
harness file). DB/HTTP integration opt-in variables were unset; no DB reset,
network model evaluation or prompt publication occurred.

Final scope review: only planned agent/MCP/evaluation files, focused tests and
documents changed by this implementation. Pre-existing knowledge signal wiring,
README additions and benchmark release capture remain intact. No scenario/BTC
validator/reference scorer changed; no score from replay is reported.

No integration action (commit/merge/push/deployment) performed. Ready for human
review of working-tree changes. Live model quality/latency, production prompts,
and attribution of missing facts in the historical SC02 run remain unverified.

Follow-up: run 20261101T193405Z-9e548dbb stopped at readiness, 39 trace rows,
37 without memory error and 2 job_failed rows (SC01/call_2/1, SC04/call_2/1).
Read-only DB query found jobs 5 and 23 failed after 5 attempts, ValueError,
accepted_proposals already saved. Offline application of their stored deltas
reproduces `episode narrative lacks supporting evidence`. Those deltas use a
single narrative_evidence_quote across multiple narrative fields; current
admission emits per-field narrative_evidence_quotes. Re-admission of their
narrative fields under current code passes apply after unsupported fields are
filtered. No database writes or model calls were performed.
Worker process started before checkout edits. Compose builds code into images
without a source bind mount. Runtime-image hash cannot be read due Docker socket
and /proc permission denial; stale-worker diagnosis is supported by the emitted
legacy delta shape and deployment configuration, not an inspected image hash.
Deployment must rebuild/recreate affected MCP images; no automatic restart,
job repair or score publication was attempted. Added README deployment step.

Runner diagnostic now identifies failed scenario/call/turn/reason without
customer text. Regression RED (generic error lacked coordinates) → GREEN:
`pytest eval_harness/test_benchmark_lifecycle.py -q`: 4 passed, 1 skipped.
Added independent admission→apply contract with two distinct narrative quotes.
Follow-up full regression (once):
`.venv/bin/python -m pytest test eval_harness/test_eval_harness.py eval_harness/test_benchmark_lifecycle.py -q`
→ 422 passed, 15 skipped, 1 upstream warning in 8.76s.
`git diff --check` passed. No services restarted or existing jobs modified.

Follow-up 2026-11-02 14:26 local: run 20261102T072633Z-156ada96 stopped visibly
after first completed response because the harness waits for distillation.
Read-only inspection at 07:27 UTC: job 1 pending, attempts=0, no lease/proposal.
Catalog/order/memory Python processes present, no LangMem worker process.
Docker access remains denied (sudo requires password); no service was started.
Compose root .env has Langfuse URL unset/empty and both Langfuse flags off.
Compose passes LANGFUSE_BASE_URL as empty string to the worker. Replaying that
Settings initialization offline reproduced url_parsing ValidationError, even
though Langfuse was disabled. Added a before validator for this optional URL;
blank→None only, invalid nonempty URL and enabled-with-missing-credentials still
fail. No Langfuse SDK/API or model/DB write was used in tests.
Config tests RED (2 failures) → GREEN: 12 passed, including real env-string path.
Worker container logs could not be inspected; this fixes the proven startup
configuration error, but live worker readiness still needs image recreation.
Config follow-up full regression (one run):
`.venv/bin/python -m pytest test eval_harness/test_eval_harness.py -q`
→ 422 passed, 14 skipped, 1 upstream warning in 8.03s.
`git diff --check` passed. Deployment/live worker not verified due Docker access.
