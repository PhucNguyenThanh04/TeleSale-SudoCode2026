# M1: tiếp tục xử lý ba gate fail của run streaming

Run nguồn: `20261117T092200Z-17b3f18d`. Phạm vi: execution health,
extraction review và TTFT p95. Giữ nguyên ngưỡng, scorer, model và artifact nguồn.

## Thay đổi và kiểm chứng

- Checkout đã chứa sửa lỗi SC-T11 sau thời điểm đo: nhận câu hỏi giao lại,
  chuẩn bị policy/status, giữ tracking prefix cho tới khi đáp án đủ và kết thúc
  business phase nếu model tiếp tục đòi tool sau đáp án đã kiểm tra. Tám regression
  có sẵn đều pass khi kiểm lại; không viết lại các sửa này.
- Sửa tiếp đường tìm sản phẩm chưa có metadata: dùng đúng một nhóm hàng khách
  nêu để tra catalog, giữ diện tích đã khai báo trước câu hỏi tư vấn, nhận
  “trong tầm giá … đổ lại” là trần chi. Shortlist có nguồn và đủ yêu cầu được trả
  qua verifier mà không cần một vòng model diễn đạt lại. Ca SC-T13 qua graph/MCP
  offline trả Xiaomi Smart 4 Lite giá 2.990.000đ, đáp ứng 25m², không tạo đơn.
- Không mở tìm kiếm nhóm chung khi khách nêu mã sản phẩm cụ thể, nhiều nhóm,
  phủ định hoặc giả định. Tra catalog thất bại không được lặp lại trong cùng lượt.
- Extractor nhận lời xin thời gian tra cứu là narrative và câu hỏi yêu cầu cụ
  thể là `product_requirements`; câu hỏi thời gian nhận hàng vẫn được đo.
- Đối chiếu 13 claim chưa xác minh đã tái hiện một khe hở guardrail: câu ghép
  “chưa được xác nhận và bàn giao” và khẳng định hệ thống chưa cập nhật hoàn tất
  giao hàng vẫn lọt qua khi tool chỉ trả `created`. Chặn các suy diễn này;
  recovery trả đúng trạng thái được tra cứu. Năm regression fail trước sửa.
- Hai test double cũ còn dùng giao thức `ainvoke`/`run` được cập nhật sang
  streaming qua adapter test hiện có. Không thay luồng production để chiều test.

Test mới đã được quan sát fail trước khi sửa. Kiểm tập trung bằng
`eval_harness.offline_tests` chặn mạng, credentials và nạp `.env`: batch cuối
285 pass, một warmup double cũ fail; sau sửa double, test đó pass riêng.
Không chạy full suite. `git diff --check` pass.
Sau sửa guardrail, 77 test tập trung về recovery, streaming và bằng chứng thương
mại pass trong 3,38 giây. Các batch có phần chồng nhau, không cộng thành tổng mới.

Log và manifest kiểm chứng:

- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-focused-tests.txt`
- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-warmup-retest.txt`
- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-shipping-tests.txt`
- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-verification.json`

## Replay và review extraction

Replay offline:
`ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-streaming-extraction/`.
Đã đối chiếu hash toàn bộ run nguồn và output replay; nguồn không đổi. Replay
chỉ đổi questions/claims. Không có inference mới và không sửa latency, tool,
memory, speech hoặc facts_used.

Không còn emitted question bất định trên bộ lời đã lưu. Còn 136 claim candidate
cần review. Review có tác giả assistant và dẫn nguồn/hash cho từng quyết định:
110 supported, 13 not_assertion, 13 unverifiable. Không có pending; complete vẫn
false. Đây không phải review độc lập của con người hay bằng chứng extraction recall.

- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-streaming-review.assistant.json`
- `ai-services/eval_harness/results/measurement-audit/20261117-m1-goal-streaming-review.summary.json`

Những điểm chưa xác minh gồm carrier suy từ tracking, quyền miễn phí đổi lần
đầu thiếu lịch sử đổi, vị trí/handover suy từ status, đồng ý giá cũ thiếu lời
xác nhận và các từ bị mask trùng tên riêng. Không gán các điểm này thành đúng.
Điểm BTC trên replay giữ nguyên TSR/HR/CCR. RQR Baseline 54,1% → 52,6% do thêm
câu hỏi yêu cầu sản phẩm vào mẫu số đúng; giảm RQR tương đối 91,7% → 91,4%.
Đây là thay đổi annotation, không phải cải thiện runtime.

## Bằng chứng còn thiếu để kết luận ba gate đạt

Cần một cặp đo mới trên code hiện tại, cùng model Gemma 4 31B/seed 7 và đúng
snapshot 29 scenario. Chưa chạy model thật trong lượt sửa này. Lệnh cụ thể:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
ai-services/.venv/bin/python run_system.py eval --expected-database telesale -- \
  --seed 7 \
  --scenarios ai-services/eval_harness/results/paired-knowledge/20261117T092200Z-17b3f18d/scenarios \
  --btc-root ai-services/eval_harness/results/paired-knowledge/20261117T092200Z-17b3f18d/btc-release \
  --out-root ai-services/eval_harness/results/paired-knowledge
```

Lệnh gọi model cho 170 lượt mỗi cấu hình, warmup và memory worker; sau pair có
knowledge detection mặc định. Runner reset dữ liệu runtime của DB `telesale`
trước mỗi cấu hình, giữ nguồn BTC/knowledge. Chỉ chạy khi được cho phép và DB
này có thể dùng riêng cho eval; không chạy đồng thời phiên chat cần giữ lại.

Sau đo, kiểm execution events, p95 cả hai phía ≤3000ms, review candidate theo
lời mới rồi chạy acceptance. Test offline chưa chứng minh ba gate live đạt.
ASR, hai vòng cải tiến, demo và chi phí vẫn là phần nghiệm thu M1 riêng.

## Run người dùng chạy sau sửa: 20261117T124410Z-8d9e50eb

Kiểm offline lại artifact với `run.json.btc_root`: 19/20 gate hội thoại pass,
chỉ `extraction_review` fail. Execution healthy; TTFT p95 Full/Baseline là
2484/2995ms, Total p95 2504/3015ms. Baseline chỉ thấp hơn ngưỡng TTFT 5ms;
đây là kết quả của run này, chưa chứng minh độ ổn định qua nhiều lần chạy.
SC-T11/call_1/turn2 hoàn tất Full/Baseline trong 501/490ms, trả quy định giao
lại và nói chưa xác minh carrier thay vì suy từ tracking prefix.

Run dùng lại snapshot của run trước. `prepare_btc_release` kiểm tra snapshot
đã đóng băng rồi trả lại chính đường dẫn đó; vì vậy run mới không có thư mục
`btc-release` riêng. Phần console và knowledge follow-up đã giả định đường dẫn
local, gây báo thiếu snapshot và FileNotFoundError dù scoring thành công.

Sửa ba nơi đọc đường dẫn: report, checkpoint follow-up và các bước feedback/
K1/scoring của knowledge experiment dùng `btc_root` đã lưu trong run; giữ fallback
local cho run cũ không có trường này. Cờ `--btc-root` truyền tường minh khi in
report vẫn được ưu tiên. Không đổi cơ chế snapshot, score, ngưỡng hoặc hash guard.
Hai regression tái hiện lỗi trước sửa; 87 test tập trung pass trong 7,09s qua
offline runner chặn mạng. Log: `results/measurement-audit/20261117-external-btc-snapshot-tests.txt`.

Không sửa file trong pair mới hoặc knowledge checkpoint, không retry detection,
không gọi model/worker. Hash pair khớp `k0_digest` đã đóng băng trong checkpoint.
Source đã đổi sau sửa tooling; resume knowledge vẫn phải tuân thủ kiểm source
digest hiện có, không chỉnh checkpoint để vượt kiểm tra này.

Kết quả kiểm lại nằm trong `ai-services/eval_harness/results/measurement-audit/`:

- `20261117T124410Z-8d9e50eb-analysis.json`: gate và lý do snapshot.
- `20261117T124410Z-8d9e50eb-report.txt`: report đọc lại, không inference mới.
- `20261117T124410Z-8d9e50eb-review.pending.json`: 156 candidate của lời mới;
  gồm 63 unresolved claim, 4 câu hỏi bất định, 49 qualified và 40 mapping ngoài
  schema. Template còn pending, không dùng lại phán định của run cũ để duyệt.
