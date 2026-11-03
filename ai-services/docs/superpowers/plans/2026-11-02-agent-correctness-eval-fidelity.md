# Agent Correctness and Eval Fidelity Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task, inline in the current checkout. Steps use checkbox (`- [x]`) syntax for tracking. Repository/user instructions override skill defaults: no sub-agents, worktrees, staging or commits.

**Goal:** Sửa đặt hàng theo biến thể, phản hồi giao dịch, grounding ưu đãi và memory/eval contracts bằng quy tắc tổng quát, có kiểm thử offline chống overfit.

**Architecture:** Giữ MCP là nơi quyết định nghiệp vụ; agent chọn sản phẩm từ metadata và chỉ xác nhận kết quả có bằng chứng. Phép đo dùng phát ngôn và provenance, giữ nguyên BTC scorer. LangMem tiếp tục đề xuất bất đồng bộ qua admission hiện tại.

**Tech Stack:** Python, pytest/unittest, LangGraph, MCP, LangMem, PostgreSQL; không thêm dependency.

**Spec:** [2026-11-02-agent-correctness-eval-fidelity-design.md](../specs/2026-11-02-agent-correctness-eval-fidelity-design.md), đã được người dùng duyệt, đặc biệt mục 2.1 chống hardcode/overfit.

**Trạng thái thực thi:** đã triển khai và kiểm chứng offline Tasks 0–10.
Xem [progress và các điều chỉnh có căn cứ](2026-11-02-agent-correctness-eval-fidelity-progress.md).
Full regression: 418 passed, 14 skipped; live eval/prompt production chưa thực hiện.
Các test semantic độc lập nằm trong file test riêng thay vì chép vào fixture BTC.

## Global Constraints

- Làm trong checkout hiện tại, không sub-agent/worktree, không git add/commit.
- Không sửa scenario, ground truth, validator hoặc reference scorer BTC.
- Không chạy live eval, reset DB, backfill hoặc thao tác tốn phí khi chưa được cho phép riêng.
- Không thêm dashboard, benchmark mới, semantic search, dependency, đổi model hoặc tăng token budget trong đợt này.
- Giữ LangMem làm long-term memory, distillation bất đồng bộ và admission có bằng chứng.
- Business rule nằm ở MCP service/shared module; agent không đọc DB nghiệp vụ trực tiếp.
- Giữ phân tách khách hàng, erasure barrier, che PII theo field path, tên tool/call id và tham số scorer so sánh.
- Mỗi lớp lỗi có regression gốc, ca độc lập đổi dữ liệu/cách nói, ca phải chặn và test bất biến nghiệp vụ. Không thêm nhánh theo sample hoặc đáp án vào prompt.
- Trong lúc làm chỉ chạy focused tests; full regression một lần ở Task 10. Không lặp successful checks nếu không có thay đổi/failure mới.

## Review Focus

1. Metadata catalog thiếu khác với sản phẩm không có variants; catalog lỗi hoặc hết tool budget không được dẫn đến tạo SKU cha — Task 1.
2. Hai variant cùng giá nhưng khác stock/promo, hoặc cùng SKU nhưng khác qty/ngày/địa chỉ, không dùng chung chứng cứ quote — Task 1.
3. Order đã tạo nhưng draft sai, timeout hoặc nhiều kết quả create không rõ đối tượng: không tạo lại và không xác nhận nhầm — Task 2.
4. Một câu nhắc nhu cầu rồi hỏi blocker, nhiều slot trong một câu, hoặc mã cũ hết hạn cạnh quà mới: trích đúng điều agent nói — Tasks 3, 5, 6.
5. Memory cùng session, sai product/room scope, proposal sai source và số tiền trùng nhau không thành carryover hoặc dữ liệu được chấp nhận — Tasks 4, 8.

## Tổ chức công việc và checkout

Một plan gồm hai phần có thể kiểm thử riêng: hành vi runtime/MCP và phép đo.
Chúng dùng chung contract evidence nên giữ một tài liệu, thực hiện tuần tự:
`0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10`.
Task 5 xây verifier ưu đãi hoàn chỉnh rồi chạy lại test phục hồi của Task 2
vì đây là một thay đổi mới trong dependency, không phải chạy lặp vô cớ.

