# Cải thiện khối Memory để phục vụ Brief tốt nhất

Nguồn: các lượt kiểm toán trong chat này (đọc [`langmem.py`](ai-services/app/schemas/langmem.py), [`brief.py`](ai-services/app/schemas/brief.py), [`constants.py`](ai-services/app/constants.py), [`context.py`](ai-services/app/agent/harness/context.py), [`memory.py`](ai-services/app/mcp_servers/mcp_memory/services/memory.py), [`langmem_admission.py`](ai-services/app/mcp_servers/mcp_memory/services/langmem_admission.py), [`distiller_worker.py`](ai-services/app/mcp_servers/mcp_memory/distiller_worker.py), [`deterministic_tool_facts.py`](ai-services/app/agent/memory/deterministic_tool_facts.py), [`episode_state.py`](ai-services/app/mcp_servers/mcp_memory/services/episode_state.py), [`episode_summary.py`](ai-services/app/mcp_servers/mcp_memory/services/episode_summary.py)) đối chiếu với `BTC-Data-Vong1-TEAMS`.

## 0. Đính chính báo cáo lượt trước

Sau khi đọc lại `distiller_worker.py`, hai ý của lượt trước **không đúng**:

| Ý đã nói | Thực tế |
|---|---|
| Tool facts (`product_advised`, `price_quoted_vnd`...) bị rớt ~100% vì prompt LangMem không nhắc | Worker lọc fact `source_kind=tool` của LLM (dòng 107) rồi thêm `verified_tool_candidates(...)` (dòng 108) và `verified_order_details` cho `order.create`. Đường deterministic **có tồn tại**. |
| Chỉ turn hiện tại có `tool_calls`, các turn trước mất | Mỗi turn có job riêng và `tool_observations` của chính nó; LLM còn được xem cửa sổ 5 turn gần nhất. Không phải lỗi. |
| `summary` episode là nối thô 3 lượt cuối | Summary được dựng từ `topics` (mục tiêu, đã tư vấn, bước tiếp theo, rào cản mở) + trích dẫn bằng chứng. |

Ngoài ra, `enabled_public_full.jsonl` (trace `memory_writes=[]` cho tool facts) có thể **cũ hơn** code hiện tại, vì working tree đang có nhiều thay đổi chưa commit. Cần chạy lại benchmark trước khi kết luận nguyên nhân tool facts không được ghi. Chưa đọc [`reported_facts.py`](ai-services/app/agent/memory/reported_facts.py), nhưng tên hàm `reported_tool_candidates(agent_text, calls)` gợi ý fact chỉ được ghi khi agent *nói ra* trong câu trả lời.

Một kết quả test mình chưa nêu rõ: khi chạy `test_memory_postgres_integration.py`, `test_mixed_session_keeps_anonymous_turn_and_marks_unowned_pending` **FAIL** (`'completed' != 'partial'`). Test này thuộc luồng xóa dữ liệu của memory và chưa được điều tra.

## 1. Các lỗ hổng đã xác minh bằng code (ảnh hưởng trực tiếp tới brief)

| # | Vấn đề | Bằng chứng | Ảnh hưởng tới brief |
|---|---|---|---|
| 1 | `CallBrief.orders` luôn rỗng; đơn hàng không vào `prompt_context` | `load_context` tạo `CallBrief(...)` không truyền `orders`; `prompt_context` không có `remembered_order_ids` | SAMPLE-03 (đổi size), TRADE-IN-AP (khách có `SKU-AP-X-2024`), `order.status` |
| 2 | Rào cản không bao giờ được đóng | `admit_episode_candidate` chỉ sinh `add_items`, không bao giờ sinh `resolve_items`, dù `apply_episode_delta` hỗ trợ | SAMPLE-01 call_2 ("ông xã đồng ý rồi") vẫn bị brief liệt kê là blocker |
| 3 | Rào cản/mục tiêu bị loại nếu không là chuỗi con nguyên văn của lời khách | `blocker.casefold() in source.casefold()` ở `langmem_admission.py` dùng cùng một chuỗi làm `text` và `evidence_quote` | LLM chuẩn hóa "cần hỏi chồng" bị bỏ, brief mất blocker. `apply_episode_delta` vốn đã tách `text` khỏi `evidence_quote` |
| 4 | Phần lớn trường episode LLM đề xuất bị bỏ | `products_discussed`, `quoted_prices`, `actions_completed`, `topics` không được đọc; `advice_given`, `next_step` có trong state nhưng admission không bao giờ điền | `summary` thiếu "đã tư vấn gì / bước tiếp theo" |
| 5 | Topic luôn mang `scope_type="unknown"` | `langmem_admission.py` dòng 86 | `rank_episodes` (so khớp `scope_type=="product"`) không bao giờ khớp |
| 6 | `valid_until` không được lưu | `put_facts` không copy trường này vào store | Không có TTL cho địa chỉ/khuyến mãi |
| 7 | Không có cảnh báo phiên cũ / SKU ngừng bán | `load_context` chỉ kiểm tồn kho, giá, KM | SC12 (khách quay lại sau 8 tháng), FAQ-16 (`successor_sku`) |
| 8 | Không làm tươi khi có ≥2 sản phẩm | `refresh_skus` chỉ lấy `advised` khi `len(scoped_products)<=1`, hoặc SKU được nhắc trong câu | SC11 (4 sản phẩm): brief ghi "Chưa kiểm tra lại giá..." |
| 9 | Làm tươi tuần tự | Vòng `for` gọi `inventory.check` rồi `pricing.get_quote` lần lượt từng SKU | Latency tăng tuyến tính theo số SKU |
| 10 | `must_not_ask` chỉ có 4 slot | `brief_must_not_ask=True` chỉ cho `room_area_m2`, `budget_vnd`, `has_children`, `product_advised` | BTC chấm 10 slot: thiếu `price_quoted_vnd`, `competitor_price_vnd`, `order_id`, `size/color`, `payment` |
| 11 | `_PRODUCT_KEYS`/`_ROOM_KEYS` quá hẹp | `memory.py` dòng 19-21 | Không lưu `size`, `color`, `blocker`... theo từng sản phẩm; `has_children` theo từng phòng |
| 12 | `suggested_opening` là một mẫu câu cố định | `context.py` dòng 356 | Chỉ nhắc 1 điểm, không gọi tên/xưng hô, không dùng `outcome`; PB-01 yêu cầu xác nhận tối đa 2 thông tin (sản phẩm + rào cản) |

