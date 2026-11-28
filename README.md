# TeleSale SudoCode 2026

Trợ lý telesale tiếng Việt qua chat và thoại, có bộ nhớ giữa các cuộc gọi.

## 1. Cài đặt và chạy

Dùng Python 3.12 và Docker Compose 2.20 trở lên. Chạy từ thư mục gốc repo, nơi đã có [gói dữ liệu BTC](BTC-Data-Vong1-TEAMS/README.md).

**Linux / macOS / WSL2**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
cp -n .env.example .env
```

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Trong `.env` ở gốc repo, điền `CLOUDFLARE_API_TOKEN` của tài khoản `CLOUDFLARE_ACCOUNT_ID` và kiểm tra bộ `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` khớp với dịch vụ model dùng để chạy. [Tệp token Cloudflare do nhóm cung cấp](https://drive.google.com/file/d/1Gt_0syi-ib1h3paOf-UdjRgNXSUCuRlD/view?usp=sharing)

Khởi động Docker trước khi chạy các lệnh dưới đây. Nếu Docker Engine yêu cầu quyền quản trị, thêm `sudo` trước lệnh `docker compose`. Lần khởi động đầu cần Internet để tải image, thư viện và model thoại.

```sh
python -m pip install -r config/requirements/host.txt
docker compose up -d --build
python seed_btc.py --data-dir ./BTC-Data-Vong1-TEAMS
```

Khi seed báo đã sẵn sàng, đăng nhập bằng `demo1` và mật khẩu `DEMO_USER_1_PASSWORD` trong `.env`. [Chat](http://127.0.0.1:8000/chat) · [Thoại](http://127.0.0.1:8000/)

## 2. Đối chiếu Baseline và Full

<a name="bước-4-xuất-baseline-và-full-k0"></a>

Sau khi nạp dữ liệu BTC, giữ server chạy và đóng phiên demo vì runner đặt lại dữ liệu runtime. Chạy từ thư mục gốc repo bằng Python trong `.venv`.

### Xuất trace Baseline và Full

Chạy Baseline không có bộ nhớ liên phiên và Full có bộ nhớ liên phiên trên cùng bộ kịch bản, model, seed và phiên bản tri thức. Nếu chạy lại, chọn tên thư mục mới thay cho `btc-eval` trong cả ba lệnh.

```sh
python run_eval.py --scenarios ./dataset/dataset_harness_texttotext --config baseline_no_memory --out ./results-submission/btc-eval/baseline.jsonl
python run_eval.py --scenarios ./dataset/dataset_harness_texttotext --config full --out ./results-submission/btc-eval/full.jsonl
```

### Chấm hai trace bằng scorer BTC

Trước khi chấm, kiểm tra `baseline.report.json` và `full.report.json` trong thư mục kết quả. Cả hai cần có `status` là `completed`, `execution_health` là `healthy` và cùng `knowledge_release_id`.

```sh
python ./BTC-Data-Vong1-TEAMS/eval/reference_eval.py --scenarios ./dataset/dataset_harness_texttotext --trace ./results-submission/btc-eval/full.jsonl --baseline ./results-submission/btc-eval/baseline.jsonl --out ./results-submission/btc-eval/btc_score.json
```

Scorer in bảng chỉ số trong terminal và lưu chi tiết ở `results-submission/btc-eval/btc_score.json`. Trong JSON, `system` là Full, `baseline` là Baseline và `comparison` là kết quả đối chiếu.

Để chạy thử trên 7 kịch bản mẫu BTC, đổi `--scenarios` thành `./BTC-Data-Vong1-TEAMS/test_set/public_sample` trong cả ba lệnh.

## 3. Đánh giá ASR và RAG

### ASR

Tải `audio-vieneu-120-cuoc.zip` từ bảng cuối README và giải nén vào `dataset/dataset_ASR/`. Ví dụ dưới dùng bộ `goi-audio/team-new-vieneu`, nơi chứa `audio/` và `ground_truth.json`. Tạo và kích hoạt môi trường ASR riêng theo mục 1 với tên `.venv-asr`, rồi chạy từ thư mục gốc repo.

```sh
python -m pip install -r config/requirements/asr.txt
python -m speech --data-dir ./BTC-Data-Vong1-TEAMS transcribe --audio ./dataset/dataset_ASR/goi-audio/team-new-vieneu/audio --out ./results-submission/asr-team-new
python -m speech --data-dir ./BTC-Data-Vong1-TEAMS eval --dataset ./dataset/dataset_ASR/goi-audio/team-new-vieneu --runs ./results-submission/asr-team-new
```

Model ASR được tải ở lần nhận dạng đầu tiên. Khi chạy bộ khác trong `goi-audio/`, đổi đường dẫn dữ liệu và thư mục kết quả trong cả hai lệnh.

### RAG

Quay lại `.venv` ở mục 1 để chấm lại trace và nhãn đã lưu. Kết quả nằm ở `results-submission/rag-replay/report.md`. Đổi `rag-replay` nếu thư mục đầu ra đã tồn tại. [Báo cáo RAG đã lưu](results-rag/e2e-score-03/report.md)

```sh
cd ai-services
python -m rag_eval score --run ../results-rag/e2e-02 --judgments ../results-rag/e2e-judge-02 --human-labels ../results-rag/human_labels-e2e-02.json --out ../results-submission/rag-replay
```

Để chạy RAG mới, giữ các dịch vụ ở mục 1 đang chạy. Trong `ai-services/.env`, đặt `MCP_KNOWLEDGE_URL=http://127.0.0.1:18014/mcp` theo cổng MCP Knowledge trên máy, sao chép `MCP_INTERNAL_TOKEN` từ `.env` gốc và điền `RAG_EVAL_JUDGE_MODEL`, `RAG_EVAL_JUDGE_API_KEY` cho model chấm. Đặt thêm `RAG_EVAL_JUDGE_BASE_URL` nếu dùng endpoint chấm riêng. Model sinh câu trả lời lấy cấu hình `LLM_*` từ `.env` gốc.

