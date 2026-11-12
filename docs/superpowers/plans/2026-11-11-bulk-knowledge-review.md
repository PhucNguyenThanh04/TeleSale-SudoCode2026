# Bulk knowledge review and offline publication proof

Authorized: verify review -> publication -> retrieval offline, add a Duyệt hết
button. Work in current checkout; do not touch scenarios or live DB/release/API.

Use the existing single-revision approve command; no new bulk server protocol.
Load draft revisions across all pages, show content/sources/tests for review, then
apply the shared reason to those exact hashes. Approval stays separate from release.
Report per-item failures and successful count; approved/rejected or technically
classified items are excluded. Select successful approvals for the existing release UI.

Verify in headless Chrome with fake AI transport: all pages, no implicit publish,
empty queue, missing review confirmation and partial failures. Verify real knowledge
review/publish/search services with offline repos/index/encoder; no model-quality claim.

## Delivered and verified

- Added Duyệt hết to /knowledge. Loads draft revisions across every page, shows
  stored content, source validity and regression tests; requires a shared reason
  and explicit review acknowledgment. Uses existing actor/hash/permission checks.
- Approves each revision separately, reports partial successes and failed IDs,
  supports refreshing remaining drafts, and selects successful approvals for the
  existing release screen. Does not create answers, publish or resolve gaps.
- Approved/rejected revisions and technical/generation/correct-refusal categories
  are excluded. Existing source validation and reviewed-test requirements remain.
- Existing release limit is 100 revisions. Approval can cover more than 100;
  release UI explains the limit and blocks oversized selections before sending.
- Chrome checks: 101 drafts across API pages, required reason and acknowledgment,
  partial 409 failure, excluded categories/statuses, empty eligible queue, no
  implicit release, old single-review/activation/rollback and mobile layout.
  Backend browser/gateway selection: 12 passed; modified bulk checks rerun green.
- New test_knowledge_publish_search_loop.py uses original BTC DT-02 conditions,
  real review commands/hybrid build/Qdrant in-memory/MCP policy.search, transactional
  memory repo and a deterministic embedding double. It verifies no new KG revision before
  activation, sourced FAQ and dependency after activation, old-release pin isolation,
  supplement opt-out, and awaiting_verification rather than automatic resolution.
- Knowledge lifecycle/revisions/releases/retrieval/publish/MCP/integration selection:
  37 passed. Test config is explicitly offline; no .env file edited. The new test
  was rerun after aligning its FAQ with the precise DT-02 source, and passed.
- Knowledge comparison controls: 4 passed. Combined unique focused checks: 53.
  No full-suite run, live DB operation, actual approval/publication, model/API call,
  deployment or scenario edit. git diff --check passed.

## K0/K1 evidence to collect after the other session finishes

Use a NEW K0 on finalized code and scenarios: previous K0 predates harness and
measurement repairs. Keep model/parameters/seed, code, dataset/scorer, memory mode,
guardrails and tools fixed between K0 and K1; pin distinct knowledge releases.
Only compare finalized runs using eval_harness.knowledge_comparison (without
--register for file-only output). The comparison refuses changed code/model/data.

For each real gap selected from new K0, retain question/answer, triage category,
source section/hash and applicability, reviewed revision/test, published release,
then K1 retrieved KG revision/source IDs and final answer. Include an unchanged
control case. Do not classify wrong-product selection, tool failure, medical
refusal or absent authorized source as a FAQ content gap just to show improvement.

The offline FAQ test proves the publication/retrieval mechanism using existing
source facts. It does NOT prove a real gap was solved, improved LLM accuracy or
latency/TSR gains. Those require new K0/K1 case traces and human review. No live
gaps were chosen/approved during implementation, and no synthetic demo data seeded.
