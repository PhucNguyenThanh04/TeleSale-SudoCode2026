# Multisession Memory Contract Implementation Plan

**Trạng thái 2026-10-20:** Đã tạo fixture, oracle và các ca kiểm; kết quả và
gap nằm ở [memory-contract-v1](../../memory-contract-v1.md). Public sample,
MCP HTTP và LLM thật chưa chạy vì chưa có DB eval tách biệt. Các checkbox dưới
đây giữ dạng plan ban đầu; ledger thực thi nằm trong `.superpowers/sdd/`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Có bộ hợp đồng chạy được cho sáu ca memory đa phiên, chỉ ra chính xác hành vi đã đạt và khoảng cách còn lại trước khi sửa runtime.

**Architecture:** Dùng fixture hội thoại tổng hợp và một runner kiểm snapshot sau từng lượt: danh tính, profile active, nguồn fact, episode, Call Brief, tool call, memory write và phần không được lộ. Chạy cùng hợp đồng ở lớp MCP memory, harness với mock BTC, rồi đối chiếu trace thật khi có DB eval tách biệt. Đây là bước chốt hợp đồng; các thay đổi schema/runtime phát sinh từ test đỏ cần plan triển khai tiếp theo dựa trên gap report.

**Tech Stack:** Python 3.12, `unittest`, LangGraph harness hiện có, MCP memory, PostgreSQL, BTC mock và `reference_eval.py`.

**Spec:** `docs/superpowers/specs/2026-10-20-multisession-memory-contract-design.md`.

## Global Constraints

- Giữ nguyên thay đổi chưa commit, đặc biệt các sửa memory và migration 0006 của bước trước; đọc `git status` trước khi sửa.
- Dùng `reference_date=2026-10-15` hoặc `call_date`/`days_later`, truyền `on` cho tool; không tính theo đồng hồ máy.
- `DIEU-CHINH-DE.md`/`GIAI-DAP-MENTOR.md` ưu tiên hơn PDF; `tools.schema.json`, `mock_tools.py`, `reference_eval.py` là chuẩn tương ứng.
- Không đưa `scenario_id`, nhãn đáp án, tên khách, SKU hoặc lời thoại fixture vào nhánh runtime. Giữ các test kiểm bằng chứng hiện có.
- Không dùng PII thật; `price_quoted_vnd` là lịch sử, giá/KM/tồn kho luôn cần kết quả tool mới theo ngày call.
- Không áp migration hoặc chạy public sample trên DB demo/live; `--isolated-db` không tự tạo DB tách biệt.
- Báo test đỏ như gap thật, không `expectedFailure`, không sửa nhãn; không tuyên bố hoàn tất runtime khi hợp đồng còn đỏ.

## Review Focus

- Một số điện thoại trả nhiều ứng viên: snapshot sau cả hai lượt không chứa profile/episode của ứng viên nào. Kiểm ở Task 2.
- Khách ẩn danh được xác minh giữa phiên: lượt cũ không xuất hiện trong episode và profile của người được xác minh. Kiểm ở Task 2.
- Khách nói về hai SKU trong cùng lượt: quote/KM của SKU thứ nhất không được gán cho SKU thứ hai. Kiểm ở Task 3.
- Sau tám tháng, giá/KM/tồn kho và địa chỉ cũ không trở thành dữ liệu hiện hành nếu không có tool mới. Kiểm ở Task 4.
- Yêu cầu xóa từ người chưa xác minh hoặc tool thất bại: agent không nói đã xóa, không lộ PII. Kiểm ở Task 5.

---

### Task 1: Đóng băng dữ liệu hợp đồng và phép kiểm snapshot

**Files:**
- Create: `ai-services/test/fixtures/memory_contract_v1.json`
- Create: `ai-services/test/memory_contract.py`
- Create: `ai-services/test/test_memory_contract_fixture.py`
- Create: `docs/memory-contract-v1.md`
- Modify: `docs/memory-policy.md` (liên kết hợp đồng, không đổi luật đang chạy)

**Interfaces:**
- Produces: `load_cases(path: Path) -> list[dict]` và `check_snapshot(expected: dict, actual: dict) -> list[str]` trong `test/memory_contract.py`. `actual` gồm `identity_status`, `customer_id`, `profile`, `episodes`, `call_brief`, `tool_calls`, `memory_writes`, `agent_text`; so sánh theo trường được khai báo, không đòi các trường khác bằng hệt.
- Fixture mỗi ca gồm `case`, `calls` (ngày/kênh/định danh/lượt), `expected_after_turn` và `forbidden`; phần lời thoại, SKU lấy từ dữ liệu tổng hợp ngoài public sample. Không gửi `case`/`expected_after_turn` vào runtime.

