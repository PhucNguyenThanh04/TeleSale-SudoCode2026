# TeleSale SudoCode 2026

Trợ lý telesale tiếng Việt qua chat và thoại, có bộ nhớ giữa các cuộc gọi.

## 1. Cài đặt

Cần Python 3.12+, Docker Compose 2.20+ và gói dữ liệu BTC đã giải nén tại `../BTC-Data-Vong1-TEAMS`. Chạy các lệnh từ thư mục gốc repo.

**Linux / macOS / WSL2**

```bash
python3 -m venv .venv
source .venv/bin/activate
cp -n .env.example .env
```

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Cài thư viện vào môi trường vừa kích hoạt:

```sh
python -m pip install -r config/requirements/host.txt
```

Trong `.env`, điền `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` cho hội thoại và `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` cho tìm kiếm chính sách.

## 2. Bật server và nạp dữ liệu BTC

```sh
python scripts/compose_up.py
python seed_btc.py --data-dir ../BTC-Data-Vong1-TEAMS
```

Script tự chọn GPU hoặc CPU. Lần đầu cần Internet để tải model. Khi seed báo `ready`, mở [Chat](http://127.0.0.1:8000/chat) hoặc [Thoại](http://127.0.0.1:8000/). Đăng nhập bằng `demo1` và mật khẩu `DEMO_USER_1_PASSWORD` trong `.env`.

## 3. Chạy eval Full và Baseline

Giữ server đang chạy, dùng Python trong `.venv`. Full dùng bộ nhớ liên phiên. Baseline chỉ giữ lịch sử trong phiên. Eval gọi model thật và đặt lại dữ liệu runtime trước mỗi cấu hình, nên hãy kết thúc phiên demo trước khi chạy.

**Chạy thử một kịch bản** trên cả hai cấu hình để kiểm tra toàn bộ luồng:

```sh
python run_eval.py --limit-scenarios 1
```

**Chạy toàn bộ bộ kịch bản của đội** (48 kịch bản):

```sh
python run_eval.py --scenarios ./eval/scenario_final
```

Để dùng bộ khác, thay `./eval/scenario_final` bằng thư mục kịch bản cần chấm. Nếu bỏ `--scenarios`, runner đọc `SCENARIOS_DIR` trong `.env`.

**Đọc kết quả.** Terminal in trạng thái và đường dẫn `run.json`. Mỗi lần chạy có thư mục riêng, mặc định là `results-submission/<run-id>/`.

| Tệp | Xem gì |
|---|---|
| `run.json` | Trạng thái, số kịch bản/lượt và đường dẫn hai trace. Nếu `failed`, xem `phase`, `error_code` và `service`. |
| `btc_score.json` | Điểm Full/Baseline của lần chạy đã xác minh (`validated`). |
| `full.diagnostics_full.jsonl`, `baseline.diagnostics_baseline.jsonl` | Lời khách, câu trả lời và công cụ đã gọi theo từng lượt. |
| `m1_conversation_acceptance.json` | Kết quả đối chiếu các tiêu chí hội thoại M1. |

**In lại bảng điểm BTC từ trace đã có** mà không gọi model. Thay `<run-id>` bằng tên thư mục vừa chạy. Lệnh dùng bản sao kịch bản của chính lần chạy đó, kể cả khi chỉ chạy thử một kịch bản.

```sh
cd "results-submission/<run-id>"
python btc-release/eval/reference_eval.py --scenarios scenarios --trace full.diagnostics_full.jsonl --baseline baseline.diagnostics_baseline.jsonl --out cross-check-score.json
cd ../..
```

**Chỉ xuất trace cho một cấu hình.** Chọn một trong hai lệnh sau. Mỗi lần chạy lại cần tên tệp đầu ra mới.

```sh
python run_eval.py --scenarios ./eval/scenario_final --config full --out ./results-submission/full.jsonl
python run_eval.py --scenarios ./eval/scenario_final --config baseline_no_memory --out ./results-submission/baseline.jsonl
```

## 4. Đánh giá bổ sung

**Tri thức.** Sau khi duyệt và phát hành phiên bản chính sách mới từ giao diện Knowledge, chấm lại với thư mục kết quả của lần chạy Full/Baseline ban đầu:

```sh
python run_knowledge_eval.py --base-run "results-submission/<run-id>"
```

**ASR local.** Trong một môi trường Python riêng, thay `<dataset>` bằng thư mục chứa `audio/` và `ground_truth.json`. Lệnh đầu cài thư viện, hai lệnh sau chép lời và chấm WER/CER.

```sh
python -m pip install -r config/requirements/asr.txt
python -m speech transcribe --audio "<dataset>/audio" --out ./results-submission/asr-team
python -m speech eval --dataset "<dataset>" --runs ./results-submission/asr-team
```

## 5. Dừng hệ thống

```sh
docker compose down
```

[Kiến trúc](docs/tai-lieu-kien-truc.md) · [Báo cáo đánh giá](docs/bao-cao-danh-gia.md) · [Bộ kịch bản](eval/scenario_final/README.md) · [Bộ dữ liệu ASR](dataset/M1-CORPUS.md)
