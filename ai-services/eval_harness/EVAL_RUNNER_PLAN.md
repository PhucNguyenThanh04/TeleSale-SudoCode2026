# Kế Hoạch Xây Dựng Bộ Công Cụ Eval Runner & Đo Đạc Benchmark 2x2 (Deep Agent vs ReAct Agent)

> **Mục tiêu:** Xây dựng bộ công cụ thực thi đánh giá (`benchmark_runner.py`), trích xuất dữ kiện thoại (`extractor.py`), và engine chấm điểm chuẩn hóa (`scorer.py`) để đo đạc ma trận đối chứng $2 \times 2$ (Deep/ReAct $\times$ Full/Baseline) trên toàn bộ 19 kịch bản (116 turns) với PostgreSQL thật và LLM thật (`gemma4:31b`), xuất ra 2 tệp kết quả độc lập `benchmark_deep_agent.json` và `benchmark_react_agent.json`.

---

## 1. Kiến Trúc Bộ Công Cụ Eval Harness

```text
eval_harness/
├── EVAL_RUNNER_PLAN.md          # Bản kế hoạch chi tiết này
├── scorer.py                    # Engine thẩm định toán học (TSR, RQR, CCR, HR, Guardrails, Latency)
├── extractor.py                 # Bộ trích xuất questions, claims, facts_used, tool_thrashing
├── benchmark_runner.py          # Script thực thi CLI chính (--agent, --config, --out)
├── test_eval_harness.py         # Unit tests kiểm tra tính đúng đắn của scorer và extractor
├── results/                     # Thư mục chứa kết quả JSON
│   ├── benchmark_deep_agent.json
│   └── benchmark_react_agent.json
└── scenarios/                   # 19 scenarios đã chuẩn hóa
```

---

## 2. Các Ràng Buộc & Nguyên Tắc Thực Thi

1. **Chuẩn đối chứng khoa học (Fair Controlled Experiment):**
   - Chạy trên cùng 1 phần cứng, cùng model `gemma4:31b`, cùng tham số `temperature = 0.2`, `max_tokens = 256`, cùng catalog sản phẩm/khuyến mãi BTC, cùng ngày tham chiếu nghiệp vụ `2026-10-15`.
   - Điểm khác biệt duy nhất ở runtime là `agent_kind` (`"deep"` vs `"react"`) và cờ bộ nhớ (`full` vs `baseline_no_memory`).
2. **Cô lập trạng thái cơ sở dữ liệu (State & Database Isolation):**
   - Mỗi lần chạy tự động sinh namespace phiên riêng (`deep_...` và `react_...`).
   - Ở chế độ `baseline_no_memory`, runner bỏ qua bước nạp memory phiên trước (`verified_customer_id = None`), đảm bảo Agent hoàn toàn không có ký ức cũ.
3. **Tuân thủ quy chuẩn đo đạc của BTC:**
   - Bỏ 3 lượt warm-up đầu tiên trước khi tính toán các phân vị độ trễ $p50$, $p95$.
   - Bộ chỉ số bắt buộc phải khớp 100% công thức của `BTC-Data-Vong1-TEAMS/eval/reference_eval.py`.

---

## 3. Kế Hoạch Triển Khai Chi Tiết (5 Tasks)

### Task 1: Xây dựng Engine Chấm Điểm Chuẩn Hóa (`eval_harness/scorer.py`)
> Triển khai module tính toán toán học cho toàn bộ các metric bắt buộc BTC và chỉ số chẩn đoán so sánh.

- [ ] **Step 1:** Tạo file `ai-services/eval_harness/scorer.py`.
- [ ] **Step 2:** Cài đặt hàm `evaluate_task_success(scenarios, trace_rows)`:
  - Kiểm tra `success_if.tool_called` và `args_match` (SKU, giá tiền theo ngày `2026-10-15`).
  - Kiểm tra các ràng buộc mở rộng: `also_ordered`, `total_match_vnd`, `agent_must_say` (từ chối/không có thông tin), `must_say_any`, `must_not_call_tools`, `forbidden_claims`.
  - Tách riêng điểm `tsr_overall` và `tsr_hard_cases` (6 ca khó SC14 – SC19).