## 2. Đề xuất theo mức ưu tiên

### P0: sửa trực tiếp những gì brief đang thiếu
1. **Điền `orders`**: đọc `owned_order_ids` + đơn trong CRM (`crm.get_customer`), thêm `variant_sku`/`status`; đưa vào `prompt_context`. Đơn đang giao thì có thể gọi `order.status`.
2. **Vòng đời blocker**: cho schema episode nhận `{text, evidence_quote}` thay cho `list[str]`; sinh `resolve_items` khi khách/agent xác nhận đã giải quyết; brief chỉ hiển thị item `open`.
3. **Thay phép kiểm tra chuỗi con** bằng `evidence_supports(text, quote)` (đã có trong `episode_state.py`) và yêu cầu quote nằm trong lời khách.
4. **Gán scope đúng cho topic**: suy từ SKU của tool call cùng turn (`scope_type="product"`), chỉ để `unknown` khi không có.
5. **Mở rộng `must_not_ask`** cho các slot BTC thực sự kiểm tra (xem bảng ở lỗ hổng 10).
6. **Ghi tool facts độc lập với lời agent** nếu đúng là `reported_*` đang phụ thuộc `agent_text` (cần xác nhận trước bằng cách đọc `reported_facts.py`). Phân biệt `looked_up` với `quoted_to_customer` để không nhớ nhầm sản phẩm chỉ mới tra cứu.

### P1: chất lượng brief
7. Lưu `valid_until`; thêm `stale_warnings` khi phiên trước > ~180 ngày (xác nhận lại địa chỉ), khi SKU `discontinued` (nêu `successor_sku`), khi KM hết hạn.
8. Làm tươi tối đa 3 SKU gần nhất bằng `asyncio.gather`, thay vì chỉ khi 1 sản phẩm.
9. Sinh `suggested_opening` theo `outcome` + hai thông tin (sản phẩm, blocker) dưới dạng câu xác nhận, có tên/xưng hô; không nhắc lại giá khi KM đã hết hạn.
10. Nới `_PRODUCT_KEYS`/`_ROOM_KEYS` (`size`, `color`, `preferred_*`, `blocker`, `objection` cho product; `has_children`, `product_advised` cho room).
11. Thêm slot **được kịch bản BTC dùng thật**: `owned_sku`, `region`, `callback_scheduled`, `alt_suggested`, `phone_provided`. Các slot suy từ `policy/` như `water_source`, `has_pets`, `foot_length_cm`, `baby_weight_kg` mới chỉ là suy đoán, chưa có kịch bản nào dùng, nên để sau.

### P2: độ bền và đo lường
12. **Bộ nhớ đồng bộ mức tối thiểu**: hiện ghi fact/episode đồng bộ bị tắt, nên nếu khách gọi lại trước khi job LangMem xong thì brief trống. Ghi đồng bộ các fact deterministic (tool facts, `customer_slot_cues`) rồi để LangMem làm giàu sau.
13. **Nén phiên bản**: store append-only theo `revision`; mỗi lần đọc quét toàn bộ phiên bản và mở kết nối mới. Cần compaction để chi phí đọc không tăng theo số job.
14. **Đo trực tiếp chất lượng memory**: các kịch bản `SC*` đã có `facts_established`; thêm test so sánh nội dung store sau `call_1` với `facts_established` (recall/precision theo slot). Hiện CCR chỉ gián tiếp đo qua `facts_used` nên khó biết lỗi nằm ở ghi hay ở đọc.
15. Điều tra test `test_mixed_session_keeps_anonymous_turn_and_marks_unowned_pending`.

## 3. Cách kiểm chứng sau khi sửa
1. Chạy lại `eval_harness` trên `SAMPLE-01..07` và `SC01..SC19`, so `memory_writes` với `facts_established`.
2. So sánh `CCR`, `RQR`, `must_not_ask` và nội dung `CallBrief` (đặc biệt `orders`, `open_blockers`, `stale_warnings`) trước/sau.
3. Đo `call_brief_latency_ms` với 1, 3 và 4 SKU để chắc việc làm tươi song song không làm xấu p95.
