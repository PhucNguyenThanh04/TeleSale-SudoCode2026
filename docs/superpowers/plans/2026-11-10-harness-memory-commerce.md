# Harness memory and November commerce implementation plan

**Goal:** Implement the approved design: November BTC tools/scorer, immediate evidence-based sales state separate from background LangMem, incremental extraction, and eval readiness shared with deployed text/voice.

**Architecture:** Keep AgentHarnessRuntime and MCP service boundaries. Transactional evidence and committed-turn read views are authoritative for sales state; LangMem proposes durable customer facts and narrative episodes. Extend existing read-your-committed-turns rather than build a second history store. Preserve both deployed text and voice lifecycles.

**Approved specification:** User accepted the preceding four-part proposal and requested thorough implementation in an active goal. Source contracts: original project PDF, ../BTC-Data-Vong1-TEAMS, and BTC-cap-nhat-11-2026 patches.

**Constraints:** Current checkout only; no subagents, live model calls, costly evaluation, database resets or deployment. Preserve pre-existing uncommitted work. Focused offline tests, no repeated successful checks without changed behavior or another concrete reason. No commit required.

## Task 1 — November BTC commerce contract
- [x] Write and observe failing offline differential tests comparing pure pricing with the new BTC mock using original catalog fixtures: equal-price units, cheapest item, three units, trade-in, exclusions, split orders, quantity and COD.
- [x] Extend commerce_rules with quote_order; preserve single quote shape and enforce new strict tie rule.
- [x] Expose pricing.quote_order through catalog validation, service, FastMCP and trusted gateway routing. Reuse identity checks; never trust caller-provided ownership.
- [x] Support validated order.create(lines) with prices per physical unit, same-day split promotion state, aggregate SKU stock checks, idempotency, persistence and status reads of lines. Keep single-item compatibility.
- [x] Extend business tool schema/policy and evidence/confirmation/guardrails to baskets. A quote or agent speech is never purchase consent. Requote/invalidate consent on relevant basket changes.
- [x] Verify focused catalog/order/guardrail tests and real runtime offline basket flow.

## Task 2 — BTC overlay and scoring
- [x] Resolve the supplied partial November patch against the original full BTC root without modifying either source; use exact new scorer/schema/mock and original catalog/policy/trace contracts.
- [x] Bind both source versions in provenance; prevent stale scorer use and preserve offline scorer replays.
- [x] Test multi-line totals, optional promo, minute timestamps and failed orders; no inference needed.

## Task 3 — Immediate operational memory
- [x] Use durable committed turns/tool observations for current-session state and unprojected prior sessions. New session/channel must see recent committed changes before worker completion.
- [x] Keep identity, erasure, TTL, evidence attribution, conflict resolution, delivery receipts, ownership, atomicity and idempotency guarantees.
- [x] Make essential customer deltas (changed choice, budget, blockers, callbacks) immediately readable with validated evidence; leave semantic/narrative enrichment to LangMem.
- [x] Test immediate channel switch, no completed worker projection, changed mind, interrupted speech, handoff, baseline isolation and erasure.

## Task 4 — Incremental distillation and eval readiness
- [x] Extract only unseen/current customer evidence with bounded context and already admitted state, preserving source order and retries. Do not drop unresolved customer facts or confirmations.
- [x] Define/read shared readiness contract for essential state; eval waits on that contract rather than every enrichment job. Worker completion/capture remains separately attributable and fully drained for final artifacts as needed.
- [x] Test worker pending/failed/retry, stale revision race, source IDs, same-customer ordering, no inference replay on read, and full/baseline parity.
- [x] Record prepare/response/essential-commit/background-finalize timing separately; document limits without claiming measured live improvement.

## Completion audit
- [x] Review every requirement above against current code and focused tests; retain active goal if any scope remains.
- [x] Update architecture/README with migration instructions, overlay usage, memory readiness, and offline verification commands.
- [x] Read full relevant diff and check diff whitespace. No live benchmark unless separately authorized.

