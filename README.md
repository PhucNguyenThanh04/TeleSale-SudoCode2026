# TeleSale SudoCode 2026

Harness telesale tiếng Việt duy trì ngữ cảnh giữa các phiên. Bản nộp M1 chạy demo qua web chat, chấm Full và baseline không có bộ nhớ liên phiên, và xử lý file ghi âm bằng ASR local.

## 1. Chuẩn bị và cài đặt

Cần Linux x86-64, Git, Docker với Compose v2, Python 3, kết nối Internet, gói dữ liệu BTC đã giải nén và thông tin truy cập LLM tương thích API OpenAI cùng Cloudflare Workers AI. Đặt `SUBMISSION_REPO_URL` và `SUBMISSION_REF` trong shell theo URL và nhánh hoặc tag ghi trong hồ sơ nộp.

```bash
git clone --branch "$SUBMISSION_REF" "$SUBMISSION_REPO_URL" TeleSale-SudoCode2026
cd TeleSale-SudoCode2026
git rev-parse HEAD

if [ ! -f .env.submission ]; then
  cp .env.submission.example .env.submission
  printf '\nSUBMISSION_RUN_AS=%s:%s\n' "$(id -u)" "$(id -g)" >> .env.submission
fi
python3 scripts/btc_secrets.py
mkdir -p results-submission/models
```

Đối chiếu SHA sau khi clone. Điền các giá trị sau trong `.env.submission`, đã tạo từ [file mẫu](.env.submission.example). Đường dẫn tương đối được tính từ gốc repo.

| Biến | Giá trị |
|---|---|
| `BTC_ROOT` | Thư mục BTC có `catalog/`, `policy/`, `schemas/` và `eval/`. |
| `SCENARIOS_DIR` | `./eval/scenario_final` cho bộ team mặc định; `<BTC_ROOT>/test_set/public_sample` để thử mẫu; thư mục JSON bộ ẩn khi BTC chấm chéo. |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Key, ID model và URL API của provider dùng để chạy hội thoại. Có thể đặt `LANGMEM_MODEL` nếu dùng model riêng để ghi nhớ. |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Tài khoản và token có quyền Workers AI để dựng và truy hồi chỉ mục chính sách. |
| `SUBMISSION_RUN_AS` | UID:GID của người sở hữu secret và thư mục kết quả, lấy bằng `printf '%s:%s\n' "$(id -u)" "$(id -g)"`. |
| `RESULTS_DIR` | Mặc định `./results-submission`. Nếu đổi đường dẫn, tạo thư mục mới và thư mục con `models` trước khi chạy. |

Giữ `.env.submission` và `secrets-submission/` ngoài Git. Lần setup đầu tải tokenizer đã ghim checksum và có thể dùng quota embedding. Lệnh `setup` nạp nguồn BTC vào PostgreSQL, tạo schema runtime và chuẩn bị chỉ mục chính sách. Nếu dùng loader thủ công với `--prepare-policy`, cần actor có quyền `knowledge_review` và file cấu hình runtime thực, chẳng hạn [config/policy-runtime.json](config/policy-runtime.json). Đường chạy Compose tự chuẩn bị cấu hình cho BTC.

Bộ team mặc định có 48 kịch bản, 118 phiên. Nếu đã tạo `.env.submission` từ bản trước, cập nhật `SCENARIOS_DIR=./eval/scenario_final` để dùng bộ này. Xem [trạng thái bằng chứng M2](docs/evaluation/m2-readiness.md) cho phần đánh giá nâng cao đang phát triển.

## 2. Demo hai phiên

```bash
export SUBMISSION_DATABASE=telesale_demo
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-demo \
  run --rm --build setup --allow-policy-build
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-demo \
  up -d --build --wait backend
```

Mở `http://127.0.0.1:8000/chat`. Đăng nhập `demo1` hoặc `demo2`, dùng mật khẩu tương ứng trong `secrets-submission/demo_user_1_password` hoặc `secrets-submission/demo_user_2_password`. Hai tài khoản mặc định gắn với khách BTC `C001` và `C002`. Nếu danh sách khách đổi, điền hai ID khác nhau qua `DEMO_USER_1_CUSTOMER_ID` và `DEMO_USER_2_CUSTOMER_ID` trước khi seed. Đổi `DEMO_PORT` nếu cổng 8000 đang bận.

1. Phiên đầu, dùng `demo1` với ngày nghiệp vụ **15/10/2026**. Theo `SAMPLE-01`, hỏi máy lọc không khí cho phòng khoảng 25 m² có trẻ nhỏ. Xem báo giá và khuyến mãi từ tool, rồi nói cần hỏi người nhà.
2. Kết thúc phiên và mở phiên mới cho cùng khách với ngày **17/10/2026**. Kiểm tra Call Brief và timeline. Agent tiếp nối tư vấn từ phiên trước, kiểm lại điều kiện hiện tại và tạo đơn sau khi khách xác nhận.
3. Video demo dài **5–8 phút**, có cả hai phiên, Call Brief, timeline, xác nhận đơn và phần chạy script đánh giá so với baseline.

