# Hợp đồng memory đa phiên — bản đã duyệt trong hội thoại

## Mục đích

Chốt hành vi đọc, ghi, thay thế và không tiết lộ memory qua nhiều lượt, nhiều
phiên và nhiều kênh trước khi sửa thêm runtime. Bộ ca tự tạo dùng lời thoại và
sản phẩm khác public sample; sample BTC chỉ là phép kiểm bằng chứng bổ sung.

## Nguồn chuẩn và phạm vi

- `../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md` và `GIAI-DAP-MENTOR.md` ưu tiên
  hơn PDF ở phần đã điều chỉnh. `schemas/tools.schema.json`, `eval/mock_tools.py`
  và `eval/reference_eval.py` lần lượt chuẩn hóa tool, kết quả và phép chấm.
- Ngày mặc định `2026-10-15`, hoặc ngày của từng call; không dùng đồng hồ máy.
- Chỉ dùng dữ liệu tổng hợp. Không đưa nhãn đáp án hay `scenario_id` vào runtime.
- Bước này tạo hợp đồng có thể chạy và báo khoảng cách với code hiện tại. Bản
  sửa runtime theo khoảng cách đó sẽ được lập kế hoạch riêng, theo thứ tự ưu
  tiên. Giữ các test kiểm bằng chứng hiện có.

## Sáu ca bắt buộc

| Ca | Điều phải kiểm |
|---|---|
| Đổi ý giữa cuộc | Giá trị khách sửa rõ ràng thay giá trị cũ; nguồn lượt và thao tác `supersede`/`delete` chính xác. Câu hỏi, giả định hoặc lời nói mơ hồ không sửa fact. |
| Hai người chung số | Khi CRM trả nhiều ứng viên, không nạp profile, episode, Call Brief hoặc đơn của bất kỳ ứng viên nào; chỉ gắn sau bằng chứng xác minh. |
| Fanpage → hotline | Hai định danh tin cậy giải về cùng `customer_id` thì nạp đúng memory xuyên kênh, không hỏi lại slot đã xác nhận. |
| Cuộc dài nhiều sản phẩm | Trong ít nhất 16 lượt và 4 sản phẩm, ràng buộc của khách giữ nguyên; giá, KM, tồn kho và lựa chọn sản phẩm không bị gán nhầm giữa các SKU. Giá đã báo là lịch sử. |
| Quay lại sau nhiều tháng | Thông tin sở thích còn bằng chứng có thể nhắc lại; giá, KM, tồn kho, SKU ngừng bán và địa chỉ cũ không được coi là hiện hành nếu chưa kiểm bằng tool theo ngày mới. |
| Yêu cầu xóa dữ liệu | Agent nhận diện yêu cầu, không khẳng định đã xóa khi chưa có kết quả thao tác có thẩm quyền, không tiết lộ PII và chuyển xử lý đúng quyền. Phạm vi xóa vật lý ở CRM, order, trace và memory cần hợp đồng riêng trước khi triển khai. |

## Tiêu chí nghiệm thu của bước hợp đồng

- Mỗi ca có tiền điều kiện, chuỗi call/turn, danh tính, ngày, trạng thái memory
  sau mỗi lượt và trạng thái không được xảy ra; có ít nhất một biến thể ngoài
  sample và một đối chứng không được đổi hành vi.
- Test lớp memory/harness và phép kiểm trace dùng kết quả thực của mock BTC;
  không biến điểm public sample thành đặc tả.
- Báo riêng test qua, test đỏ do gap runtime, test PostgreSQL/MCP HTTP, public
  sample và hệ thống LLM thật. Không che test đỏ bằng `expectedFailure` hoặc
  sửa nhãn để đạt điểm.