## Progress / rulings
- Initial inspection: current checkout has additional text lifecycle and many existing uncommitted changes. Preserve them; implementation must support text and voice, not force all evaluations into voice.
- Task 1 starts with pure pricing contract and service integration; goal remains active until Tasks 1–4 and audit are complete.

## Checkpoint 2026-11-10 — implementation in progress, goal remains active

Implemented and checked so far:
- New pure `commerce_rules.quote_order`, new tie rule for scalar pricing; differential tests use the EXACT November BTC mock against original catalog fixtures. Catalog MCP/gateway expose `pricing.quote_order` with trusted identity handling.
- `order.create(lines)` validates each physical unit, aggregate stock and COD, uses customer transaction lock for same-day split promotion admission, persists lines, preserves single-SKU fields. New `backend/migrations/0006_order_lines.sql` is written but NOT applied. Order/catalog SQL reads now require this migration.
- New `eval_harness/btc_release.py` makes an immutable full contract snapshot from original data plus exact three November files. Single CLI, benchmark CLI and paired coordinator use it automatically; report and paired model metadata bind snapshot hash. Old explicit scorer replay helper remains usable for old artifacts.
- Immediate read views now discover committed customer sessions even when LangMem has no projected episode. Evidence-checked deterministic customer facts and tool facts overlay pending jobs, with source IDs/revision protection. Long calls use full committed evidence rather than silently losing the first choice after 12 turns. Blocker resolution reuses the existing decision-maker rules. Reuse one SQL evidence read per session for fact and episode hydration.
- Moved the existing deterministic supplement function unchanged into `app/agent/memory/customer_facts.py`, re-exported by langmem_extractor, so immediate memory reads do not import LangMem/model manager.
- Worker extraction receives ONE new source turn with previous agent speech as reference context, rather than re-sending the five-turn window. The canonical consultation reconstruction still uses committed history. Current-session open items are also available for resolution.
- Basket boundary module `mcp_shared/basket.py` validates customer acceptance of a delivered, priced basket against current quote, stock, ownership, day, quantity and terms. BusinessTools exposes the new tool and typed lines; repeated basket writes in one turn return the existing receipt. Canonical evidence, diagnostics and safe memory observation allowlists recognize the new pricing tool. Monetary checking supports basket totals and explicit unit prices.
- Eval no longer waits/captures enrichment BETWEEN utterances. It commits delivered working state, continues the call, then drains each source job and captures writes once at the CALL boundary before the next session/scoring. Decision captures are retained until worker readback. Separate `essential_commit_ms`/`background_finalize_ms` fields were added; legacy memory_finalize_ms sums them. This is deliberately not "drop all waits": session-boundary drain still preserves semantic profile consistency.

Observed test evidence (all offline, no live model/database/reset):
- Initial November pricing tests: 12 expected failures; initial service/line validation tests then failed before implementation. Differential pricing + original business tests: 16 passed; expanded pricing/schema/MCP group: 19 passed; multiline/side-effect group: 4 passed; split/price distribution: 2 passed; actual MCP multiline order: 1 passed. Variant contracts initially exposed outdated test fixture missing category and None handling; fixed fixture/early validation, then 18 passed.
- Snapshot tests: 3 passed. Root/coordinator/CLI integration test assertions failed before wiring snapshots; after wiring, 37 passed, 1 skipped (isolated PostgreSQL requirement).
- Operational memory tests failed before hydration; now 7 cases pass including unprojected channel switch, baseline isolation, changed budget, blocker resolution/hypothetical, long calls and ownership/erasure. Duplicate-evidence-read assertion failed before per-read caching and now passes.
- Relevant memory suites: 52 passed; extractor/schema group 21 passed; worker/admission/recall 34 passed; after caching, operational/consultation/retrieval group 33 passed.
- Existing continuation integration initially failed because its fake sliced `[-None:]` when production requested full evidence; updated ONLY fake slicing to honor limit=None (also contract_memory_updates fake). Then 46 passed. Separate memory HTTP case needed explicit offline AI_INTERNAL_TOKEN; passed in its own process.
- Basket boundary/model discovery: 14 cases passed. Roundtrip tests expected 9 model tools; updated expected public contract to 10 including pricing_quote_order, and all 6 mocked HTTP roundtrips passed. New privacy/price tests failed first and then 2 passed; basket/evidence/promotion/variant/tool-budget group 64 passed.
- Repeated-basket creation test reproduced duplicate calls and now passes with the receipt guard.
- New eval memory-readiness tests failed before removing per-turn waits; then 2 passed. Legacy lifecycle tests correctly failed on old per-turn barrier expectation; updated only sequencing expectations to call-boundary draining. Focused revised lifecycle + duplicate-basket test: 10 passed.
- git diff --check has passed so far. No full suite, no subagents or worktrees. Existing unrelated user changes preserved.