Chạy tiếp từ `ai-services/` với các thư mục đầu ra chưa tồn tại. Hai lệnh `run` và `judge` gọi dịch vụ model.

```sh
python -m pip install -r rag_eval/requirements.txt
python -m rag_eval run --btc-root ../BTC-Data-Vong1-TEAMS --mode end-to-end --out ../results-submission/rag-run --allow-live
python -m rag_eval judge --run ../results-submission/rag-run --out ../results-submission/rag-judge --allow-live
python -m rag_eval score --run ../results-submission/rag-run --judgments ../results-submission/rag-judge --out ../results-submission/rag-score
```

## Dừng hệ thống

Từ thư mục gốc repo, chạy `docker compose down`. Thêm `sudo` nếu Docker Engine yêu cầu quyền quản trị.

## Tài liệu nộp cho BTC

| Nội dung | Vị trí |
|---|---|
| Bộ kịch bản harness | [48 kịch bản của đội](dataset/dataset_harness_texttotext/) · [7 kịch bản mẫu BTC](BTC-Data-Vong1-TEAMS/test_set/public_sample/) |
| Dataset âm thanh | [Tải trên Google Drive](https://drive.google.com/drive/folders/1165N54haGdVxfJV6RGBnJhJPDA0sJjAL) |
| Kiến trúc hệ thống | [Xem sơ đồ HTML](https://htmlpreview.github.io/?https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026/blob/phuc/docs/so-do-he-thong.html) |
| Vòng lặp harness | [Xem sơ đồ HTML](https://htmlpreview.github.io/?https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026/blob/phuc/docs/vong-lap-harness.html) |
| Tài liệu kiến trúc | [Đọc tài liệu Markdown](docs/tai-lieu-kien-truc.md) |
| Công cụ và quyết định thiết kế | [Danh sách công cụ](docs/tai-lieu-kien-truc.md#4-danh-sách-công-cụ) · [Quyết định thiết kế](docs/tai-lieu-kien-truc.md#5-quyết-định-thiết-kế-và-lý-do-lựa-chọn) |
| Báo cáo đánh giá | [Đọc báo cáo Markdown](docs/bao-cao-danh-gia.md) |
