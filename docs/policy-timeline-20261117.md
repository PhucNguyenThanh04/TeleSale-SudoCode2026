# Policy contract và timeline khách — 17/11/2026

Đã thực hiện spec → plan → triển khai → kiểm chứng offline trong checkout hiện
tại. Không model/embedding live, DB/reset/migration, worktree/subagent hoặc commit.
Không sửa scorer, scenario, dữ liệu BTC hoặc trace cũ.

- [Spec](superpowers/specs/2026-11-17-policy-timeline-design.md).
- [Plan và ledger](superpowers/plans/2026-11-17-policy-timeline.md).

## 1. Ca guardrail policy

Tái hiện ban đầu: case có ngày đơn đã xác minh lấy được evidence, grounding
pass, nhưng verifier từ chối với `policy_question_unanswered`. Fixture gọi
query `đổi trả` trong khi followup contract đối chiếu câu hỏi đầy đủ; test có
ngày đơn nhưng không mô tả câu hỏi theo đơn hoặc khai báo owned order cho task.

Sửa **fixture integration**, không nới guardrail production:

- Trường hợp verified hỏi về đúng OD-TEST, có owned order và order.status.
- Query lấy từ `followup_task(state).policy_query`, qua BusinessTools/MCP thật;
  kiểm search đó có được `policy_call_for_task` nhận đúng binding hay không.
- Giữ nguyên các expected: nguồn/ngày xác minh được trả lời 7 ngày; ngày khách
  tự khai chỉ được giải thích có điều kiện; entitlement chưa xác minh bị chặn.
- Thêm negative tests cho query, order_date, order binding và release khác.

Batch policy ban đầu sau sửa: **26 passed**. Các case này cũng nằm trong batch
AI/memory/policy cuối **79 passed**. Không dùng sửa test để tuyên bố model thật
đã tăng TSR hoặc hết lỗi policy trên mọi cách hỏi.

## 2. Timeline M1

### Đường đi

`/chat` → authenticated `POST /api/chat/timeline` → internal-token
`POST /v1/chat/sessions/timeline` → runtime bound session →
`MCPMemoryStore.read_timeline` → `memory.timeline` → projection/runtime metadata.

Timeline chỉ được đọc sau prepare, đúng channel identity/ngày đã bound. Gateway
lấy identity từ account; HTTP không nhận customer_id, verified identity hay
CRM history từ browser. Unknown/ambiguous/baseline no-prior trả not_applicable.
Không tạo session bằng thao tác đọc lịch sử và không gọi inference/CRM lại.

### Nội dung và tính đúng

- Item public: session_id, ngày nghiệp vụ, kênh, summary, outcome, summary_status.
  Không trả transcript, profile, proposal hoặc tool payload. Summary mask PII.
- Gộp episode được chọn theo completed revision, metadata runtime.turns/jobs
  và lịch sử CRM đã có trong identity. Trùng session_id gộp một bản.
- Không dùng top-5/relevance của prompt. Sắp ngày giảm dần, session_id tie-break
  ổn định; mặc định 10/page, limit 1..20, total/next_offset rõ ràng.
- Ngày chỉ là ngày nghiệp vụ đã lưu; không suy ra giờ/phút hoặc thứ tự trong
  ngày từ UUID. Không lấy summary/CRM ở ngày tương lai gắn vào metadata cũ.
- Bản partial/pending không thay summary đã xác minh. Chưa có summary hiện
  thông báo rõ; pending có nhãn đang cập nhật. Outcome `khac` của lời cảm ơn
  cuối không xóa kết quả chốt đơn/hẹn lại đã có.
- Khóa erasure/customer, kiểm owner trước đọc/merge; episode deleted/inactive
  không hồi sinh bằng runtime/CRM fallback hoặc thay ngày nghiệp vụ.
- Page/error được validate ở AI và gateway; upstream sai identity/pagination
  hoặc malformed không được đưa tới browser. Response dùng Cache-Control:no-store.

### UI

Có khối “Lịch sử tương tác”, “Xem thêm” và “Tải lại lịch sử”. Tải HTTP riêng
sau ready, không chặn websocket/chat và không chờ LLM tạo lại summary. Refresh
khi memory completed. Lỗi tải khác lịch sử rỗng; lỗi đọc xóa dữ liệu đang hiện.
Abort/version guard bỏ response cũ khi refresh, kết thúc hoặc mở phiên mới.
Render bằng textContent, không diễn giải HTML trong summary.

