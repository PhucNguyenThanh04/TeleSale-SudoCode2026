# Báo cáo Speech API

Cập nhật: 2026-10-30. Dịch vụ speech đang chạy trên máy KHOI và được xuất bản qua Cloudflare Tunnel.

## Truy cập và phạm vi

| Mục | Địa chỉ / trạng thái |
| --- | --- |
| Swagger UI | <https://sudoapi.ktoxz.id.vn/docs> |
| OpenAPI JSON | <https://sudoapi.ktoxz.id.vn/openapi.json> |
| ReDoc | <https://sudoapi.ktoxz.id.vn/redoc> |
| Trang thử giọng | <https://telesale.ktoxz.id.vn/> |
| Origin trên KHOI | `127.0.0.1:18110`, task `TeleSaleSpeech18110`; VieNeu nội bộ `127.0.0.1:18111`, task `TeleSaleVieNeu18111` |
| Xác thực | Không yêu cầu bearer token, JWT hoặc đăng nhập |

Speech API chạy độc lập trên KHOI. Trang hội thoại nội bộ `/app/` trên backend cục bộ nay nối micro → Speech API VAD/STT → `/api/chat` → Speech API VieNeu; trang thử giọng công khai vẫn kiểm tra speech riêng. Model đang dùng: Silero VAD, Gipformer 1.5 68M RNNT int8 ONNX qua sherpa-onnx, KorvaTTS CPU và VieNeu v3 Turbo ONNX fp32 CPU. STT xử lý offline trên từng đoạn VAD; chưa có nhận dạng streaming.

## Các endpoint

### `GET /health`

Kiểm tra model đã sẵn sàng. Phản hồi mẫu:

```json
{"status":"ready","vad":"silero","stt":"gipformer1.5-68M-rnnt-int8","tts":"korvatts","additional_tts":"vieneu-v3turbo-onnx-fp32 (separate sidecar)","stt_streaming":false}
```

### `POST /v1/speech/transcribe`

Gửi **bytes WAV trực tiếp** trong body với `Content-Type: audio/wav`, `audio/x-wav` hoặc `application/octet-stream`. Không gửi multipart/form-data. Hỗ trợ mono/stereo, tần số lấy mẫu 8–96 kHz; server trộn thành mono và chuyển về 16 kHz. Giới hạn 30 giây và 10 MiB.

```bash
curl -X POST https://sudoapi.ktoxz.id.vn/v1/speech/transcribe \
  -H "Content-Type: audio/wav" --data-binary @sample.wav
```

Phản hồi gồm `text` (bản chép lời ghép), `segments[]` (`start_s`, `end_s`, `text`) và `debug` (`vad_ms`, `stt_ms`, `audio_s`, `streaming_stt`). Không phát hiện lời nói thì `text` rỗng và `segments` rỗng. `vad_ms`/`stt_ms` là thời gian xử lý server, không gồm truyền tải mạng.

### `POST /v1/speech/synthesize`

Body JSON: `text` từ 1 đến 500 ký tự; `voice` mặc định `khanh_vy`. Kết quả là một file WAV (`audio/wav`). Header `X-TTS-Milliseconds` và `X-Audio-Seconds` cho biết thời gian tạo và độ dài âm thanh.

```bash
curl -X POST https://sudoapi.ktoxz.id.vn/v1/speech/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"Xin chào chị.","voice":"khanh_vy"}' -o speech.wav
```

Các giọng hợp lệ: `bao_kim`, `gia_bao`, `khanh_vy`, `hoang_nam`, `ngoc_huyen`, `huu_dat`, `phuong_linh`, `quang_huy`, `quynh_nhu`, `thanh_phong`.

### `POST /v1/speech/synthesize/sequence`

Nhận cùng body JSON như endpoint trên. Service tách tại dấu `.` hoặc khi đủ 20 từ (đếm theo khoảng trắng), tùy mốc nào đến trước. Mỗi đoạn được tổng hợp thành WAV riêng. JSON trả về:

