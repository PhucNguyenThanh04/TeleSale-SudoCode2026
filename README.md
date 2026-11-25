# TeleSale SudoCode 2026

Harness telesale tiếng Việt có bộ nhớ đa phiên. Luồng bàn giao gồm ba bước riêng: **bật server → nạp dữ liệu BTC → chạy eval**.

## 1. Clone và đặt cấu hình

Máy cần Linux x86-64, Git, Python 3.12 trở lên và Docker Compose 2.20 trở lên. Tài khoản chạy phải truy cập được Docker (`docker ps` thành công). Các thư viện AI/backend được cài trong image; bước seed chạy bằng Python ngoài host và cần môi trường bên dưới.

```bash
git clone --branch main --single-branch https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026.git
cd TeleSale-SudoCode2026
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r config/submission/seed.txt
```

Đặt file `.env` đầy đủ vào gốc repo. Nếu tự tạo cấu hình, copy `.env.example` thành `.env` rồi điền key/model/endpoint. File mẫu liệt kê đủ biến; ngày chấm BTC thay bằng key của BTC. `.env` riêng trong từng server không cần có khi chạy theo luồng Docker này.

Hai trường sau trong `.env` chọn stack nộp bài. Khi thiếu `COMPOSE_FILE`, file mặc định `docker-compose.yml` cũng dẫn vào cùng stack; cấu hình phát triển cũ được tách sang `compose.dev.yml`:

```dotenv
COMPOSE_FILE=compose.submission.yml
COMPOSE_PROJECT_NAME=telesale-btc
```

## 2. Bật toàn bộ server

```bash
docker compose up -d --build
```

Lệnh bật PostgreSQL, Qdrant, Redis, bốn MCP server, AI service, backend và các worker. Bước này chỉ cần repo và `.env`, chưa cần thư mục dữ liệu BTC. Các server dùng volume nội bộ; lệnh không nạp dữ liệu và không chạy eval.

Compose build một image AI và một image backend; MCP, worker và eval dùng lại các image này. Sau khi đổi mã nguồn, chạy lại lệnh trên trước bước seed/eval. `Dockerfile.submission.dockerignore` lọc context cho bản nộp; `.dockerignore` ở root lọc context khi dùng Dockerfile backend cũ. Virtualenv, cache, test, báo cáo, model weights và audio được loại khỏi context của bản nộp.

Lần đầu database còn trống, các container ứng dụng chờ dữ liệu; log có thể hiện `Waiting for BTC data` và health ở trạng thái `starting`. Chạy bước 3 để hoàn tất khởi tạo.

## 3. Nạp dữ liệu BTC

Giải nén gói BTC vào thư mục bất kỳ, rồi truyền đường dẫn trực tiếp cho script Python:

```text
thu_muc_lam_viec/
├── BTC-Data-Vong1-TEAMS/
└── TeleSale-SudoCode2026/
    ├── .env
    ├── compose.submission.yml
    ├── seed_btc.py
    ├── runtime/
    └── run_eval.py
```

```bash
python seed_btc.py --data-dir ../BTC-Data-Vong1-TEAMS
```

`--data-dir` nhận cả đường dẫn tương đối và tuyệt đối. Script kết nối thẳng tới PostgreSQL/Qdrant trên loopback, không gọi Docker và không cần `sudo`. Cấu hình kết nối và API được đọc từ `.env` ở root.

Script nạp catalog/CRM/policy vào PostgreSQL, tạo schema runtime, dựng chỉ mục policy trên Qdrant, cấp quyền bốn MCP và tạo tài khoản demo. Policy/tokenizer được ghi vào `runtime/` của repo; các container đọc thư mục này ở chế độ chỉ đọc. Hai thư mục rỗng đã có trong repo nên `up` không cần dữ liệu BTC tồn tại trước. Lần đầu seed tải tokenizer có kiểm checksum và gọi embedding theo cấu hình.

Sau khi nạp thành công, script lưu đường dẫn nguồn vào `BTC_ROOT` trong `.env` cho bước eval và chờ AI, bốn MCP cùng backend sẵn sàng. PostgreSQL mở ở `127.0.0.1:15432`, Qdrant ở `127.0.0.1:16333`; có thể đổi bằng `SUBMISSION_POSTGRES_PORT` và `SUBMISSION_QDRANT_PORT` rồi khởi tạo lại container bằng Compose. Các cổng kiểm tra AI/MCP cũng chỉ mở trên loopback và có thể đổi bằng các biến `SUBMISSION_*_PORT` trong file mẫu.