REMAINING — do not mark goal complete:
1. Complete basket behavior beyond boundary tests: real AgentHarnessRuntime end-to-end with tool/service contracts, deterministic purchase continuation, prior-session basket view, per-unit promotion grounding, and invalidation on product/variant/quantity/address/payment/terms changes. Review room/child-safety/budget constraints for every basket line. Scalar purchase code must not inadvertently manufacture a one-product order when a basket is current.
2. Immediate operational memory: include committed callbacks/actions and basket evidence in episode views; callback observations currently use legacy window/reason allowlist and deterministic_episode_tools currently requires callback status despite BTC returning callback_id/callback_at. Preserve handoff and interrupted speech; add tests for projected tombstones/newer revision and failed/delayed worker races. Check chronological ordering of newly discovered prior episodes (currently appended in old-to-new iteration).
3. Shared readiness contract: enforce actual `MemoryUpdate.turn_saved` before eval advances (real voice receipt/text response), while adapting test doubles explicitly. Current new code does not yet enforce it. Text `essential_commit_ms` currently zero because persistence is inside runtime.run; measure persist node separately without subtracting it from deployed text response latency.
4. Eval drain changes need wider focused verification AFTER last edits: entrypoints/official publication, source attribution, decision diagnostics (including worker envelope), partial traces and worker failures. Review that pending streamed rows are rewritten with final writes/status before scoring; capture failure should mark enrichment failed. No repeated worker waits remain between turns.
5. Worker: remove exception-driven TypeError double invocation if an extractor itself fails; establish same-customer job order across sessions and retry/revision guards; verify unseen-only extraction preserves unresolved facts and completed revisions. Do not simply skip semantic extraction or admit unsupported proposals.
6. Update README/architecture for migration, resolved BTC snapshot/provenance, readiness semantics, call-boundary drain and timing scopes. Audit every task against source and focused tests; no live latency-improvement claim without authorized measurement.

Next useful action: finish and verify shared readiness/text timing and deferred eval diagnostics, then complete basket runtime/operational episode integration and final review. Goal scope is unchanged.

## Checkpoint bổ sung — readiness, runtime basket và kiểm tra hồi quy

