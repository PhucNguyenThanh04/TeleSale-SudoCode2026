# Kết quả triển khai BTC eval harness repair — 2026-11-04

Spec và plan đã được người dùng duyệt. Đã triển khai trong checkout hiện tại,
không tạo worktree/sub-agent, không stage hoặc commit.

Đã kiểm chứng offline; chưa xác minh live.

## Thay đổi

- Hai CLI dùng chung runner/adapter, giữ identity và ngày/ASR; cả full và
  baseline chờ job, thu accepted writes và ghi lại JSONL sau backfill.
- Loader kiểm đầu vào trước model/reset; hỗ trợ directory/bundle và snapshot
  đúng dataset để scorer đọc. `dry-run` cũ trả lỗi hướng dẫn thay vì chạy thật.
- Preflight kiểm bốn MCP, release/index readiness và DB của chính runner
  trước warm-up. Các probe trả endpoint server thực; reset giữ phạm vi runtime.
- `seed_history` hỗ trợ dạng session CRM được ghi trong README, scope theo
  scenario/identity; baseline không đọc lịch sử đó, không có turn/writes giả.
- Questions giữ `other`; claims bổ sung policy, `is_human`, tiền nhỏ/số chữ,
  phủ định/correction và lịch sử. Giá trị sai agent nói vẫn được chấm là sai.
- Brief giữ kiểu dữ liệu; kiểm raw schema trước mask. Safe evidence giữ
  dấu vết PII/redaction mất bằng chứng; trạng thái invalid không có điểm
  chính thức. Worker/turn/artifact failure có trạng thái failed.
- Ba warm-up riêng có gateway chặn ghi; TTFT=Total nonstream, giữ đủ scored
  turns và cảnh báo dưới 100 lượt. Chỉ xuất brief latency có phép đo thực.
- Pair publication ghi artifact trước trạng thái cuối; standalone report dùng
  completed, chỉ pair qua audit/scorer mới có validated. README có lệnh dùng.

## Kiểm chứng

Từ `ai-services/`, profile offline bỏ `.env`/secret phát triển và chặn socket
network cả trong Python subprocess. Không gọi API/model/MCP/DB thật.

```bash
.venv/bin/python eval_harness/offline_tests.py eval_harness \
  ../eval/test_run_eval.py ../eval/test_trace_audit.py ../eval/test_score_pair.py \
  test/test_mcp_gateway.py test/test_mcp_knowledge.py test/test_policy_search.py \
  test/test_scoped_context.py test/test_knowledge_releases.py -q
```

Kết quả: **202 passed, 4 skipped**, 16,06 giây. Bốn test DB opt-in bị bỏ qua.
Sau khi thêm/sửa ca lỗi ghi sidecar cuối cùng, chạy lại riêng
`../eval/test_run_eval.py`: **12 passed**, 2,19 giây. Hai kết quả có test trùng
nhau; không cộng chúng thành tổng số test khác nhau.

Fixture stateful đi qua cả root/benchmark entry point và scorer BTC nguyên
bản: HR wrong=1/total=2, RQR redundant=1/total_questions=3, CCR used=1/required=2,
claims_human=1; hai task cố ý thất bại. Re-score trực tiếp tái tạo cùng report.
Đây là dữ liệu tổng hợp để kiểm harness, không phải điểm chất lượng agent thật.
CLI help/offline-check/retired-dry-run và syntax/whitespace cũng đã được kiểm.

Chỉ thử full regression **một lần**:

```bash
.venv/bin/python eval_harness/offline_tests.py test eval_harness ../eval -q
```

Dừng collection vì test cũ `eval/test_memory_facts_baseline.py` import
`app.agent.memory.fact_candidates` không còn tồn tại. Không có test nào chạy
trong lần full này; không sửa module ngoài phạm vi và không chạy lại full.
Không kết luận full regression đã đạt.

## Quyết định triển khai và giới hạn

