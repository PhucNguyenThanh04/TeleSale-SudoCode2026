# TeleSale SudoCode 2026

Trợ lý telesale tiếng Việt qua chat và thoại, có bộ nhớ giữa các cuộc gọi.

## 1. Cài đặt và chạy

Cần Python 3.12+ và Docker Compose 2.20+. Chạy từ thư mục gốc repo, nơi đã có [gói dữ liệu BTC](BTC-Data-Vong1-TEAMS/README.md).

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

Trong `.env`, điền `CLOUDFLARE_API_TOKEN` từ [tệp Google Drive](https://drive.google.com/file/d/1Gt_0syi-ib1h3paOf-UdjRgNXSUCuRlD/view?usp=sharing). Sau đó cài thư viện, bật Docker và nạp dữ liệu.

```sh
python -m pip install -r config/requirements/host.txt
docker compose up -d --build
python seed_btc.py --data-dir ./BTC-Data-Vong1-TEAMS
```

Nếu dùng Docker Desktop, mở ứng dụng trước. Nếu Docker Engine yêu cầu quyền quản trị, thêm `sudo` trước lệnh `docker compose`. Lần build đầu cần Internet.

Khi seed báo đã sẵn sàng, đăng nhập bằng `demo1` và mật khẩu `DEMO_USER_1_PASSWORD` trong `.env`. [Chat](http://127.0.0.1:8000/chat) · [Thoại](http://127.0.0.1:8000/)

## 2. Đánh giá harness

Đặt 48 tệp `TEAM-*.json`, `_manifest.json` và `_source_map.json` của đội trực tiếp trong `dataset/dataset_harness_texttotext/`. Với checkout mới, chép bộ kịch bản vào đường dẫn này vì Git đang bỏ qua thư mục dataset. Có thể đặt `SCENARIOS_DIR='./dataset/dataset_harness_texttotext'` trong `.env` để dùng runner mà không cần truyền `--scenarios`.

Giữ server chạy, dùng Python trong `.venv` và đóng phiên demo trước khi chấm vì runner đặt lại dữ liệu runtime. Giữ nguyên bộ kịch bản, seed và model. Đổi tên `btc-eval` nếu đã dùng thư mục kết quả này.

<a name="bước-4-xuất-baseline-và-full-k0"></a>

### Xuất Baseline và Full K0

K0 là bản tri thức trước khi bổ sung. Xuất hai trace, kiểm tra hai tệp `.report.json` đều báo hoàn tất và cùng release K0, rồi chấm bằng scorer trong snapshot BTC của lượt Full.

```sh
python run_eval.py --scenarios ./dataset/dataset_harness_texttotext --config baseline_no_memory --out ./results-submission/btc-eval/baseline.jsonl
python run_eval.py --scenarios ./dataset/dataset_harness_texttotext --config full --out ./results-submission/btc-eval/full-k0.jsonl
```

```sh
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./dataset/dataset_harness_texttotext --trace ./results-submission/btc-eval/full-k0.jsonl --baseline ./results-submission/btc-eval/baseline.jsonl --out ./results-submission/btc-eval/btc-k0.json
```

### Duyệt và chấm K1

1. Lấy `run_id` từ `results-submission/btc-eval/full-k0.knowledge-gaps.json` và mở `http://127.0.0.1:8000/knowledge?run_id=<run-id>`.
2. Kiểm tra nguồn, nội dung và ca kiểm thử của đề xuất, rồi bấm **Duyệt và phát hành các mục đã chọn**. Nếu chưa có đề xuất đủ căn cứ, dừng ở K0.
3. Ghi lại mã release K1, chạy lại Full, rồi kiểm tra `full-k1.report.json` báo hoàn tất và đúng mã K1 trước khi chấm.

```sh
python run_eval.py --scenarios ./dataset/dataset_harness_texttotext --config full --out ./results-submission/btc-eval/full-k1.jsonl
```

```sh
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./dataset/dataset_harness_texttotext --trace ./results-submission/btc-eval/full-k1.jsonl --out ./results-submission/btc-eval/btc-k1.json
```

So mục `system` trong `btc-k0.json` và `btc-k1.json`. Để kiểm chứng từng gap, đối chiếu cùng `scenario_id`, `call` và `turn` trong hai trace Full rồi xem `tool_calls` của K1 có truy xuất mục vừa phát hành hay không.

### Chạy cặp hoặc tiếp tục từ trace

- Chạy cặp Baseline và Full K0 bằng `python run_eval.py --scenarios ./dataset/dataset_harness_texttotext`. Thêm `--limit-scenarios 1` để chạy thử một kịch bản.
- Tiếp tục tạo đề xuất từ trace đã lưu bằng `python run_knowledge_eval.py --full-trace ./results-submission/btc-eval/full-k0.jsonl`.
- Sau khi phát hành K1 từ một lượt chạy cặp, dùng `python run_knowledge_eval.py --base-run "results-submission/<run-id>"` để chấm và xuất bảng so sánh.

Nếu Full K1 vẫn báo release cũ, kiểm tra `KNOWLEDGE_RELEASE_ID`. Nếu lượt chạy hết thời gian gọi model, có thể tăng `LLM_TIMEOUT_SECONDS` trong `.env`.

## 3. Đánh giá ASR và RAG

### ASR

Tải `audio-vieneu-120-cuoc.zip` từ bảng cuối README và giải nén vào `dataset/dataset_ASR/`. Hai lệnh dưới dùng thư mục chứa cả `audio/` và `ground_truth.json`. Nếu gói giải nén tạo thêm một thư mục con, dùng đường dẫn thư mục con đó. Chạy trong môi trường Python riêng.

```sh
python -m pip install -r config/requirements/asr.txt
python -m speech --data-dir ./BTC-Data-Vong1-TEAMS transcribe --audio ./dataset/dataset_ASR/audio --out ./results-submission/asr-team
python -m speech --data-dir ./BTC-Data-Vong1-TEAMS eval --dataset ./dataset/dataset_ASR --runs ./results-submission/asr-team
```

### RAG

Chấm lại trace và nhãn đã lưu. Đổi `rag-replay` nếu thư mục đầu ra đã tồn tại. [Báo cáo RAG](results-rag/e2e-score-03/report.md)

```sh
cd ai-services
python -m rag_eval score --run ../results-rag/e2e-02 --judgments ../results-rag/e2e-judge-02 --human-labels ../results-rag/human_labels-e2e-02.json --out ../results-submission/rag-replay
```

Để tạo trace RAG mới, chạy từ `ai-services/` với các thư mục đầu ra chưa tồn tại. Hai lệnh `run` và `judge` gọi dịch vụ model.

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
| Bộ kịch bản harness | `dataset/dataset_harness_texttotext/`. Mô tả nằm trong `README.md` của bộ dữ liệu. |
| Dataset âm thanh | [Tải trên Google Drive](https://drive.google.com/drive/folders/1165N54haGdVxfJV6RGBnJhJPDA0sJjAL) |
| [Kiến trúc hệ thống](https://htmlpreview.github.io/?https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026/blob/phuc/docs/so-do-he-thong.html) | Sơ đồ HTML |
| [Vòng lặp harness](https://htmlpreview.github.io/?https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026/blob/phuc/docs/vong-lap-harness.html) | Sơ đồ HTML |
| [Tài liệu kiến trúc](docs/tai-lieu-kien-truc.md) | Markdown |
| Công cụ và quyết định thiết kế | [Danh sách công cụ](docs/tai-lieu-kien-truc.md#4-danh-sách-công-cụ) · [Quyết định thiết kế](docs/tai-lieu-kien-truc.md#5-quyết-định-thiết-kế-và-lý-do-lựa-chọn) |
| [Báo cáo đánh giá](docs/bao-cao-danh-gia.md) | Markdown |