- Shared readiness đã kiểm `MemoryUpdate.turn_saved` khi runtime trả receipt; trạng thái chưa lưu dừng trước lượt tiếp. Text persist node đo `memory_commit_ms`; eval ghi riêng essential/background. Cần tiếp tục audit partial-failure artifacts và các test attribution/decision envelope.
- Worker kiểm attempt đang giữ lease trước extraction/save/projection/error completion, xếp job theo customer giữa các session; TypeError nội bộ extractor không gây gọi model lần hai. Có migration index mới `ai-services/migrations/0004_memory_job_order.sql`, chưa áp dụng. Chưa kiểm concurrency trên PostgreSQL thực.
- Operational read có tombstone revision barrier, thứ tự phiên cùng ngày, callback tool evidence và schema episode đầy đủ. Basket offer được dựng từ speech đã commit + quote có source, không phụ thuộc worker.
- Runtime thật (graph Deep/ReAct + MCP catalog/order + memory services; thay inference/storage bằng fake) kiểm text/voice: nhận offer phiên trước, quote mới, tạo đúng một đơn hai unit khi worker pending; baseline/interrupted không tạo đơn. Bốn ca bổ sung giá tăng giữa hai phiên không tạo đơn với consent cũ; kiểm quote mới thực sự có giá khác.
- Sửa yêu cầu “cần khóa trẻ em” bị parser bỏ sót. Test tái hiện rồi sửa: báo giá scalar cũ không được hợp thức hóa tổng basket sai. Test scalar order khi khách chấp nhận basket đã bị boundary hiện có chặn, không thêm production guard dư thừa.
- Catalog quote_order giờ đọc promo đã dùng cùng ngày như order.create; test tái hiện báo giá giảm lần hai và create từ chối trước sửa, sau sửa quote/create đồng nhất. Fake MCP fixture bổ sung cùng contract repo mới.
- Order-level freeship được ground từ order_promos/freeship khi không tham chiếu riêng unit; không suy ra giảm 50% cho cả giỏ. Test gồm mã đúng/sai, freeship false và mixed discount claim.
- README harness đã sửa lifecycle không chờ worker giữa turn, timing text overlap, snapshot tháng 11 và hai migration chưa áp dụng.

Evidence mới (offline): basket/runtime/promotion/consultation group 69 passed; price-change runtime 4 passed; eval readiness/lifecycle/entrypoints/official/offline group 48 passed + 1 skipped (PostgreSQL); worker/operational/pricing/snapshot group 45 passed; sau same-day quote change pricing/variant/runtime 58 passed + 1 fixture failure, fixture corrected and failed case 1 passed. Freeship/percentage selection 3 passed. Scalar bypass negative case 1 passed. `git diff --check` sạch ở lần kiểm vừa rồi. Không chạy live inference/eval, migration hoặc full suite.

Goal vẫn active. Còn cần audit toàn bộ requirement, kiểm snapshot/provenance và worker retry/stale races sâu hơn, eval partial trace/decision attribution; đối chiếu basket khi thay product/variant/address/payment/terms và đường phục hồi sau offer thay đổi; xem lại ngân sách/giá theo unit và điều kiện BTC. Các checkbox completion phía trên chưa phải tuyên bố hoàn tất.

- Verification tiếp: decision diagnostics/turn diagnostics/trace evidence/report metrics 52 passed; sáu test attribution cũ thiếu prepare/playback và giả định wait hai lần. Cập nhật doubles theo lifecycle, giữ kiểm source isolation và lỗi capture toàn batch; cả 6 passed. Không thêm fallback production để dung nạp runtime thiếu lifecycle.
- Worker thêm hai test offline: projection retry dùng accepted_proposals không gọi extractor lại; mất claim ngay trước projection không publish hoặc finish job mới. Cả 2 passed. Promotion/shortlist regression 23 passed. Diff whitespace vẫn sạch.

## Checkpoint — phục hồi sau thay đổi giá, playback và lease

