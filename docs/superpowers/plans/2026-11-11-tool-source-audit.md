# All-tool audit against BTC source

User goal: review every current repo tool and improve evidenced defects using
../BTC-Data-Vong1-TEAMS as the countercheck source, including official Nov patch.
Current checkout only; preserve existing modifications and BTC source bytes.
No paid inference, live eval/benchmark, DB writes/reset/import, agents or worktrees.

## Scope / proof

- CRM lookup: all 50 customers and available phone/Zalo/FB identifiers; shared phone,
  unknown input, owner boundaries and runtime-order enrichment.
- catalog.search: names/categories/variants, price/area/discontinued filters and
  deliberate ranked-discovery differences from the literal BTC mock must be explicit.
- inventory.check: every parent/variant, inventory event boundaries, discontinued SKUs.
- pricing.get_quote / pricing.quote_order: BTC mock as oracle, promotion date boundaries,
  regions, ownership/once use, exclusions, ties, multi-line quantities and split orders.
- order.create/status/update: actual service and input boundary using fake repos;
  quote/stock/owner/COD/idempotency, persisted unit lines and meaningful status metadata.
- schedule.callback: business hours, Sunday/holiday, timezone, moved_from.
- handoff.transfer: brief schema, nullable fields, owner and idempotency.
- memory.read/write/turn_status: custom contract/provenance/TTL/PII/owner and async status.
- policy.search: BTC 14 docs/99 chunks/60 labeled questions as corpus evidence; public,
  internal, historical version, dependencies and retrieval input/output boundaries.
- eval.database_identity / eval.knowledge_release: read-only authenticated diagnostics,
  not model-visible business tools; schema/list integration checked.

Plan: inventory + source review -> deterministic differential/contract tests -> fix
only reproducible defects -> focused connected validation -> per-tool findings/limits.
Do not present mocked retrieval as measured live RAG quality or production DB proof.

## Results, 2026-11-11

Reviewed all four MCP servers: 19 declarations, 16 distinct names (database identity
appears in all four). FastMCP in-memory list_tools verifies the actual surface and
that the model sees only the 10 business tools. CRM, memory and eval probes remain
orchestration-only. No new tool or dependency was added.

| Tool | Evidence / finding |
|---|---|
| crm.get_customer | All populated phone/Zalo/FB identities of the 50 original customers compared with the official mock; ambiguity and unknown identities retained. Runtime orders now include payment/promos. |
| catalog.search | All 136 parent/variant SKU lookups and category/price/discontinued combinations compared with the official mock. Ranked/accent-insensitive free-text discovery is intentionally different; existing tests cover named brands, model digits, types and unrelated-result rejection. |
| inventory.check | 8,160 SKU/date combinations match the official mock, including event boundaries and discontinued products. |
| pricing.get_quote | 16,320 combinations match official pricing fields after removal of the internal cost field: 136 SKUs × 60 boundary dates × anonymous/verified trade-in owner. Service additionally provides delivery estimates. Identity fallback corrected to match order/harness behavior. |
| pricing.quote_order | 224 two-air-purifier baskets match the complete November result, including ties, dates and trade-in ownership. Restored the missing official note about splitting differently priced units. Existing November tests also cover quantity, split orders, one-use promos and mismatched prices. |
| order.create | Offline service/MCP checks cover per-unit quote validation, aggregate stock, COD limit, split-order promotion consumption and idempotency. Existing per-customer transaction lock retained. |
| order.status | Both actual repository SELECTs executed using attached in-memory SQLite with a BTC-generated receipt; payment/promos retained, delivery address omitted, foreign customer returns no orders. PostgreSQL execution not claimed. |
| order.update | Two concurrent exchange calls reproduced both getting the free-first-exchange fee. Added the existing per-customer transaction lock to updates; regression now yields fees 0 and 60,000. Fake concurrency test, not a live PostgreSQL load test. |
| schedule.callback | Ten date/time cases compared with mock, including Sunday, holiday, after-hours, 11/11 and explicit +07:00. Hour-only movement correctly reports moved_from already; no callback implementation change was needed. Source conflict below remains explicit. |
| handoff.transfer | BTC JSON schema validation, required/nullable values, invalid brief rejection, identity boundaries and replay without duplicate ticket checked. |
| memory.read | Offline contracts cover session ownership, older matching episode selection, inactive/uncommitted revisions, erasure and stale price/stock refresh. Stored presence is not proof of use by the agent. |
| memory.write | Commit-turn contract, provenance, PII masking, worker admission and episode resolution covered; legacy arbitrary fact writes rejected. Worker success is not equivalent to semantic extraction quality. |
| memory.turn_status | Pending/failed never expose proposals; completed changes are whitelisted/masked; owner/erasure/missing-turn states checked. |
| policy.search | 14 source docs/99 sections accounted for: 93 safe chunks, six explicit exclusions. All 60 labeled QA references map to raw source; answerable references map to served chunks. Tests cover historical applicability, required links, internal disclosure limits, authenticated context, revocation and dependency failure. This is corpus/contract coverage, not measured Recall@k. |
| eval.database_identity | Four registrations verified; gateway tests check routing, timeout, unsupported server and removal of extra connection details. SQL inspected; no live database probe run. |
| eval.knowledge_release | Server delegation and service manifest/index checks reviewed; MCP test returns the requested pinned release. Internal probe is not exposed to the model. |

### Production changes in this goal

Only four evidenced corrections: catalog identity fallback; payment/promos in both
runtime-order projections; basket quote note; customer lock for order.update.
Other dirty agent/catalog/memory/harness/frontend files predate this goal and were
preserved. No source catalog, CRM seed, policy, November mock or K0 artifact edited.

### Remaining differences / recommendations

- `catalog.search` free-text ranking differs from the mock's literal all-token
  matching. Exact SKU and tested structured filters match. Do not claim complete
  output parity for arbitrary free-text queries; document this discovery extension
  in the submission, or explicitly choose strict mock search before changing it.
- LN-01/LN-02 policy says nearest working slot and 11/11 hours 07–23. The supplied
  mock instead moves Sunday 08:00 to the following working day, can move weekday
  21:30 back to 08:00 on the same date, and uses regular hours on 11/11. Current
  tool mirrors that reference behavior. No silent calendar override was made.
- Exchange/return mock does not enforce delivery-age, opened seal or category
  eligibility; update_address has no new-address argument in the supplied schema.
  Policy advice must not be presented as eligibility already verified by this tool.
  Enforcing richer eligibility requires an agreed contract and receipt-condition data.
- No live Postgres lock/transaction validation, deployed RAG recall, model-quality
  evaluation, ASR/TTS check or latency benchmark. None is inferred from fake repos.
  The source audit cannot establish a new end-to-end TSR/HR/CCR result.

### Validation

- 219 focused tests passed across 25 files: source matrix, November pricing,
  MCP business/gateway/logging/memory/knowledge, turn status, memory contracts,
  worker/episodes, policy sources/rules/contracts/search/dependencies/agent evidence/
  integration/lookup/storage, and ranked catalog.
- Two additional focused tests passed for complete SKU/structured catalog lookup
  and callback date/time parity (added after the 219-test run).
- 74 connected tests passed in test_variant_contracts.py, test_basket_runtime.py,
  test_session_state.py and test_session_product_resolution.py, including real
  graph/MCP execution with fake storage and inference.
- Total for this audit: 295 passing focused tests; no full-suite run or model call.
- Source file list and SHA256 compared against /tmp/tool-audit-start.json;
  both original BTC and November patch unchanged. git diff --check passed.
