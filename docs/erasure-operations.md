# Vận hành yêu cầu xóa dữ liệu (bản triển khai thử nghiệm)

Tài liệu này đi cùng [ma trận phạm vi](erasure-contract.md). Ma trận vẫn chờ
chủ sở hữu dữ liệu duyệt đối với đơn hàng, BTC seed, trace và backup. Không
chạy executor trên DB nghiệp vụ hoặc thông báo xóa toàn bộ khi còn kho `pending`.

## Những phần đã có trong code

- Agent tiếp nhận qua `handoff.transfer`. Ticket `queued` chỉ có nghĩa là yêu
  cầu đã được chuyển tới người xử lý.
- MCP memory có request nội bộ theo `customer_id`, `verification_ref`,
  `verified_by`, `request_key` UUID và danh sách kho trong phạm vi. Request tạo
  barrier bền trong PostgreSQL; mọi read/write có `customer_id` đó bị chặn.
- `execute_erasure` chỉ xử lý `ai_memory`. Nó xóa fact, episode, order link,
  turn đã quy chủ; làm rỗng kết quả operation có thể phát lại fact. Lượt vô
  danh và pending fact trong phiên lẫn chủ không bị quy đoán. Retry giữ barrier.
- Backend có service độc lập xóa chat session đã xác minh theo `customer_id` và
  bảng suppression ngăn tự gắn lại khách từ CRM seed. Nó chưa nối với request
  hay receipt của MCP memory.

`request_erasure` và `execute_erasure` là hàm service nội bộ, chưa có operator
CLI/API được bảo vệ và chưa có điều phối liên DB. Không gọi trực tiếp từ agent
hoặc mở quyền cho MCP tool. Việc có `verification_ref` trong request **không
tự chứng minh** đã xác minh danh tính; hệ thống quản lý ca phải cung cấp và
kiểm soát bằng chứng đó.

## Điều kiện để chuyển sang vận hành thật

1. Duyệt ma trận: quyết định chủ quản, retention/end condition và cách xử lý
   mọi kho trong phạm vi. Ghi riêng các bản sao giữ lại. Xác minh đúng một
   `customer_id`; số điện thoại chung không phải bộ chọn.
2. Áp migration AI `0006` → `0007` → `0008` và backend `0004` theo README;
   phân quyền DB cho operator workflow. Kiểm bằng DB thử nghiệm trước.
3. Xây và kiểm operator entrypoint có xác thực; nối backend, order, BTC runtime,
   trace và backup theo ma trận được duyệt. Mỗi kho phải ghi kết quả riêng;
   một kho lỗi không được làm mất barrier hoặc biến receipt thành `completed`.
4. Kiểm lại bằng truy vấn chỉ trả số lượng/trạng thái, không in PII. Sau restore
   hoặc reimport, áp suppression trước khi mở quyền đọc; diễn tập trên bản sao
   cô lập để chứng minh không tái xuất hiện.

## Bằng chứng hiện có và giới hạn

Unit/mock kiểm memory, chống gán nhầm số chung, scope sản phẩm/phòng và tóm tắt
cuộc dài. PostgreSQL integration tạo DB tạm, áp migration, kiểm xóa memory và
backend chat theo `customer_id`, rồi xóa DB tạm. Chưa kiểm MCP HTTP, DB nghiệp
vụ, trace JSONL/Langfuse, backup restore hay full/baseline LLM. Receipt hiện
chỉ có thể `completed` cho riêng `ai_memory` khi không còn pending fact mơ hồ;
mọi kho khác trong scope vẫn `pending`.
