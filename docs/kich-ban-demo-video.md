# Kịch bản video demo (C.6)

Thời lượng mục tiêu: 6–7 phút. Khách: C001 chị Hoa (tài khoản `demo1`). Sản phẩm: RunLite 1 (SKU-SN-RUN1, 1.290.000đ), khuyến mãi RUN-10 giảm 10% (12–25/10/2026, không áp dụng size 43, mỗi khách một lần).

## Chuẩn bị trước khi quay

1. Chạy stack: `python scripts/compose_up.py` rồi `python seed_btc.py`.
2. Mở http://127.0.0.1:8000/chat, đăng nhập `demo1`.
3. Nếu chị Hoa đã có lịch sử từ lần thử trước, chạy lại `python seed_btc.py` để sạch dữ liệu.
4. Bật phần mềm quay màn hình: OBS (khuyên dùng, 1920×1080, 30fps, thu cả micro) hoặc Win+Alt+R (Xbox Game Bar).
5. Phóng to trình duyệt 110–125% để chữ đọc được trên video. Đóng các tab và thông báo khác.

## Mở đầu (khoảng 30 giây)

Lời thoại: "Đây là hệ thống AI telesale của nhóm. Em sẽ demo ba cuộc gọi với cùng một khách hàng: lần đầu tư vấn, lần hai chốt đơn, lần ba đổi size sau khi mua."

Hành động: chỉ vào ô ngày nghiệp vụ, Call Brief và timeline bộ nhớ (lúc này trống).

## Cuộc gọi 1 — Ngày nghiệp vụ 15/10/2026 (khoảng 2 phút)

Đặt ngày 2026-10-15, bắt đầu phiên. Gõ (hoặc nói) lần lượt:

1. "Chào em, chị đang tìm một đôi giày chạy bộ nhẹ để chạy buổi sáng."
2. "Đôi RunLite 1 giá bao nhiêu em?"
3. "Có đang khuyến mãi gì không?"
4. "Chị đi size 40, màu trắng còn không em?"
5. "Vậy tổng tiền là bao nhiêu?"
6. "Để chị hỏi ý chồng rồi chị gọi lại sau nhé."

Điểm cần chỉ ra trên video: giá và khuyến mãi lấy từ công cụ (RUN-10 giảm 10%), kiểm tra tồn kho size 40 màu trắng, AI không ép chốt khi khách hẹn. Kết thúc phiên, chờ timeline xuất hiện mục cuộc gọi 1.

## Cuộc gọi 2 — Ngày nghiệp vụ 18/10/2026 (khoảng 2 phút)

Đặt ngày 2026-10-18, bắt đầu phiên mới. Trước khi gõ gì, dừng 3–5 giây ở Call Brief: có sản phẩm đang cân nhắc, size 40, màu trắng, khuyến mãi RUN-10, lý do hẹn (hỏi ý chồng).

Lời thoại: "Hệ thống nhận ra khách cũ và nạp Call Brief trong khoảng 200 ms."

1. "Alo em, chị Hoa đây, hôm trước chị hỏi đôi giày chạy."
   Kỳ vọng: AI xác nhận tiếp nối (RunLite 1, size 40, trắng), không hỏi lại size và màu.
2. "Ừ chồng chị đồng ý rồi, chị lấy một đôi nhé."
3. "Giao về địa chỉ cũ của chị."
4. "Đúng rồi, chị xác nhận đặt."

Điểm cần chỉ ra: AI không hỏi lại thông tin đã biết, báo giá có khuyến mãi còn hạn, tạo đơn và đọc mã đơn. Timeline có thêm cuộc gọi 2.

## Cuộc gọi 3 — Ngày nghiệp vụ 22/10/2026 (khoảng 1,5 phút)

Đặt ngày 2026-10-22, bắt đầu phiên mới. Dừng ở Call Brief: có đơn vừa đặt.

1. "Em ơi chị nhận giày rồi nhưng hơi chật, chị muốn đổi sang size 41."
   Kỳ vọng: AI tra đơn của chị, kiểm tra size 41 màu trắng còn hàng, nêu chính sách đổi.
2. "Vẫn màu trắng em nhé."
3. "Ok em làm giúp chị."

Điểm cần chỉ ra: AI dùng đơn hàng trong bộ nhớ, không hỏi lại mã đơn hay địa chỉ.

## Kết thúc (khoảng 30 giây)

Mở rộng timeline, cuộn qua ba cuộc gọi. Lời thoại: "Toàn bộ lịch sử khách được lưu và dùng lại ở mỗi cuộc gọi. Kết quả trên 48 kịch bản của BTC: TSR 81,2%, RQR 3%, CCR 65,6%, không vi phạm guardrail."

## Mẹo quay

- Quay từng cuộc gọi thành clip riêng, sau đó ghép lại. Nếu AI trả lời lệch, quay lại cuộc gọi đó (seed lại nếu cần làm từ đầu).
- Thời gian chờ mỗi lượt khoảng 3–6 giây; cắt bớt khoảng chờ khi dựng nếu video dài quá 8 phút.
- Không để lộ file .env hoặc terminal có khóa API trong khung hình.