Dừng project bằng `docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-demo --profile '*' down`. Lệnh giữ các volume. Nếu đổi gói dữ liệu BTC, dùng tên project mới để có volume riêng.

## 3. Đánh giá hội thoại và chấm chéo BTC

Chạy trên DB eval riêng vì runner reset runtime trước mỗi cấu hình. Giữ demo trên project khác. Hai cấu hình dùng cùng model, tham số, seed, nguồn, knowledge release và bộ test. Baseline giữ ngữ cảnh trong phiên và tắt nạp bộ nhớ từ phiên trước.

```bash
export SUBMISSION_DATABASE=telesale_eval_m1
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm --build setup --allow-policy-build
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm eval
```

Lệnh `eval` chạy hai cấu hình, gọi scorer BTC và in bảng. Mỗi run có `run.json`, hai trace JSONL, `btc_score.json` và `m1_conversation_acceptance.json` dưới `RESULTS_DIR`. Đọc kết quả nghiệm thu và trạng thái thực thi cùng với bảng điểm.

Để BTC chạy từng cấu hình trên bộ ẩn, đặt `SCENARIOS_DIR` trong `.env.submission`, chạy setup cùng project như trên, rồi chạy:

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval-trace \
  --btc-root /btc --scenarios /scenarios --config full --out /results/full.jsonl --isolated-db
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval-trace \
  --btc-root /btc --scenarios /scenarios --config baseline_no_memory \
  --out /results/baseline.jsonl --isolated-db
```

Service `eval-trace` gọi [run_eval.py](run_eval.py) với các cờ `--scenarios`, `--config` và `--out` của BTC. Runner từ chối ghi đè. Nếu chạy lại, chọn tên output mới cho cả hai trace.

Để chấm lại hai trace trên host, đặt `SCENARIOS_DIR` và `RESULTS_DIR` trong shell theo cùng đường dẫn đã điền trong `.env.submission`. Với tên output ở ví dụ trên:

```bash
python3 "$RESULTS_DIR/full.btc-release/eval/reference_eval.py" \
  --scenarios "$SCENARIOS_DIR" --trace "$RESULTS_DIR/full.jsonl" \
  --baseline "$RESULTS_DIR/baseline.jsonl" --out "$RESULTS_DIR/cross-check-score.json"
```

Để scorer BTC tính ASR cùng lệnh này, thêm `--asr` trỏ tới thư mục có cả `ground_truth.json` và `hypotheses.json` của bộ audio cần chấm.

Trace dùng `schemas/trace_log.schema.json` của BTC. Extractor của team phân loại câu hỏi mở/xác nhận theo slot từ lời agent và trích claim kiểm chứng được từ câu trả lời, tham chiếu kết quả tool để xác định đối tượng. BTC đối chiếu mẫu 20 lượt để kiểm tra độ phủ của `questions` và `claims`. Bảng A.6 ghi RQR, CCR, TSR, HR giá/KM và số lượt trung bình, kèm TSR ca khó và vi phạm guardrail.

Mốc M1 gồm RQR giảm tương đối **≥40%**, TSR **≥70%**, HR giá/KM **≤5%**, Call Brief **≤5 giây**, TTFT chat p95 **≤3 giây** và Total p95 **≤8 giây**. Đo ít nhất 100 lượt mỗi cấu hình sau 3 lượt warm-up. TTFT tính đến phần trả lời đầu tiên qua guardrail, Total đến phần trả lời cuối; `response_ms` còn gồm lưu dữ liệu. Kết quả streaming cũ thiếu `total_basis` chưa chứng minh được Total theo mốc BTC. Với hệ thống không streaming, BTC quy ước TTFT bằng Total. Bảy mẫu công khai dùng để thử tích hợp.

## 4. Đánh giá hai vòng cải tiến

1. Chạy `eval` để tạo K0. Workflow nhận kết quả cuộc gọi và điểm đánh giá để tạo đề xuất cần rà soát. Giữ nguyên project eval, code, model, seed và bộ test.
2. Bật giao diện trên project eval bằng `SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval up -d --build --wait backend`. Nếu demo đang chiếm cổng, đặt `DEMO_PORT` khác trước khi bật. Mở link `/knowledge?run_id=...` mà runner in ra. Reviewer đối chiếu nguồn và regression test, chọn đề xuất rồi duyệt và phát hành. Tạm dừng thao tác UI trong lúc đo.
3. Sau khi release K1 được kích hoạt, thay `<run-k0>` bằng tên thư mục run K0 trong `RESULTS_DIR` và chạy:

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm knowledge-eval \
  --base-run "/results/<run-k0>"
```

