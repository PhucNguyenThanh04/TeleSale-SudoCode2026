# Sửa contract policy integration và timeline bộ nhớ M1

## Phạm vi

Người dùng giao tự spec → plan → execute hai phần đã thảo luận: xác định/sửa ca
guardrail policy đang fail và thêm timeline khách trên chat. Checkout hiện tại,
không worktree/subagent/commit; giữ thay đổi có sẵn. Không live eval, DB reset,
model/embedding, sửa trace/scorer/BTC, ASR hay Exemplar.

## 1. Policy

Đã tái hiện offline: retrieval và grounding đạt, nhưng
`policy_question_unanswered` khiến câu 7 ngày thành fallback. Test dùng query
`đổi trả`, trong khi `followup_task` dùng câu hỏi đầy đủ; có ngày đơn nhưng câu
hỏi/state không thể hiện đơn thuộc khách theo followup contract.

Sửa fixture qua cùng `followup_task`/query/order binding mà harness thật dùng,
giữ nguyên expectation: verified date được trả lời đúng nguồn, reported date
chỉ giải thích có điều kiện, không xác nhận entitlement chưa chứng minh. Thêm
negative tests cho query/ngày/order binding/release lệch; không nới production
guardrail chỉ để test xanh. Nếu test đúng contract vẫn fail thì tìm và sửa đúng
runtime, không đổi expected output để che lỗi.

## 2. Timeline

- Thêm `memory.timeline` read-only, adapter MCPMemoryStore và AI endpoint
  `POST /v1/chat/sessions/timeline`. Backend có endpoint cookie-authenticated
  `POST /api/chat/timeline`, lấy channel identity từ account, không từ browser.
- Runtime chỉ đọc cho session đã chuẩn bị, đúng fingerprint/channel và ngày
  bound. Unknown/ambiguous/baseline no-prior trả not_applicable, không lookup
  khách tùy ý. Không gọi LLM, không đưa timeline vào prompt, không prepare lại.
- Memory service khóa erasure/customer như memory.read, kiểm session owner và
  erasure barrier. Đọc episode versions và chỉ chọn completed revisions; không
  dùng proposal/partial version. Runtime sessions chưa có summary hiện thông báo
  chưa có tóm tắt được xác minh. Summary version có tombstone/inactive không
  được hồi sinh bằng fallback runtime/CRM.
- Gộp episode hợp lệ, metadata phiên runtime và CRM sessions đã có trong trusted
  identity. Khách không được gửi CRM history/customer_id qua HTTP. Chỉ đọc lịch
  sử không sau ngày nghiệp vụ của phiên. Trùng session_id gộp một bản.
- Phân trang theo ngày giảm dần, session_id làm tie-break ổn định (không suy ra
  giờ thực từ UUID). Page mặc định 10, limit 1..20, offset >=0, total/next_offset
  rõ ràng. Không dùng top-5 episode theo relevance làm toàn bộ lịch sử.
- Item public: session_id, on, channel, summary <=800 ký tự, outcome,
  summary_status (ready/pending/unavailable). Không transcript, tool payload,
  profile hay PII thô. Summary mask PII; UI textContent chống HTML injection.
- Scan metadata/episode của một khách rồi paginate trong service; timeout 2s.
  Đây là giới hạn M1, không tự nhận tối ưu tải rất lớn. Không schema/migration
  mới; metadata truy vấn runtime.turns/jobs hiện có và projection hiện có.
- UI tải HTTP riêng sau ready, không chờ timeline trước khi gửi chat. Có trạng
  thái loading/empty/not_applicable/error và tải lại/xem thêm. Refresh khi memory
  completed; abort/bỏ response cũ khi refresh, phiên mới, kết thúc/logout. Lỗi
  không hiển thị như lịch sử rỗng và xóa dữ liệu đang hiển thị khi read thất bại.

## Nghiệm thu

- Test policy gốc qua, negative controls vẫn chặn; không hạ guardrail.
- Timeline service/MCP: chronological >5 items, pagination, completed revision,
  source merge, date filtering, owner/erasure, không lộ raw text/PII.
- Runtime/API: token/known-session/fingerprint/date binding, không inference;
  backend authentication/identity override, malformed upstream fail closed.
- Browser offline (Chrome + mock AI, không model/DB): hai phiên cùng khách,
  đa kênh, xem thêm, refresh/reload, error/retry, chống HTML/stale response.
- Focused tests theo lớp; không full suite. Ghi spec/plan, lệnh và kết quả thật;
  không lấy test giả lập thay số chất lượng/latency của eval mới.
