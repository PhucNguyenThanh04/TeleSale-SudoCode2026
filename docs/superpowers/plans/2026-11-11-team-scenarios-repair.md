# Sửa dữ liệu team theo BTC

Phạm vi: sửa T01–T22 để dùng customer, định danh kênh và hàng trong nguồn BTC;
không bổ sung CRM/catalog BTC hoặc thay harness/scorer.

- Đã gỡ helper ghép CRM và thay đổi validator đi kèm từ hướng cũ.
- Đã remap 22 khách phân biệt, tránh 7 khách public sample và shared phone.
- T11/T12 dùng đơn seed đúng chủ; T02/T20/T22 tạo đơn từ phiên mua trước.
- T19 chuyển Facebook thật; các alias Zalo còn lại đối chiếu CRM gốc.
- Giữ sửa contract/PII matcher trước đó, cập nhật ngày/giá/đổi trả liên quan.
- Kiểm offline nguồn không đổi, identity/owner/SKU và expected tools với mock
  BTC patch tháng 11; không coi mock replay là eval chất lượng model.

Không model, import/reset DB, worktree, subagent hoặc commit tự động.