- [ ] **Step 3:** Cài đặt hàm `evaluate_memory_metrics(scenarios, trace_full, trace_baseline)`:
  - Tính `RQR`: Tỷ lệ câu hỏi lặp thuộc `must_not_ask`.
  - Tính $\Delta \text{RQR}_{\text{relative}} = \frac{\text{RQR}_{\text{baseline}} - \text{RQR}_{\text{full}}}{\text{RQR}_{\text{baseline}}} \times 100\%$ (kiểm ngưỡng $\ge 40\%$).
  - Tính `CCR`: Tỷ lệ facts trong `must_carry_over` được dùng lại.
- [ ] **Step 4:** Cài đặt hàm `evaluate_hallucination(scenarios, trace_rows)`:
  - So sánh `claims` với `ground_truth_facts`, tính riêng `price_promo_hr` (kiểm ngưỡng $\le 5\%$).
- [ ] **Step 5:** Cài đặt hàm `evaluate_guardrails(scenarios, trace_rows)`:
  - Đếm vi phạm PII regex (CCCD 12 số, STK 10-14 số), lộ giá nhập nội bộ (`forbidden_pattern`), chuyển máy thừa (`over_escalation`), tự nhận người thật (`claims_human`).
- [ ] **Step 6:** Cài đặt hàm `evaluate_diagnostics_and_latency(trace_rows)`:
  - Đếm `tool_thrashing` (lặp tool cùng args trong turn) và `tool_limit_reached`.
  - Tính $p50$, $p95$ sau khi loại 3 lượt warm-up.

---

### Task 2: Xây dựng Bộ Trích Xuất Lượt Thoại & Kiểm Soát Trace (`eval_harness/extractor.py`)
> Chuyển đổi trạng thái đàm thoại và kết quả của Agent thành cấu trúc trace chuẩn, kèm cơ chế audit chống bắt nhầm.

- [ ] **Step 1:** Tạo file `ai-services/eval_harness/extractor.py`.
- [ ] **Step 2:** Cài đặt bộ trích câu hỏi `extract_questions(agent_text)`:
  - Nhận diện câu hỏi mở (`open`) và câu hỏi xác nhận (`confirm`), liên kết với tên slot tương ứng (diện tích, màu sắc, ngân sách, người nhà).
- [ ] **Step 3:** Cài đặt bộ trích khẳng định `extract_claims(agent_text, tool_calls)`:
  - Trích xuất các khẳng định về giá bán, khuyến mãi, tồn kho, thuộc tính kỹ thuật.
- [ ] **Step 4:** Cài đặt cơ chế `trace_audit_log`:
  - Lưu lại raw text và lý do gán nhãn câu hỏi/claim vào kết quả để người dùng có thể đối chiếu kiểm tra tay (human audit) khi cần.

---

### Task 3: Xây dựng Eval Runner Đa Chế Độ (`eval_harness/benchmark_runner.py`)
> Tích hợp trực tiếp với `AgentHarnessRuntime` của `ai-services`, nạp kịch bản và chạy live đàm thoại.

- [ ] **Step 1:** Tạo file `ai-services/eval_harness/benchmark_runner.py`.
- [ ] **Step 2:** Cấu hình CLI Arguments:
  - `--agent [deep|react]`: Chỉ định agent cần chạy.
  - `--config [full|baseline|both]`: Mặc định `both` để đo được cả 2 cấu hình phục vụ tính $\Delta \text{RQR}$.
  - `--dry-run [N]`: Cờ kiểm thử nhanh N scenarios.
  - `--out [path]`: Đường dẫn tệp kết quả JSON đầu ra.
- [ ] **Step 3:** Cài đặt vòng lặp đàm thoại từng kịch bản:
  - Duyệt `calls` (`call_1`, `call_2`, `call_3` nếu có).
  - Khởi tạo `TextTurnRequest` với ngày gọi đúng (`reference_date = 2026-10-15` + `days_later`).
  - Gửi qua `runtime.run(turn)`, đo độ trễ chuẩn xác bằng `time.perf_counter()`.
  - Thu thập `TurnState = runtime.state_for(turn)` để lấy danh sách `tool_calls` và `memory_writes`.
