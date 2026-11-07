# Speech demo trên Linux

Chạy tại thư mục gốc repository. Python 3.12 dành riêng cho speech,
không cài speech vào môi trường vLLM.

```bash
uv venv --python 3.12 .venv-speech-serving
uv pip install --python .venv-speech-serving/bin/python -r speech/serving/requirements-local.lock.txt
bash scripts/serve-speech.sh
```

Lần đầu cần Internet để tải trọng số. Chờ cả hai tiến trình báo
`Application startup complete`. Nhấn Ctrl+C để dừng cả hai.
Script từ chối khởi động nếu cổng 18110 hoặc 18111 đã bị chiếm.

Nếu VieNeu báo `External data path escapes model directory`, dừng server,
chạy lệnh sau để thay symlink đã tải bằng file thật rồi khởi động lại.
Lệnh chỉ xử lý snapshot của hai repository VieNeu/codec trong cache mặc định:

```bash
.venv-speech-serving/bin/python - <<'PY'
from pathlib import Path
import shutil
hub = (Path.home() / '.cache/huggingface/hub').resolve()
repos = ('models--pnnbao-ump--VieNeu-TTS-v3-Turbo',
         'models--OpenMOSS-Team--MOSS-Audio-Tokenizer-Nano-ONNX')
for repo in repos:
    for path in (hub / repo / 'snapshots').rglob('*'):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(hub) or not target.is_file():
                raise RuntimeError(str(path))
            temporary = path.with_name(path.name + '.materializing')
            shutil.copyfile(target, temporary)
            temporary.replace(path)
PY
```

Máy hiện tại đã được xử lý bước này. Nếu dùng `HF_HOME` riêng, cần dùng
đúng đường dẫn cache đó thay cho cache mặc định trong lệnh trên.

- Demo trình duyệt: http://127.0.0.1:18110/
- Swagger: http://127.0.0.1:18110/docs
- VAD/STT readiness: http://127.0.0.1:18110/health
- VieNeu readiness: http://127.0.0.1:18111/health

Một địa chỉ API dùng cho client: `http://127.0.0.1:18110`.

| Chức năng | Endpoint |
|---|---|
| WAV → Silero VAD → Gipformer int8 → transcript | `POST /v1/speech/transcribe` |
| PCM16 mono 16 kHz → sự kiện bắt đầu/kết thúc tiếng nói và transcript | `WS /v1/speech/listen` |
| Danh sách giọng VieNeu | `GET /v1/speech/vieneu/voices` |
| VieNeu → WAV | `POST /v1/speech/vieneu/synthesize` |
| VieNeu → SSE chứa các khung PCM | `POST /v1/speech/vieneu/stream` |

```bash
curl -H 'Content-Type: audio/wav' --data-binary @customer.wav \
  http://127.0.0.1:18110/v1/speech/transcribe
curl -H 'Content-Type: application/json' \
  -d '{"text":"Xin chào, em có thể giúp gì cho anh chị?","voice":"Trúc Ly"}' \
  http://127.0.0.1:18110/v1/speech/vieneu/synthesize -o /tmp/speech-demo.wav
```

Các model chạy CPU. API chính hiện nạp cả KorvaTTS để giữ các endpoint
`/v1/speech/synthesize` cũ; demo pipeline dùng endpoint `/vieneu/` để chọn
VieNeu. Không nạp Whisper/PhoWhisper. Model Gipformer và Silero nằm trong
`speech/serving/models/`; SDK TTS dùng cache của thư viện tương ứng.

Đây là server speech, chưa tự gọi Agent: client gửi transcript tới Agent,
sau đó gửi câu trả lời tới endpoint TTS. STT trả kết quả sau mỗi lượt nói,
không có transcript từng phần. VAD phát hiện tiếng nói, không xác định danh tính
người nói. Chi tiết định dạng WebSocket: `speech/serving/README.md`.