```json
{
  "segments": [
    {"index": 0, "text": "Xin chào chị.", "audio_base64": "<WAV base64>", "tts_ms": 950, "audio_s": 1.6},
    {"index": 1, "text": "Em tư vấn mẫu AirPure X ạ.", "audio_base64": "<WAV base64>", "tts_ms": 1300, "audio_s": 2.5}
  ],
  "pause_ms": 200
}
```

Đây là endpoint **batch** để tương thích: server tạo xong toàn bộ đoạn rồi mới trả một JSON. Nó không phù hợp khi cần phát câu đầu sớm.

### `POST /v1/speech/synthesize/stream`

Nhận cùng body JSON. Phản hồi là **SSE** (`text/event-stream`) qua POST, không phải JSON đơn. Các event:

| Event | Nội dung |
| --- | --- |
| `start` | `segments_total`, `pause_ms: 200` |
| `segment` | `index`, `text`, `audio_base64` (WAV), `tts_ms`, `audio_s` |
| `done` | `segments_total` khi mọi câu đã tạo xong |
| `error` | Thông báo lỗi nếu quá trình tạo thất bại sau khi stream đã bắt đầu |

Server gửi `segment` ngay khi WAV tương ứng tạo xong, trước khi bắt đầu tổng hợp các câu tiếp theo. Trang web dùng luồng này: câu 1 về là phát ngay; các câu sau vào hàng đợi. Sau sự kiện `ended` của audio, trang đặt timer 200 ms rồi phát câu kế nếu nó đã sẵn sàng. Nếu câu kế chưa về, trang chờ đến khi nhận được; khoảng nghỉ khi đó sẽ dài hơn 200 ms. Client có thể hủy kết nối khi rời trang; tác vụ tổng hợp đang chạy trong một lần suy luận chưa bị ngắt giữa chừng.

```bash
curl -N -X POST https://sudoapi.ktoxz.id.vn/v1/speech/synthesize/stream \
  -H "Content-Type: application/json" \
  -d '{"text":"Xin chào chị. Em tư vấn AirPure X ạ.","voice":"khanh_vy"}'
```

Trong một phép đo qua Cloudflare với ba câu tổng hợp, WAV đầu tiên tới client sau **1,53 giây**, event `done` sau **4,34 giây**: câu đầu có thể phát sớm hơn khoảng **2,81 giây** so với cách chờ tất cả câu. Đây là một lần đo chức năng, không phải benchmark độ trễ ổn định.

### VieNeu: giọng và hai cách tạo âm thanh

`GET /v1/speech/vieneu/voices` trả danh sách `voices[]` gồm `label` và `id`. Hiện sidecar trả 25 giọng. Chọn `id` đưa vào body JSON `{"text":"Xin chào chị.","voice":"Trúc Ly"}`.

`POST /v1/speech/vieneu/synthesize` trả một WAV PCM 48 kHz hoàn chỉnh với `X-TTS-Milliseconds` và `X-Audio-Seconds`. `POST /v1/speech/vieneu/stream` trả SSE theo từng khung âm thanh:

| Event | Nội dung |
| --- | --- |
| `start` | `segments_total`, `pause_ms: 200`, `sample_rate: 48000` |
| `segment_start` | `index`, `text` của câu đang tạo |
| `audio_chunk` | `index`, `frame`, `sample_rate`, `pcm16_base64` (PCM16 mono, chưa có WAV header) |
| `segment_end` | `index`, `frames` |
| `done` / `error` | Kết thúc hoặc lỗi suy luận |

VieNeu cũng tách câu tại một dấu chấm hoặc tối đa 20 từ. Trang thử giọng dùng Web Audio để phát từng khung ngay khi nhận và đặt khoảng nghỉ 200 ms giữa các câu; không chờ tạo xong toàn bộ câu. Trong một phép đo trên KHOI, khung đầu đến sau **487 ms** qua loopback sidecar, **785 ms** qua proxy loopback, **1.089 ms** qua Cloudflare; hai câu kết thúc tương ứng sau **2,78 / 3,26 / 3,51 giây**. Độ trễ thay đổi theo tải và mạng, đây không phải benchmark ổn định. Một yêu cầu Python mặc định bị Cloudflare chặn mã 1010; thử lại với User-Agent dạng trình duyệt đã thành công. Các client API có thể bị quy tắc bot của Cloudflare ảnh hưởng.

