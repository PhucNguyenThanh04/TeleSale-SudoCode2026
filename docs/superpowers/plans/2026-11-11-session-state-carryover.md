# Session State Carryover Implementation Plan

**Goal:** Giữ context/brief và tiến trình xuyên cuộc gọi, tra cứu trước khi hỏi lại, phân loại lỗi model cụ thể.
**Architecture:** Runtime chung text/voice + SessionState owner-bound; durable reconstruction từ memory evidence hiện có; consultation/purchase gates giữ nguyên.
**Tech Stack:** Python, LangGraph, Pydantic, MCP/PostgreSQL; focused offline pytest và mocked model/HTTP.
**Spec:** `docs/superpowers/specs/2026-11-11-session-state-carryover-design.md`.

## Global constraints
- Current checkout; giữ thay đổi cũ. Không subagents/worktrees/auto-commit.
- Không live inference/eval/benchmark hoặc reset/migrate database triển khai. Không sửa nhãn/scorer hoặc bơm facts_established vào runtime.
- Focused tests, không chạy full suite trừ yêu cầu repo. Không thêm dependency, dashboard hoặc refactor không cần thiết.
- User giao tự viết và thực thi: không dừng chờ xác nhận lại spec/plan. Tự review thay cho subagent theo AGENTS/user preferences.

## Review focus
- Brief cache không được làm sống lại dữ liệu erased/TTL/deleted hoặc kéo prior memory vào baseline.
- Tool/read observations giữ source/session/customer khi process khởi động lại; draft voice không thành consent.
- Tên sản phẩm cụ thể khác với scope mơ hồ; kết quả nhiều SKU không được chọn phần tử đầu.
- Khách thay lựa chọn/giá/payment/budget sau xác nhận phải invalidate đúng phần, không reset mọi tiến trình.
- Local errors có code an toàn xuyên các lớp diagnostics; không thêm raw exception text hoặc retry vô hạn.

## Task 1 — Live Call Brief qua mọi lượt
Files: `app/agent/harness/context.py`, `test/test_session_preparation.py`, `test/test_brief_product_state.py` dưới ai-services.
- [x] Thêm test returning caller có brief ở lượt 2; cập nhật budget/blocker vào brief, không gọi quote/stock dư chỉ vì render lại.
- [x] Chạy RED: `PYTHONPATH=ai-services:ai-services/test:. ai-services/.venv/bin/python -m pytest -q ai-services/test/test_session_preparation.py --tb=short`.
- [x] Tách điều kiện render brief khỏi điều kiện refresh. Giữ security read mỗi lượt, không copy brief cũ khi read lỗi.
- [x] GREEN focused preparation/brief/freshness tests, ghi kết quả.

## Task 2 — SessionState và khôi phục durable
Files: new `ai-services/app/agent/harness/session_state.py`; runtime.py/state.py/session_nodes.py/context.py; memory service/schemas nếu cần đọc lại source-bound observations; new `ai-services/test/test_session_state.py`.
Interface: `SessionState` owner/session/day/full-baseline, context view, decision/pending fields; runtime quản lý trong session lock. Context mới authoritative, chỉ cập nhật receipt/offer từ committed evidence. Dùng consultation decision hiện có làm phase, không thêm máy trạng thái song song.
- [x] Tests prepare→nhiều lượt (kết hợp regression mới và boundary tests hiện có), sửa facts, worker pending, process recreation, same session identity conflict, baseline/erasure/outage, voice interrupted, repeated message receipt.
- [x] Tích hợp SessionState qua runtime/context/commit; rebuild từ durable evidence, không authoritative cache.
- [x] GREEN: `... -m pytest -q ai-services/test/test_session_state.py ai-services/test/test_session_preparation.py ai-services/test/test_basket_runtime.py --tb=short`.

## Task 3 — Product resolution trước clarification
Files: business_agent.py, consultation_shortlist.py và session_nodes.py trong ai-services/app; new `ai-services/test/test_session_product_resolution.py`.
Interface: shared bounded read preparation dùng customer text/source-bound context; catalog result vẫn qua resolver và purchase gates hiện có.
- [x] Regression replay AirPure X đã nêu tên nhưng thiếu metadata, returning “mẫu hôm trước”, ambiguous match, no match/failed refresh, cancellation, size/payment đã nêu; assert không hỏi chọn sản phẩm thừa hoặc tạo đơn sai.
- [x] Thêm bước xác minh query cụ thể trong budget hiện có; hỏi đúng phần chưa biết, không search lời chào.
- [x] GREEN focused new tests + consultation/followup suites bị ảnh hưởng.

