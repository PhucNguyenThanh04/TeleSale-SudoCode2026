# Execution ledger — plan: docs/superpowers/plans/2026-11-21-ai-audit-repairs.md

## Authority and setup

- Active goal: autonomous spec → plan → execution for all fourteen audit findings.
- Current checkout has many pre-existing modifications and untracked repairs. Preserve them; no subagents, worktrees, commits, deployments or paid calls.
- Spec and plan created after inspecting current state. The previous audit is evidence to revalidate, not an instruction to blindly change code.
- Ruling: user explicitly delegated design decisions and execution, so skill approval pauses and subagent/worktree steps do not apply.
- Ruling: source-correct review-pending return intake is acceptable when fulfillment eligibility cannot be verified; a customer request must not manufacture delivery/condition facts.
- Full offline suite runs: 0.

## Task state

- Task 1: complete. New PII regressions RED: 9 failed/4 passed; GREEN plus write/privacy/log/guardrail checks: 151 passed (3.15s). Shared masker now handles separated and long numbers while retaining priced amounts and product identifiers.
- Task 2: complete. New identity regressions RED: 2 failed/1 passed; GREEN with shared identity and deep-memory checks: 23 passed (3.13s). Self-asserted chat phone no longer verifies identity; signed unlinked identity works; conflicting linked identities remain rejected.
- Task 3: complete. Eligibility regressions RED: 7 failed/1 passed; first GREEN with preview/update/write/identity checks: 137 passed. Added unknown-policy and explicit eligible/hygiene coverage; final return/preview/line checks: 42 passed (2.41s). Missing conditions create review-pending intake; verified expired/damaged/clearance/unsealed requests do not write; old policy retains its fee/period.
- Task 4: complete. Resolution regressions RED: 5 failed; GREEN with direct admission, worker, and primary-memory tests: 57 passed (2.34s). Independent review is required and bound to original item/current source; absence of review cannot close an item. Saved review digests preserve retry safety. One existing worker fixture needed an actual async knowledge enqueue mock under the configured knowledge-enabled environment.
- Task 5: complete. RED: four missing-private-context failures, followed by two address parsing regressions. GREEN: 106 passed / 16 external HTTP/PostgreSQL integration tests skipped (2.75s). Raw address is stored only in an erasable private turn column with a dated masked source reference. Migration 0006 and fixture/bootstrap setup updated; no live migration performed.
- Task 6: complete. RED: 2 failures (completed erasure misclassified, owner cache retained). GREEN with restart/delivery/erasure/deep-memory tests: 23 passed (3.25s). Completed reads now restart anonymously and purge owner caches; permanent tombstone still blocks old writes/workers. Additional retry/cross-session and in-flight cancellation coverage passed in the final gate.
- Task 7: complete. RED: 2 failures (greeting blocked by knowledge outage; release lookup scanned full snapshot). Lazy turn pin, cheap manifest reference, batched snapshot/revocation checks and bounded validation cache implemented. Focused gate: 47 passed / 2 failures caused by fixture runtime config differing from local .env; production compatibility validation remains correct. Test configuration was isolated; snapshot-cache and lazy-pin/revocation coverage passed in the final gate.
- Task 8: complete. Ruling: execute this coupled worker-summary change alongside Task 4. RED: full old summary hides latest goal (1 failed). GREEN with independent resolution, summary, primary-memory and fact-review tests: 65 passed (2.41s). Summary rebuilds from current canonical state and latest accepted source-backed changes.
- Task 9: complete. Context RED: 2 MB of unbounded sources; GREEN with memory/source checks: 23 passed (2.57s). Durable retry/cache RED: 2 failed; GREEN with context/receipt/projection checks: 13 passed (2.54s). Model fields have explicit budgets and incomplete-source writes are denied. Real operational reads batch pending turns plus recent completed turns, capped at 240; longer sources remain explicitly incomplete. Runtime caps idle sessions, retained turns and cached tool history; request-hash replay added with migration 0007. Replay/MCP/ledger cases passed in the final gate; PostgreSQL integration remains explicitly skipped without its isolated DSN.
- Task 10: complete. RED: 3 failures for missing receipts, callback and provenance; GREEN with worker/status/operational/tool checks: 45 passed / 1 HTTP test skipped (2.99s). Projection now propagates actual source_kind into accepted writes. Follow-up provenance/knowledge/erasure gate: 18 passed (3.15s).
- Task 11: complete. Deadline RED: 3 failed (17.21s). Execution/model/verification bounded by one deadline with reserved receipt persistence time; publication still waits for full verification. First GREEN: 32 passed / 1 test assertion incorrectly assumed the first tool was a write rather than CRM. Corrected to select receipt; deadline/preparation/policy gate: 31 passed (4.55s). No live latency claim.
- Task 12: complete. RED: 2 failed (missing BTC invariants; repair replaced selected managed prompt). GREEN with authorization/publication checks: 107 passed (2.63s). PB-01/06/09 instructions and authorization's offer requirement are explicit. Selected prompt is fetched once and reused exactly for repair.
- Task 13: complete. RED: 2 failed (basket context absent; same-turn create keys collide). GREEN with signed writes/provider schemas/November pricing: 130 passed (3.10s). Four-product offline flow completes in seven business calls. Default tool budget remains 8; local override raised 5→8. Output budget raised 256→1024 for structured multi-line payloads. No provider call or restart performed.
- Task 14: complete. Preparation tests now follow model-led reads and safe model handling during pending erasure/outage; 31 passed in combined gate. Existing policy fixture now isolates test embedding config from local settings rather than weakening runtime compatibility checks. Historical Nov18 extraction report passes stored trace/sidecar hashes but current verifier rejects its old extractor fingerprint; preserve original evidence and report this incompatibility explicitly. Historical score remains historical; no live replay or human labels fabricated.


