# Sổ Tư Vấn

Giao diện thử nghiệm nội bộ cho `POST /api/chat`. Backend phục vụ trang cùng origin tại
`http://127.0.0.1:8000/app/`. Trang không kết nối trực tiếp đến AI hoặc MCP.

1. Khởi động backend cùng PostgreSQL, Redis, AI service và ba MCP server theo README của repo.
2. Mở `/app/`. Trang tự thiết lập phiên truy cập nội bộ trên localhost.
3. Nhập định danh từ kênh và ngày cuộc gọi, rồi gửi tin.

Phiên truy cập nằm trong cookie HttpOnly và Redis, hết hạn sau 24 giờ. Mỗi lần bấm
**Bắt đầu cuộc gọi mới** là một phiên mới; xác minh
danh tính phải được thực hiện ngoài nội dung khách tự khai theo hợp đồng backend. Trang này chưa
có đăng nhập tài khoản, ghi âm, phát âm thanh hoặc bảng debug từng thành phần.
