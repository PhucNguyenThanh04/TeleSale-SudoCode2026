# Cuộc gọi TeleSale

Website dùng HTML/CSS/ES modules, không cần Node hay bước build. Gateway FastAPI
phục vụ trang và WebSocket cùng origin, token nội bộ chỉ nằm ở backend.

## Kế hoạch và tiêu chí

- [x] Phục vụ `/` và `/assets/` từ `app.voice_main`, kiểm tra HTTP offline.
- [x] Thu mic bằng AudioWorklet, đổi về PCM16 mono 16 kHz; phát PCM nối tiếp và
  xác nhận sau khi phát xong để tự nghe lượt tiếp theo trong cùng phiên agent.
- [x] Kết thúc ở mọi trạng thái phải tắt track mic, dừng loa, đóng WebSocket;
  kiểm tra nhiều lượt và lỗi bằng Chrome với speech/agent giả lập.

## Chạy

Tại thư mục gốc, khởi động speech và AI harness theo cấu hình hiện tại. Cấu hình
`backend/.env` theo `backend/.env.example`, đặc biệt URL và token AI phải khớp
harness. Sau đó:

```bash
backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000 bằng Chrome/Edge, cho phép mic, nhấn **Bắt đầu gọi**.
Nói rồi ngừng một chút để agent trả lời; website tự nghe tiếp sau khi phát xong.
Nhấn **Kết thúc** để dừng phiên. Dùng tai nghe để tránh tiếng loa lọt vào mic.
Nhận dạng lời nói do speech service thực hiện, không dùng Web Speech API.

Mục “Thông tin phiên” cho phép đặt định danh kênh và ngày nghiệp vụ trước khi gọi.
Mặc định là `web_chat`, định danh tạm trong tab và ngày hiện tại tại Việt Nam;
định danh này không phải xác thực khách hàng. Khi thử một khách hàng/kịch bản có
sẵn, nhập đúng kênh, định danh và ngày của dữ liệu đó.

Truy cập từ máy khác cần HTTPS/WSS và reverse proxy hỗ trợ WebSocket. Mic chỉ
hoạt động trên secure context (HTTPS hoặc localhost). Đây là demo không đăng
nhập; không tự công khai dịch vụ ra Internet. Không lưu âm thanh/transcript vào
trình duyệt; nội dung chỉ hiển thị trong phiên trang đang mở.

Luồng hiện tại nói theo lượt: mic tiếp tục mở trong phiên nhưng chỉ gửi âm thanh
khi trạng thái “Đang nghe”; chưa hỗ trợ ngắt lời agent giữa câu.

## Kiểm thử offline

```bash
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/test/test_voice_site.py backend/test/test_voice_browser.py backend/test/test_voice_contract.py backend/test/test_voice_speech.py backend/test/test_voice_flow.py backend/test/test_voice_websocket.py backend/test/test_voice_transport.py -q -o asyncio_default_fixture_loop_scope=function
```

Browser test cần Google Chrome hoặc `CHROME_BIN`; dùng mic giả và speech/agent
giả lập, không gọi model, DB hay dịch vụ trả phí. Các bài này không chứng minh
chất lượng model hoặc độ trễ hội thoại thật.

## Trạng thái kiểm chứng trên máy hiện tại

- 36 kiểm thử voice/UI qua, gồm 5 bài Chrome thật với mic giả.
- Đã kiểm tra giao diện desktop 1440 px và mobile 375 px, không tràn ngang.
- Speech STT/VAD và VieNeu báo ready; gateway mở/đóng được phiên với speech thật.
- Chưa kiểm chứng hội thoại agent thật: các MCP ở 8011–8014 chưa chạy, tài khoản
  hiện tại không truy cập được Docker socket và sudo cần mật khẩu. Khởi động
  các dịch vụ theo README gốc bằng tài khoản có quyền Docker trước khi gọi thật.
- API AI và gateway đã khởi động; trạng thái ready của API không xác nhận LLM,
  database, index knowledge hoặc các công cụ nghiệp vụ hoạt động.