Checkout lúc lập plan có thay đổi ngoài phạm vi ở Knowledge Gap Loop, gồm
`agent_nodes.py`, runtime/gateway, memory service/store, benchmark runner,
official pipeline, README và migration. Không reset/revert hay ghi đè các
thay đổi đó. Trước khi sửa mỗi file, đọc diff hiện tại; giữ nguyên signal,
feedback, lifecycle và routing của công việc khác. Các scenario SC08–SC19
đang bị xóa trong working tree: không khôi phục hoặc thay scenario ở plan này.

### Bản đồ file

| File | Trách nhiệm trong plan |
| --- | --- |
| `app/agent/harness/policy.py` | Phân biệt trạng thái chọn variant; kiểm điều kiện create |
| `app/agent/implementations/business_agent.py` | Lấy catalog thiếu qua gateway, tool guidance và prompt tổng quát |
| `app/mcp_servers/mcp_order/services/order.py` | Chặn SKU cha có variants trước khi ghi đơn |
| `app/agent/harness/session_nodes.py` | Câu phục hồi xác nhận order/quote có bằng chứng |
| `app/agent/harness/agent_nodes.py` | Tích hợp phục hồi vào cả hai nhánh verifier |
| `app/agent/guardrails/promotion_grounding.py` (mới) | Kiểm quyền lợi/mã/thời hạn theo quote và catalog |
| `app/agent/guardrails/checks.py` | Gọi kiểm tra ưu đãi mới; giữ các check khác |
| `app/agent/harness/brief_opening.py`, `context.py` | Nhắc nhu cầu và theo dõi blocker; không hỏi lại profile |
| `eval_harness/extractor.py` | Câu hỏi và claim từ phát ngôn |
| `eval_harness/reference_adapter.py`, `benchmark_runner.py` | Nguồn session, scope và snapshot fact trước call |
| `eval_harness/memory_recall.py` | So khớp expected slot, ghi chú giới hạn diagnostic |
| `app/agent/memory/langmem_extractor.py`, memory admission/worker | Sửa mất fact tại tầng được chứng minh |
| `eval_harness/reextract_trace.py` (mới) | Replay extraction từ artifact, không gọi runtime/model |

Các test mới dưới đây là unit/contract tests, không phải benchmark scenario.
Các file không liệt kê chỉ được sửa khi chứng minh là dependency trực tiếp;
không đổi schema SQL/public API để tiện triển khai.

## Task 0: Ghi căn cứ và chuẩn bị kiểm chứng

**Files:** đọc spec, `AGENTS.md`, diff của các file trong bản đồ; tạo
`docs/superpowers/plans/2026-11-02-agent-correctness-eval-fidelity-progress.md`.

**Interfaces:** progress ghi task, thay đổi, command/result, giới hạn và
quyết định chống overfit; không chứa customer transcript/secret.

- [x] Đọc spec và diff hiện tại của file sắp sửa; ghi HEAD và danh sách thay
  đổi có sẵn trong progress. Dùng working tree hiện tại làm căn cứ thực thi,
  không giả định source digest cũ còn khớp.
- [x] Kiểm tra `.venv/bin/python`, các file focused test và artifact run gốc
  còn có; ghi rõ phần nào thiếu. Không cài dependency hoặc reset môi trường.
- [x] Đối chiếu chữ ký thực tế với plan trước mỗi task; thay đổi nhỏ cập nhật
  vào progress, thay đổi contract phải được làm rõ trước khi mở rộng scope.

**Done:** có căn cứ checkout và đường dẫn artifact, chưa chạy full suite/model.

## Task 1: Variant resolution và rào chặn MCP

**Files:** sửa `app/agent/harness/policy.py`,
`app/agent/implementations/business_agent.py`,
`app/mcp_servers/mcp_order/services/order.py`;
test `test/test_business_completion.py`, `test/test_mcp_business.py`.

**Interfaces:** thêm frozen `ProductSelection` tại `policy.py` với
`status: Literal['resolved','catalog_required','selection_required','selection_unavailable']`,
`sku: str | None`, `parent_sku: str | None`, `missing_fields: tuple[str, ...]`.
`resolve_product_selection(state: TurnState, args: dict[str, Any]) -> ProductSelection`;
giữ `catalog_variant(state, args) -> str | None` như wrapper tương thích.
Giữ `prepare_tool_call(state, clock) -> tuple[str, dict[str, Any]] | None`.
MCP trả `{'error': 'variant_selection_required'}` nếu SKU cha có variants.

- [x] Thêm failing tests: `test_missing_catalog_does_not_authorize_parent_order`,
  `test_returning_purchase_fetches_catalog_and_resolves_variant`,
  `test_create_rejects_parent_with_variants_before_any_write`. Fake repo phải
  chứng minh `insert_order`, `next_order_id`, `use_promo` chưa được gọi khi
  bị chặn. Thêm ca non-variant vẫn tạo được.
