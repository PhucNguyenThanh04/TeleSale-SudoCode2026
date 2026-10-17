# Hợp đồng tool BTC

Cập nhật: 2026-10-15. Nguồn chuẩn luôn là `../BTC-Data-Vong1-TEAMS/schemas/tools.schema.json`; kết quả đối chiếu `eval/mock_tools.py`, điều kiện `success_if.args_match` trong sample và `eval/reference_eval.py`. Tài liệu này chỉ là bản đồ, không thay schema BTC.

- Giữ nguyên tên tool và tên tham số ở MCP boundary lẫn `tool_calls[].name/args`. Tham số riêng chỉ được thêm tùy chọn. Ngày nghiệp vụ là `on` (`YYYY-MM-DD`) lấy từ call; hàm mock nào không nhận `on` thì adapter không truyền vào hàm đó. Không dùng đồng hồ hệ thống để tính nghiệp vụ.
- `crm.get_customer(phone?, zalo_id?, fb_id?)`: cần ít nhất một định danh, trả `ambiguous/candidates` khi SĐT chung. Không dùng profile của ứng viên trước khi xác minh.
- `catalog.search(query?, category?, sku?, max_price_vnd?, min_room_area_m2?)`: `min_room_area_m2` là integer. Trả SKU, thuộc tính, biến thể. `inventory.check(sku, on)`: SKU chính hoặc variant; trả `in_stock`, `qty`, `restock_expected`, `discontinued`, `successor_sku` khi liên quan.
- `pricing.get_quote(sku, on, qty?, customer_phone?, address?, basket_skus?)`: dùng `final_price_vnd`, danh sách KM áp dụng/hết hạn/không đủ điều kiện và freeship. Báo giá cũ chỉ là lịch sử; kiểm lại mỗi call, không tự cộng dồn KM hoặc lộ giá sàn nội bộ.
- `order.create(customer_phone, sku, qty, price_vnd, payment, on, promo_code?, address?)`: `price_vnd` là **giá một đơn vị sau KM**; payment thuộc `COD|bank|momo|zalopay`; `address` tùy chọn. Chỉ thông báo tạo đơn khi trả `order_id` và `status: created`; xử lý lỗi tồn kho, giá, giới hạn COD. Mock mặc định COD nhưng schema BTC liệt kê payment bắt buộc: không tự áp dụng mặc định trong runtime nếu không có quy tắc nghiệp vụ công bố.
- `order.update(order_id, action, on, new_variant_sku?, reason?)`: action thuộc `exchange_size|exchange_product|return|update_address`; kiểm quyền sở hữu và tồn biến thể. `order.status(order_id? hoặc customer_phone?)` là M2.
- `schedule.callback(customer_phone, callback_at, note?)`: nếu có `moved_from`, báo thời điểm mới. `handoff.transfer(brief)`: brief theo `schemas/handoff_brief.schema.json`; chỉ báo chuyển máy khi tool trả `ticket_id`.
- `memory.read/write`: BTC không cố định tham số; phải ghi nguồn lượt/phiên, xử lý supersede và trace `memory_writes` đúng thao tác.
- M1 truy hồi chính sách qua tool bổ sung `policy.search(query,on,order_date?)` ở `mcp-catalog`. Repo lọc `access_level=public`, `effective_from`/`effective_until`, `date_basis` trước khi trả cho model; `order_date` chỉ lấy từ `order.status` đã xác minh. Tool này không đổi contract các tool BTC.
