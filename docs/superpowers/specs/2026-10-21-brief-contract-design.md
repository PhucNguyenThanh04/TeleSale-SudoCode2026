# Call Brief và handoff brief cho harness text-to-text

Ngày 2026-10-21. Thiết kế này ghi lại phạm vi người dùng đã duyệt trong trao
đổi: **kiểm chứng riêng hai brief → sửa handoff brief thông thường → sửa Call
Brief → kiểm rộng harness văn bản**. Mục tiêu là đáp ứng BTC và tăng độ vững
trước test ẩn, không tối ưu theo câu chữ của public sample.

## Mục đích và giới hạn

- Đầu vào là lượt chat/transcript **đã ở dạng text**; agent tiếp tục dùng
  LangGraph, PostgreSQL memory và ba MCP hiện có. Không nối ASR, thêm UI hoặc
  đổi model trong đợt này.
- `schemas/call_brief.schema.json` và `schemas/handoff_brief.schema.json` của
  BTC quy định hình dạng; `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md` quy định
  thời điểm tạo, cách tính latency và điều kiện chấm chuyển máy. `mock_tools.py`
  quy định kết quả tool. Public sample chỉ là ca hồi quy.
- Không đọc nhãn đáp án hay `scenario_id` trong runtime. Giữ mọi điều kiện của
  khách, nguồn fact, ngày nghiệp vụ `on` và ranh giới danh tính/PII hiện có.

## Hành vi cần đạt

1. Một bộ kiểm tra riêng nhận **output thật của hàm tạo brief/tool call**,
   đối chiếu BTC JSON Schema, bằng chứng trong state và các ca biến thể. Ghi
   baseline đỏ trước khi sửa. Ca đối chứng gồm khách mới/không rõ danh tính,
   yêu cầu bình thường không chuyển máy và handoff thiếu số tin cậy.
2. Handoff thông thường không tin nguyên `brief` do LLM tạo. Harness dùng đề
   xuất của model cho ý định chuyển và lý do, rồi dựng/kiểm brief từ turn hiện
   tại, fact đã xác nhận, episode và kết quả tool. `customer_phone`, tên/ID,
   SKU, giá, KM, ngày và nguồn không được model tự khai. Với nhiều SKU không
   xác định được mẫu đang bàn, trường `product_advised`/giá để `null`; tóm tắt
   vẫn giữ các sản phẩm đã biết. Tóm tắt, câu hỏi chưa giải đáp và bước tiếp
   theo giúp người nhận tiếp tục cuộc trò chuyện, không hỏi lại từ đầu.
3. MCP order kiểm **giá trị** của handoff brief theo contract trước khi lưu và
   tạo ticket, không chỉ kiểm tên trường. Harness chỉ báo chuyển thành công khi
   tool trả `status=queued` và `ticket_id` hợp lệ. Yêu cầu xóa dữ liệu vẫn chỉ
   được chuyển tiếp, không tuyên bố đã xóa.
4. Call Brief chỉ tạo cho khách quay lại đã nhận diện chắc chắn. Nó hiển thị
   lịch sử sản phẩm/phòng riêng, báo giá cũ là lịch sử, `quoted_on` từ fact,
   `promo_still_active` chỉ khi được kiểm lại theo `request.on`, và cảnh báo
   khi chưa kiểm được. `must_not_ask`, rào cản, câu mở đầu và hành động tiếp
   theo phải dựa trên fact hiện có; không đọc vẹt toàn bộ hồ sơ. Số phiên trước
   là số phiên khác nhau đã biết, không phải độ dài danh sách tóm tắt bị cắt.
5. `latency_ms` của Call Brief bao gồm nhận diện CRM, đọc DB và kiểm tra tính
   mới trước khi brief sẵn sàng. Nếu phần episode đã tính ở phiên trước thì
   `precomputed_parts` khai báo đúng; phần refresh vẫn tính trong latency.
6. Cuối đợt, chạy contract/unit/mock cho các ca trên và một lượt kiểm harness
   **text-to-text** với cùng tool/model/dữ liệu khi môi trường cho phép. Báo
   riêng điều đã kiểm bằng fake model, BTC mock, MCP HTTP và LLM thật. Không
   coi điểm public sample là đặc tả của test ẩn.

## Điều không thuộc đợt này

ASR/voice, UI, quy trình xóa dữ liệu thật xuyên mọi kho và tính năng nổi bật
khác. Không mở rộng quy mô eval toàn hệ thống trước khi hai brief đạt contract.
