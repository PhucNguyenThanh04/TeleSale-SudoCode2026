# Quy trình rà soát MCP tools (2026-10-30)

## Phạm vi và trạng thái kiểm tra

Ba server đăng ký 12 business tools và `eval.database_identity` trên từng server.
Đã đọc đường đi từ handler, schema, service, repository đến gateway và ngữ cảnh agent;
đã chạy bộ test `python -m pytest test eval_harness/test_eval_harness.py -q`
(342 passed, 16 skipped). Kết quả này xác nhận regression hiện tại, chưa xác nhận các
tool hoạt động đúng với PostgreSQL thật hoặc dưới tải thực tế.

| Server | Tool | Kết quả đọc mã và test hiện có | Việc cần xác minh thêm |
| --- | --- | --- | --- |
| Catalog | `crm.get_customer` | Có kiểm tra identity; trả cả orders và sessions | Giới hạn kích thước, kiểm tra dữ liệu nhiều đơn/phiên, trùng identity |
| Catalog | `catalog.search` | Có lọc và giới hạn 20 sản phẩm; test đối chiếu BTC | Đo token đầu ra, thuộc tính/variants dài, phân trang hoặc chọn trường |
| Catalog | `inventory.check` | Có kiểm tra ngày và SKU; test đối chiếu BTC | Ngày ranh giới, biến thể, hết hàng và restock |
| Catalog | `pricing.get_quote` | Giá/khuyến mãi dùng chung với `order.create`; test đối chiếu BTC | Đo context cả lượt; xem danh sách promo không áp dụng và tính nhất quán với đơn |
| Catalog | `policy.search` | SQL lọc public/ngày, retrieval chọn tối đa 5 chunk; có test | Giới hạn độ dài body, chính sách dài, ngày tạo đơn |
| Order | `order.create` | Có identity, tồn kho, giá hiện hành, payment, idempotency | Giao dịch đồng thời, khuyến mãi dùng một lần, retry qua HTTP |
| Order | `order.status` | Có kiểm tra sở hữu; trả toàn bộ đơn khi tìm theo phone | Giới hạn số đơn/trường, thứ tự, đơn cũ và đơn runtime |
| Order | `order.update` | Có kiểm tra sở hữu; một số nhánh kiểm tra kho và tính chênh lệch | Quy tắc đổi/trả theo trạng thái đơn và chính sách, lặp cập nhật |
| Order | `schedule.callback` | Có identity và điều chỉnh thời điểm | Múi giờ, ngày nghỉ, giờ làm việc, callback trùng |
| Order | `handoff.transfer` | Có schema brief và idempotency; có test | Độ dài brief và xác minh hotline với khách chưa có CRM |
| Memory | `memory.read` | Có ràng buộc chủ phiên, `max_episodes` tối đa 20 | Kích thước history, facts, topics, `prior_session_ids` dài |
| Memory | `memory.write` | Có xác minh fact, replay và một số giới hạn input | Dữ liệu `data` lớn, xung đột đồng thời, mất kết nối khi commit |
| Cả ba | `eval.database_identity` | Gateway chỉ giữ database/host/port; có test | Chỉ mở cho môi trường eval, kiểm tra auth trên HTTP thật |

## Phát hiện ưu tiên

Log test tay lúc 15:49 cho thấy hai lần `pricing.get_quote` được gọi bằng tên
(`AirPure X`, `Xiaomi Smart 4 Lite`) và nhận `unknown_sku`. Sau đó
`catalog.search` trả 16 mục, rồi graph báo `GraphRecursionError`. Đây là lỗi
quy trình gọi tool và giới hạn vòng agent; log không cho thấy quote thành công
hay lỗi context window. Đã thêm chặn tên sản phẩm trước MCP và ngừng cấp tool
cho model khi hết ngân sách của lượt; cần chạy lại đúng ca này trên môi trường
có MCP/LLM để xác nhận kết quả thực tế.