Đọc bảng so sánh trong thư mục kế bên run K0, có hậu tố `.knowledge`. Báo các chỉ số tăng hoặc giảm trên cùng bộ test và lưu bằng chứng người duyệt. Nếu chưa có bằng chứng cải thiện, ghi rõ trong báo cáo. Ước tính chi phí/cuộc từ usage và đơn giá provider, gồm lượt hội thoại và worker ghi nhớ; ghi rõ cấu hình, phần cứng và giả định.

## 5. ASR local và chấm điểm

Chuẩn bị riêng bộ audio BTC và bộ team, mỗi bộ có `audio/*.wav` và `ground_truth.json`. Bộ team cần ít nhất **20 file để báo cáo ASR**; corpus nộp M1 cần **40 cuộc audio, ít nhất 1 giờ và hai vùng giọng**. Đặt `AUDIO_DATASET_DIR` trỏ tới bộ team trước, rồi chạy:

```bash
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm --build asr transcribe --audio /audio-dataset/audio \
  --device cpu --compute-type int8 --model whisper-small --out /results/asr-team
docker compose --env-file .env.submission -f compose.submission.yml -p telesale-btc-eval \
  run --rm asr eval --dataset /audio-dataset --runs /results/asr-team
```

Đổi `AUDIO_DATASET_DIR` sang bộ BTC và lặp lại với output `/results/asr-btc`. Model chạy local và có thể tải weights lần đầu vào `RESULTS_DIR/models`. Báo riêng WER, CER, độ chính xác số tiền và số điện thoại của hai bộ. ASR chấm theo quy tắc chuẩn hóa của BTC.

Với kịch bản có `customer_turns_asr`, harness dùng input đã khai báo cho cả Full và baseline. Để tạo bộ replay từ audio có mốc lời khách, dùng các lệnh `python -m speech prepare-replay`, `export-replay` và `verify-replay`, sau đó gắn bundle vào scenario bằng `python -m eval_harness.asr_inputs` với mapping khách, phiên và ngày đã đối chiếu. Chỉ đưa lời khách đã nhận dạng vào harness. Dùng cùng thư mục kết quả làm `SCENARIOS_DIR` cho hai cấu hình.

Để ghép hai điểm ASR đã lưu vào bảng eval, đặt `BTC_ASR_DATASET_DIR` và `TEAM_ASR_DATASET_DIR` trong `.env.submission` rồi chạy:

```bash
SUBMISSION_DATABASE=telesale_eval_m1 docker compose --env-file .env.submission \
  -f compose.submission.yml -p telesale-btc-eval run --rm eval \
  --btc-root /btc --scenarios /scenarios --out-root /results \
  --asr-btc-dataset /asr-btc-input --asr-btc-run /results/asr-btc \
  --asr-team-dataset /asr-team-input --asr-team-run /results/asr-team
```

Khi kiểm corpus transcript riêng, có thể chạy validator với đường dẫn nguồn BTC thật:

```bash
python3 -m speech --data-dir "$BTC_ROOT" validate --dialogues \
  speech/dialogues/team_synthetic.json speech/dialogues/team_clone.template.json \
  speech/dialogues/team_session2.json speech/dialogues/team_session3.json \
  speech/dialogues/team_new_customers.json --out speech-validation.md
```

## 6. Hồ sơ nộp

| Đầu mục | Hồ sơ |
|---|---|
| Mã nguồn và website | URL repo, branch hoặc tag, SHA commit, hướng dẫn chạy tại README này. Web có chat, Call Brief và timeline. |
| Dataset | [Mô tả corpus](dataset/M1-CORPUS.md). Bàn giao archive dữ liệu và checksum riêng. |
| Kiến trúc | [Sơ đồ harness, bộ nhớ và MCP](docs/m1-architecture.md). |
| Báo cáo | [Báo cáo đánh giá M1](docs/btc-m1-evaluation-report.md), gồm kết quả lịch sử, phân tích lỗi và giới hạn bằng chứng. Nộp kết quả Full/baseline, ASR và hai vòng cải tiến gắn với commit được chấm. |
| Video và slide | Video 5–8 phút theo [demo hai phiên](#2-demo-hai-phiên). Slide tối đa 15 trang. [Nội dung slide](docs/btc-m1-slides.md). |

[Hồ sơ diễn tập](docs/btc-submission-evidence.md) ghi nhận đã chạy Docker, đăng nhập, chat hai phiên và xuất trace với provider giả lập. Kết quả điểm chính thức cần dùng commit, dữ liệu và cấu hình thật của bản chấm. Bản dataset diễn tập RC2 có 121 transcript và 22 WAV; các mốc còn thiếu được ghi trong mô tả corpus.