- [ ] **Step 1:** Viết `test_memory_contract_fixture.py` kiểm đủ sáu ca trong spec; mỗi ca có ít nhất hai call khi cần, ngày cố định, một biến thể khác cách nói/sản phẩm và một đối chứng không đổi hành vi.
- [ ] **Step 2:** Chạy `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'test_memory_contract_fixture.py' -v`; xác nhận đỏ vì loader/checker chưa có.
- [ ] **Step 3:** Tạo fixture và hai hàm ở trên. `check_snapshot` trả lỗi có tên trường và call/turn, không in PII hoặc toàn bộ prompt.
- [ ] **Step 4:** Chạy lại cùng lệnh đến khi xanh; `git diff --check`.

### Task 2: Chạy hợp đồng danh tính trên memory và harness

**Files:**
- Create: `ai-services/test/contract_memory_identity.py`
- Read/use: `ai-services/test/test_mcp_memory.py`, `ai-services/test/test_deep_memory.py`
- Read/use: `ai-services/app/mcp_servers/mcp_memory/services/memory.py`, `ai-services/app/agent/harness/context.py`

**Interfaces:**
- Consumes: `load_cases`, `check_snapshot` của Task 1.
- Produces: snapshot sau từng lượt cho ca hai người chung số, xác minh muộn và Fanpage → hotline; chạy được với `FakeGateway`/`FakeMemory` hiện có hoặc fake tách riêng nếu cần, không dùng public sample làm input.

- [ ] **Step 1:** Viết test đọc fixture và chạy chuỗi lượt với session/client_msg_id ổn định; assert không nạp memory ứng viên, không chuyển lượt ẩn danh vào episode/profile, cùng `customer_id` đọc được thông tin xuyên kênh.
- [ ] **Step 2:** Chạy `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_memory_identity.py' -v`; ghi rõ đỏ ở lớp nào hoặc xanh nhờ bước identity trước.
- [ ] **Step 3:** Thêm đối chứng cho cùng lớp lỗi và ghi kết quả; không sửa runtime hoặc nhãn fixture trong bước chốt hợp đồng.
- [ ] **Step 4:** Chạy lại ca Task 2 và `test_mcp_memory`, `test_deep_memory`; lưu kết quả theo ca trong `docs/memory-contract-v1.md`.

### Task 3: Chốt đổi ý và cuộc dài nhiều sản phẩm

**Files:**
- Create: `ai-services/test/contract_memory_updates.py`
- Read/use: `ai-services/app/agent/memory/fact_candidates.py`, `ai-services/app/agent/memory/reported_facts.py`, `ai-services/app/mcp_servers/mcp_memory/services/memory.py`
- Modify: `docs/memory-contract-v1.md`

**Interfaces:**
- Consumes: fixture và snapshot checker của Task 1.
- Produces: báo cáo từng fact với `key`, `value`, `op`, `source`, `source_turn_id`, `on`; với quan sát sản phẩm, báo SKU gắn với quote/KM/tồn kho hoặc ghi gap nếu schema hiện tại không mang được SKU.

- [ ] **Step 1:** Viết test cho lời sửa rõ ràng trong cùng cuộc và ở cuộc sau: giá trị mới active, giá trị cũ vô hiệu; câu hỏi/giả định không đổi fact. Dùng cách diễn đạt khác `SAMPLE-*`.
- [ ] **Step 2:** Viết test 16 lượt/4 sản phẩm, trong đó hai SKU được nhắc cùng lượt; kiểm ràng buộc khách không đổi, quote/KM/tồn kho gắn đúng SKU và giá cũ không được dùng để tạo đơn.
- [ ] **Step 3:** Chạy `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_memory_updates.py' -v`; ghi ca đỏ và vị trí mất dữ liệu. Nếu cần đổi schema lưu nhiều sản phẩm, ghi thành hạng mục thiết kế tiếp theo, không ép bốn SKU vào slot đơn `product_advised`.
- [ ] **Step 4:** Chạy lại test mới và test bằng chứng hiện có (`test_deep_memory`, `test_mcp_memory`, `test_slot_value_domains`); cập nhật bảng gap, gồm đối chứng không được đổi hành vi.

### Task 4: Chốt độ mới sau nhiều tháng

**Files:**
- Create: `ai-services/test/contract_memory_freshness.py`
- Read/use: `ai-services/app/agent/harness/context.py`, `ai-services/app/agent/implementations/business_agent.py`
- Modify: `docs/memory-contract-v1.md`

**Interfaces:**
- Consumes: `on` của call trong fixture; BTC mock là oracle cho kết quả giá/KM/tồn kho theo ngày.
- Produces: snapshot chỉ rõ dữ liệu nào được nhắc như lịch sử, tool nào được gọi lại và thông tin nào bị chặn cho đến khi có kết quả mới.