- [x] Parameterize hai catalog synthetic khác tên/mã/size/màu/giá và thứ tự
  variants; yêu cầu chọn cùng quan hệ. Test lựa chọn mới thắng memory cũ,
  scope khác không ảnh hưởng, thiếu màu chỉ yêu cầu màu, lựa chọn không tồn
  tại không tự đổi. Model giả lập phải truyền lựa chọn mới trong tool args.
- [x] Test parent evidence không đủ cho variant, hai variant cùng giá khác
  stock, variant cộng giá và size bị loại promo; quote khác ngày/qty/địa chỉ
  hoặc basket không đủ cho create. Catalog lỗi/hết budget không gọi create.
- [x] Run `.venv/bin/python -m pytest test/test_business_completion.py test/test_mcp_business.py -q`;
  xác nhận test mới fail vì hành vi hiện có, không vì fixture/import hỏng.
- [x] Implement resolver dựa catalog thành công trong current/session calls;
  thiếu metadata khác `variants=[]`. Khi create thiếu catalog, BusinessTools
  thực hiện tối đa một `catalog.search(sku=...)` qua đường gateway có ghi
  nhận tool_count/trace trước khi resolve và trước guard known_skus chỉ biết
  các sản phẩm khác. Read có size/color nhưng thiếu metadata trả
  `catalog_required`/`next_tool='catalog.search'`, không giả là thiếu lựa
  chọn khách. Tách thân invoke thành
  `async _invoke_locked(self, name: str, proposed: dict[str, Any]) -> dict[str, Any]`
  để gọi read nội bộ mà không acquire lại `asyncio.Lock`; `invoke()` là entry
  point giữ lock. Không thêm direct DB hoặc recursion catalog vô hạn.
- [x] Bỏ điều kiện stock/quote dựa prefix SKU trong create; dùng đúng SKU,
  `on`, qty mặc định 1 và các điều kiện quote đã chuẩn hóa. Không tự thêm
  create khi còn thiếu read; trả hướng dẫn tool chính xác. Giữ cache/idempotency
  và budget hiện có. MCP kiểm parent bằng product/variant metadata trước
  stock/quote và trước mọi write; không suy đoán bằng cấu trúc chuỗi SKU.
- [x] Rerun hai file focused trên; PASS toàn bộ. Ghi quy tắc tổng quát và
  test độc lập, không ghi “fix riêng SC04”.

## Task 2: Phục hồi câu trả lời sau side effect

**Files:** sửa `app/agent/harness/session_nodes.py`,
`app/agent/harness/agent_nodes.py`, constant FALLBACK ở `guardrails/checks.py`
nếu cần bỏ lời hứa hỗ trợ không có hành động;
tạo `test/test_transaction_reply.py`.

**Interfaces:** `safe_transaction_reply(state: TurnState) -> str | None`
và `safe_quote_reply(state: TurnState) -> str | None` trong `session_nodes.py`;
helper thuần, không gọi model/gateway. Dùng kết quả
Task 1 để phát hiện order SKU mâu thuẫn lựa chọn khi đủ evidence.

- [x] Test async verifier với order status created và draft sai ngày giao
  hoặc hứa quà sai: answer giữ xác nhận/mã đơn đúng, bỏ chi tiết sai; cả
  `check_grounding` lẫn `check_answer` phải được áp dụng lại cho câu phục hồi.
- [x] Test hai lối rejection (grounding và answer), qty >1 dùng total đúng,
  order lỗi/timeout không thành success, nhiều order không rõ đối tượng
  không chọn đại, created sai lựa chọn không xác nhận như đơn đúng, không có
  ticket thì không nói đã chuyển nhân viên. Assert gateway write count không
  tăng trong verify. Dùng hai mã order/SKU/giá khác sample.
- [x] Test read-only có quote hiện tại đúng SKU nhưng thiếu catalog ở lượt
  này vẫn trả được giá đã xác minh, không bịa tên/thuộc tính sản phẩm. Hai
  quote khác SKU mơ hồ phải trả None; quote lỗi/cũ khác ngày không được dùng.
- [x] Run `.venv/bin/python -m pytest test/test_transaction_reply.py -q`; FAIL
  đúng hành vi. Implement helper; ưu tiên transaction recovery trước reply
  về catalog/promo khi có write. Nếu không có evidence thành công và có
  write không rõ kết quả, nói chưa xác minh trạng thái, không nói chắc chắn
  chưa tạo đơn. Không thêm retry/create/compensation.
