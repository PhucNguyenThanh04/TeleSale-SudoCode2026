# TeleSale SudoCode 2026

Trợ lý telesale tiếng Việt qua chat và thoại, có bộ nhớ giữa các cuộc gọi.

## Bước 1. Chuẩn bị môi trường

Cần Python 3.12+, Docker Compose 2.20+ và gói BTC đã giải nén tại `../BTC-Data-Vong1-TEAMS`. Chạy từ thư mục gốc repo. Chọn **một** nhóm lệnh để tạo và kích hoạt `.venv`.

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

**Mọi hệ điều hành** dùng lệnh sau trong môi trường vừa kích hoạt.

```sh
python -m pip install -r config/requirements/host.txt
```

Trong `.env`, điền `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` cho hội thoại và `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` cho tìm kiếm chính sách.

## Bước 2. Bật server

Chọn lệnh theo hệ điều hành. Lần build đầu cần Internet để tải phụ thuộc.

**Ubuntu / WSL2 chạy Docker Engine trong Ubuntu**

```bash
sudo docker compose up -d --build
```

**Windows / macOS / WSL2 dùng Docker Desktop**

Mở Docker Desktop, rồi chạy lệnh sau từ thư mục gốc repo.

```sh
docker compose up -d --build
```

## Bước 3. Nạp dữ liệu BTC

Lệnh này dùng chung trên mọi hệ điều hành.

```sh
python seed_btc.py --data-dir ../BTC-Data-Vong1-TEAMS
```

Chờ seed báo các dịch vụ đã sẵn sàng. Nếu muốn thử trước khi eval, mở [Chat](http://127.0.0.1:8000/chat) hoặc [Thoại](http://127.0.0.1:8000/) và đăng nhập bằng `demo1` cùng mật khẩu `DEMO_USER_1_PASSWORD` trong `.env`.

Các lệnh Python ở những bước tiếp theo dùng chung cho Ubuntu, Windows và macOS. Giữ server chạy và dùng Python trong `.venv`.

## Bước 4. Xuất Baseline và Full K0

K0 là Knowledge trước khi bổ sung. Kết thúc phiên demo trước khi eval vì runner đặt lại dữ liệu runtime. Giữ nguyên bộ kịch bản, seed và model qua các lượt. Thay `btc-eval` trong các lệnh nếu thư mục kết quả đã được dùng.

```sh
python run_eval.py --scenarios ./eval/scenario_final --config baseline_no_memory --out ./results-submission/btc-eval/baseline.jsonl
python run_eval.py --scenarios ./eval/scenario_final --config full --out ./results-submission/btc-eval/full-k0.jsonl
```

**Kết quả** gồm `baseline.jsonl`, `full-k0.jsonl` và `full-k0.knowledge-gaps.json`. Xem hai file `.report.json` để xác nhận cả hai run đã hoàn tất và dùng cùng release K0.

## Bước 5. Chấm K0 bằng scorer BTC

Chấm hai trace vừa tạo bằng reference scorer của BTC.

```sh
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./eval/scenario_final --trace ./results-submission/btc-eval/full-k0.jsonl --baseline ./results-submission/btc-eval/baseline.jsonl --out ./results-submission/btc-eval/btc-k0.json
```

**Kết quả** nằm trong `btc-k0.json`. Xem điểm trước khi duyệt gap.

## Bước 6. Duyệt gap và phát hành K1

1. Lấy `run_id` từ `full-k0.knowledge-gaps.json` và mở `http://127.0.0.1:8000/knowledge?run_id=<run-id>`.
2. Chọn gap có nguồn đủ căn cứ, kiểm tra nội dung và test, rồi bấm **Duyệt và phát hành các mục đã chọn**.
3. Ghi lại mã K1 mà giao diện báo. Nếu chưa có gap đủ căn cứ, dừng ở kết quả K0.

## Bước 7. Xuất Full K1

Sau khi K1 được phát hành, chạy lại Full trên cùng bộ kịch bản.

```sh
python run_eval.py --scenarios ./eval/scenario_final --config full --out ./results-submission/btc-eval/full-k1.jsonl
```

**Kết quả** gồm `full-k1.jsonl` và `full-k1.knowledge-gaps.json`. Trước khi chấm, kiểm tra `full-k1.report.json` báo đã hoàn tất và dùng đúng mã release K1.

## Bước 8. Chấm riêng Full K1 và đối chiếu

Dùng cùng reference scorer của BTC để chấm riêng Full K1.

```sh
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./eval/scenario_final --trace ./results-submission/btc-eval/full-k1.jsonl --out ./results-submission/btc-eval/btc-k1.json
```

**Kết quả** nằm trong `btc-k1.json`. So mục `system` trong hai file điểm để xem mức thay đổi toàn bộ bộ test. Để kiểm tra một gap cụ thể, xem cùng `scenario_id`, `call` và `turn` trong hai trace Full. K0 cần có câu bị bỏ sót, còn K1 cần trả lời đúng và có `tool_calls` cho thấy đã truy xuất mục vừa phát hành.

## Tùy chọn và xử lý lỗi

**Tiếp tục tạo đề xuất từ trace đã lưu.** Nếu worker bị gián đoạn hoặc file gap mới có trạng thái `exported`, kiểm tra cấu hình reviewer và worker rồi chạy lệnh dưới đây. Lệnh tiếp tục từ trace K0 mà không chạy lại hội thoại. Nếu Full lần hai vẫn báo release cũ, kiểm tra cấu hình ghim `KNOWLEDGE_RELEASE_ID` trước khi chạy lại.

```sh
python run_knowledge_eval.py --full-trace ./results-submission/btc-eval/full-k0.jsonl
```

**Chạy cặp tự động.** CLI cũng hỗ trợ `python run_eval.py --scenarios ./eval/scenario_final` để tạo một cặp K0 trong thư mục run riêng. Có thể dùng `--limit-scenarios 1` để chạy thử. Với kết quả từ luồng cặp, `python run_knowledge_eval.py --base-run "results-submission/<run-id>"` chạy Full K1 sau khi đã duyệt và publish, rồi ghi bảng so sánh vào thư mục `<run-id>.knowledge`.

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

## Dừng hệ thống

Dùng cách gọi Docker ở bước 2.

**Ubuntu / WSL2 chạy Docker Engine trong Ubuntu**

```bash
sudo docker compose down
```

**Windows / macOS / WSL2 dùng Docker Desktop**

```sh
docker compose down
```

[Kiến trúc](docs/tai-lieu-kien-truc.md) · [Đánh giá M1 · 48 kịch bản](docs/btc-m1-evaluation-report.md) · [Đối chiếu BTC · 7 kịch bản mẫu](docs/bao-cao-danh-gia.md) · [Bộ kịch bản](eval/scenario_final/README.md) · [Bộ dữ liệu ASR](dataset/M1-CORPUS.md)