- Test runtime price-change được mở rộng thành ba lượt: giá cũ đã nghe, quote mới cao hơn chưa có consent, rồi khách xác nhận giá mới trong cùng phiên. Trước sửa, postprocess ghi đè quote mới bằng câu hỏi chọn sản phẩm của scalar consultation. Thêm `safe_basket_reply` trong session_nodes, dùng quote hiện tại và giữ các gate sản phẩm/quantity/delivery; cả bốn cấu hình Deep/ReAct × text/voice tạo đúng một đơn giá mới sau xác nhận, không tạo trước đó.
- Quote có thể được đọc lại ở lượt sau khi voice bị ngắt. Test mới thất bại trước sửa; gate giờ chấp nhận quote có source ở lượt đã commit trước lời đọc lại, đồng thời kiểm monetary evidence của lời đã phát. Không cho tool quote ở tương lai làm bằng chứng lời nói trước đó.
- Basket kiểm variant against customer selection và signature gồm freeship; test variant chưa nói rõ bị chặn, offer size 39 hợp lệ được chấp nhận, khách đổi size 40 không tạo đơn size 39. Test successful create dùng state copy để không nhầm receipt idempotency với consent của lượt mới.
- Sửa mô tả model tools/system prompt: giỏ hàng dùng pricing.quote_order/order.create(lines), không bắt gọi thêm scalar quote. Architecture M1 được cập nhật working read view, worker incremental và eval call-boundary barrier.
- Worker: bỏ điều kiện SQL bỏ rơi lease lần cuối; attempt thứ sáu chỉ terminalize job `failed/lease_attempts_exhausted`, không gọi extractor/projector. Trước sửa test tái hiện gọi extractor thêm; sau sửa worker/primary/erasure 25 passed. Cập nhật ba fixture/assertion cũ cho commit timing, một source turn + previous_agent_text và async claim guard; consultation/promotion memory 56 test khác đã qua ở lần kiểm trước sửa fixture.
- Basket/runtime/followup 65 passed; variant/changed-offer selection 13 passed; basket/model-tool-contract sau sửa prompt 41 passed. `git diff --check` sạch.
- Thêm integration test PostgreSQL cho final-attempt crash không kẹt session tiếp, và reapply migration index; 2 test skipped vì thiếu MEMORY_INTEGRATION_ADMIN_DSN. Docker local không truy cập được daemon (OS permission); không chạy DB/migration thật, không suy ra concurrency thực đã được kiểm chứng.

Goal chưa complete: cần requirement-by-requirement audit cuối, hoàn thiện/kiểm đường đổi giỏ hàng và review toàn diff liên quan; các integration SQL mới chưa có kết quả PostgreSQL thật. Không mở thêm dashboard/benchmark hoặc chỉnh các thay đổi cũ không liên quan.

## Final requirement audit — implementation verified

Audit này thay thế các trạng thái pending trong checkpoint lịch sử ở trên. Phạm vi hoàn tất là implementation và kiểm chứng, không bao gồm triển khai/migration database thật hoặc đo KPI bằng model live.

