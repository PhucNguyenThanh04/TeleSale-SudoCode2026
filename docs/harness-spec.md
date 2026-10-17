# Harness text: trạng thái và bằng chứng

Cập nhật: 2026-10-15. Đây là thiết kế mục tiêu, không phải cam kết rằng code hiện tại đã triển khai đủ. Nguồn BTC: `../BTC-Data-Vong1-TEAMS` tính từ gốc repo; có thể chỉ định `BTC_DATA_DIR` khi chạy dataloader.

## Luồng mỗi lượt

`TextTurnRequest` → runtime khởi tạo danh tính phiên khi cần → `accept` → `retrieve_context` → `run_agent` (Deep hoặc ReAct; gọi tool theo precondition) → `verify` → `persist` → một câu trả lời cuối. Runtime khóa theo `session_id`, dùng lại danh tính cho các lượt tiếp theo trong cùng worker và từ chối đổi channel hoặc channel identity. Khi worker khởi động lại hoặc phiên chuyển worker, CRM được tra lại một lần; backend vẫn giữ định danh phiên trong PostgreSQL. Đây là luồng hiện tại; các bước stage/slot bên dưới là thiết kế mục tiêu.

- LLM đề xuất ý định, slot, câu nói và hành động; code xác nhận giá trị, resolve SKU với catalog và chặn tool không đủ điều kiện. Không đưa nhãn `facts_established`, `ground_truth_facts`, `success_if` của kịch bản vào runtime.
- Stage gợi ý: `IDENTIFY`, `DISCOVER`, `RECOMMEND`, `OBJECTION`, `CLOSE`, `WRAPUP`; `RETURNING` và `AFTER_SALES` là nhánh. Cho phép đi lùi hoặc đổi nhánh khi khách đổi ý. Stage không thay điều kiện cụ thể của từng tool.
- Mỗi slot có `value`, nguồn (lượt/phiên/tool), ngày quan sát, trạng thái xác nhận và hiệu lực. Memory phân biệt lời khách, kết quả tool có ngày/hạn, và cam kết agent có trạng thái thực hiện; cập nhật fact phải supersede giá trị cũ.
- Diện tích, ngân sách, nhu cầu, sản phẩm từng tư vấn, blocker và giá **từng báo** là lịch sử có thể mang sang phiên. Giá từng báo lưu cùng SKU, `quoted_on`, `promo_code`/`promo_expiry` khi có; đầu call sau luôn lấy quote mới theo `on`, kể cả khi không có KM. Tồn kho, giá hiện tại, KM, freeship, SKU còn bán, chính sách và ngày giao phải xác minh lại trước khi khẳng định hoặc hành động.
- Định danh xuyên kênh dùng mapping CRM giữa phone/FB/Zalo và `customer_id`. Số dùng chung hoặc mapping thiếu phải được xử lý như mơ hồ. Không lấy `customer_phone` ở metadata chấm làm bằng chứng danh tính nếu request thực không cung cấp.

## Điều kiện gọi tool và câu trả lời

- `order.create`: khách đã muốn đặt; danh tính và phone đủ tin cậy; SKU/biến thể có trong catalog; tồn kho và quote đúng SKU, số lượng, vùng/giỏ và ngày gọi; payment đã biết. `price_vnd` là giá một đơn vị sau KM. Khi đủ điều kiện, gọi ngay trong lượt khách nói “lên đơn”; sau `status: created` mới đọc lại đơn và `order_id` từ tool. Không mặc định COD khi khách chưa nêu hoặc chưa có quy tắc được công bố. `address` tùy chọn theo BTC, nhưng không được bịa địa chỉ hay hứa giao đến nơi cụ thể nếu thiếu.
- `order.update`: cần đúng order của khách; resolve variant mới qua catalog và kiểm tồn kho/ngày, chính sách đổi trả theo ngày tạo đơn. `schedule.callback` chỉ tạo khi khách đồng ý thời điểm. `handoff.transfer` chỉ báo chuyển máy khi có ticket ID.
- Có thể song song hóa các truy vấn đọc độc lập sau khi biết SKU/ngày; không song song hóa các bước phụ thuộc như quote → tạo đơn → ghi liên kết order. Mỗi lượt khách có đúng một phản hồi cuối.
- Prompt chỉ gồm quy tắc cố định, state/slot còn thiếu, Call Brief/fact kèm nguồn và ngày, kết quả tool mới nhất và vài lượt gần nhất. Nạp chính sách khi intent cần; không đưa dữ liệu nội bộ hay PII thô vào prompt.
- Kiểm claim về tiền, ngày, tồn kho, KM, phí, chính sách, giao hàng và trạng thái đơn với bằng chứng hiện hành. Nếu lệch, sinh lại có giới hạn rồi fallback an toàn. Không hỏi mở lại slot đã biết; xác nhận lần nữa trong cùng call chỉ khi thực sự cần.
- ASR/teencode: ITN cho số/đơn vị/thời gian; grounding tên sản phẩm vào catalog alias/variant; độ tin cậy thấp thì hỏi làm rõ. Dùng `asr/ground_truth.json` của BTC cho quy tắc WER/CER/Entity Accuracy. Raw và normalized trong trace/log đều phải mask PII.

## Ranh giới PII và địa chỉ

- Địa chỉ giao hàng là dữ liệu nghiệp vụ cần thiết cho order nhưng không thuộc prompt, vector store hoặc checkpoint. Thiết kế mục tiêu: prompt thấy `address_ref` hoặc bản che; node gọi tool lấy địa chỉ thật từ kho nghiệp vụ bằng ref sau khi xác thực khách, truyền cho tool và không ghi thô vào trace. Chưa có cơ chế `address_ref` trong code; khi triển khai phải thêm kiểm tra quyền sở hữu và TTL địa chỉ, không giả vờ đã có.
- Nếu khách nói “địa chỉ cũ” mà CRM/đơn trước không có địa chỉ đáng tin cậy, không bịa. Hỏi khi cần hoàn tất giao hàng; không biến `address` thành tham số bắt buộc của tool BTC.

## Chính sách M1

- M1 dùng `policy.search` trong `mcp-catalog`, đọc `btc_source.policy_chunks` với quyền `SELECT` của role `mcp_catalog`. PostgreSQL lọc quyền `public` và hiệu lực theo ngày trước khi service xếp hạng từ khóa. Với đơn cũ, harness chỉ truyền `order_date` lấy từ kết quả `order.status` đã xác minh. Qdrant/semantic ranking chưa nối vào runtime.
- Lọc `access_level=public` trước khi đưa nội dung cho model. Dùng đúng metadata `effective_from`, `effective_until`, `date_basis`: `call_date` cho chính sách hiện hành theo cuộc gọi; `order_date` cho đổi trả/bảo hành của đơn cũ. Sau lọc mới xếp hạng/chọn chunk. Nếu không có nguồn hợp lệ thì nói chưa đủ thông tin.

## Eval

- Dùng cùng service nghiệp vụ cho demo và eval. Checkout hiện thiếu package `eval/` mà `run_eval.py` import; cần khôi phục runner trước khi chạy chấm public sample đa phiên.
- Chấm cả hai cấu hình trên cùng model/tool/dữ liệu; baseline chỉ bỏ nạp memory từ phiên trước. Dùng trace thật và `reference_eval.py` kiểm `must_not_ask`, `must_carry_over`, `success_if`, `ground_truth_facts`, memory writes và guardrail. Không sửa lời agent/trace theo nhãn đáp án.