- [x] Giữ `verifier_events`/knowledge signals đang có và ghi reason rejection
  gốc; không xóa sự kiện vì phục hồi thành công. Handoff chỉ xác nhận queued
  có ticket. Read-only recovery thêm safe_quote_reply vào các helper hiện
  tại, chỉ dùng quote current-turn; nếu thiếu tên đã xác minh, dùng SKU tool
  trả về. Không biến quote recovery thành lời xác nhận order.
- [x] Rerun file mới cùng `test/test_business_completion.py -q`; PASS. Với
  fallback cũ không có rejected draft, ghi “chưa rõ nguyên nhân”, không gán
  bừa reason hoặc tuyên bố đã sửa 12/39 lượt.

## Task 3: Trích đúng câu hỏi và phạm vi slot

**Files:** sửa `eval_harness/extractor.py`,
`eval_harness/fixtures/text_extraction_labels.json`,
`eval_harness/test_trace_extraction.py`.

**Interfaces:** giữ `extract_questions(agent_text: str) -> list[dict[str, Any]]`;
output vẫn `slot/type/text`. Dùng `slot='blocker'` cho câu hỏi tiến độ thật,
không giả làm `has_children`; schema BTC cho phép slot string.

- [x] Thêm fixture nhãn độc lập: nhắc khóa trẻ em rồi hỏi đã trao đổi với
  người quyết định; nhu cầu cũ + hỏi giá mới; câu hỏi thật về trẻ nhỏ; một
  câu hỏi size và màu; hỏi không có dấu `?`; xác nhận đơn khác hỏi mở.
  Có câu gần giống nhưng nghĩa khác, dấu chấm trong giá, nhiều mệnh đề.
- [x] Run `.venv/bin/python -m pytest eval_harness/test_trace_extraction.py -q`;
  test mới FAIL. Implement phân đoạn mệnh đề hỏi rồi phân loại slot theo
  vị từ/cấu trúc hỏi, không first-match keyword toàn câu. Giữ text gốc của
  câu hỏi, không thay đổi agent_text. Không thêm câu thoại sample vào rule.
- [x] Rerun focused file; PASS cả fixture cũ hợp lệ và ca mới. Nếu fixture
  cũ sai ngữ nghĩa, ghi rationale từ câu thoại trước khi sửa nhãn; không
  lấy output mới làm nhãn đúng mặc định.

## Task 4: `facts_used` theo session, scope và giá trị

**Files:** sửa `eval_harness/reference_adapter.py`, `eval_harness/benchmark_runner.py`;
tạo `eval_harness/test_fact_usage.py`; bổ sung `eval_harness/test_eval_harness.py`.

**Interfaces:** thêm `_source_session_id(source: Any) -> str | None`;
mở rộng cuối chữ ký `facts_used(..., current_session_id: str | None = None,
*, customer_text: str = '') -> list[str]`, giữ các tham số cũ. `simulate_call`
giữ snapshot profile/scoped facts từ state retrieve của lượt đầu, trước khi
write của call mới; các lượt sau đối chiếu snapshot này thay vì fact đã bị
ghi đè source trong cùng call. Không thay public trace schema.

- [x] Test parser `langmem:old-session:turn-1`, định dạng legacy
  `old-session:turn-1` đang có trong tests, same-session, rỗng, truncated và
  malformed. Chỉ nguồn hợp lệ khác current mới đủ điều kiện.
- [x] Test boolean polarity, diễn đạt “cho bé nhà mình”, tiền có dấu/k/triệu,
  tiền đối thủ khác giá shop, số trùng tình cờ và `True != 1` về ngữ nghĩa.
  Hai SKU/room cùng giá trị không được tính lẫn; tool arg phải khớp slot
  nghiệp vụ, không đếm boolean từ include_discontinued như has_children.
- [x] Test harness giữ snapshot qua hai lượt: fact trước call được supersede
  cùng giá trị trong call vẫn có thể dùng với đúng nguồn snapshot; fact mới
  chỉ xuất hiện trong call không được tính. Giá trị do khách nhắc lại trong
  lượt hiện tại và agent chỉ lặp lại không đủ chứng minh carryover.