Dùng lại cùng nguồn thì script giữ dữ liệu hiện có; nguồn khác trên database đã khởi tạo sẽ bị từ chối. Script không tự xóa hoặc reset database.

Giữ gói dữ liệu BTC tại `BTC_ROOT` cho bước eval vì runner cần schema, scorer và kiểm tra nguồn khớp với database.

Sau bước này, mở `http://127.0.0.1:8000/chat`:

- `demo1` / `demo1-btc-2026`, gắn khách `C001`.
- `demo2` / `demo2-btc-2026`, gắn khách `C002`.

Nếu sửa mật khẩu hoặc khách gắn với tài khoản trong `.env`, dùng giá trị tương ứng.

## 4. Chạy eval

```bash
python3 run_eval.py
```

Script chạy Full và baseline không bộ nhớ liên phiên trên stack đã bật, gọi scorer BTC và in bảng chỉ số. Script không tự bật server hoặc nạp dữ liệu. Hai cấu hình dùng cùng model, tham số, seed, nguồn, knowledge release và bộ test; baseline giữ ngữ cảnh trong phiên, tắt bộ nhớ liên phiên.

Kết quả nằm trong `RESULTS_DIR/<run-id>/`, mặc định `results-submission/<run-id>/`, gồm `run.json`, hai trace JSONL, `btc_score.json` và `m1_conversation_acceptance.json`. Đọc cả trạng thái thực thi và kết quả nghiệm thu.

Thử một scenario trước khi chạy toàn bộ:

```bash
python3 run_eval.py --limit-scenarios 1
```

Script tạo thư mục đầu ra trên host và truyền UID:GID hiện tại vào job Docker để host đọc được kết quả. Khi eval chạy, dừng thao tác chat/review trên UI vì runner reset runtime trước mỗi cấu hình. Database này dành riêng cho bản nộp, không dùng cho dữ liệu vận hành thật.

### Chấm chéo theo giao diện BTC

`run_eval.py` nhận đường dẫn trên máy host, không yêu cầu BTC tự đổi sang đường dẫn trong container:

```bash
python3 run_eval.py --scenarios ./eval/scenario_final \
  --config full --out ./results-submission/full.jsonl

python3 run_eval.py --scenarios ./eval/scenario_final \
  --config baseline_no_memory --out ./results-submission/baseline.jsonl
```

BTC thay `--scenarios` bằng thư mục bộ ẩn. `--config` xuất một trace; bỏ `--config` thì script chạy cả cặp và in bảng. Khi chạy cả cặp, `--out` nếu có là thư mục kết quả; khi chạy một cấu hình, `--out` là file JSONL. Runner từ chối ghi đè trace đã có.

Scorer BTC có thể chấm lại hai trace, với các đường dẫn theo bố cục mặc định:

```bash
python3 ../BTC-Data-Vong1-TEAMS/eval/reference_eval.py \
  --scenarios ./eval/scenario_final \
  --trace ./results-submission/full.jsonl \
  --baseline ./results-submission/baseline.jsonl \
  --out ./results-submission/cross-check-score.json
```

Đổi đường dẫn nguồn/bộ ẩn nếu dùng bố cục khác. Trace tuân theo `schemas/trace_log.schema.json`; extractor của nhóm tạo `questions` và `claims` để BTC kiểm tra. Theo giải đáp tháng 11, `trace_must_not_match` xét `agent_text` và `memory_writes`; tool args giữ giá trị thực thi. Seed history được nhập trước lượt khách, không tính seed writes vào trace.

`BTC_CALLBACK_MOCK=1` trong mẫu giúp lịch hẹn của runner và MCP order khớp mock tham chiếu BTC. Mốc M1: RQR giảm tương đối ≥40%, TSR ≥70%, HR giá/KM ≤5%, Call Brief ≤5 giây, TTFT p95 ≤3 giây và Total p95 ≤8 giây, tối thiểu 100 lượt sau 3 lượt warm-up. Nếu cả hai RQR bằng 0, BGK xét CCR thay thế; script không tự kết luận giảm 100%.

## 5. Demo hai phiên và vòng cải tiến

1. Đăng nhập `demo1`, mở phiên ngày **15/10/2026**, hỏi máy lọc cho phòng khoảng 25 m² có trẻ nhỏ; xem giá/KM từ tool rồi hẹn hỏi người nhà.
2. Mở phiên mới cùng khách ngày **17/10/2026**; kiểm tra Call Brief và timeline, tiếp nối tư vấn và chốt đơn sau xác nhận.
3. Video 5–8 phút có hai phiên và phần chạy eval so với baseline.

Sau run K0, mở link `/knowledge?run_id=...` mà runner in ra. Reviewer đối chiếu nguồn và regression, duyệt/phát hành K1 rồi chạy:

```bash
SUBMISSION_RUN_AS="$(id -u):$(id -g)" docker compose run --rm --no-deps knowledge-eval \
  --base-run "/results/<run-k0>"
```

Bảng so sánh ở thư mục có hậu tố `.knowledge`. Giữ cùng code/model/seed/test để đối chiếu hai vòng; lưu bằng chứng người duyệt, báo cả cải thiện và suy giảm cùng chi phí/cuộc.

## 6. ASR local

Bộ audio do nhóm bàn giao riêng, gồm `audio/*.wav` và `ground_truth.json`. Đặt `AUDIO_DATASET_DIR` trong `.env`, rồi chạy:

```bash
SUBMISSION_RUN_AS="$(id -u):$(id -g)" docker compose run --rm --build asr \
  transcribe --audio /audio-dataset/audio --out /results/asr-team
SUBMISSION_RUN_AS="$(id -u):$(id -g)" docker compose run --rm asr \
  eval --dataset /audio-dataset --runs /results/asr-team
```

Đổi sang bộ public BTC và dùng output `/results/asr-btc` để báo riêng WER/CER/Entity Accuracy. BTC không phát audio public D01–D04; nhóm tự thu/TTS theo kịch bản và ground truth mới. Bộ private dùng xếp hạng do BTC giữ. Corpus M1 cần ≥40 cuộc audio, tổng ≥60 phút; báo cáo ASR team cần ≥20 file. Ghi rõ hạn chế giọng, không dùng ghi âm khách thật.

ASR `whisper-small` dùng weights `Systran/faster-whisper-small`, mặc định CPU/int8. Weights tải lần transcribe đầu vào `RESULTS_DIR/models`; máy offline cần chuẩn bị cache cùng phiên bản. Transcript ASR đi qua cùng harness; bộ có `customer_turns_asr` dùng cùng input cho Full và baseline.

## 7. Cấu hình và hồ sơ

| Nhóm cấu hình | Cách dùng |
|---|---|
| `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME` | Chọn một stack cho cả server, seed và eval. |
| `BTC_ROOT` | Gói BTC có `catalog/`, `policy/`, `schemas/`, `eval/`, `asr/`. |
| `SUBMISSION_POSTGRES_PORT`, `SUBMISSION_QDRANT_PORT` | Cổng loopback để script Python seed trên host kết nối vào database trong Docker. |
| `SCENARIOS_DIR`, `RESULTS_DIR` | Bộ scenario mặc định và nơi ghi kết quả; cờ của script eval có thể ghi đè. |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LANGMEM_MODEL` | API tương thích OpenAI; khai báo model chính xác. LangMem để trống dùng cùng model hội thoại. |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_API_BASE_URL` | Embedding Cloudflare `@cf/baai/bge-m3`; cấu hình policy ở `config/policy-runtime.json`. Tokenizer được tải và kiểm checksum ở bước seed. |
| Mật khẩu DB, token nội bộ, tài khoản demo | Có giá trị mẫu; Compose cấp riêng cho từng container qua environment/secret mount. |
| `ASR_*`, `ELEVENLABS_*` | ASR local; ElevenLabs chỉ cần khi sinh audio bằng TTS. |

Tài nguyên CPU dự kiến: Linux x86-64, 4 vCPU, RAM 8 GiB, 20 GiB trống, không cần GPU cho ASR CPU/int8. Đây là cấu hình dự kiến; latency phải đo trên phần cứng/provider thực tế. Gói BTC phải đúng phiên bản; ground truth mới có D01 entity dạng list và D02 cùng khách D01. Manifest scenario kiểm hash và từ chối nguồn cũ.

Bộ team mặc định có 48 scenario, 118 phiên. Bảy mẫu BTC chỉ dùng thử tích hợp. Xem [scenario](eval/scenario_final/README.md), [trạng thái M2](docs/evaluation/m2-readiness.md), [corpus](dataset/M1-CORPUS.md), [kiến trúc](docs/m1-architecture.md), [báo cáo](docs/btc-m1-evaluation-report.md), [slide](docs/btc-m1-slides.md) và [bằng chứng diễn tập](docs/btc-submission-evidence.md). Kết quả lịch sử không thay cho đánh giá trên commit nộp bài; video và slide chuẩn bị theo thông báo BTC.

Ghi SHA bản nộp bằng `git rev-parse HEAD`. Ngừng stack bằng `docker compose down`; lệnh này giữ volume dữ liệu. Dùng cùng `COMPOSE_PROJECT_NAME` cho toàn bộ ba bước.