## Final gate and review

- Final focused command: `cd ai-services && .venv/bin/python -m pytest test/test_audit_*.py test/test_session_preparation.py test/test_managed_prompts.py test/test_memory_erasure_workflow.py test/test_memory_erasure_contract.py test/test_langmem_erasure.py test/test_operational_memory.py test/test_policy_integration.py test/test_policy_publish.py test/test_policy_search.py test/test_policy_product_context.py test/test_mcp_gateway.py test/test_mcp_data_identity.py test/test_langmem_projection.py test/test_langmem_worker.py test/test_langmem_admission.py test/test_langmem_primary.py test/test_memory_fact_review.py test/test_structured_episode_memory.py test/test_episode_summary.py test/test_turn_memory_status.py test/test_write_authorization.py test/test_chat_stream_runtime.py test/test_guarded_streaming.py test/test_model_tool_contract.py test/test_november_pricing.py test/test_order_preview.py test/test_order_update_lines.py test/test_agent_context_repairs.py test/test_agent_context_restart.py test/test_mcp_logging.py test/test_guardrail_false_positives.py test/test_configs.py test/test_llm.py test/test_mcp_memory.py test/test_memory_postgres_integration.py test/test_bootstrap_policy.py -q --tb=short`.
- Result: **557 passed, 15 skipped, one dependency deprecation warning, 11.21 seconds, exit 0**. The 15 skips require an isolated PostgreSQL admin DSN; no live database was touched.
- Evidence: `docs/ai-audit-offline-tests-20261121.txt` and `docs/ai-audit-offline-verification-20261121.json` with current source hashes.
- Full suites: **0**. Repository instructions require focused tests and do not require a full suite for this change. Repeated checks only followed code changes, fixture failures or newly added cases.
- Final inline review found and removed numeric chat-ID→phone fallback in both SQL repositories (RED: two failures; focused identity/retry GREEN: 16 passed). It also corrected recovery to inspect `runtime.tool_operations`, the actual business ledger, and added the necessary read-only role grant.
- An actual signed in-process MCP order creation followed by timeout and runtime restart now has a focused regression proving one order only; it is included in the final gate.
- Completed-erasure tests cover cross-session cache purge, pending voice playback cancellation and another in-flight answer cancellation. Context completeness is included in the write-review binding.
- Summary follow-up covers a verified callback receipt in the rebuilt current summary. Cross-channel restart replay retains original source IDs while every distillation job remains pending; no resolution is invented.
- Historical triage is saved in `docs/ai-audit-historical-extraction-triage-20261121.json`: all 38 Full and 29 baseline unresolved candidates have source-bound assistant triage. Original trace/sidecar hashes match. Current extraction verification rejects the historical fingerprint/candidates, so no current acceptance, human judgment, new score or semantic support label is fabricated.
- User instructions override finishing/review skill menus, full-suite reruns and subagent dispatch. Review was inline; leave all patches in the original dirty checkout. No commit, merge, push, worktree, deployment, provider call, database reset or service restart was performed.

## Requirement-to-evidence map

| Requirement | Main offline regression |
|---|---|
| 1 PII boundaries | `test_audit_pii.py`, logging and false-positive guards |
| 2 verified identity | `test_audit_identity.py`, `test_mcp_data_identity.py` |
| 3 returns and old/new policy | `test_audit_returns.py`, preview and order-line tests |
| 4 independently reviewed resolutions | `test_audit_episode_review.py`, structured/admission/worker tests |
| 5 private delivery source | `test_audit_delivery_context.py` |
| 6 completed erasure and purge | `test_audit_erasure_restart.py`, erasure and delayed-worker tests |
| 7 lazy knowledge pin and safe cache | `test_audit_knowledge_availability.py`, policy integration/search/publish tests |
| 8 rebuilt summaries | `test_audit_episode_summary.py`, episode-summary/worker tests |
| 9 bounded context/cache and durable retry | `test_audit_context_budget.py`, `test_audit_durable_retry.py` |
| 10 durable receipts and provenance | `test_audit_tool_receipts.py`, turn-status/projection/worker tests |
| 11 bounded turn deadline and publication | `test_audit_turn_deadline.py`, guarded streaming/runtime tests |
| 12 BTC prompt rules and selected-prompt reuse | `test_audit_prompt_invariants.py`, managed-prompt and write-authorization tests |
| 13 split-order keys/context and budget | `test_audit_split_order.py`, provider schema and November pricing tests |
| 14 pending cross-channel replay and evidence | `test_audit_pending_channel_replay.py`, historical triage and final focused log |

## Operational limits and next execution boundary

- Existing installations need migrations **0006 and 0007** and coordinated AI/memory upgrade; bootstrap/provisioning already include the schema and role grant. Migrations were prepared, not applied.
- Database integration, current-provider semantic accuracy and real latency remain external validation. The test suite uses fake models and in-process MCP; no paid or live evaluation was authorized or performed.
- Long/incomplete context blocks writes, and a committed write without a completed reply requires recovery rather than blind execution. Voice replay returns the heard prefix; replay does not persist a Call Brief. These conservative limits are documented in the harness contract.
- Historical BTC scoring and unresolved-candidate human review are unchanged. Assistant triage does not replace independent review or a new model run.
