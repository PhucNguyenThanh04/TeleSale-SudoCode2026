# Harness evidence implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; người dùng
> đã giao tự spec → plan → executor. Không subagent/worktree hoặc approval lặp.

**Goal:** Chấm Tool-Call Accuracy từ trace có nhãn và xuất bằng chứng rollback
knowledge offline qua các service/MCP thật.

**Architecture:** Hai CLI độc lập dưới `eval_harness`, không thay runtime/scorer.
TCA thuần standard library. Rollback dùng dependencies có sẵn và adapter RAM
giới hạn trong rehearsal, không thay repository production.

**Tech Stack:** Python 3.12, pytest offline wrapper, FastMCP, Qdrant local.

**Spec:** `docs/superpowers/specs/2026-11-16-harness-evidence-design.md`.

## Global Constraints

- Checkout hiện tại, không worktree/subagent; giữ mọi thay đổi ngoài phạm vi.
- Không live LLM/embedding, DB/reset/activate release thật hoặc dependency mới.
- Không sửa dữ liệu/scorer BTC, agent, ASR, RAG eval, Exemplar Bank.
- Không commit; kiểm focused và CLI offline, không full suite.

## Review Focus

- Không thể bỏ các lượt fail khỏi mẫu số bằng input thiếu/duplicate.
- Matching phải one-to-one; expectation rộng không được chiếm call duy nhất của
  expectation hẹp khi vẫn có cách ghép toàn bộ.
- TCA không đồng nghĩa tool chạy thành công hoặc đánh giá toàn bộ tool/turn.
- Rehearsal không đọc .env/mạng; review mô phỏng không giả làm human review.
- Rollback đổi active cho lượt mới nhưng không được làm sai snapshot đã pin.

## Task 1: TCA và ví dụ chạy được

**Files:** Create `ai-services/eval_harness/tool_accuracy.py`,
`ai-services/eval_harness/test_tool_accuracy.py`,
`ai-services/eval_harness/fixtures/tool_accuracy/{labels.json,trace.jsonl}`.

**Interfaces:** `score_trace(rows: list[dict], labels: dict) -> dict`;
CLI `python -m eval_harness.tool_accuracy --trace FILE --labels FILE --out DIR`.

- [x] Viết test công thức/negative calls, nested args/one-to-one matching,
  hash/locator/input validation, coverage và CLI không ghi đè.
- [x] Chạy RED bằng wrapper offline, xác nhận lỗi do module chưa tồn tại.
- [x] Implement parser, matcher, scorer, reports và fixtures synthetic.
- [x] Chạy test focused GREEN, lưu kết quả vào biên bản.

## Task 2: Rollback rehearsal

**Files:** Create `ai-services/eval_harness/knowledge_rollback.py`,
`ai-services/eval_harness/test_knowledge_rollback.py`.

**Interfaces:** `async rehearse(btc_root: Path) -> dict`;
CLI `python -m eval_harness.knowledge_rollback --btc-root DIR --out DIR`.

- [x] Test chuỗi K0→K1→K0 qua MCP thật, audit, CAS/quyền, immutable pin,
  corpus hash, review label và fail-closed output.
- [x] Chạy RED; implement adapters RAM + fixture encoder và orchestration.
- [x] Chạy GREEN với network bị chặn; kiểm service regression liên quan.

## Task 3: Hướng dẫn và completion audit

**Files:** Create `docs/harness-evidence-20261116.md`; append mục CLI nhỏ vào
`ai-services/eval_harness/README.md`, không sửa các phần khác đang dirty.

- [x] Ghi cách soạn nhãn thật, công thức/phạm vi, lệnh chạy và giới hạn proof.
- [x] Chạy hai CLI offline vào thư mục artifact mới, kiểm JSON/Markdown và
  refusal overwrite. Không dùng kết quả fixture làm số model.
- [x] Self-review toàn bộ diff theo spec; focused regression và whitespace.
- [x] Đối chiếu từng yêu cầu với file/output thực; ghi kết quả, hoàn tất goal.

## Execution ledger

- Pre-flight: Task 1 và Task 2 không chia sẻ interface; Task 3 dùng CLI của cả hai.
- Ruling: thực hiện tự kiểm review, không tạo subagent/worktree theo AGENTS.md;
  không dừng chờ duyệt spec/plan vì người dùng đã giao tự chạy toàn bộ quy trình.
- Task 1: complete — RED module missing; GREEN 17 focused tests. Fixtures được
  khai báo độc lập, không dùng observed calls tạo expected labels.
- Task 2: initial GREEN 4 focused tests. Root cause lần chạy đầu: signed MCP
  context phải dùng principal `harness`; sửa fixture theo contract thật, không
  nới authentication. Kiểm regression và CLI cuối ở Task 3.
- Task 2: complete — 11 checks qua CLI thật offline; thêm output-path guard sau
  hai test RED, không ghi artifact vào BTC source. Config hash được lưu rõ.
- Task 3: complete — focused cuối 36 passed/9,03s; CLI help, refusal overwrite,
  fixture 3/6 và mẫu historical 3/6 (6/170 lượt) đã chạy, input hashes còn khớp.
  Rollback artifact cuối `results/harness-evidence/20261116-rollback-02/`.
- Self-review: không thay agent/scorer/ASR/RAG eval hoặc production lifecycle;
  coverage, review mô phỏng và pinned snapshot semantics được ghi rõ.
- Ngoài phạm vi: một test guardrail policy integration fail cả khi chạy riêng
  không import hai module mới; giữ nguyên, ghi chi tiết trong biên bản bàn giao.
