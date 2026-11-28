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

## 3. Chạy eval K0 với Full và Baseline

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

Sau khi cặp K0 đạt `validated` và `healthy`, runner tìm knowledge gaps từ trace Full. Nếu terminal báo `proposals_ready`, mở link duyệt mà terminal in ra. Đề xuất nằm trong `results-submission/<run-id>.knowledge/proposals.json`. Nếu thấy `no_eligible_gaps`, chuyển đến bước 6 để chấm lại cặp K0.

## 4. Duyệt và phát hành Knowledge K1

1. Mở `http://127.0.0.1:8000/knowledge?run_id=<run-id>.knowledge` với `<run-id>` của bước 3. Trang Knowledge trên stack demo mở trực tiếp.
2. Bấm **Duyệt và phát hành**. Xem **Nội dung đã lưu**, **Nguồn và hiệu lực** và **Regression test**, rồi tick **Chọn** ở các đề xuất đồng ý phát hành.
3. Nhập **Lý do duyệt hàng loạt**, tick xác nhận đã đối chiếu nội dung, nguồn và test, rồi bấm **Duyệt và phát hành các mục đã chọn**.
4. Khi thấy **Đã phát hành … · release …**, phiên bản K1 đã hoạt động.

## 5. Chạy lại eval Full với K1

Giữ nguyên stack, seed, cấu hình eval và các tệp của run K0. Truyền thư mục gốc của run ở bước 3 vào `--base-run`.

```sh
python run_knowledge_eval.py --base-run "results-submission/<run-id>"
```

Lệnh gọi model để tạo trace Full K1 trên đúng bộ kịch bản của K0 và dùng lại hai trace K0. Xem bảng so sánh **Baseline K0 / Full K0 / Full K1** trong `results-submission/<run-id>.knowledge/comparison.md` và kết quả theo từng gap trong `comparison.json` cùng thư mục.

## 6. Chấm lại bằng reference scorer của BTC

Sau khi eval K1 hoàn tất, chạy các lệnh dưới đây để kiểm tra lại điểm từ trace đã lưu. Các runner đã gọi scorer BTC khi tạo báo cáo. Bước này chạy scorer trực tiếp trên bản sao kịch bản của run K0 và dùng lại Baseline K0 cho cả hai lần chấm. Nếu bỏ qua K1 vì không có đề xuất, chỉ chạy lệnh chấm K0.

```sh
cd "results-submission/<run-id>"
python btc-release/eval/reference_eval.py --scenarios scenarios --trace full.diagnostics_full.jsonl --baseline baseline.diagnostics_baseline.jsonl --out "../<run-id>.cross-check-k0.json"
python btc-release/eval/reference_eval.py --scenarios scenarios --trace "../<run-id>.knowledge/k1/full.diagnostics_full.jsonl" --baseline baseline.diagnostics_baseline.jsonl --out "../<run-id>.cross-check-k1.json"
cd ../..
```

Hai tệp điểm được lưu ở `results-submission/`. Bản chấm K1 so sánh khác release vì dùng Full K1 với Baseline K0.

## 7. Đánh giá bổ sung

**Chỉ xuất trace cho một cấu hình.** Chọn một trong hai lệnh sau. Mỗi lần chạy lại cần tên tệp đầu ra mới.

```sh
python run_eval.py --scenarios ./eval/scenario_final --config full --out ./results-submission/full.jsonl
python run_eval.py --scenarios ./eval/scenario_final --config baseline_no_memory --out ./results-submission/baseline.jsonl
```

**ASR local.** Trong một môi trường Python riêng, thay `<dataset>` bằng thư mục chứa `audio/` và `ground_truth.json`. Lệnh đầu cài thư viện, hai lệnh sau chép lời và chấm WER/CER.

```sh
python -m pip install -r config/requirements/asr.txt
python -m speech transcribe --audio "<dataset>/audio" --out ./results-submission/asr-team
python -m speech eval --dataset "<dataset>" --runs ./results-submission/asr-team
```

**Đánh giá RAG độc lập (M2, `qa_labeled.json` 60 câu).** Chạy từ `ai-services/` trong môi trường có `rag_eval/requirements.txt` (`ragas==0.4.4`):

```sh
cd ai-services
python -m rag_eval run --btc-root ../../BTC-Data-Vong1-TEAMS --mode end-to-end --out ../results-rag/e2e-new --allow-live
python -m rag_eval judge --run ../results-rag/e2e-02 --out ../results-rag/e2e-judge-02 --allow-live
python -m rag_eval score --run ../results-rag/e2e-02 --judgments ../results-rag/e2e-judge-02 --human-labels ../results-rag/human_labels-e2e-02.json --out ../results-rag/e2e-score-03
cd ..
```

Để đối chiếu chéo trực tiếp bằng scorer tham chiếu của BTC trên `rag_results.json`:

```sh
python -c "import json, sys; sys.path.insert(0, 'results-rag/e2e-02/btc/eval'); import reference_eval; print(json.dumps(reference_eval.rag_eval('results-rag/e2e-02/btc/rag/qa_labeled.json', 'results-rag/e2e-score-03/rag_results.json'), ensure_ascii=False, indent=2))"
```

## 8. Dừng hệ thống

```sh
docker compose down
```

[Kiến trúc](docs/tai-lieu-kien-truc.md) · [Đánh giá M1 · 48 kịch bản](docs/btc-m1-evaluation-report.md) · [Đối chiếu BTC · 7 kịch bản mẫu](docs/bao-cao-danh-gia.md) · [Bộ kịch bản](eval/scenario_final/README.md) · [Bộ dữ liệu ASR](dataset/M1-CORPUS.md)