- [x] Run `.venv/bin/python -m pytest eval_harness/test_fact_usage.py eval_harness/test_eval_harness.py eval_harness/test_trace_extraction.py -q`;
  FAIL đúng nguyên nhân. Implement parser strict, slot-aware use và scope
  association trước khi xuất tập tên slot. Mơ hồ scope/nguồn thì không tính.
  Candidate ownership do memory boundary của runtime xác minh; test harness
  không đưa facts từ customer khác vào snapshot.
- [x] Rerun ba file; PASS, đặc biệt test giữ mọi tool name/call id/scorer args.
  Không diễn giải một giá trị vừa được khách cung cấp như bằng chứng memory.

## Task 5: Grounding quyền lợi ưu đãi theo từng nội dung

**Files:** tạo `app/agent/guardrails/promotion_grounding.py`,
`test/test_promotion_grounding.py`; sửa `app/agent/guardrails/checks.py`,
`app/agent/harness/session_nodes.py` nếu helper tạo reply chưa đủ evidence.

**Interfaces:** `check_promotion_grounding(candidate: str, tool_calls: list[dict[str, Any]]) -> str | None`.
Reason dùng nhóm hiện có `promotion_quote_missing`, `promotion_code_mismatch`,
`promotion_detail_unverified`; giữ `check_answer(...)` public interface.
Module mới không import `checks.py` hoặc `eval_harness`, tránh vòng dependency.

- [x] Test freecod-only không chứng minh gift/discount; lời hứa quà không có
  keyword ưu đãi vẫn bị kiểm tra; gift đúng nhưng số lượng/tên/hạn sai; hai
  promo khác hạn; mã cũ expired cạnh gift hiện tại; shipping false nhưng
  hứa miễn phí; percent sai và giá niêm yết/giá cuối riêng. Quote đúng vẫn pass.
- [x] Parameterize product/gift/promo code/ngày và thứ tự applied promos;
  đổi expiry/stock/scope phải đổi quyết định tương ứng. Test nhiều SKU cùng
  turn, phủ định “không còn”, lịch sử “lần trước”, và câu hỏi về quà: không
  chấm nhầm thành lời hứa hiện tại. Mã/danh xưng không biết thì giữ trạng
  thái chưa xác minh, không đoán tên quà từ SKU.
- [x] Run `.venv/bin/python -m pytest test/test_promotion_grounding.py -q`;
  FAIL. Implement liên kết từng quyền lợi với quote SKU/on và metadata quà;
  deadline gắn đúng promo, không lấy bất kỳ applied entry làm chứng cứ.
  Quantity quà không có trong source không được khẳng định số lượng tùy ý.
- [x] Tích hợp check mới trong `check_answer`, không tắt checks khác. Sửa
  recovery helper để chỉ tạo câu có thể qua cùng verifier; giữ giá/order
  được chứng minh khi bỏ quyền lợi sai.
- [x] Run `.venv/bin/python -m pytest test/test_promotion_grounding.py test/test_promotion_recovery.py test/test_promotion_refresh.py test/test_second_item_promotion.py test/test_transaction_reply.py -q`;
  PASS. Nếu fixture cũ dùng quyền lợi không có chứng cứ, sửa fixture nguồn
  hoặc expected rejection theo business contract, không nới check để pass.

## Task 6: Claim extraction trung thực với phát ngôn

**Files:** sửa `eval_harness/extractor.py`,
`eval_harness/fixtures/text_extraction_labels.json`,
`eval_harness/test_trace_extraction.py`.

**Interfaces:** giữ `extract_claims(agent_text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]`.
Giá niêm yết rõ dùng `list_price_vnd`, giá bán cuối dùng `price_vnd`; mã promo
được agent nói rõ dùng field theo convention hiện có `promo_<code>_active`.
Phát ngôn generic hiện tại về ưu đãi/quà dùng `promo_active`; giữ `text` làm
bằng chứng. Không gán code từ tool nếu agent không nói rõ code.

- [x] Thêm fixture list/final price trong cùng câu, số tiền ngân sách/đối thủ,
  gift có/không chữ ưu đãi, mã expired + gift còn hạn, phủ định/historical/
  hypothetical, deadline dạng ngày. Generic gift của trace SC02 phải còn
  claim generic và discrepancy với ground truth, không biến mất sau sửa.
- [x] Test thay quote từ gift thật thành quote sai không đổi claim agent đã
  nói; đổi phát ngôn mới đổi claim. Explicit code khác nhau giữ đúng mã,
  mã không được nói không được xuất hiện do tool “gợi ý”. Ground truth chỉ
  nằm ở test scorer, không đưa vào extractor.