CSS chỉ đổi thẻ conversation của chat sang chiều cao theo nội dung; không đổi
bố cục voice. Đã xem screenshot Chrome và kiểm bounding boxes để lịch sử không
tràn khỏi container. Danh sách có vùng cuộn để không đẩy toàn bộ cuộc chat.

## 3. Kiểm chứng

| Phạm vi | Kết quả cuối |
|---|---|
| AI/memory/policy focused | **79 passed**, 4,61 giây; một warning deprecation thư viện |
| Gateway/UI focused | **16 passed**, 4,27 giây; một warning TestClient và cảnh báo cấu hình pytest_asyncio |
| Chrome | Ba bài text browser qua, gồm hai bài timeline mới |
| Policy gốc | RED: 1 fail/2 pass trong ba case; GREEN sau sửa contract, negative controls vẫn chặn |
| Lớp mới | Đã quan sát RED trước khi thêm service, API, route và UI |
| Trace lịch sử | SHA256 vẫn khớp report TCA của goal trước |
| Whitespace | `git diff --check` qua |

Các regression timeline phát hiện/sửa trong self-review: summary tương lai
không được gắn vào phiên cũ; tombstone không bị fallback hồi sinh; outcome
mặc định của lượt cuối không xóa kết quả phiên. Browser test xác nhận chat
vẫn gửi/nhận khi fetch lịch sử bị giữ lại, response muộn không lấn phiên mới,
error/retry/empty/not-applicable, xem đủ 12 phiên, đổi kênh và full page reload.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/test/test_memory_timeline.py ai-services/test/test_memory_timeline_api.py \
  ai-services/test/test_policy_integration.py ai-services/test/test_policy_rules.py \
  ai-services/test/test_policy_agent_evidence.py ai-services/test/test_mcp_memory.py \
  ai-services/test/test_scoped_memory_service.py ai-services/test/test_turn_memory_status.py \
  ai-services/test/test_memory_erasure_contract.py ai-services/test/test_memory_quality_contracts.py --tb=short

PYTHONPATH=backend backend/.venv/bin/python -m pytest -q \
  backend/test/test_text_timeline.py backend/test/test_text_gateway.py \
  backend/test/test_text_browser.py --tb=short
```

AI tests dùng wrapper chặn mạng, loại credentials và không đọc `.env`. Gateway
tests dùng MockTransport; browser dùng Chrome/loopback với AI/store giả lập,
không mở mic hoặc gọi speech/model/DB. Ảnh và biên bản được lưu ở
`ai-services/eval_harness/results/policy-timeline-20261117/` (Git ignored).

## 4. Cách xem trên hệ thống đã cấu hình

1. Khởi động stack demo theo README hiện có; không cần migration/dependency mới.
   Dùng một AI worker theo kiến trúc hiện tại và chạy LangMem worker nếu muốn
   tóm tắt mới được enrich.
2. Đăng nhập `/chat`, chọn kênh/ngày và bắt đầu phiên của khách đã nhận diện.
   Call Brief và lịch sử là hai khối riêng.
3. Trao đổi, đợi memory hoàn tất; lịch sử tự tải lại. Kết thúc, chọn kênh khác
   cùng account, bắt đầu phiên mới và xem lịch sử xuyên phiên/kênh.
4. “Xem thêm” đọc các page tiếp; “Tải lại lịch sử” lấy lại page đầu.

Không tự chạy startup/eval live để kiểm tài liệu. Nếu memory read thất bại hoặc
erasure đang chặn, UI thông báo chưa tải được, không giả là chưa từng tương tác.

## 5. Giới hạn

- Chưa smoke PostgreSQL/stack/model thật trong goal này; SQL được kiểm contract
  với async fake connection. Không tự nhận đã đạt số latency/TSR mới.
- Read timeline có budget 2 giây ở memory service; runtime có budget 3 giây cho
  MCP. Bản M1 scan metadata/episode của riêng khách rồi paginate, chưa tối ưu
  keyset/index cho khách có lịch sử rất lớn. Đã ghi shortcut ngay trong code.
- Phân trang offset không phải snapshot bất biến. Khi có thay đổi đồng thời ở
  phiên khác, dùng “Tải lại lịch sử” để lấy danh sách mới; không phải live feed.
- Dữ liệu cũ có thể thiếu summary đã xác minh; hiển thị thiếu thông tin đúng
  thực tế. Không dùng LLM để bịa hoặc lấp nội dung lịch sử còn thiếu.
- Các file source mới phải được đưa vào bản nộp; screenshot/result ignored cần
  artifact bundle riêng nếu muốn gửi BTC. Đây là nghiệm thu hai phần này,
  không phải kết luận hoàn thành toàn bộ M1/M2.