- [ ] **Step 4:** Tích hợp `extractor` và `scorer` để tự động tổng hợp toàn bộ kết quả.
- [ ] **Step 5:** Định dạng cấu trúc JSON đầu ra và hiển thị bảng tổng kết trên terminal.

---

### Task 4: Kiểm Thử Đơn Vị & Thử Nghiệm Kiểm Chứng Cục Bộ (Dry-Run Verification)
> Đảm bảo toàn bộ pipeline chạy mượt mà, không gặp lỗi cú pháp hay nghẽn runtime trước khi chạy full batch.

- [ ] **Step 1:** Viết script kiểm thử đơn vị `ai-services/eval_harness/test_eval_harness.py` kiểm tra tính đúng đắn của `scorer.py` trên dữ liệu giả lập.
- [ ] **Step 2:** Chạy lệnh dry-run 1 kịch bản (`SC01`) trên Deep Agent:
  ```bash
  PYTHONPATH=ai-services ai-services/.venv/bin/python ai-services/eval_harness/benchmark_runner.py --agent deep --dry-run 1
  ```
- [ ] **Step 3:** Chạy lệnh dry-run 1 kịch bản (`SC01`) trên ReAct Agent:
  ```bash
  PYTHONPATH=ai-services ai-services/.venv/bin/python ai-services/eval_harness/benchmark_runner.py --agent react --dry-run 1
  ```
- [ ] **Step 4:** Kiểm tra định dạng JSON đầu ra, đảm bảo các trường metadata, metrics và scenarios detail đều có giá trị hợp lệ.

---

### Task 5: Thực Thi Benchmark Toàn Diện & Xuất Tệp Kết Quả
> Chạy batch full 19 kịch bản (116 turns) cho cả Deep Agent và ReAct Agent với DB thật và LLM thật.

- [ ] **Step 1:** Chạy Full Benchmark cho **Deep Agent**:
  ```bash
  PYTHONPATH=ai-services ai-services/.venv/bin/python ai-services/eval_harness/benchmark_runner.py \
    --agent deep --config both \
    --out ai-services/eval_harness/results/benchmark_deep_agent.json
  ```
- [ ] **Step 2:** Chạy Full Benchmark cho **ReAct Agent**:
  ```bash
  PYTHONPATH=ai-services ai-services/.venv/bin/python ai-services/eval_harness/benchmark_runner.py \
    --agent react --config both \
    --out ai-services/eval_harness/results/benchmark_react_agent.json
  ```
- [ ] **Step 3:** Kiểm tra tính toàn vẹn của 2 file JSON kết quả trong `ai-services/eval_harness/results/`.
- [ ] **Step 4:** Tổng kết và báo cáo các chỉ số định lượng then chốt cho User.

---

## 4. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

1. **Sinh đủ 2 tệp kết quả JSON độc lập**:
   - `ai-services/eval_harness/results/benchmark_deep_agent.json`
   - `ai-services/eval_harness/results/benchmark_react_agent.json`
2. **Đầy đủ các metric cốt lõi**:
   - TSR Overall & TSR Ca Khó.
   - RQR Full, RQR Baseline, và % Mức giảm tương đối $\Delta \text{RQR}$ ($\ge 40\%$).
   - CCR (Context Carryover Rate).
   - HR Giá & Khuyến mãi (Price/Promo HR $\le 5\%$).
   - Guardrail Violations (0 vi phạm).
   - Latency $p50$, $p95$ (sau khi loại 3 lượt warm-up).
   - Tool Thrashing Count & Tool Calls per Turn.
3. **Chạy thành công 100% trên môi trường thật** (PostgreSQL 5432, 3 MCP servers, model `gemma4:31b` qua Ollama Cloud) mà không có ngoại lệ làm gián đoạn chương trình.
