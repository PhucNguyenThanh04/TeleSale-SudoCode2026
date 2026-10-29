# Sổ Tư Vấn

Giao diện thử nghiệm nội bộ cho `POST /api/chat`. Backend phục vụ trang cùng origin tại
`http://127.0.0.1:8000/app/`. Trang không kết nối trực tiếp đến AI hoặc MCP.

1. Khởi động backend cùng PostgreSQL, Redis, AI service và ba MCP server theo README của repo.
2. Mở `/app/`. Trang tự thiết lập phiên truy cập nội bộ trên localhost.
3. Nhập định danh từ kênh và ngày cuộc gọi, rồi gửi tin.

Phiên truy cập nằm trong cookie HttpOnly và Redis, hết hạn sau 24 giờ. Mỗi lần bấm
**Bắt đầu cuộc gọi mới** là một phiên mới; xác minh
danh tính phải được thực hiện ngoài nội dung khách tự khai theo hợp đồng backend.

## Luồng âm thanh

Trên `/app/`, điền định danh kênh và ngày cuộc gọi, sau đó bấm **Bắt đầu ghi âm** và **Dừng và gửi**. Trình duyệt gửi WAV tới Speech API công khai, nhận kết quả Silero VAD và Gipformer STT, rồi gửi bản chép lời qua `/api/chat` với `customer_input_mode=asr_transcript`. Khi agent trả lời, trình duyệt đọc phản hồi bằng VieNeu v3 Turbo, giọng Trúc Ly, theo từng khung âm thanh. Các câu cách nhau ít nhất 200 ms. Mục **Chi tiết luồng âm thanh** ghi trạng thái và thời gian Micro, VAD, STT, Agent, VieNeu. Có thể dừng giọng đang phát; văn bản trả lời vẫn hiển thị.

Văn bản gõ cũng được đọc bằng VieNeu sau khi agent trả lời. Frontend gọi `https://sudoapi.ktoxz.id.vn` trực tiếp cho VAD/STT/TTS; Speech API cho phép CORS từ `http://127.0.0.1:8000` và `http://localhost:8000`. Chat vẫn đi qua backend cùng origin và cookie phiên HttpOnly, không dùng bearer JWT. Micro chỉ hoạt động trong secure context (localhost hoặc HTTPS). Backend, AI service, PostgreSQL, Redis và ba MCP server cần chạy để hoàn tất lượt chat; Speech API một mình chỉ thử được VAD/STT/TTS.