- [x] Run `.venv/bin/python -m pytest eval_harness/test_trace_extraction.py -q`;
  FAIL. Implement phân đoạn/negation/phạm vi lời nói, không suy truth từ
  tool. Giữ mọi claim có thể kiểm chứng; field scorer không biết vẫn không
  được xem là “đúng”. Không đổi reference scorer hoặc scenario để ghi điểm.
- [x] Rerun focused file; PASS. Ghi mapping field và giới hạn generic promo
  trong `eval_harness/README.md` ở Task 9; không công bố HR thấp hơn như
  tiến bộ agent chỉ vì đổi cách trích claim.

## Task 7: Opening và prompt tổng quát cho khách quay lại

**Files:** sửa `app/agent/harness/brief_opening.py`,
`app/agent/implementations/business_agent.py`, `app/agent/harness/context.py`
nếu cần nối trạng thái resolved; tạo `test/test_returning_opening.py`;
test hiện có `test/test_business_completion.py`, `test/test_managed_prompts.py`.

**Interfaces:** giữ `build_suggested_opening(...) -> str`; không thêm yêu
cầu API. Current customer request vẫn là ưu tiên cao hơn suggested opening.

- [x] Test returning customer có profile đã biết: câu nhắc giải pháp là
  khẳng định; câu hỏi chỉ hỏi blocker đang mở; resolved blocker không bị
  hỏi lại. Đổi nhu cầu/sản phẩm/người quyết định/cách nói, không cố định
  “hỏi chồng”. Khách yêu cầu mua được mock model tiếp tục tool create thay
  vì chèn câu hỏi thăm dò mới.
- [x] Run `.venv/bin/python -m pytest test/test_returning_opening.py -q`;
  FAIL. Implement opening ngắn với trạng thái đúng. Prompt ghi quy tắc
  hồ sơ đã biết/blocker/metadata tổng quát; bỏ ví dụ SKU cụ thể và khuyến
  nghị vượt ngân sách vô điều kiện trong đường prompt đang sửa. Quyết định
  sản phẩm dựa thuộc tính catalog và ràng buộc thực của khách.
- [x] Mock prompt loader để biết local fallback và production prompt nào
  được dùng. Không gọi/publish Langfuse từ xa; nếu prompt production chưa
  được cập nhật, ghi rõ artifact draft/local chưa có hiệu lực production.
- [x] Run `.venv/bin/python -m pytest test/test_returning_opening.py test/test_business_completion.py test/test_managed_prompts.py -q`;
  PASS. Extraction Task 3 phải phân loại đúng câu opening mới và paraphrase.

## Task 8: Fact thiếu, admission và ý nghĩa diagnostic memory

**Files:** sửa có căn cứ `app/agent/memory/langmem_extractor.py`,
`app/mcp_servers/mcp_memory/services/langmem_admission.py`,
`app/mcp_servers/mcp_memory/distiller_worker.py`; sửa
`eval_harness/memory_recall.py`; test `test/test_langmem_extractor.py`,
`test/test_langmem_admission.py`, `test/test_structured_episode_memory.py`,
`eval_harness/test_eval_harness.py`.

**Interfaces:** giữ `extract_candidates(model, turns, existing, open_items=None)`
và `admit_profile_candidates(customer_id, session_id, candidates, committed_turns, tool_calls)`.
Giữ shape các count trong `evaluate_memory_recall`; thêm mô tả vào `notes`
đã có, không tạo metric mới. `_slot_value_matches` chuẩn hóa free text với
negation/chủ thể đúng nghĩa, không fuzzy SKU/tiền.

- [x] Lần theo một fact thiếu bằng committed input → proposals → rejection
  → accepted writes nếu artifact/diagnostic có; chỉ dùng read-only dữ liệu
  đã che PII. Thiếu bằng chứng lịch sử thì ghi không xác định, không suy ra
  nguyên nhân. Tái hiện độc lập failure invalid proposal suppresses valid
  supplement bằng fake manager, không gọi model.
- [x] Test candidate sai turn/source/evidence không chặn ứng viên bổ sung
  hợp lệ cùng slot; candidate hợp lệ không bị ghi thêm duplicate. Test hai
  price khác thật đều có evidence được xử lý như conflict, không âm thầm
  chọn giá thuận lợi. Source/customer khác không được admit.
- [x] Test blocker có/không dấu và alias “ông xã/chồng” đúng nghĩa khớp;
  “đã hỏi/không cần hỏi” không khớp “cần hỏi”, vợ khác chồng. Giữ blocker
  open/resolved qua call, không thay “cân nhắc” bằng “so giá” theo nhãn.
