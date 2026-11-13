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

Chat text M1 có tại `/chat` trên cùng gateway, không cần micro hoặc speech service.
Đăng nhập bằng tài khoản demo, chọn kênh/ngày rồi bắt đầu phiên; Call Brief được nạp trước tin nhắn đầu.
Memory pending được theo dõi nền, kết thúc/mở phiên mới để thử khách quay lại.
Quy trình nghiệm thu và bàn giao ASR: [M1 acceptance](../docs/m1-acceptance.md).

Tại thư mục gốc, khởi động speech và AI harness theo cấu hình hiện tại. Cấu hình
`backend/.env` theo `backend/.env.example`, đặc biệt URL và token AI phải khớp
harness. Sau đó:

```bash
backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Thiết lập tài khoản theo [hướng dẫn auth demo](../backend/DEMO_AUTH.md).
Mở http://127.0.0.1:8000/login bằng Chrome/Edge, đăng nhập, cho phép mic rồi nhấn **Bắt đầu gọi**.
Nói rồi ngừng một chút để agent trả lời; website tự nghe tiếp sau khi phát xong.
Nhấn **Kết thúc** để dừng phiên. Dùng tai nghe để tránh tiếng loa lọt vào mic.
Nhận dạng lời nói do speech service thực hiện, không dùng Web Speech API.

Mục “Thông tin phiên” cho phép chọn kênh và ngày nghiệp vụ. Định danh lấy từ
profile BTC đã gán cho tài khoản, không chỉnh sửa từ trình duyệt. Hai người demo
đăng nhập ở hai browser profile hoặc một cửa sổ thường và một cửa sổ ẩn danh.

Truy cập từ máy khác cần HTTPS/WSS, `DEMO_COOKIE_SECURE=true` và reverse proxy hỗ
trợ WebSocket. Mic chỉ hoạt động trên secure context (HTTPS hoặc localhost).
Không lưu âm thanh/transcript vào
trình duyệt; nội dung chỉ hiển thị trong phiên trang đang mở.

Mic tiếp tục gửi âm thanh khi trợ lý đang xử lý hoặc đang nói. Bạn có thể nói
để ngắt lời; backend dừng lượt phát cũ và xử lý câu mới theo đúng thứ tự.

Dưới mỗi câu trả lời có “Bộ nhớ sau lượt này” khi AI trả metadata: đã lưu hội
thoại, đang cập nhật hồ sơ, hoặc danh sách fact thực sự được ghi mới/cập nhật/xóa.
Kết quả LangMem được cập nhật nền qua WebSocket, không chặn phát tiếng. Job hoàn
tất nhưng không ghi fact hiển thị “Không có thay đổi hồ sơ mới”; job lỗi, không
đọc được hoặc quá 60 giây hiển thị trạng thái riêng, không giả định đã nhớ.
Kết thúc cuộc gọi sẽ dừng theo dõi; pending chưa có kết quả được ghi rõ trên UI.
Demo mặc định dùng định danh `web_chat` chưa xác minh nên chỉ lưu hội thoại;
muốn thấy fact dài hạn cần dùng khách đã nhận diện và chạy LangMem worker.
Chỉ hiển thị các slot được phép đã che PII, không hiển thị proposal hay bằng
chứng gốc. Thay đổi episode/brief không nằm trong danh sách thay đổi fact này.

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

## Ngắt lời và xác nhận phát

Micro tiếp tục gửi audio khi trợ lý đang xử lý hoặc đang nói. Khi backend báo
`playback_interrupt`, trình duyệt dừng nguồn audio, bỏ hàng đợi và xác nhận mốc
`played_chars` cuối đã phát hết. Các audio cũ đến trễ không được phát lại.
Mốc được xác nhận theo đồng hồ AudioContext, không theo lúc nhận gói tin.
Memory giọng nói chỉ lưu các câu đã xác nhận phát hết; phần câu bị ngắt giữa
chừng được bỏ qua vì chưa có thời gian từng từ. Bật echo cancellation và nên
kiểm tra trên thiết bị thật; test offline không đánh giá chất lượng chống vọng.

## Duyệt Knowledge Gap

Trang `/knowledge` trên cùng gateway dùng API Knowledge thật qua proxy server.
Không cần build frontend. Trước khi mở trang:

1. Trang yêu cầu đăng nhập tài khoản demo. Gateway dùng
   `KNOWLEDGE_REVIEWER_ID` trong `backend/.env` (mặc định `local-reviewer`).
2. Người quản trị cấp quyền cho actor này tại AI service một lần:

   ```bash
   cd ai-services
   .venv/bin/python -m app.knowledge.cli grant --actor local-reviewer
   ```

   CLI cần `KNOWLEDGE_ADMIN_DATABASE_URL` đúng DB knowledge. Actor vẫn được
   kiểm quyền tại AI service; browser không tự chọn hoặc cấp quyền actor.
3. Khởi động AI service có `KNOWLEDGE_DATABASE_URL` và worker
   `python -m app.knowledge.worker` với `KNOWLEDGE_WORKER_DATABASE_URL` riêng.
   Bật `KNOWLEDGE_ENABLED=true` ở AI service để thu feedback runtime. Chạy gateway
   rồi mở `http://127.0.0.1:8000/knowledge`; danh sách gap được tải tự động.
   `KNOWLEDGE_REVIEW_TOKEN` không còn được sử dụng.

