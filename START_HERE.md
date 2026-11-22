# Bản nộp BTC · TeleSale SudoCode

Repo chạy trên Linux x86-64 với Docker Compose, Python 3 để sinh secret và Internet để tải image, tokenizer và gọi provider. ASR xử lý file bằng CPU local. Chuẩn bị gói dữ liệu chính thức đã giải nén và thông tin truy cập LLM, Cloudflare Workers AI.

## 1. Clone repo và chuẩn bị một lần

Điền `SUBMISSION_REPO_URL` và `SUBMISSION_REF` theo URL GitHub và branch hoặc tag ghi trong hồ sơ nộp. Sau khi clone, đối chiếu commit in ra với commit của bản nộp.

```bash
git clone --branch "$SUBMISSION_REF" "$SUBMISSION_REPO_URL" TeleSale-SudoCode2026
cd TeleSale-SudoCode2026
git rev-parse HEAD
```

Chạy các bước tiếp theo từ gốc repo. `Dockerfile.submission` và `compose.submission.yml` trong repo đủ để build ba image AI, backend và ASR trên máy chấm.

```bash
if [ ! -f .env.submission ]; then
  cp .env.submission.example .env.submission
  printf '\nSUBMISSION_RUN_AS=%s:%s\n' "$(id -u)" "$(id -g)" >> .env.submission
fi
python3 scripts/btc_secrets.py
mkdir -p results-submission/models
```

Điền `BTC_ROOT`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `CLOUDFLARE_ACCOUNT_ID` và `CLOUDFLARE_API_TOKEN` trong `.env.submission`. `BTC_ROOT` là thư mục có `catalog/`, `policy/`, `schemas/` và `eval/`. `SCENARIOS_DIR` chỉ tới thư mục JSON muốn chạy, ví dụ bộ scenario team trong repo hoặc `test_set/public_sample` trong gói BTC. Khi chấm chéo, đổi giá trị này sang thư mục test ẩn. Các đường dẫn tương đối tính từ gốc repo.

`SUBMISSION_RUN_AS` là UID:GID của tài khoản sở hữu thư mục kết quả và file secret. Với `.env.submission` đã có, điền giá trị từ lệnh `printf '%s:%s\n' "$(id -u)" "$(id -g)"`. Khi đổi `RESULTS_DIR`, tạo thư mục `models` bên trong đường dẫn mới.

DB eval dùng một project riêng. Setup lần đầu có thể tải tokenizer đã ghim checksum và tiêu quota embedding để dựng policy.

```bash
export SUBMISSION_DATABASE=telesale_eval_m1
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm --build setup --allow-policy-build
```

Setup nạp `btc_source`, tạo runtime, store và policy. Chạy lại với cùng nguồn sẽ xác minh DB và dùng lại dữ liệu. Khi dùng gói BTC khác, chọn project mới để nhận volume mới. Giữ nguyên secret đã sinh tương ứng với các volume cũ.

## 2. Eval M1 bằng một lệnh

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval
```

Lệnh khởi động các MCP và worker cần thiết, chạy Full và baseline, gọi scorer BTC và in bảng chỉ số trên terminal. Output nằm trong một thư mục run mới dưới `RESULTS_DIR`. Đọc `run.json` để xác định tên hai trace và trạng thái, `btc_score.json` để xem điểm, và `m1_conversation_acceptance.json` để xem các điều kiện hội thoại. Runner sử dụng cùng nguồn và ghim cùng release cho hai cấu hình. Mỗi cấu hình bắt đầu với trạng thái runtime được reset trên DB eval riêng.

Khi kiểm chứng vòng cải tiến, dùng run eval làm vòng 0. Có thể bật `backend` trên chính project eval trong lúc duyệt đề xuất ở `/knowledge`. Sau khi người phụ trách phát hành release, chạy `run --rm knowledge-eval --base-run /results/<run-vong-0>` bằng Compose cùng project eval. Dừng thao tác qua giao diện trong lúc đo vòng 0 và vòng 1. Giữ cùng scenario và cấu hình model cho hai vòng.

Đường chấm chéo từng cấu hình giữ giao diện `run_eval.py`.

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval-trace \
  --btc-root /btc --scenarios /scenarios --config full --out /results/full.jsonl --isolated-db
```