## Giới hạn và vận hành

- Không có xác thực. Cả API và Swagger đều công khai. Giới hạn ứng dụng: tối đa 20 yêu cầu suy luận/phút/IP theo bộ nhớ tiến trình; task khởi động lại sẽ xóa bộ đếm. CORS cho trình duyệt cho phép `https://telesale.ktoxz.id.vn`, `http://127.0.0.1:8000` và `http://localhost:8000`; CORS không thay thế xác thực.
- VAD/STT/KorvaTTS dùng chung một khóa suy luận trong tiến trình; VieNeu có khóa riêng trong sidecar. Mỗi mô hình TTS vẫn xử lý tuần tự các yêu cầu của chính nó. Tải đồng thời có thể làm tăng thời gian chờ.
- Dữ liệu âm thanh được xử lý trong bộ nhớ, không ghi file đầu vào/đầu ra. Kết quả API có `Cache-Control: no-store`.
- Hai task Windows chạy với quyền thường của `pc\khoi`, tự chạy khi KHOI đăng nhập sau khi reboot. Cả hai dịch vụ chỉ bind loopback; Cloudflare Tunnel vẫn chuyển tiếp hai hostname tới port 18110. Các route cũ `api2`/`judge` không bị thay đổi.
- Lỗi thường gặp: `400` WAV sai/giọng sai/văn bản chỉ có dấu; `413` body trên 10 MiB; `415` Content-Type sai; `422` JSON sai hoặc text vượt 500 ký tự; `429` quá 20 lượt/phút/IP; `503` model chưa sẵn sàng. Khi origin tắt hoặc đang khởi động lại, Cloudflare có thể trả `502`.

## Đã kiểm tra

- Swagger `/docs` và `/openapi.json` trả HTTP 200 không đăng nhập.
- Smoke test công khai tạo WAV TTS, gửi WAV đó qua VAD/STT và nhận transcript/segment/timing.
- Sequence hai câu trả về hai WAV đúng thứ tự, `pause_ms=200`; trang web đã phát lần lượt câu 1 và câu 2.
- Stream ba câu trả từng WAV đúng thứ tự qua HTTPS; câu đầu đến trước `done`. Bài kiểm tra trình phát xác nhận nó phát câu 1 khi câu 2 còn chưa trả về, giữ câu 2 trong queue và dùng timer 200 ms sau khi câu 1 phát xong.
- Unit test bộ tách câu kiểm tra dấu chấm, ngưỡng 20 từ, khoảng trắng và trường hợp một câu ngắn.
- VieNeu sidecar nạp model ONNX CPU fp32, liệt kê 25 giọng, tổng hợp được âm thanh thực, trả `audio_chunk` trước `done` qua loopback, proxy và Cloudflare. Endpoint giọng công khai trả đúng 25 mục; endpoint WAV công khai trả file PCM WAV hợp lệ.
- Chạy lại smoke công khai KorvaTTS → Silero VAD → Gipformer STT và `/sequence` sau khi triển khai VieNeu: các endpoint cũ vẫn hoạt động.
- Sau khi nối frontend, kiểm qua Cloudflare VieNeu stream → WAV → VAD/STT và preflight CORS cho `http://127.0.0.1:8000`. Luồng VieNeu cũng nhận một câu trả lời dài hơn 500 ký tự. Trang speech công khai chọn VieNeu mặc định.

Các phép thử trên chứng minh kết nối và định dạng phản hồi. Chưa đo chất lượng cảm nhận của các giọng VieNeu, độ chính xác STT bằng bộ eval tiếng Việt/call center hoặc tải đồng thời. Chưa kiểm chứng trọn lượt hội thoại trên `/app/` vì backend cục bộ và các dịch vụ dữ liệu đang tắt; chưa kiểm chứng thủ công âm thanh VieNeu trên trình duyệt ở máy người dùng.