Luồng sử dụng: chọn gap → đọc câu hỏi/câu trả lời và nguồn feedback → phân loại
nguyên nhân → mở draft tự động nếu có hoặc tạo đề xuất → chọn nguồn public và
đọc hiệu lực/nội dung → lưu → review regression test → nhập lý do, xác nhận đã
review → duyệt hoặc từ chối. Sửa nội dung hoặc test tạo revision mới cần duyệt lại;
chỉnh sửa chưa lưu không được dùng để duyệt bản cũ. Lỗi 409 yêu cầu làm mới và
đọc lại, trang không tự retry ghi đè.

Nút **Duyệt hết** nạp bản nháp ở mọi trang để đối chiếu nội dung, nguồn và test.
Nhập lý do chung, xác nhận đã review rồi duyệt danh sách. Trang báo số thành công
và mã bản lỗi để kiểm tra lại; gap chưa có đề xuất không được tự tạo đáp án.
Các bản duyệt thành công được chọn trong tab Phát hành, chưa tự phát hành.
Mỗi release chứa tối đa 100 bản; danh sách duyệt có thể lớn hơn giới hạn này.

Tab **Phát hành** chọn các bản approved → chuẩn bị release → mở manifest/checks
→ xác nhận phát hành hoặc khôi phục release cũ. Chuẩn bị có thể build hybrid
index tùy cấu hình AI service, nên không coi là thao tác chỉ đọc. Bản mới chỉ
chứa các revision đã chọn; UI cảnh báo các revision active sẽ bị bỏ. Các gate
source hash, approval/test, permission và CAS vẫn do AI service kiểm. Phát hành
không tự đánh dấu gap resolved: cần bằng chứng eval trước/sau riêng. Kết quả
retrieval offline không đồng nghĩa đã kiểm chất lượng LLM.

Trang hiện phân biệt gap technical/generation/correct_refusal và chặn soạn nội
dung cho các nhóm này. Nội dung được hiển thị bằng text, không render HTML từ
feedback. Gateway yêu cầu JWT cookie từ browser, server cố định reviewer,
không cache dữ liệu admin và chặn Origin khác khi ghi. Token nội bộ AI vẫn chỉ
được gửi từ gateway tới AI service. Bản demo này chạy trên localhost. Cả UI và backend không tự seed gap hoặc gọi eval để có
số liệu demo. Chưa có gap thì chạy luồng feedback/worker hiện có từ dữ liệu thật.

Kiểm thử focused, offline:

```bash
PYTHONPATH=backend:backend/test backend/.venv/bin/python -m pytest -q backend/test/test_knowledge_gateway.py backend/test/test_knowledge_browser.py -o asyncio_default_fixture_loop_scope=function
```

Browser test dùng Chrome thật, upstream giả và không có model/DB/phát hành thật.