- [x] Test order ID động chỉ hợp lệ theo tool link; expected ID khác không
  tự khớp. `written` vẫn là số slot/call đã quan sát, extra hợp lệ không bị
  xóa. Repeated value khác scope/ngày vẫn giữ provenance; revision/retry
  không làm sống lại dữ liệu bị xóa. `channel` giữ metadata, alternative
  chưa tư vấn không được bịa để tăng recall.
- [x] Run `.venv/bin/python -m pytest test/test_langmem_extractor.py test/test_langmem_admission.py test/test_structured_episode_memory.py eval_harness/test_eval_harness.py -q`;
  xác nhận failures mới. Chỉ sửa tầng đã tái hiện: supplement dựa candidate
  có source/evidence hợp lệ của latest turn, không dựa mỗi key xuất hiện;
  admission vẫn là quyết định cuối. Không thêm sync long-term write hoặc
  bỏ admission. Không thay compaction/TTL nếu không có lỗi được chứng minh.
- [x] Rerun cùng focused command; PASS. Cập nhật diagnostic notes: expected
  slots không đầy đủ, mismatched ID/ground truth vẫn là discrepancy. Báo
  rõ fact nào được chứng minh đã sửa và fact nào chưa truy được nguyên nhân.

## Task 9: Re-extract offline và báo cáo giới hạn

**Files:** tạo `eval_harness/reextract_trace.py`,
`eval_harness/test_reextract_trace.py`; sửa `eval_harness/README.md`.

**Interfaces:** `reextract_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]`
chỉ tạo lại `questions/claims`. CLI:
`.venv/bin/python -m eval_harness.reextract_trace --input <trace.jsonl> --output <new-trace.jsonl>`.
Từ chối overwrite file tồn tại hoặc output trùng input. Không import runtime,
DB gateway, model builder hoặc gọi official run/reset.

- [x] Test input không bị mutate; chỉ questions/claims thay đổi, agent_text,
  user text, tools/results, writes, facts_used, latency giữ nguyên. Giữ
  config, scenario/call/turn, thứ tự và coverage. Từ chối JSONL hỏng/duplicated
  turn/overwrite; không tự mask lại dữ liệu hoặc bỏ lượt hỏng để chạy tiếp.
- [x] Test rõ facts_used không thể tái tạo đáng tin từ public trace cũ vì
  thiếu snapshot profile/provenance: giữ nguyên và ghi giới hạn. Thay đổi
  CCR adapter chỉ được chứng minh bằng Tasks 4/8 hoặc run mới được cho phép.
- [x] Run `.venv/bin/python -m pytest eval_harness/test_reextract_trace.py -q`;
  FAIL. Implement CLI dùng extractor hiện tại; validate schema/coverage
  với tùy chọn `--scenarios <dir> --btc-root <dir> --config <config>` cung
  cấp cùng nhau qua `eval.trace_audit.audit_trace(scenarios_dir, trace_path,
  expected_config, btc_root)`, chỉ đọc utility, không sửa validator. Khi
  không có ba tùy chọn này, kiểm JSONL/unique keys/thứ tự và bảo toàn tập
  lượt đầu vào; ghi rõ chưa audit exact scenario coverage. Validate trước
  và sau re-extraction, lỗi thì không để lại output hoàn chỉnh. Validation
  không biến replay thành official run hay sửa manifest/hash run gốc.
- [x] Rerun file mới; PASS. Dùng CLI cho FULL và baseline gốc vào thư mục
  ignored mới `eval_harness/results/<run-id>/offline-reextract-<timestamp>/`.
  Hash input trước/sau phải bằng nhau. Không score “agent sau sửa”.
- [x] Ghi README: mapping question/claim, generic promo mismatch SC02,
  baseline RQR 0 giữ relative reduction null và verdict BTC gốc, recall/
  precision nội bộ là expected-slot diagnostic. Giữ nguyên run gốc và toàn
  bộ score chính thức; không sửa dashboard/official_pipeline/knowledge flow.

## Task 10: Rà soát chống overfit và kiểm chứng cuối

**Files:** progress của Task 0 và diff của toàn bộ file đã sửa; không thêm
chức năng. Tự review, không dispatch reviewer/sub-agent.