- [ ] **Step 1:** Viết ca quay lại sau tám tháng với SKU ngừng bán, KM hết hạn và địa chỉ cũ; assert `on` của các tool bằng ngày call mới, không dùng giá/KM/tồn kho cũ như hiện hành, không đưa địa chỉ thô vào prompt/trace.
- [ ] **Step 2:** Thêm đối chứng quay lại sớm khi sở thích bền vững vẫn được dùng, nhưng giá vẫn phải quote lại.
- [ ] **Step 3:** Chạy `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_memory_freshness.py' -v`; ghi gap và nguyên nhân ở lớp truy hồi, TTL hoặc tool, không làm yếu ràng buộc truy vấn để có kết quả.
- [ ] **Step 4:** Ghi rõ `address_ref` chưa triển khai; nếu ca cần đọc địa chỉ thật, đưa vào plan riêng về kho PII và quyền sở hữu, không thêm địa chỉ thô vào memory hiện tại.

### Task 5: Chốt hợp đồng yêu cầu xóa dữ liệu

**Files:**
- Create: `ai-services/test/contract_memory_erasure_request.py`
- Modify: `docs/memory-contract-v1.md`
- Read/use: `ai-services/app/mcp_servers/mcp_memory/schemas.py`, `ai-services/app/agent/guardrails/checks.py`, `ai-services/app/agent/harness/agent_nodes.py`

**Interfaces:**
- Produces: ba trạng thái hợp đồng `unverified_request`, `verified_request_pending`, `authorized_completion`; trạng thái cuối chỉ được dùng khi có thao tác xóa có thẩm quyền và kết quả thành công. Không coi `memory.write` với `op=delete` một fact là xóa toàn bộ khách.

- [ ] **Step 1:** Viết test cho khách chưa xác minh, khách đã xác minh và lỗi tool: agent không nói “đã xóa” nếu chưa có kết quả, không lặp PII, và có đường chuyển xử lý phù hợp.
- [ ] **Step 2:** Chạy `cd ai-services && .venv/bin/python -m unittest discover -s test -p 'contract_memory_erasure_request.py' -v`; báo gap thực tế. Ghi rõ hiện `delete_customer` không có trong schema/action.
- [ ] **Step 3:** Tài liệu hóa phạm vi cần quyết định trước khi làm xóa vật lý: `ai_memory`, CRM seed/runtime, order, checkpoint, trace và backup; người xác thực, kết quả và retention. Không tạo API purge trong bước hợp đồng.
- [ ] **Step 4:** Kiểm đối chứng: yêu cầu xóa một sở thích cụ thể không được hiểu là xóa cả khách; `op=delete` của `blocker` vẫn giữ nghĩa cũ.

### Task 6: Đối chiếu PostgreSQL, BTC và bàn giao gap report

**Files:**
- Modify: `docs/memory-contract-v1.md`
- Read/use: `ai-services/test/test_memory_identity_migration.py`, `eval/run_eval.py`, `../BTC-Data-Vong1-TEAMS/eval/reference_eval.py`

**Interfaces:**
- Produces: bảng sáu ca với trạng thái `unit/mock`, `PostgreSQL`, `MCP HTTP`, `public sample`, `LLM thật`; mỗi gap có lớp gây lỗi, bằng chứng và nhiệm vụ sửa tiếp theo.

- [ ] **Step 1:** Chạy toàn bộ `ai-services`/`backend`/`eval` unit suites và migration test trên `pg_temp` trong transaction rollback; ghi số test và skip. Không áp 0006 lên DB demo/live để kiểm thử.
- [ ] **Step 2:** Khi đã có DB eval tách biệt, nạp cùng seed và chạy full/baseline trên cùng model/tool/tham số; reset trạng thái giữa hai cấu hình. Kiểm JSONL theo `trace_log.schema.json`, rồi chạy `reference_eval.py` cho RQR/CCR/TSR/HR. Nếu chưa có DB eval, ghi “chưa chạy”, không thay bằng unit xanh.
- [ ] **Step 3:** Đối chiếu public sample như phép kiểm bổ sung; liệt kê bất kỳ mâu thuẫn nào giữa sample và nguồn chuẩn mà không sửa runtime/trace để tăng điểm.
- [ ] **Step 4:** Hoàn thiện `docs/memory-contract-v1.md`: hành vi đã đạt, test đỏ, rủi ro dữ liệu legacy không có claim operation key, và thứ tự plan sửa runtime tiếp theo. Chạy `git diff --check`.

Các file `contract_*.py` được chạy tường minh và có thể đỏ trong bước khảo sát;
`unittest discover -s test` mặc định vẫn là gate hồi quy hiện có. Báo cáo phải
ghi số ca đỏ và lệnh tái hiện, để việc tách gate không che lỗi.

## Handoff

Kết thúc plan này khi hợp đồng và gap report đủ để chọn bản sửa tiếp theo. Không đánh dấu sáu ca là runtime đạt chỉ vì fixture/test được viết; ca đỏ phải còn nhìn thấy trong báo cáo. Thứ tự sửa sau đó: cập nhật fact rõ ràng → nhiều sản phẩm → độ mới theo ngày → quy trình xóa dữ liệu có thẩm quyền. Giữ việc xử lý identity và migration 0006 của bước trước trong cùng đợt review trước khi triển khai.
