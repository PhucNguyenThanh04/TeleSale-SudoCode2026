# M1: chạy, kiểm chứng và bàn giao

Phạm vi là M1 của đề gốc và các điều chỉnh BTC, không dùng bảng trọng số trong
`DANH_GIA_BTC_VA_AI_SERVICES.md` làm rubric chính thức. Dataset do thành viên khác
chuẩn bị; phần dưới nhận, kiểm tra và chạy dữ liệu đó, không tự sinh dataset.

## 1. Phân biệt ba loại bằng chứng

- Test offline chứng minh hợp đồng/luồng xử lý với model, I/O hoặc repository giả.
  Không chứng minh TSR, chất lượng tiếng Việt hay tốc độ của model thực tế.
- Run `validated` chứng minh các artifact được pipeline xuất/chấm đúng hợp đồng.
  Nó vẫn có thể có execution degraded, extraction cần review và chưa đạt KPI.
- Nghiệm thu M1 cần cả hội thoại, ASR, vòng cải tiến và demo. Công cụ
  `m1_acceptance` chỉ kết luận phần hội thoại; không gọi kết quả đó là toàn bộ M1.

## 2. Chat demo M1

Dùng gateway đang có, không dùng `backend/app/main.py` cũ: các module của entrypoint
đó không còn đầy đủ trong checkout. Gateway không yêu cầu PostgreSQL/Redis riêng;
AI và các MCP vẫn cần database/worker theo `ai-services/README.md`.

```bash
backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/chat`. Không cần microphone hoặc speech service cho chat.
Token nội bộ nằm trong backend/.env, không đưa vào trình duyệt. Đây vẫn là gateway
demo không đăng nhập như chế độ voice hiện có, không phải triển khai tổng đài thật.

1. Nhập kênh, định danh đúng CRM và ngày nghiệp vụ. Bắt đầu phiên sẽ nhận diện
   khách và nạp brief qua API chuẩn bị phiên trước tin nhắn đầu tiên.
2. Trao đổi nhu cầu, xem tư vấn/báo giá, nói cần hỏi người nhà. Quan sát kết quả
   memory thực tế bên dưới câu trả lời; pending/failed không được coi là đã nhớ.
3. Chờ worker hoàn tất, kết thúc phiên, tăng ngày và bắt đầu phiên mới với cùng
   khách. Brief phải hiện lịch sử sản phẩm/giá và bước tiếp theo.
4. Xác nhận lựa chọn và báo giá hiện tại để tạo đơn. Retry không được tạo thêm đơn.
5. Làm tương tự với đổi variant, đổi kênh định danh của cùng khách và thay đổi
   giá/KM. Không sửa dữ liệu nguồn BTC để làm đẹp kết quả.

Không giả định một số điện thoại do khách gõ trong tin nhắn là bằng chứng sở hữu.
Khách chưa xác minh hoặc dùng chung số phải giữ ranh giới danh tính hiện có.

## 3. Nhận dataset và ASR

Dataset scenario cần `scenario_id`, khách/kênh/định danh, các `call_1..call_n`,
ngày nghiệp vụ, lượt khách, mục tiêu và `success_if`. Phiên quay lại cần nhãn
`must_carry_over` và `must_not_ask` thích hợp. Giá/KM phải khớp BTC theo ngày gọi.
Khóa bản đã review để cả full/baseline và hai vòng cải tiến dùng cùng nội dung.

Kiểm offline, không gửi request:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.m1_acceptance dataset /path/to/scenarios --btc-root ../BTC-Data-Vong1-TEAMS
```

CLI trả mã 1 khi thiếu ngưỡng. Độ phủ scenario tối thiểu: 20 ca đa phiên và 5 ca
khó. Đây không thay cho kiểm quy mô corpus 120 transcript, 40 audio/1 giờ,
30 khách đa phiên, 10 khách đa kênh và 2 miền giọng do người làm dataset bàn giao.

Speech bàn giao replay đã seal theo `speech/README.md` §11. Harness cần mapping
tường minh giữa identity/session của replay với scenario/call, không tự ghép file
thành cùng khách. Ví dụ bindings (lưu ngoài dataset gốc):

```json
{
  "schema_version": 1,
  "identities": {"customer-ref": "CASE-01"},
  "sessions": [
    {"scenario_id": "CASE-01", "call": "call_1", "session_key": "session-one"},
    {"scenario_id": "CASE-01", "call": "call_2", "session_key": "session-two"}
  ]
}
```

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.asr_inputs --scenarios /path/to/scenarios --btc-root ../BTC-Data-Vong1-TEAMS --bundle /path/to/sealed-replay --bindings /path/to/bindings.json --out /path/to/new-asr-scenarios
```

