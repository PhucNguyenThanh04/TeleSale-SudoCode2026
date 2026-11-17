# Policy contract và memory timeline implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Người dùng đã
> giao tự spec → plan → execute, không dừng hỏi duyệt hoặc tạo subagent/worktree.

**Goal:** Sửa đúng ca policy integration và hoàn thiện timeline khách M1 qua
memory/MCP/AI/gateway/UI, kiểm chứng offline.

**Architecture:** Policy fixture sử dụng followup contract thật. Timeline là
đường đọc riêng không đổi pipeline inference; service khách-scoped gộp lịch sử
và paginate, HTTP đọc riêng tránh chặn websocket/chat.

**Tech Stack:** Python/FastAPI/Pydantic/FastMCP, frontend JS sẵn có, pytest và
Chrome headless offline. Không dependency mới.

**Spec:** `docs/superpowers/specs/2026-11-17-policy-timeline-design.md`.

## Global constraints

- Current checkout; không subagent/worktree/commit hoặc sửa ngoài hai phần.
- Không model/embedding live, DB/reset/schema migration hoặc sửa BTC/scorer/trace.
- Giữ expectation policy, ownership/erasure, baseline no-prior và latency path.
- Chỉ focused tests; browser dùng loopback và AI/store mock.

## Review focus

- Query/order/date/release khác nhau không được dùng chéo evidence policy.
- Pending/deleted memory không xuất hiện như summary đã xác minh.
- CRM hoặc runtime fallback không làm sống lại history đã xóa.
- Browser không đổi customer/channel identity; phiên cũ không cập nhật UI mới.
- API error khác history rỗng; pagination không bị relevance/top-5 cắt mất.

## Task 1 — Policy fixture và negative controls

**Files:** `ai-services/test/test_policy_integration.py`.
**Interface:** fixture gọi `followup_task(state).policy_query`, có owned order
và câu hỏi đúng đơn khi verified; vẫn dùng BusinessTools/MCP/verifier thật.

- [x] Reproduce RED gốc offline, log xác nhận grounding pass/completeness fail.
- [x] Sửa fixture đúng contract, thêm query/date/order/release negative controls.
- [x] GREEN focused policy/followup; ghi nguyên nhân và phạm vi sửa.

## Task 2 — Timeline service/MCP/runtime/API

**Files:** Create `ai-services/app/mcp_servers/mcp_memory/services/timeline.py`,
`ai-services/app/schemas/timeline.py`, `ai-services/test/test_memory_timeline.py`,
`ai-services/test/test_memory_timeline_api.py`; modify memory schemas/handlers/repo,
memory store, harness runtime, API chat.
**Interfaces:** `read_timeline(repo, customer_id, session_id, on, offset=0,
limit=10, crm_sessions=(), projector=None) -> dict`; `memory.timeline` same input;
`runtime.memory_timeline(request) -> TimelinePage`; AI HTTP wraps session_id.

- [x] Write RED service/MCP tests: merge/paging/>5/completed/tombstone/owner/erase.
- [x] Implement models/read-only repo metadata/service/MCP/store; GREEN.
- [x] Write RED runtime/API tests for session/date/token/unknown/no LLM.
- [x] Implement bound runtime + AI endpoint, GREEN.

## Task 3 — Gateway và UI

**Files:** `backend/app/api/text.py`, `backend/test/test_text_timeline.py`,
`backend/app/schemas/timeline.py`,
`frontend/chat.html`, `frontend/chat.js`, `frontend/style.css`,
`backend/test/test_text_browser.py`.
**Interfaces:** authenticated POST `/api/chat/timeline` accepts session_id,
channel,on,offset,limit; response `{session_id,timeline}`. AI gets identity only
from account binding. UI fetches page after websocket ready.

- [x] RED gateway tests: auth/binding/validation/failures, then implement.
- [x] RED real-browser tests: initial page, >5/history/load-more, memory refresh,
  new session/reload, XSS/error/retry/stale response; implement minimal UI.
- [x] GREEN focused gateway and browser, no model/DB.

## Task 4 — Completion audit và bàn giao

- [x] Focused integration regression từng lớp và whitespace; không full suite.
- [x] Read final diff against spec; kiểm source preservation và không đổi scorer.
- [x] `docs/policy-timeline-20261117.md` ghi nguyên nhân, contract, cách demo,
  kiểm tra/giới hạn. Update frontend docs liên quan.
- [x] Đối chiếu mọi tiêu chí với file/output thật, hoàn tất goal.

## Ledger

- Preflight: Task 2 public TimelinePage là contract Task 3 proxy/UI tiêu thụ;
  response identity phải giữ session_id. Task 1 không chia sẻ interface.
- User authorization: tự spec/plan/execute, áp dụng current checkout/no agents;
  không yêu cầu approval lặp hoặc commit thay người dùng.
- Task 1 complete: original RED `policy_question_unanswered`; sửa fixture query,
  owned order và câu hỏi đúng đơn, giữ expected. 26 policy tests GREEN, bốn
  negative controls giữ nguyên query/date/order/release boundary.
- Task 2 complete: service/MCP RED→GREEN, runtime/API 10 RED→GREEN. Self-review
  thêm as-of/tombstone/CRM future và default outcome regression RED→GREEN.
- Task 3 complete: gateway 7 RED→GREEN; Chrome UI RED missing DOM, sau đó
  GREEN pagination/refresh/reload/identity, pending-fetch chat và stale response.
  Screenshot chỉ ra container overflow; test bounding-box RED và CSS chat-only
  sửa thành GREEN. Không thay layout voice.
- Task 4 complete: final AI/memory/policy 79 passed/4,61s, gateway/UI 16
  passed/4,27s, trace hash còn nguyên và whitespace qua. Tự review theo spec,
  không tạo subagent hoặc chạy toàn bộ suite/live stack.
- Ruling: budget read 2s và paginate sau scan riêng khách ở bản M1; đã ghi
  shortcut/giới hạn, không thêm schema hoặc hệ lưu lịch sử thứ hai.
