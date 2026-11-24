# TeleSale SudoCode 2026

Harness telesale tiếng Việt duy trì ngữ cảnh giữa các phiên. Bản nộp M1 chạy demo qua web chat, chấm Full và baseline không có bộ nhớ liên phiên, và xử lý file ghi âm bằng ASR local.

## 1. Chạy bản nộp

Máy cần Linux x86-64, Git, Python 3, Docker Compose và kết nối Internet. Nhóm bàn giao repo trên `main`, một file `.env` đã điền sẵn key/mật khẩu và gói dữ liệu BTC.

**Bước 1 — Clone main:**

```bash
git clone --branch main --single-branch https://github.com/PhucNguyenThanh04/TeleSale-SudoCode2026.git
cd TeleSale-SudoCode2026
```

**Bước 2 — Đặt file `.env` nhóm cung cấp vào gốc repo và giải nén dữ liệu BTC bên cạnh repo:**

```text
thu_muc_lam_viec/
├── BTC-Data-Vong1-TEAMS/
└── TeleSale-SudoCode2026/
    ├── .env
    ├── compose.submission.yml
    └── run_submission.py
```

File `.env` bàn giao có sẵn key LLM, Cloudflare, model, endpoint, mật khẩu database, tài khoản demo và token nội bộ. Compose tự cấp cấu hình cho từng server; BTC không cần tạo `.env` trong `backend/` hay `ai-services/`. Với bố cục trên, `BTC_ROOT=../BTC-Data-Vong1-TEAMS` dùng được ngay. Nếu đặt dữ liệu ở nơi khác, sửa riêng `BTC_ROOT` trong `.env`. Bộ test mặc định là `eval/scenario_final`.

**Bước 3 — Chạy:**

```bash
python3 run_submission.py
```

Lệnh tự chạy toàn bộ luồng: **PostgreSQL/Qdrant → khởi tạo dữ liệu → MCP/worker → Full + baseline → xuất trace → scorer BTC → bảng kết quả**. Kết quả nằm trong `results-submission/<run-id>/`; `run.json` ghi trạng thái thực thi.