## Task 4 — Chẩn đoán model và replay kết thúc
Files: execution_diagnostics.py/observability.py, local_llm.py nếu cần structured error, eval_harness/turn_diagnostics.py; test_execution_diagnostics.py/test_local_llm.py; README/architecture.
- [x] Mocked local error → safe class/code qua diagnostics (context overflow, malformed/truncated tool, schema/transport), raw body/PII không xuất.
- [x] Phân loại lỗi dựa exception structured metadata, không đoán từ artifact cũ. Không đổi guardrails config ngầm.
- [x] Replay các đường SAMPLE-01/04/05/06 có model stub và memory/tool thật trong process; test carryover/clarification quan sát được, không hardcode scenario IDs vào production.
- [x] GREEN nhóm focused; cập nhật tài liệu state, recovery, restart và giới hạn số liệu live.

## Completion audit
- [x] Đối chiếu từng tiêu chí spec với source và kết quả tests; review diff liên quan; `git diff --check`.
- [x] Ghi rõ tests đã chạy, việc chưa đo live; chỉ complete khi mọi task bắt buộc hoàn tất.

## Execution ledger
- Plan tự review: bốn task bao phủ spec. Ưu tiên Task 1 tạo thay đổi nhỏ kiểm chứng được, Task 2 giữ coherence/recovery, Task 3 xử lý phản ví dụ hỏi lại thực, Task 4 khôi phục khả năng quan sát và replay.
- Ruling: không dùng skill worktree/subagent/commit/full-suite workflows vì user cấm hoặc giới hạn rõ; không cần xin phép lại để thực thi plan.
- Task 1 RED: hai test brief lượt 2/update budget thất bại. Tách render brief mọi lượt khỏi refresh chỉ khi cần; thêm reuse quote đã có. Một lần kiểm phát hiện thiếu import build_commerce_evidence, đã sửa. Fixture ReturningMemory từng trả current_episode={} thiếu session_id nên khiến lượt sau lỗi memory; sửa fixture theo schema, không thêm fallback production cho malformed memory. GREEN preparation/brief/freshness: 25 passed, warning trustcall/LangGraph có sẵn.
- Task 2 đang thực thi: SessionState owner/day/full-baseline-bound quản lý context và decision dưới session lock; seed không mang agent draft/ephemeral turn flags; fresh memory replaces view, read failure clears cache/scoped facts. Ba unit tests scope/replacement/voice draft đã qua; runtime/preparation/basket group ban đầu 41 passed.
- Task 2 RED→GREEN restart: hai case text/voice runtime mới không dùng được basket đã nghe, nhầm sang scalar quote và hỏi xác nhận lại. Memory read nay trả owner/source-bound session_tool_calls từ committed log (dùng lại rows cache); context phục hồi nguồn còn thiếu, ưu tiên live observations của một source đầy đủ, không dedupe mất refresh trong cùng source. Hai case đã qua.
- Task 2 RED→GREEN long session: thêm 14 lượt filler để offer ra khỏi prompt/history window 12 lượt, cả text/voice mất offer. Basket gate nay đọc offer có nguồn trong current_episode đã dựng từ committed evidence; không thêm toàn bộ history vào prompt. Hai case đã qua; khách xác nhận tạo đúng một đơn hai units trong khi worker vẫn pending.
- Task 2 RED→GREEN failed refresh: durable memory_observations trước đây bỏ failed reads nên restart có thể hồi sinh quote cũ. Giữ barrier read_failed đã sanitize cho catalog/inventory/pricing, không giữ raw provider error; cả error/ok=false/success=false có test. Operational/session/worker group: 39 passed. SessionState/basket boundary/real-runtime group sau sửa current_episode: 69 passed.
- `git diff --check` sạch. Không gọi model, không live eval/benchmark, không thao tác DB triển khai. Chưa tuyên bố KPI CCR/RQR cải thiện bằng số liệu live.

## Completion audit — 2026-11-11

Lượt trước tạo tiến triển: sửa regression quote-only, 50 focused tests qua; không có process pytest còn chạy. Lượt này hoàn tất replay còn thiếu, thêm coverage outage/parser/context overflow và khóa mode của cached retry.