Adapter kiểm hash clip, chỉ dùng lời khách đã ASR, kiểm ngày/khách/thứ tự/số lượt
và giữ nhãn ở phía scorer. Không gửi lời nhân viên hoặc đáp án vào input của model.
Output mới có `customer_turns_asr` và provenance; dùng nguyên output đó cho cả hai
cấu hình. Lệnh này chỉ chuẩn bị input, không chạy ASR hoặc harness.

ASR cần báo cáo trên audio BTC và ít nhất 20 file nhóm. `speech eval` vẫn dùng
scorer BTC; score mới bổ sung hash GT/hypotheses/run metadata/audio và độ chính xác
riêng cho số tiền/SĐT. Báo cáo cũ thiếu binding phải được chấm lại offline trên
hypotheses đã lưu, không tự coi là bằng chứng đã xác minh.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.asr_evidence --group btc --dataset /path/to/btc-asr-dataset --run /path/to/btc-asr-run --btc-root ../BTC-Data-Vong1-TEAMS
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.asr_evidence --group team --dataset /path/to/team-asr-dataset --run /path/to/team-asr-run --btc-root ../BTC-Data-Vong1-TEAMS
```

Không lấy trung bình các tỷ lệ WER của nhiều corpus để gọi là WER tổng. Báo riêng
hai nhóm, hoặc chấm lại corpus gộp bằng scorer nếu cần số tổng. Tập dev đã dùng
để chỉnh lexicon phải được ghi là dev, không gọi là holdout.

## 4. Chạy cặp full/baseline

Đây là bước **LIVE**: gọi LLM và reset runtime của database eval. Chỉ thực hiện
sau khi đã được phép dùng model và xác nhận database được reset. Cả bốn MCP và
worker phải cùng trỏ vào database eval tách riêng; `--expected-database` kiểm tra
đích, không tự tạo/cấu hình database hay biến database demo thành an toàn để reset.

```bash
AGENT_GUARDRAILS_ENABLED=true PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.run_official --scenarios /path/to/frozen-scenarios --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale_eval_m1 --out-root ai-services/eval_harness/results
```

Chọn profile API trong cấu hình trước khi chạy và giữ nguyên giữa full/baseline.
Deep Agent dùng streaming có guardrails cho text; không còn tùy chọn local LLM,
ReAct hoặc text không streaming. Chạy smoke trên 7 sample trước khi chạy tập lớn nếu chưa kiểm tích hợp.
Smoke không thay cho nghiệm thu về độ phủ hoặc p95.

Đọc số lưu và kiểm bằng chứng:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.report_metrics /path/to/run
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.m1_acceptance run /path/to/run --btc-root ../BTC-Data-Vong1-TEAMS
```

Cổng hội thoại: TSR >=70%; HR giá/KM <=5% với denominator khác 0; RQR giảm tương
đối >=40%. Baseline RQR=0 không chứng minh giảm 40%. Kiểm extraction cần review;
không thay câu nói của agent hoặc sửa ground truth theo output để đạt điểm.

Call Brief <=5 giây; chat TTFT p95 <=3 giây; total p95 <=8 giây. P95 cần ít nhất
100 lượt/cấu hình sau warmup. Runner phân biệt prepare, response và worker wait.
Chat lưu phần trả lời đã phát trước sự kiện `done`; voice lưu sau playback.
Chat M1 hiện dùng cơ sở `streaming_guarded_answer_delta`: TTFT tới delta trả lời
đầu tiên đã qua guardrails; Total tới hoàn tất nội dung và persistence. Báo cáo
không streaming cũ vẫn được đọc theo quy tắc 7 (`TTFT = Total`) và không được
đổi thành số đo streaming. Voice giữ TTFT proxy và không được dùng để tuyên bố
đạt chat M1. M1 không yêu cầu TTFA/TTS.

## 5. Knowledge Gap Loop hai vòng

Workflow đã có: feedback -> job/gap -> draft revision/test -> reviewer approve
-> prepare release -> activate, có kiểm source hash, CAS và rollback.
API nội bộ `/v1/knowledge/events` nhận `business_outcome`, `evaluation_result`,
`operator_feedback`, `runtime_signal`. Runtime tự thu outcome/fallback khi
knowledge được cấu hình; xác nhận thực tế có ít nhất hai nguồn feedback theo đề.
Không dùng lỗi hạ tầng hoặc một lần model bịa giá làm nguồn chính sách mới.