Để thử trước một scenario, dùng `python3 run_submission.py eval --limit-scenarios 1`. Chạy giao diện bằng lệnh ở mục 2. Các tham số, model và phần cứng được mô tả tại [chi tiết cấu hình](#7-chi-tiết-cấu-hình-và-triển-khai).

## 2. Demo hai phiên

```bash
python3 run_submission.py demo
```

Mở `http://127.0.0.1:8000/chat`. Đăng nhập `demo1` / `demo1-btc-2026` hoặc `demo2` / `demo2-btc-2026`; nếu đổi mật khẩu trong `.env`, dùng giá trị `DEMO_USER_1_PASSWORD` hoặc `DEMO_USER_2_PASSWORD` tương ứng. Hai tài khoản mặc định gắn với khách BTC `C001` và `C002`. Nếu danh sách khách đổi, điền hai ID khác nhau qua `DEMO_USER_1_CUSTOMER_ID` và `DEMO_USER_2_CUSTOMER_ID` trước khi seed. Đổi `DEMO_PORT` nếu cổng 8000 đang bận.

1. Phiên đầu, dùng `demo1` với ngày nghiệp vụ **15/10/2026**. Theo `SAMPLE-01`, hỏi máy lọc không khí cho phòng khoảng 25 m² có trẻ nhỏ. Xem báo giá và khuyến mãi từ tool, rồi nói cần hỏi người nhà.
2. Kết thúc phiên và mở phiên mới cho cùng khách với ngày **17/10/2026**. Kiểm tra Call Brief và timeline. Agent tiếp nối tư vấn từ phiên trước, kiểm lại điều kiện hiện tại và tạo đơn sau khi khách xác nhận.
3. Video demo dài **5–8 phút**, có cả hai phiên, Call Brief, timeline, xác nhận đơn và phần chạy script đánh giá so với baseline.

Dừng project bằng `docker compose --env-file .env -f compose.submission.yml -p telesale-btc-demo --profile '*' down`. Lệnh giữ các volume. Nếu đổi gói dữ liệu BTC, dùng tên project mới để có volume riêng.

## 3. Đánh giá hội thoại và chấm chéo BTC

Chạy trên DB eval riêng vì runner reset runtime trước mỗi cấu hình. Giữ demo trên project khác. Hai cấu hình dùng cùng model, tham số, seed, nguồn, knowledge release và bộ test. Baseline giữ ngữ cảnh trong phiên và tắt nạp bộ nhớ từ phiên trước.

```bash
python3 run_submission.py
```

Sau khi đặt `.env` ở mục 1, lệnh trên build image, khởi động PostgreSQL/Qdrant, chạy setup, cấp quyền MCP, chờ các MCP sẵn sàng rồi chạy Full và baseline. Script tự chọn project `telesale-btc-eval`, database `telesale_eval_m1`; demo dùng project/database riêng. Runner xuất trace, gọi scorer BTC và in bảng. Mỗi run có `run.json`, hai trace JSONL, `btc_score.json` và `m1_conversation_acceptance.json` dưới `RESULTS_DIR`. Đọc kết quả nghiệm thu và trạng thái thực thi cùng với bảng điểm.

Để BTC chạy từng cấu hình trên bộ ẩn, đặt `SCENARIOS_DIR` trong `.env` rồi chạy; Compose dùng cùng luồng setup/MCP tự động:

```bash
python3 run_submission.py eval-trace \
  --btc-root /btc --scenarios /scenarios --config full --out /results/full.jsonl --isolated-db
python3 run_submission.py eval-trace \
  --btc-root /btc --scenarios /scenarios --config baseline_no_memory \
  --out /results/baseline.jsonl --isolated-db
```

Service `eval-trace` gọi [run_eval.py](run_eval.py) với các cờ `--scenarios`, `--config` và `--out` của BTC. Runner từ chối ghi đè. Nếu chạy lại, chọn tên output mới cho cả hai trace.

Launcher bật `BTC_CALLBACK_MOCK=1` cho tiến trình eval và MCP order trong project chấm để lịch hẹn khớp `eval/mock_tools.py`. Demo áp dụng giờ mở cửa trong tài liệu `[LN-01]` và `[LN-02]`. Khi chạy eval trực tiếp bên ngoài launcher, bật cùng biến ở runner và MCP order của DB eval riêng.

Để chấm lại hai trace trên host, đặt `SCENARIOS_DIR` và `RESULTS_DIR` trong shell theo cùng đường dẫn đã điền trong `.env`. Với tên output ở ví dụ trên:

```bash
python3 "$RESULTS_DIR/full.btc-release/eval/reference_eval.py" \
  --scenarios "$SCENARIOS_DIR" --trace "$RESULTS_DIR/full.jsonl" \
  --baseline "$RESULTS_DIR/baseline.jsonl" --out "$RESULTS_DIR/cross-check-score.json"
```

Để scorer BTC tính ASR cùng lệnh này, thêm `--asr` trỏ tới thư mục có cả `ground_truth.json` và `hypotheses.json` của bộ audio cần chấm.

Trace dùng `schemas/trace_log.schema.json` của BTC. Extractor của team phân loại câu hỏi mở/xác nhận theo slot từ lời agent và trích claim kiểm chứng được từ câu trả lời, tham chiếu kết quả tool để xác định đối tượng. BTC đối chiếu mẫu 20 lượt để kiểm tra độ phủ của `questions` và `claims`. Bảng A.6 ghi RQR, CCR, TSR, HR giá/KM và số lượt trung bình, kèm TSR ca khó và vi phạm guardrail.

Theo giải đáp BTC tháng 11, trace chấm giữ nguyên `tool_calls[].args` đã thực thi, gồm SĐT/địa chỉ. File trace này cần được lưu trong phạm vi chấm điểm; log vận hành và prompt gửi model ngoài vẫn che PII. Địa chỉ/SĐT hợp lệ có thể xuất trong memory_writes; CCCD/STK không được lưu nguyên văn. `trace_must_not_match` chỉ xét agent_text và memory_writes. Seed_history có thể dùng channel=phone và facts kèm as_of; runner xác minh khách, nhập các phiên/fact vào runtime memory trước cuộc gọi. Facts rỗng được trích từ summary bằng pipeline extraction hiện hành; seed writes không xuất thành lượt chấm. Baseline tắt memory liên phiên.

Mốc M1 gồm RQR giảm tương đối **≥40%**, TSR **≥70%**, HR giá/KM **≤5%**, Call Brief **≤5 giây**, TTFT chat p95 **≤3 giây** và Total p95 **≤8 giây**. Đo ít nhất 100 lượt mỗi cấu hình sau 3 lượt warm-up. TTFT tính đến phần trả lời đầu tiên qua guardrail, Total đến phần trả lời cuối; `response_ms` còn gồm lưu dữ liệu. Kết quả streaming cũ thiếu `total_basis` chưa chứng minh được Total theo mốc BTC. Với hệ thống không streaming, BTC quy ước TTFT bằng Total. Bảy mẫu công khai dùng để thử tích hợp.

Nếu Full và baseline đều RQR=0 thì ngưỡng giảm 40% không áp dụng: báo cáo đưa CCR cho BGK xét, không tự tính giảm 100% hoặc tự đặt ngưỡng CCR. Nếu baseline=0 nhưng Full>0 thì không đạt; thiếu số đo vẫn được báo riêng. Gate tự động không thay kết luận BGK đối với ca cần xét CCR.

## 4. Đánh giá hai vòng cải tiến

1. Chạy `eval` để tạo K0. Workflow nhận kết quả cuộc gọi và điểm đánh giá để tạo đề xuất cần rà soát. Giữ nguyên project eval, code, model, seed và bộ test.
2. Bật giao diện trên project eval bằng `SUBMISSION_DATABASE=telesale_eval_m1 BTC_CALLBACK_MOCK=1 docker compose --env-file .env -f compose.submission.yml -p telesale-btc-eval up -d --build --wait backend`. Nếu demo đang chiếm cổng, đặt `DEMO_PORT` khác trong `.env` trước khi bật. Mở link `/knowledge?run_id=...` mà runner in ra. Reviewer đối chiếu nguồn và regression test, chọn đề xuất rồi duyệt và phát hành. Tạm dừng thao tác UI trong lúc đo.
3. Sau khi release K1 được kích hoạt, thay `<run-k0>` bằng tên thư mục run K0 trong `RESULTS_DIR` và chạy:

```bash
python3 run_submission.py knowledge-eval \
  --base-run "/results/<run-k0>"
```

Đọc bảng so sánh trong thư mục kế bên run K0, có hậu tố `.knowledge`. Báo các chỉ số tăng hoặc giảm trên cùng bộ test và lưu bằng chứng người duyệt. Nếu chưa có bằng chứng cải thiện, ghi rõ trong báo cáo. Ước tính chi phí/cuộc từ usage và đơn giá provider, gồm lượt hội thoại và worker ghi nhớ; ghi rõ cấu hình, phần cứng và giả định.

## 5. ASR local và chấm điểm

BTC không phát audio public D01–D04. Team tự tạo từ kịch bản BTC bằng TTS hoặc giọng thành viên, có thể dùng `asr/make_audio.py` của BTC. Đặt audio và segment theo ID bên cạnh ground_truth đã cập nhật: D01 có entities_multi, D02 là cùng khách với D01. Audio private dùng xếp hạng do BTC giữ và chạy ngày chấm; không cần có bộ private để nộp. Điểm public/team chỉ chứng minh pipeline và phân tích lỗi. Không cần chờ validate_scenarios.py hoặc scenario.schema.json: BTC xác nhận validator là công cụ nội bộ và định dạng mô tả trong scenario_format.md.

Chuẩn bị riêng bộ audio public BTC và bộ team, mỗi bộ có `audio/*.wav` và `ground_truth.json`. Bộ team cần ít nhất **20 file để báo cáo ASR**; corpus nộp M1 cần **40 cuộc audio, tổng ít nhất 1 giờ**. Theo giải đáp mới, không bắt đủ vùng giọng: ghi rõ giọng đang có và hạn chế, không giả giọng hoặc dùng ghi âm khách hàng thật. Đặt `AUDIO_DATASET_DIR` trỏ tới bộ team trước, rồi chạy:

```bash
python3 run_submission.py asr transcribe --audio /audio-dataset/audio --out /results/asr-team
python3 run_submission.py asr eval --dataset /audio-dataset --runs /results/asr-team
```

Đổi `AUDIO_DATASET_DIR` sang bộ BTC và lặp lại với output `/results/asr-btc`. Model chạy local và có thể tải weights lần đầu vào `RESULTS_DIR/models`. Báo riêng WER, CER, độ chính xác số tiền và số điện thoại của hai bộ. ASR chấm theo quy tắc chuẩn hóa của BTC.

Gate nhóm chấp nhận đủ bốn mẫu public khi ground truth, audio và hypothesis được gắn hash đúng; đây là bằng chứng pipeline, không phải điểm private. Scorer BTC hỗ trợ any-match cho entity dạng list và thêm độ chính xác entity theo từng lượt khi có turns/idx. Audio hoặc hypothesis D02 theo bản thoại cũ cần tạo lại/kiểm lại trước khi chấm; không thay ground truth rồi dùng lại điểm cũ.

Với kịch bản có `customer_turns_asr`, harness dùng input đã khai báo cho cả Full và baseline. Để tạo bộ replay từ audio có mốc lời khách, dùng các lệnh `python -m speech prepare-replay`, `export-replay` và `verify-replay`, sau đó gắn bundle vào scenario bằng `python -m eval_harness.asr_inputs` với mapping khách, phiên và ngày đã đối chiếu. Chỉ đưa lời khách đã nhận dạng vào harness. Dùng cùng thư mục kết quả làm `SCENARIOS_DIR` cho hai cấu hình.

Để ghép hai điểm ASR đã lưu vào bảng eval, đặt `BTC_ASR_DATASET_DIR` và `TEAM_ASR_DATASET_DIR` trong `.env` rồi chạy:

```bash
python3 run_submission.py eval \
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
| Mã nguồn và website | URL repo, nhánh `main`, SHA commit nộp bài, file `.env` bàn giao kèm và hướng dẫn chạy tại README này. Web có chat, Call Brief và timeline. |
| Dataset | [Mô tả corpus](dataset/M1-CORPUS.md). Bàn giao archive dữ liệu và checksum riêng. |
| Kiến trúc | [Sơ đồ harness, bộ nhớ và MCP](docs/m1-architecture.md). |
| Báo cáo | [Báo cáo đánh giá M1](docs/btc-m1-evaluation-report.md), gồm kết quả lịch sử, phân tích lỗi và giới hạn bằng chứng. Nộp kết quả Full/baseline, ASR và hai vòng cải tiến gắn với commit được chấm. |
| Video và slide | Video 5–8 phút theo [demo hai phiên](#2-demo-hai-phiên). Slide tối đa 15 trang. [Nội dung slide](docs/btc-m1-slides.md). |

[Hồ sơ diễn tập](docs/btc-submission-evidence.md) ghi nhận đã chạy Docker, đăng nhập, chat hai phiên và xuất trace với provider giả lập. Kết quả điểm chính thức cần dùng commit, dữ liệu và cấu hình thật của bản chấm. Bản dataset diễn tập RC2 có 121 transcript và 22 WAV; các mốc còn thiếu được ghi trong mô tả corpus.

## 7. Chi tiết cấu hình và triển khai

Đối chiếu SHA sau khi clone. `.env` bàn giao là cấu hình chung đã điền đủ cho bản Docker. [`.env.example`](.env.example) liệt kê các tham số để tham khảo hoặc tạo cấu hình khác. Khi BTC dùng key riêng, thay `LLM_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` cùng model/endpoint tương ứng trong `.env`. Đường dẫn tương đối được tính từ gốc repo.

| Biến | Giá trị |
|---|---|
| `BTC_ROOT` | Thư mục BTC có `catalog/`, `policy/`, `schemas/` và `eval/`. |
| `SCENARIOS_DIR` | `./eval/scenario_final` cho bộ team mặc định; `<BTC_ROOT>/test_set/public_sample` để thử mẫu; thư mục JSON bộ ẩn khi BTC chấm chéo. |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Key, ID model và URL API của provider dùng để chạy hội thoại. Có thể đặt `LANGMEM_MODEL` nếu dùng model riêng để ghi nhớ. |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_API_BASE_URL` | Tài khoản/token Workers AI và endpoint embedding, mặc định `https://api.cloudflare.com/client/v4`. Đây là credential riêng với key LLM. |
| `ASR_MODEL`, `ASR_DEVICE`, `ASR_COMPUTE_TYPE` | Mặc định `whisper-small`, `cpu`, `int8`; CLI cho phép ghi đè bằng flag. Model được chạy local. |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_API_BASE_URL` | Chỉ cần nếu tự sinh corpus bằng ElevenLabs; endpoint mặc định `https://api.elevenlabs.io`. Không cần TTS để chấm M1. |
| `POSTGRES_PASSWORD`, `MCP_*_PASSWORD`, `WORKER_PASSWORD`, `REVIEWER_PASSWORD`, `BACKEND_PASSWORD` | Mật khẩu nội bộ đã điền sẵn trong file mẫu; mật khẩu DB dùng chuỗi hex theo script cấp quyền. |
| `MCP_INTERNAL_TOKEN`, `AI_INTERNAL_TOKEN`, `DEMO_JWT_SECRET`, `DEMO_USER_1_PASSWORD`, `DEMO_USER_2_PASSWORD` | Token nội bộ và mật khẩu đăng nhập demo, đã điền sẵn. |
| `SUBMISSION_RUN_AS` | Để trống để lệnh chạy tự lấy UID:GID của người dùng hiện tại; có thể điền UID:GID cụ thể. |
| `RESULTS_DIR` | Mặc định `./results-submission`; lệnh chạy tự tạo thư mục kết quả và thư mục con `models`. |

Chạy bằng `python3 run_submission.py`. Script chỉ cần Python chuẩn và Docker Compose trên host, tự chuẩn bị thư mục kết quả và quyền ghi file. Compose lấy toàn bộ thông tin kết nối nội bộ từ `.env`, cấp cho container qua biến môi trường và secret mount; BTC không cần tạo thư mục `secrets-submission/` hoặc chạy script sinh mật khẩu. Cơ chế này dùng [environment secrets của Docker Compose](https://docs.docker.com/reference/compose-file/secrets/).

Lần setup đầu tải tokenizer đã ghim checksum và có thể dùng quota embedding. Service `setup` nạp nguồn BTC vào PostgreSQL, tạo schema runtime và chuẩn bị chỉ mục chính sách. Compose tự chạy service này trước khi cấp quyền và khởi động MCP; setup thành công mới tiếp tục chạy demo hoặc eval. Setup dùng lại dữ liệu khi nguồn không đổi và từ chối nguồn khác trên DB đã khởi tạo. Mật khẩu trong `.env` phải khớp với database nếu tái sử dụng volume từ lần chạy trước. Nếu dùng loader thủ công với `--prepare-policy`, cần actor có quyền `knowledge_review` và file cấu hình runtime thực, chẳng hạn [config/policy-runtime.json](config/policy-runtime.json). Đường chạy Compose tự chuẩn bị cấu hình cho BTC.

File `.env` bàn giao dùng key/model/endpoint của nhóm để chạy thử. Ngày chấm BTC dùng API key của BTC và thay các giá trị tương ứng trong chính file này; đường gọi LLM dùng API tương thích OpenAI. Model hội thoại lấy từ `LLM_MODEL`; mẫu `.env.example` đề xuất `gpt-6-luna`. `LANGMEM_MODEL` để trống dùng cùng model, nếu đổi phải khai báo ID chính xác. Embedding dùng Cloudflare `@cf/baai/bge-m3`, cấu hình trong `config/policy-runtime.json`; tokenizer local được tải và kiểm checksum ở setup. ASR `whisper-small` ánh xạ tới `Systran/faster-whisper-small`; weights tự tải ở lần transcribe đầu, lưu trong `RESULTS_DIR/models`. Máy không có Internet cần chuẩn bị cache weights/tokenizer cùng phiên bản trước. TTS chỉ dùng khi soạn audio; model/voice được ghi trong cấu hình giọng và manifest của corpus.

Cấu hình tối thiểu dự kiến để bàn giao stack M1 CPU/int8: Linux x86-64, 4 vCPU, RAM 8 GiB và 20 GiB trống cho image/cache/dữ liệu. Không yêu cầu GPU cho cấu hình này. Đây là mức tài nguyên triển khai được khai báo, chưa phải bằng chứng latency trên model/provider thật; báo cáo phải ghi phần cứng thực tế của lần đo.

Bộ team mặc định có 48 kịch bản, 118 phiên tại `SCENARIOS_DIR=./eval/scenario_final`. Khi chuyển từ bản dùng `.env.submission`, dùng file `.env` bàn giao mới. Xem [trạng thái bằng chứng M2](docs/evaluation/m2-readiness.md) cho phần đánh giá nâng cao đang phát triển.

Gói BTC phải được đồng bộ trước khi setup/chấm. Nếu nhận bản ground truth sửa dưới tên `asr/ground_truth copy.json`, đặt bản BTC mới vào đúng `asr/ground_truth.json` trước khi dùng; file đúng có D01 sku/price list và D02 cùng khách D01. Manifest bộ team kiểm hash nguồn và sẽ dừng nếu dùng bản cũ. Khi BTC chạy bộ ẩn, thay SCENARIOS_DIR bằng bộ ẩn của BTC và giữ đúng nguồn đi kèm.