- [x] Lập mapping spec → Task/test và xác nhận mỗi lớp lỗi có ca ngoài sample,
  cặp chấp nhận/chặn, đổi tên/giá/ngày và đảo điều kiện nghiệp vụ. Rà diff
  code/prompt tìm SKU/giá/câu mẫu/ID; phân biệt constants nghiệp vụ có nguồn
  với nhánh chữa riêng sample. Không chỉ dùng search thay code review.
- [x] Kiểm tra schema/trace preservation, PII/customer/erasure contracts và
  thay đổi Knowledge Gap Loop có sẵn không bị ghi đè. Nếu có failure mới
  do integration, sửa tối thiểu rồi chạy focused file liên quan.
- [x] Chạy full regression đúng một lần:
  `.venv/bin/python -m pytest test eval_harness/test_eval_harness.py`.
  Kỳ vọng PASS; recorded skip không được báo là đã kiểm DB. Các test eval
  file khác đã được kiểm focused ở task sở hữu; không chạy full lần hai.
- [x] Nếu full có failure: ghi rõ kết quả lần chạy, chỉ chạy focused tests
  cho failure sau khi sửa; không lặp full. DB integration có side effect
  chỉ chạy trong môi trường được phép, không tự reset/provision.
- [x] `git diff --check`; review final diff và progress; báo changed behavior,
  test commands/results, giới hạn replay, prompt production còn chưa áp
  dụng nếu có, cùng phần memory chưa đủ dữ liệu truy nguyên.
- [x] Dừng ở bàn giao implementation offline. Không tuyên bố pass private
  hoặc ngưỡng BTC; live FULL/baseline và thao tác DB cần yêu cầu riêng.

## Bao phủ spec và điều kiện bàn giao

| Spec | Task/test sở hữu |
| --- | --- |
| 2, 2.1: scope/chống overfit | Global Constraints, mọi task, review Task 10 |
| 3: biến thể và order | Task 1 |
| 4: phản hồi side effect và fallback | Task 2, kiểm integration sau Task 5 |
| 5: quyền lợi ưu đãi | Task 5 |
| 6: khách quay lại/blocker | Task 7 và extraction Task 3 |
| 7.1: câu hỏi/claim | Tasks 3, 6 |
| 7.2: session/scope/carryover | Task 4 |
| 7.3, 8: diagnostic, missing fact | Task 8, ghi giới hạn Task 9 |
| 9–11: interfaces/xác minh/handoff | Tasks 0, 9, 10 |

Plan không giả định có thể tái dựng rejected draft hoặc profile snapshot từ
trace cũ. Kết quả live và nguyên nhân lịch sử thiếu evidence là giới hạn
được giữ công khai, không là chỗ trống để implementer bịa dữ liệu.

**Handoff:** người dùng yêu cầu lập plan; chưa bắt đầu implementation trong
lượt viết tài liệu. Khi triển khai theo yêu cầu tiếp theo, dùng inline
`executing-plans`, giữ các ràng buộc không sub-agent/worktree/commit và
không tự chạy live eval.

## Assertions tối thiểu để khóa các contract chính

Các ví dụ là assertion cần có trong task tương ứng; dữ liệu synthetic của
task phải tự dựng theo schema, không import đáp án scenario BTC.

```python
# Task 1: metadata chưa biết khác với sản phẩm không có variant.
selection = resolve_product_selection(state_without_catalog, {"sku": "ITEM-A"})
assert selection.status == "catalog_required"
assert selection.sku is None

# Task 3: nhắc trẻ em không biến câu hỏi tiến độ thành hỏi hồ sơ.
questions = extract_questions(
    "Mẫu này có khóa trẻ em. Mình đã bàn với người nhà xong chưa ạ?"
)
assert [(q["slot"], q["type"]) for q in questions] == [("blocker", "open")]

# Task 4: nguồn cùng session không được tính carryover.
assert _source_session_id("langmem:session-now:turn-1") == "session-now"
assert facts_used(
    "Mình đang xem ITEM-A.", [],
    {"product_advised": {"value": "ITEM-A", "source": "langmem:session-now:turn-1"}},
    current_session_id="session-now",
) == []

# Task 6: quote không được sửa điều agent thực sự đã nói.
assert extract_claims(spoken_offer, real_gift_quote) == extract_claims(
    spoken_offer, freecod_only_quote
)

# Task 9: artifact gốc không đổi, không tái tạo facts_used từ dữ liệu thiếu.
new_rows = reextract_rows(original_rows)
assert original_rows == original_copy
assert [r["facts_used"] for r in new_rows] == [r["facts_used"] for r in original_rows]
```