Xuất feedback từ score/trace đã kiểm hash (offline):

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.evaluation_feedback --run /path/to/round0 --btc-root ../BTC-Data-Vong1-TEAMS --out /path/to/new-feedback.jsonl
```

Thêm `--ingest` chỉ khi được phép ghi vào AI service local đang cấu hình. Events
được ghi idempotent vào cùng queue; thao tác này không duyệt hoặc phát hành tri
thức. Khi retry, dùng output mới hoặc gửi lại events đã xuất với nguyên key.
Execution thiếu diagnostics/không khỏe được phân loại technical để không tự học
lỗi hạ tầng thành chính sách.

Thứ tự thực hiện:

1. Khóa code, model/tham số, phần cứng, BTC seed và bộ test; chạy vòng 0.
2. Đối chiếu failure với trace, đưa feedback vào workflow. Reviewer phân biệt
   thiếu nguồn, retrieval, generation và technical. Giá/KM động không được viết
   thành FAQ cố định.
3. Dùng API nội bộ có xác thực để `create_revision`, duyệt nguồn và regression
   bằng `approve`, rồi `prepare_release`/`activate_release` với expected active ID.
   Có thể cấp quyền reviewer bằng `python -m app.knowledge.cli grant --actor ID`.
   Không tự duyệt nội dung chỉ để hoàn tất demo.
4. Giữ nguyên test/model/code, chỉ thay knowledge release đã được duyệt, chạy vòng 1.
5. Kiểm so sánh, đọc từng ca hồi quy và chỉ xác nhận gap đã giải quyết sau review.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.improvement_evidence /path/to/round0 /path/to/round1 --btc-root ../BTC-Data-Vong1-TEAMS
```

Công cụ kiểm hash, thứ tự hai vòng, cùng model/seed/code/phần cứng/test, knowledge
release khác nhau và metric delta. Kết quả giống nhau, thiếu metric, execution
không khỏe hoặc extraction chưa xác minh không được coi là cải tiến đã chứng minh.
Đây là phép so sánh Knowledge Gap Loop; nếu đổi code/prompt/model thì cần thiết kế
thí nghiệm khác, không gán delta cho riêng knowledge release.

## 6. Chi phí và hồ sơ demo

Đề cho dùng API nhưng cần ước tính chi phí/cuộc. Chưa có usage/pricing đã xác minh
cho model đích thì ghi **chưa ước tính**, không coi chạy local là chi phí bằng 0.
Không dùng riêng giá quảng cáo/model parameter count để suy chi phí.

Với API tính theo token, ghi rõ provider/model, ngày giá, loại tiền và giả định:

```
Chi phí LLM/cuộc = (token input hội thoại + token input memory)/1e6 * giá input
                + (token output hội thoại + token output memory)/1e6 * giá output
```

Tính cả request tool-loop/retry và memory worker; ghi riêng cache discount nếu có.
Nếu chỉ đo được hội thoại thì báo chi phí thành phần, không gọi là toàn bộ cuộc.
Với local: ghi phần cứng, thời gian GPU/CPU và đơn giá/giả định phân bổ. ASR local
tách riêng; TTS/voice là phần mở rộng, không bắt buộc để hoàn thành M1.

Hồ sơ nghiệm thu cần: version code/config không chứa secret, hash dataset,
run/score/manifest/trace hai cấu hình, báo cáo ASR, hai vòng feedback và release
approval, video/demo hai phiên, hướng dẫn chạy, giới hạn và ước tính chi phí.

## 7. Trạng thái hiện tại

Đã có kiểm offline cho memory/admission, identity đa kênh, selection/variant,
offer thay đổi, exactly-once order, handoff, chat/voice lifecycle và UI Chrome.
Chưa dùng các test đó để tuyên bố đạt KPI runtime.

Còn cần: dataset bàn giao đúng quy mô; cho phép và chuẩn bị database eval tách
riêng; chạy model đích, đo latency thực, ASR đủ tập, hai vòng knowledge đã review,
usage/giá API hoặc giả định chi phí local và demo với dịch vụ thật.

Tài liệu kiến trúc: [m1-architecture.md](m1-architecture.md). Phân tích hơn 10 lỗi
ở mốc trước sửa: [m1-error-analysis-20261109.md](m1-error-analysis-20261109.md).
Theo mục F của đề gốc, video nộp dài 5–8 phút và slide tối đa 15 trang; video cần
ghi demo với dịch vụ thật, không dùng browser test với model giả làm bằng chứng.