1. **Nguy cơ context chủ yếu ở các kết quả tích lũy và kết quả tìm kiếm rộng.**
   Với dữ liệu BTC mẫu (40 sản phẩm, 13 khuyến mãi), quote lớn nhất trong ba ngày
   được đo là 514 byte; `catalog.search` không lọc là 10.932 byte cho 20/38 mục.
   `safe_tool_result` che PII nhưng không rút gọn kích thước. `prompt_context`
   đưa tất cả `tool_calls` của lượt hiện tại vào `tool_observations`; model còn nhận
   kết quả tool trong vòng gọi LangChain. Chưa có bằng chứng một quote riêng lẻ
   gây tràn context; cần đo trace của lần test tay để xác định chính xác.
2. **Quote gửi thông tin không cần cho báo giá thông thường.** `expired_promos`,
   `ineligible_promos`, `not_applied_exclusive` được trả cho model cùng giá cuối,
   mặc dù guardrail và tạo đơn dùng `applied_promos`, `final_price_vnd` và
   `freeship`. Giữ chi tiết này ở lớp nghiệp vụ/diagnostic và tạo projection ngắn
   cho model là hướng sửa cần kiểm tra bằng contract test.
3. **Một số response chưa có ngân sách đầu ra.** CRM orders/sessions,
   `order.status` theo phone, `memory.read` history/facts/topics/prior IDs và
   body của `policy.search` có thể lớn theo dữ liệu. Giới hạn số phần tử không
   tương đương giới hạn byte/token.

## Quy trình có thể chạy lại

1. **Kiểm kê:** so tên tool ở `@mcp.tool`, schema, `invoke`, gateway và tool agent.
   Ghi rõ tool nào chỉ dùng nội bộ/eval.
2. **Lập contract từng tool:** input hợp lệ/sai, quyền truy cập, ngày nghiệp vụ,
   dữ liệu nguồn, output tối thiểu cho agent, side effect, idempotency và mã lỗi.
3. **Dựng dữ liệu thử cố định:** SKU thường/variant/ngừng bán; promo áp dụng,
   hết hạn, không đủ điều kiện; khách có nhiều đơn/phiên; policy dài; ẩn danh và
   identity trùng. Không dùng PII thật.
4. **Test các lớp:** service thuần, handler validation, FastMCP qua gateway,
   PostgreSQL test riêng, và một lượt agent. So output với contract BTC và
   kiểm tra không lộ dữ liệu giữa khách.
5. **Đo ngân sách context:** ghi `len(json.dumps(result, ensure_ascii=False))`
   và số token bằng tokenizer của model cho từng response, tổng `tool_observations`
   và toàn bộ messages trong một lượt. Báo p50/p95/max, số call và SKU, không
   ghi raw PII. Kiểm tra lượt có 1, 2, 3 tool và nhiều phiên lịch sử.
6. **Sửa theo bằng chứng:** rút gọn projection gửi model, giữ bản đầy đủ cho
   kiểm tra nghiệp vụ khi cần; đặt giới hạn rõ ràng cho danh sách và body;
   tránh thay đổi contract giá hoặc chính sách khi chỉ tối ưu context.
7. **Gate hoàn thành:** test đỏ/xanh cho từng lỗi, toàn bộ pytest, test HTTP/DB
   với biến môi trường test, rồi chạy lại các kịch bản test tay. Chỉ đánh dấu
   tool hoàn thiện khi output, quyền, side effect, độ dài và đường lỗi đều đạt.

## Thứ tự xử lý đề xuất

P0: thu trace và đo context của ca `get_quote` gây lỗi; kiểm tra tổng số lần gọi
và kết quả `catalog.search`. P1: projection ngắn cho quote/catalog và ngưỡng
byte/token ở agent. P2: các response không có giới hạn và test DB/HTTP cho mọi
tool có side effect. Giữ nguyên dữ liệu chưa commit hiện có trong workspace.