| Yêu cầu | Code và bằng chứng kiểm chứng |
|---|---|
| BTC tháng 11, giá từng unit, tie/cheapest/trade-in/ba máy/exclusions/COD | `commerce_rules.quote_order`, catalog/order schemas/services/tools/gateway; differential tests `test_november_pricing.py` chạy exact November mock với catalog gốc; variant/scalar compatibility đã kiểm. |
| Lưu lines, aggregate stock, once-per-day, replay và cạnh tranh tạo đơn | `0006_order_lines.sql`, OrderRepo customer lock + service reprice. Test PostgreSQL thật tạo hai đơn đồng thời: đúng một created, một price_mismatch; replay không tạo thêm; status trả đúng lines; scalar backfill đúng; catalog báo giá lại theo promo đã dùng. |
| Consent từ lời đã phát, không từ model/tool; invalidate thay đổi | `basket.py`, policy/business boundary và verifier. Runtime Deep/ReAct × text/voice: old offer, giá tăng, xác nhận mới, quantity/product/mixed basket changes; không tạo trước consent, tạo đúng units sau consent. Baseline và voice interrupted không mượn prior offer. Repeated playback, nguồn quote trước speech, identity/day/stock/payment/terms/freeship/room/child lock/variant có test riêng. |
| Ngân sách và grounding theo unit | Final audit tái hiện rồi sửa unit budget bị so với total, unknown basis và budget=0 bị bỏ qua. Scalar quote cũ không thể override giá unit giảm; so sánh sản phẩm ngoài basket vẫn được ground theo scalar quote của nó. Mỗi variant phải có terms thực sự được nói; fallback nêu size/color của từng variant. |
| Snapshot BTC đầy đủ, scorer nguyên bản và provenance | `btc_release.py`: overlay đúng 3 file, hash base/patch/effective, từ chối snapshot bị sửa; root CLI/coordinator/benchmark cùng resolve snapshot và bind btc_contract. Snapshot/scorer tests kiểm lines/failed order/optional promo/minute datetime. Offline replay root cũ vẫn giữ nguyên scorer đã chọn. |
| Working state đọc ngay, không chờ projection | `memory.read` hydrate committed evidence/current/prior session, cache SQL rows; deterministic supplement chuyển module nhưng AST function không đổi. Tests operational memory kiểm pending worker, đổi budget/selection, long call, blockers, tombstone, recency, callback, owner/erasure, baseline. Runtime mua qua phiên khác khi mọi job pending. |
| Giữ admission, TTL, nguồn, handoff, erasure, idempotency | Focused operational/freshness/retrieval/quality/handoff: 41 passed. PostgreSQL memory integration kiểm projection chưa completed bị ẩn, supersession/retry/erasure/ownership/idempotency thực. Không tạo kho history thứ hai hoặc gọi model trong read. |
| Extraction gia tăng, retry và thứ tự source | Worker gửi một source turn mới + previous_agent_text + admitted facts/open items. Internal TypeError không chạy extractor hai lần; saved proposals dùng lại khi retry; stale attempt không publish. PostgreSQL thật kiểm hai connection không claim đồng thời cùng khách giữa session, khách khác vẫn tiến được; expired final attempt được terminalize và session sau tiến tiếp. |
| Lifecycle eval đúng triển khai và artifacts hoàn chỉnh | Runtime chung text/voice, enforce turn_saved; worker drain cuối cuộc trước session/chấm. Readiness/lifecycle/entrypoint/official/offline group 48 passed + 1 skipped ở lần trước; attribution 6 passed; diagnostic/trace/report group 52 passed. Review `run_configuration.finally` xác nhận rewrite trace bằng writes/status cuối; worker/capture lỗi vẫn chặn scoring và giữ source attribution. |
| Timing và tài liệu | Persist node đo essential text commit, vẫn nằm trong response; voice commit sau response; background drain riêng. README/architecture mô tả scopes/TTFT nonstreaming và hai migration, có lệnh offline + PostgreSQL integration. Không tuyên bố số phần trăm giảm latency. |
| Scope và vệ sinh | Giữ checkout và thay đổi có sẵn; không subagent/worktree/full project suite/live model/reset database triển khai. Review relevant production diff và `git diff --check` sạch. |

Final verification mới nhất:
- Basket/runtime/promotion/evidence sau sửa budget và scalar override: 89 passed; sau bổ sung variant terms, basket/runtime 62 passed (36 boundary cases và 26 real-graph cases).
- Operational/freshness/retrieval/quality/handoff: 41 passed.
- PostgreSQL 16.15 chạy tạm từ gói Ubuntu giải nén dưới `/tmp`, Unix socket riêng: 13 ca memory ban đầu có 11 passed/2 fixture failures; sửa mode fixture và wait-source contract, cả 2 ca đã qua. Thêm concurrency/attempt test 1 passed và commerce transaction/backfill test 1 passed. Tổng 15 ca hiện tại đều đã có kết quả pass, không lặp lại các ca đã qua khi không đổi behavior.
- Worker/primary/erasure 25 passed; snapshot/pricing/operational checks và các nhóm khác có kết quả cụ thể trong checkpoints trên.
- PostgreSQL tạm đã dừng và toàn bộ cluster/gói download đã xóa. Không thêm dependency vào project hoặc cài dịch vụ hệ thống. Hai migration chỉ áp dụng trong test databases tạm, chưa áp dụng database triển khai.

Không còn việc implementation bắt buộc trong goal này. Đo latency/model quality live, áp migration vào môi trường dùng thật và rollout là bước vận hành riêng, cần phạm vi/ủy quyền tương ứng; không được coi số test offline là bằng chứng đạt KPI live.