- Bổ sung nhỏ vào probe DB của shared/memory repository và knowledge
  `release_ref`: cần endpoint thực và ready/index verification để preflight
  có ý nghĩa. Không đổi business rules.
- Giữ nguồn scenario snapshot nguyên vẹn cho reproducibility; snapshot là
  input, không phải public trace đã mask. Quyền truy cập như dữ liệu nguồn;
  không chia sẻ snapshot có thông tin riêng tư.
- Nhãn extraction mới nằm trong bảng test viết tay; không sinh expected bằng
  implementation. Regex vẫn có giới hạn diễn đạt, cần đối chiếu tay.
- Self-review theo năm Review Focus của plan, không có reviewer độc lập theo
  yêu cầu không dùng sub-agent của người dùng.
- Trước live cần stack chạy phiên bản mới của các MCP probe/knowledge service;
  chưa rebuild/restart dịch vụ. Chỉ chạy cặp thật/reset sau ủy quyền riêng.

## Sửa lỗi preflight từ run thực ngày 2026-11-04

Run `20261104T155524Z-5548075f` failed trước khi có conversation trace.
Probe chỉ đọc cho thấy catalog/order/memory vẫn báo hostname cấu hình cũ;
knowledge có tool eval.database_identity nhưng ném lỗi UnitOfWork không có
execute. Nguyên nhân: Database.database_identity dùng transaction() bị
KnowledgeRepo override để trả domain UnitOfWork.

Đã sửa probe lấy raw SQLAlchemy session trực tiếp, không qua override và
không lấy advisory lock. Thêm regression test bằng chính lớp KnowledgeRepo.
Đồng thời report/coordinator/CLI giữ phase, mã lỗi cố định và service, không
lưu raw exception/DSN/PII. Artifact run cũ giữ nguyên.

Kiểm chứng: 16 passed, 2 skipped cho service preflight, coordinator và reset.
Đã thử probe mới qua PolicyRepository trên DB thật ở chế độ chỉ đọc: thành
công. Không chạy model/reset/rebuild/restart hoặc chạy lại eval. Cần người
vận hành rebuild bốn MCP để cập nhật code trong image trước lần eval mới:

```bash
# Từ root repo
docker compose --env-file .env --env-file ai-services/.env up -d --build --no-deps \
  mcp-catalog mcp-order mcp-memory mcp-knowledge
```

## Sửa contract warm-up từ run 20261104T160016Z-55b3c8f5

Run đã qua preflight rồi failed ở warmup. Tái hiện offline bằng graph thật,
MCPMemoryStore thật và model giả cho thấy WarmupGateway trả memory.write
thiếu turn_no. Persist yêu cầu turn_no là integer >= 1 nên ném
memory_turn_write_failed; test trước mock runtime.run đã không kiểm contract này.

Đã sửa response warm-up thành `{turn_no: 1, memory_writes: []}`: mỗi warm-up
là session riêng một turn, không ghi store thật và không đưa synthetic writes
vào trace scored. Regression test chạy ba warm-up qua graph/memory adapter
thật, kiểm ba session riêng và không có external tool call.

Kiểm chứng focused latency/parity/lifecycle: 9 passed, 1 skipped (2,49 giây).
Không gọi model thật, không reset DB hoặc chạy lại eval. Thay đổi nằm trong
harness chạy trên host, không cần rebuild MCP cho riêng bản sửa này.

## Hiển thị tiến độ CLI

Coordinator trước đây capture cả stdout/stderr nên terminal không có tiến
độ. Đã cho child stdout kế thừa terminal, chạy Python -u, giữ stderr private.
Log chỉ ghi phase, chỉ số scenario/turn, warm-up và trạng thái chờ memory;
không in lời khách, câu trả lời hay tool args. Test subprocess options và
nhóm coordinator/latency/parity: 10 passed. Kiểm tra không còn eval process
trước khi sửa; không tự chạy lại eval hoặc thay artifact run đang có.
