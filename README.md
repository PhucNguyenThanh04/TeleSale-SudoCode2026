# TeleSale SudoCode 2026

Harness telesale tiếng Việt có bộ nhớ đa phiên. Luồng chạy gồm 3 bước: **bật server → nạp dữ liệu BTC → chạy eval**.

## Yêu cầu

- Git, Python ≥ 3.12, Docker Compose ≥ 2.20 (khuyến nghị 4 vCPU, 8 GiB RAM, 20 GiB trống).
- Docker chạy các server; script seed và eval chạy trực tiếp bằng Python trên host.

| Hệ điều hành | Chuẩn bị môi trường |
|---|---|
| **Ubuntu (Linux)** | Cài Docker Engine + Compose plugin (`docker compose`), `git`, `python3.12`, `python3.12-venv`. |
| **macOS** | Cài [Docker Desktop](https://www.docker.com/products/docker-desktop/) (hoặc OrbStack/Colima), `git`, Python 3.12+ (`brew install python@3.12`). |
| **Windows** | Cài [Docker Desktop](https://www.docker.com/products/docker-desktop/) (bật WSL2), `git`, Python 3.12+ (chọn *Add Python to PATH*). Có thể dùng PowerShell hoặc chạy toàn bộ trong WSL2 theo mục Ubuntu. |

## 1. Cài đặt & Cấu hình

### Ubuntu / macOS

```bash
git clone --branch main --single-branch https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026.git
cd TeleSale-SudoCode2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r config/requirements/host.txt
cp .env.example .env
```

### Windows (PowerShell)

```powershell
git clone --branch main --single-branch https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026.git
cd TeleSale-SudoCode2026
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r config/requirements/host.txt
Copy-Item .env.example .env
```

> Nếu PowerShell chặn kích hoạt venv, chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (hoặc dùng CMD: `.\.venv\Scripts\activate.bat`).

Điền API key, model và endpoint trong `.env` (nếu dùng lại `.env` từ bản cũ, xóa dòng `COMPOSE_FILE`).

## 2. Bật server

Chạy giống nhau trên Ubuntu, macOS và Windows (đảm bảo Docker Desktop đang bật trên Windows/macOS):

```bash
python scripts/compose_up.py
```

- Lệnh kiểm tra GPU bằng container CUDA rồi tự chọn image GPU hoặc CPU. Trên Ubuntu, cần cho user quyền truy cập Docker trước khi chạy.
- Nếu muốn chạy CPU trực tiếp: `docker compose up -d --build`.
- Bước này chưa cần dữ liệu BTC. Lần đầu chạy, container ứng dụng có thể báo `Waiting for BTC data` cho tới khi hoàn tất bước 3.
- Dừng stack: `docker compose down` (giữ nguyên volume dữ liệu).

## 3. Nạp dữ liệu BTC

Giải nén gói BTC (ví dụ đặt tại `../BTC-Data-Vong1-TEAMS`), giữ `.venv` đang kích hoạt rồi chạy:

```bash
python seed_btc.py --data-dir ../BTC-Data-Vong1-TEAMS
```

- Script nạp catalog/CRM/policy vào PostgreSQL (`127.0.0.1:15432`) và Qdrant (`127.0.0.1:16333`), ghi `BTC_ROOT` vào `.env` và chờ toàn bộ service sẵn sàng.
- Giữ nguyên thư mục dữ liệu BTC cho bước eval. Không tự reset DB nếu đã seed từ nguồn khác.

**Truy cập UI** tại `http://127.0.0.1:8000/chat`:
- `demo1` / `demo1-btc-2026` (khách `C001`)
- `demo2` / `demo2-btc-2026` (khách `C002`)

### Dùng Voice

`python scripts/compose_up.py` tự khởi động cả `speech` (Gipformer ASR, Silero VAD, KorvaTTS) và `vieneu` (VieNeu TTS). Backend kết nối trực tiếp qua mạng Docker và chờ speech sẵn sàng trước khi khởi động.

- Có GPU NVIDIA dùng được qua Docker (bao gồm RTX 3050): tự chọn image CUDA 13, chạy ASR/VAD/KorvaTTS và VieNeu trên GPU. Không có GPU, driver không tương thích hoặc Docker chưa được cấp GPU: tự chọn image CPU.
- Trên Linux, chế độ GPU cần driver NVIDIA tương thích CUDA 13 và [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Trên Windows, dùng Docker Desktop với WSL2 và driver NVIDIA hỗ trợ GPU trong WSL2. Không cần cài CUDA Toolkit hay `.venv-speech-serving` trên host.
- RTX 3050 Laptop hiện tại có 4 GiB VRAM; VieNeu giới hạn một luồng. Chưa đo mức dùng VRAM khi chạy đầy đủ trong container; cần để đủ VRAM trống cho cả hai service.
- GPU dùng các phiên bản trong `speech/serving/requirements-cuda13.txt`; image CPU giữ thư viện riêng. Cả hai dùng Gipformer, KorvaTTS và VieNeu `3.8.3`; Gipformer dùng FP32 trên GPU và INT8 trên CPU.
- Lần đầu cần Internet để tải model và chờ warmup; quá trình này có thể mất nhiều phút. Model được lưu trong các volume `speech-models` và `speech-huggingface`, giữ lại khi chạy `docker compose down`.
- Nếu đang chạy speech trực tiếp trên host, dừng tiến trình đó trước để giải phóng cổng `18110`, hoặc đổi `SUBMISSION_SPEECH_PORT` trong `.env`.
- Xem tiến trình khởi động: `docker compose logs -f speech vieneu`.
- Kiểm tra API: `http://127.0.0.1:18110/health` (đổi cổng theo `SUBMISSION_SPEECH_PORT` nếu đã cấu hình).

Sau khi nạp dữ liệu BTC và các service sẵn sàng, mở `http://127.0.0.1:8000/` để dùng Voice.

## 4. Chạy Eval

Giữ `.venv` đang kích hoạt (chạy giống nhau trên cả 3 hệ điều hành):

```bash
python run_eval.py --limit-scenarios 1   # thử nhanh 1 scenario
python run_eval.py                       # chạy đầy đủ Full vs Baseline
```

- Kết quả lưu tại `results-submission/<run-id>/` (`run.json`, trace JSONL, `btc_score.json`, `m1_conversation_acceptance.json`).
- Không thao tác chat/review trên UI trong lúc eval chạy vì runner sẽ reset runtime trước mỗi cấu hình.

### Chấm chéo theo giao diện BTC

```bash
python run_eval.py --scenarios ./eval/scenario_final --config full --out ./results-submission/full.jsonl
python run_eval.py --scenarios ./eval/scenario_final --config baseline_no_memory --out ./results-submission/baseline.jsonl

python ../BTC-Data-Vong1-TEAMS/eval/reference_eval.py --scenarios ./eval/scenario_final --trace ./results-submission/full.jsonl --baseline ./results-submission/baseline.jsonl --out ./results-submission/cross-check-score.json
```

Thay `--scenarios` bằng thư mục bộ ẩn nếu cần. Runner không ghi đè file kết quả đã tồn tại.

### Vòng cải tiến tri thức (K0 → K1)

Sau run K0, mở link `/knowledge?run_id=...` do runner in ra để duyệt và phát hành K1, sau đó chạy:

```bash
python run_knowledge_eval.py --base-run "./results-submission/<run-k0>"
```

## 5. ASR local (tùy chọn)

Cài đặt trong virtualenv riêng để không xung đột thư viện harness (mặc định dùng `Systran/faster-whisper-small` trên CPU/int8):

**Ubuntu / macOS:**
```bash
python3 -m venv .venv-asr
.venv-asr/bin/python -m pip install -r config/requirements/asr.txt
.venv-asr/bin/python -m speech transcribe --audio ./dataset/audio --out ./results-submission/asr-team
.venv-asr/bin/python -m speech eval --dataset ./dataset --runs ./results-submission/asr-team
```

**Windows (PowerShell):**
```powershell
py -3.12 -m venv .venv-asr
.\.venv-asr\Scripts\python.exe -m pip install -r config/requirements/asr.txt
.\.venv-asr\Scripts\python.exe -m speech transcribe --audio ./dataset/audio --out ./results-submission/asr-team
.\.venv-asr\Scripts\python.exe -m speech eval --dataset ./dataset --runs ./results-submission/asr-team
```

## Cấu hình chính (`.env`)

| Biến | Mô tả |
|---|---|
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LANGMEM_MODEL` | API tương thích OpenAI (`LANGMEM_MODEL` để trống sẽ dùng `LLM_MODEL`). |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_API_BASE_URL` | Embedding `@cf/baai/bge-m3` cho policy (`config/policy-runtime.json`). |
| `BTC_ROOT`, `SCENARIOS_DIR`, `RESULTS_DIR` | Đường dẫn gói BTC, bộ scenario mặc định và thư mục kết quả. |
| `SUBMISSION_POSTGRES_PORT`, `SUBMISSION_QDRANT_PORT` | Cổng loopback cho host kết nối vào DB trong Docker. |
| `BTC_CALLBACK_MOCK` | Đặt `1` để lịch hẹn khớp mock tham chiếu BTC. |
| `ASR_*`, `ELEVENLABS_*` | Cấu hình ASR local và TTS (khi sinh audio). |

## Tài liệu tham khảo

- [Scenario](eval/scenario_final/README.md) · [Kiến trúc](docs/m1-architecture.md) · [Báo cáo M1](docs/btc-m1-evaluation-report.md) · [Trạng thái M2](docs/evaluation/m2-readiness.md) · [Corpus](dataset/M1-CORPUS.md)
