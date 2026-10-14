# Backend

Áp dụng dưới `backend/`; đọc thêm `../AGENTS.md`.

- Backend xác thực frontend, tạo/quản lý phiên và chuyển `TextTurnRequest` đã chuẩn hóa sang AI service. Không đưa công thức giá, tồn kho, KM hoặc order business về backend.
- Không tin `customer_id`, danh tính kênh hay địa chỉ do LLM/khách tự khai nếu chưa xác minh; chỉ gửi ngữ cảnh đáng tin cậy. Bảo vệ PII trong log/trace; dữ liệu giao hàng thật ở kho nghiệp vụ có kiểm soát.
- SQLAlchemy async dùng `postgresql+asyncpg://` và session theo request. `config/*.yml` chưa được runtime nạp tự động; kiểm tra `.env`/`app/configs.py`.
- Test: từ thư mục này chạy `python -m unittest discover -s test -v`; khi đổi hợp đồng AI, kiểm `CHAT_API_CONTRACT.md` và test chat service.
