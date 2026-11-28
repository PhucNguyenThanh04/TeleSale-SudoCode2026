# Kịch bản video demo (C.6)

Thời lượng mục tiêu: 6–7 phút. Khách: C001 chị Hoa (tài khoản `demo1`, số điện thoại 0984726714). Sản phẩm: RunLite 1 size 39 màu trắng (SKU-SN-RUN1-39-TRANG, giá niêm yết 1.290.000đ, còn 9 đôi), khuyến mãi RUN-10 giảm 10% còn 1.161.000đ (12–25/10/2026, mỗi khách một lần). Cuộc gọi 3 đổi sang size 40 màu trắng (còn 2 đôi).

Lưu ý: giá RunLite 1 khác nhau theo size (size 43 đắt hơn), nên khách phải nói size và màu ngay từ câu hỏi giá. Nếu không, AI không có báo giá cho đúng biến thể và trả lời bằng câu fallback.

## Chuẩn bị trước khi quay

1. Chạy stack: `python scripts/compose_up.py`, rồi `python seed_btc.py --data-dir <thư mục BTC-Data-Vong1-TEAMS>`.
2. Xoá lịch sử demo của chị Hoa (cần làm lại trước mỗi lần quay từ đầu):

```powershell
@'
begin;
delete from runtime.promo_uses where customer_phone='0984726714';
delete from runtime.tool_orders where customer_phone='0984726714' or customer_id='C001';
delete from runtime.store where prefix like 'customers.C001.%';
delete from runtime.langmem_distillation_jobs where customer_id='C001';
delete from runtime.order_links where customer_id='C001';
delete from runtime.turns where customer_id='C001';
delete from runtime.chat_sessions where customer_id='C001';
commit;
'@ | docker exec -i telesale-readme-postgres-1 sh -c 'psql -U $POSTGRES_USER -d telesale_eval_m1'
```

3. Mở http://127.0.0.1:8000/chat, đăng nhập `demo1`. Kênh: Hotline. Định danh kênh: `0984726714`.
4. Bật phần mềm quay màn hình: OBS (khuyên dùng, 1920×1080, 30fps, thu cả micro) hoặc Win+Alt+R (Xbox Game Bar).
5. Phóng to trình duyệt 110–125% để chữ dễ đọc trên video. Đóng các tab khác và tắt thông báo.

## Mở đầu (khoảng 30 giây)

Lời thoại: "Đây là hệ thống AI telesale của nhóm. Em sẽ demo ba cuộc gọi với cùng một khách hàng: lần đầu tư vấn, lần hai chốt đơn, lần ba đổi size sau khi mua."

Hành động: chỉ vào ô ngày nghiệp vụ, Call Brief và timeline bộ nhớ (lúc này trống).

## Cuộc gọi 1 — Ngày nghiệp vụ 15/10/2026 (khoảng 2 phút)

Đặt ngày 2026-10-15, bấm bắt đầu phiên. Gõ lần lượt:

1. "Chào em, chị đang tìm một đôi giày chạy bộ nhẹ để chạy buổi sáng."
2. "Chị đi size 39, thích màu trắng. Đôi RunLite 1 size 39 màu trắng giá bao nhiêu em?"
3. "Có đang khuyến mãi gì không em?"
4. "Size 39 màu trắng còn hàng không em?"
5. "Để chị hỏi ý chồng rồi chị gọi lại sau nhé."

Kết quả khi chạy thử: AI báo giá 1.161.000đ sau khi áp RUN-10 (giảm 129.000đ), xác nhận còn hàng, và không ép khách chốt khi khách hẹn gọi lại.

Điểm cần chỉ ra trên video: giá, khuyến mãi và tồn kho đều lấy từ công cụ. Kết thúc phiên, chờ timeline hiện cuộc gọi 1.

## Cuộc gọi 2 — Ngày nghiệp vụ 18/10/2026 (khoảng 1,5 phút)

Đặt ngày 2026-10-18, bấm Phiên mới. Trước khi gõ gì, dừng 3–5 giây ở Call Brief. Brief cho thấy khách cũ, có 1 phiên trước ngày 15/10, đã tư vấn SKU-SN-RUN1-39-TRANG, và `must_not_ask` gồm size và màu.

Lời thoại: "Hệ thống nhận ra khách cũ và nạp Call Brief trong khoảng 200 ms."

1. "Alo em, chị Hoa đây, hôm trước chị hỏi đôi giày chạy."
   Kết quả khi chạy thử: "Em nhớ chị rồi, hôm trước chị đang quan tâm mẫu RunLite 1 size 39 màu trắng…" AI không hỏi lại size và màu.
2. "Ừ chồng chị đồng ý rồi, chị lấy một đôi, thanh toán khi nhận hàng nhé."
   Kết quả khi chạy thử: AI tạo đơn, đọc mã OD6000xx, tổng 1.161.000đ, COD, dự kiến giao 22/10/2026.
3. "Cảm ơn em nhé."

Cuộc gọi này chạy ổn định qua cả 4 lần thử.

## Cuộc gọi 3 — Ngày nghiệp vụ 22/10/2026 (khoảng 1,5 phút)

Đặt ngày 2026-10-22, bấm Phiên mới. Dừng ở Call Brief: có đơn vừa đặt, kết quả lần trước là "chốt đơn".

1. "Em ơi chị nhận giày rồi nhưng hơi chật, chị muốn đổi sang size 40."
2. "Vẫn màu trắng em nhé."
3. "Ok em đổi giúp chị nhé."

Kết quả khi chạy thử: AI tra đơn, xem chính sách đổi size, kiểm tra size 40 màu trắng còn hàng, rồi gửi yêu cầu đổi cho đúng đơn: "đã gửi yêu cầu đổi … sang size 40 màu trắng cho đơn hàng OD6000xx, đang chờ duyệt". AI không hỏi lại mã đơn hay địa chỉ.

## Kết thúc (khoảng 30 giây)

Mở rộng timeline, cuộn qua ba cuộc gọi. Lời thoại: "Toàn bộ lịch sử khách được lưu và dùng lại ở mỗi cuộc gọi. Trên 48 kịch bản của BTC: TSR 81,2%, RQR 3%, CCR 65,6%, không vi phạm guardrail."

## Khi AI trả lời lệch

Mô hình không cho kết quả giống hệt nhau mỗi lần. Khi chạy thử, có lúc một lượt trả câu "em chưa xác minh đủ thông tin…" (guardrail chặn câu trả lời chưa có bằng chứng). Lỗi này hay gặp nhất ở lượt đầu cuộc gọi 3 và lượt hỏi tồn kho của cuộc gọi 1.

- Gặp ở cuộc gọi 1 hoặc 3: gõ lại đúng câu đó một lần nữa. Thường lần hai sẽ qua. Cắt lượt lỗi khi dựng.
- Nếu muốn video sạch: chạy lệnh xoá lịch sử ở phần Chuẩn bị, rồi quay lại từ cuộc gọi 1.
- Không cần giấu hẳn: một câu fallback cũng cho thấy guardrail không để AI bịa thông tin.

## Mẹo quay

- Quay mỗi cuộc gọi thành một clip riêng rồi ghép lại.
- Mỗi lượt chờ khoảng 2–8 giây. Cắt bớt khoảng chờ khi dựng nếu video dài quá 8 phút.
- Không để lộ file .env hoặc cửa sổ terminal có khóa API trong khung hình.