| Requirement | Source và bằng chứng hiện tại |
| --- | --- |
| Brief mọi lượt, facts thay đổi, không refresh dư | context.py tách create_brief/should_refresh; test_session_preparation kiểm lượt 2/3, thay budget/blocker, fresh read sau preparation và không gọi quote dư. |
| SessionState có scope, không dùng draft làm consent | session_state.py chỉ chứa context allowlist/decision, resume reset owner/day/mode; test_session_state kiểm deep copy, replacement, xóa/failure và scope. |
| Durable restart, long session, worker pending | memory read trả observations owner/session/source-bound từ committed rows; context phục hồi nguồn thiếu; test_session_state restart text/voice, 0/14 filler, tạo đúng một đơn hai máy trong khi jobs pending. current_episode chứa delivered offer ngoài history window. |
| Voice, baseline, giá đổi, receipt và ownership | test_basket_runtime chạy Deep/ReAct × text/voice, full/baseline, interrupted, repricing; test_voice_playback kiểm prefix, wrong identity, absent/expired/conflicting receipt; test_operational_memory kiểm owner/erasure/baseline/tombstone/blocker trước worker. |
| Không dùng stale cache khi memory lỗi | preparation tests kiểm erasure cả lượt mới và retry, outage rồi fresh recovery; runtime cached retry kiểm memory, request fields và full/baseline mode trước trả cache. Session view bị vô hiệu khi read thất bại. |
| Product lookup trước câu hỏi thừa | catalog_query.py nhận literal identifier; BusinessTools chỉ lookup bổ sung khi purchase intent, trong budget; selection gate không dùng unresolved new choice với consent cũ. Product-resolution tests kiểm resolved/ambiguous/no-match/failure, không repeat lookup, không chọn first item hoặc tạo đơn sai. |
| Không làm hỏng quote-only/basket | Regression từng báo 8 failed/61 passed: search AirPure Pro kéo cả phụ kiện, thay offer. Giới hạn fallback vào purchase intent; giữ search semantics hiện có. Thêm quote-only regression và assert giá giỏ thật sự được nói. Sau sửa: 50 passed; group cuối bao gồm thay đổi retry: 78 passed. |
| Replay SAMPLE-01/04/05/06 | test_session_product_resolution dùng nguyên customer turns qua benchmark runner, MCP commerce và memory services thật, storage/model giả. 05: Deep/ReAct × text/voice kiểm không hỏi selection thừa và đúng đơn giá mới. 01/04/06: text/voice kiểm brief mọi lượt quay lại, scoped product/facts/episodes còn khi worker pending. 04 dùng CRM đã nối FB-phone; không tuyên bố replay này chứng minh anonymous identity attribution hoặc model quality. Không inject facts_established. |
| Safe diagnostics | LocalToolOutputError có code; execution_diagnostics/observability/turn_diagnostics giữ class/code allowlist. Mock HTTP malformed/truncated; actual ValidationError/OutputParserException; structured context overflow và SDK transport/status; tests không để raw body/PII vào event/summary. Không suy ra nguyên nhân 13 unknown_error cũ. |
| Không đổi semantics eval/config hoặc chạy model thật | Không sửa scorer/labels để tăng điểm, không đổi guardrails env. Không live inference/eval, benchmark, reset hoặc migration DB triển khai. Không subagent/worktree/auto-commit. |
| Docs và review | README và m1-architecture mô tả brief/session/restart/delivery/error boundaries; tự đọc diff/source liên quan theo AGENTS. git diff --check sạch. |

### Verification commands và kết quả

Dùng `PYTHONPATH=ai-services:ai-services/test:. ai-services/.venv/bin/python -m pytest -q ... --tb=short`:

- Runtime group: `test_session_preparation.py test_session_state.py test_session_product_resolution.py test_basket_runtime.py test_voice_playback.py` trong ai-services/test: **78 passed**, `/tmp/carryover-runtime-final.log`.
- Boundary group: `test_session_preparation.py test_voice_playback.py test_operational_memory.py test_basket_harness.py test_returning_purchase_recovery.py test_consultation_followup.py` trong ai-services/test và `ai-services/eval_harness/test_entrypoint_parity.py`: **104 passed**, `/tmp/carryover-boundaries-final.log`. Sau đó thêm outage/mode tests trong preparation, được bao phủ bởi runtime group cuối.
- Diagnostics group: `ai-services/test/test_execution_diagnostics.py ai-services/test/test_local_llm.py ai-services/eval_harness/test_turn_diagnostics.py`: **47 passed**, `/tmp/diagnostics-final.log`.
- Sáu replay context mới chạy riêng: **6 passed**, `/tmp/context-replays.log`; sau đó cũng nằm trong runtime group cuối. Outage mới chạy riêng **1 passed**, rồi nằm trong runtime group cuối.

Các nhóm có overlap, không cộng số tests thành số lượng unique. Log /tmp chỉ là output kiểm chứng ở máy hiện tại; test source là artifact bền vững. Không chạy full suite vì repo không yêu cầu và user giới hạn focused tests.

### Giới hạn đã xác định

- Đây là kiểm chứng offline bằng model stub; chưa chứng minh mức cải thiện CCR/RQR hoặc latency với LLM local. Chỉ live eval được user cho phép sau này mới đo được KPI.
- Literal identifier fallback không thay thế NLP/ASR normalization của model; câu mơ hồ vẫn cần giải nghĩa hoặc hỏi phân biệt. Không ép một SKU khi catalog trả nhiều khả năng.
- Retry response process-local giữ idempotent payload, kiểm fresh memory security; cùng client_msg_id không được đổi input/date/identity/delivery/memory mode. Không bổ sung checkpointer hay snapshot DB thứ hai.
- Không deploy, không commit và không sửa kết quả eval cũ. Các thay đổi đã có sẵn của người dùng được giữ nguyên.

Audit kết luận toàn bộ scope implementation và offline verification của spec hoàn tất; KPI live là phần chưa đo đã được spec yêu cầu báo riêng, không phải kết quả được ngầm khẳng định.