Đổi thành `--config baseline_no_memory --out /results/baseline.jsonl` cho cấu hình kia. Nếu file output đã tồn tại, chọn tên mới. Có thể dùng scorer chính thức để chấm lại hai trace, với đúng thư mục scenario. Khi chạy ngoài container, dùng [lệnh Python và đường dẫn phía host](docs/submission-runbook.md#5-lệnh-btc-chấm-chéo).

## 3. Demo chat trên một project riêng

```bash
export SUBMISSION_DATABASE=telesale_demo
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-demo \
  run --rm --build setup --allow-policy-build
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-demo \
  up -d --wait backend
```

Mở `http://127.0.0.1:8000/chat`. Đăng nhập `demo1` hoặc `demo2`, dùng mật khẩu trong `secrets-submission/demo_user_1_password` hoặc `demo_user_2_password`. Tài khoản mặc định gắn với BTC `C001` và `C002`. Nếu bộ BTC khác dùng ID khác, chọn hai ID khác nhau có định danh riêng trong `.env.submission` trước khi seed.

Chạy hai phiên cùng khách để xem tư vấn và báo giá ở phiên đầu, rồi Call Brief, timeline và tiếp nối ở phiên sau. Trang `/knowledge` dùng cho quy trình review. Lệnh `docker compose` với cùng tham số project và `--profile '*' down` dừng toàn bộ dịch vụ và giữ các volume. Sau khi sửa logic, dùng `up -d --build --wait backend` để build và chạy lại demo.

Khi ghi video 5–8 phút theo C.6, dùng `demo1` gắn với C001 của `SAMPLE-01` và ngày nghiệp vụ `2026-10-15` rồi `2026-10-17`. Ghi hai phiên với stack và model làm việc thực tế. Có thể bám theo thời lượng sau.

| Thời điểm | Nội dung cần quay |
|---|---|
| 0:00–0:40 | Giới thiệu bài toán và các khu vực chat, Call Brief, timeline |
| 0:40–2:30 | Phiên 1. Khách hỏi máy lọc không khí cho phòng khoảng 25 m², có trẻ nhỏ. Cho xem báo giá và KM có nguồn, rồi để khách nói cần hỏi người nhà |
| 2:30–4:50 | Kết thúc phiên, mở phiên mới cùng khách sau hai ngày. Quay Call Brief, lịch sử và cách agent tiếp tục mà dùng lại dữ liệu đã có. Khách xác nhận điều kiện mua. Cho xem kết quả tạo đơn trong UI |
| 4:50–6:00 | Quay lệnh eval và bảng Full/baseline từ đúng run, kèm tên bộ test và cấu hình model |
| 6:00–6:40 | Giới thiệu cách đo ASR và một bài học từ vòng Knowledge Gap có review |

## 4. ASR local trên file ghi âm

Đặt `AUDIO_DATASET_DIR` tới một dataset có `audio/` và `ground_truth.json`. Dùng một lần cho bộ BTC và một lần cho bộ team.

```bash
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm --build asr transcribe --audio /audio-dataset/audio \
  --device cpu --compute-type int8 --model whisper-small --out /results/asr-team
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm asr eval --dataset /audio-dataset --runs /results/asr-team
```

Lần đầu preset có thể tải trọng số vào `RESULTS_DIR/models`, được mount vào `/models`. ASR chạy trên máy. Có thể truyền thư mục model đã chuẩn bị trong mount cho `--model`. Lặp với output `/results/asr-btc` sau khi có audio BTC.

Để đưa lượt khách từ file ghi âm qua cùng harness, tạo gói replay bằng các lệnh `prepare-replay`, `export-replay` và `verify-replay`. Sau đó dùng `eval_harness.asr_inputs` để gắn replay vào scenario dựa trên mapping đã duyệt, rồi đặt `SCENARIOS_DIR` tới thư mục mới. Hai cấu hình eval dùng chung bản transcript ASR này. [Chuẩn bị replay](speech/README.md#11-gói-replay-offline--bàn-giao-cho-nhóm-harness) · [Mapping và lệnh nối harness](docs/m1-acceptance.md#3-nhận-dataset-và-asr).

Để bảng eval in cả điểm ASR đã lưu, điền hai đường dẫn dataset vào `BTC_ASR_DATASET_DIR` và `TEAM_ASR_DATASET_DIR`, rồi chạy:

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval \
  --btc-root /btc --scenarios /scenarios --out-root /results \
  --asr-btc-dataset /asr-btc-input --asr-btc-run /results/asr-btc \
  --asr-team-dataset /asr-team-input --asr-team-run /results/asr-team
```

[Kiến trúc](docs/m1-architecture.md) · [Hồ sơ và trạng thái bằng chứng](docs/btc-submission-evidence.md) · [Chấm và kiểm chứng M1](docs/m1-acceptance.md)
