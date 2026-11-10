# Team harness v1

Bộ eval M1 của nhóm theo yêu cầu Phúc ngày 07/11 và định dạng
`test_set/public_sample` của BTC. Gồm 22 scenario, 52 cuộc gọi, 12 ca khó và
12 khách có phiên hotline nối sang Zalo. Phiên 1 dựa trên T01–T22 của speech.
Nhóm chuẩn hóa lời khách sang dạng viết và biên soạn phiên 2; 8 scenario có thêm call 3 nối tiếp, 14 scenario giữ 2 call. Một số ca chuyển
lượt chốt đơn sang phiên 2 hoặc bổ sung xác nhận của khách để hành động có
đủ điều kiện. Mỗi file giữ nguyên ID của ca gốc.

```text
TeleSale-SudoCode2026/
├── speech/dialogues/                 # Script A/C nguồn cho speech
├── speech/data/                      # WAV, nhãn ASR, benchmark và gói replay
├── test_set/team_harness_v1/
│   ├── SC-T01.json … SC-T22.json       # Lượt khách và nhãn chấm riêng
│   ├── _crm_seed.json                 # 22 khách tổng hợp, 5 đơn lịch sử
│   └── README.md
├── dataloader_offline/                # Import vào PostgreSQL eval
├── eval/run_eval.py                   # Runner của nhóm
├── eval/runs/                        # Trace full/baseline và báo cáo
├── ai-services/                      # Harness, memory và các tool MCP
└── backend/                          # API và quản lý phiên
```

- Runner chỉ đưa `customer_turns`, định danh kênh và ngày gọi vào harness.
  Nhãn `success_if`, `facts_established`, `must_carry_over` và `must_not_ask`
  dành cho chấm. Fixture nằm trong file bắt đầu bằng dấu gạch dưới để runner
  và scorer bỏ qua khi quét scenario.
- T01 đo tiếp nối từ tư vấn đến chốt đơn. T02/T20 có đơn gốc để kiểm đổi
  size. T09 đổi trạng thái tồn và có giờ hẹn rõ ở phiên 2. T13 đổi ngân sách.
  T17/T21 kiểm lại giá khi ưu đãi đã hết. T05 kiểm chuyển người thật.
- Các tài khoản `SYN-*` dành cho DB eval. Hồ sơ T11/T12/T20/T22 dùng overlay
  đã có trong nguồn speech, T02 bổ sung đơn giả lập khớp mã và biến thể khách nêu.
- Chỉ gắn nhãn `price_vnd` hoặc `in_stock` chung khi ca có một đối tượng
  rõ ràng. Ca nhiều món dùng SKU/giá trong rule tool và tổng đơn khi phù hợp.
  Các field còn lại chỉ được tính nếu extractor ghi claim tương ứng.
- BTC chấm `success_if` theo lời thoại và tên/tham số tool. Khi đọc kết quả
  cần xem thêm `tool_calls[].result` để biết thao tác thực sự thành công.
  Trace chỉ giữ dấu hiệu có nội dung ở một số trường brief, không xuất nguyên
  nội dung riêng tư của brief. Rubric cần đọc nội dung thì dùng bản kiểm soát riêng.
- Bộ 52 cuộc gọi này phục vụ C.4. Call 2 và call 3 trong harness là input text; speech giữ mỗi cuộc gọi trong một WAV riêng. Khi kiểm quy mô corpus C.1 của cả nhóm, tính
  riêng corpus hội thoại/audio và xác minh số liệu theo đề. Các phiên 2 ở đây
  là text. Replay ASR ngày 28/10 là bộ thử tích hợp riêng.

## Chạy trên DB eval

Từ gốc clone, đặt `BTC_DATA_DIR` và `DATABASE_URL` trỏ tới gói BTC và DB eval
riêng. Cấu hình các MCP vào cùng DB đó và áp migrations theo README repo.
Lệnh import có thể chạy lại trên DB eval cùng seed.

```powershell
$set = 'test_set/team_harness_v1'
$schema = Join-Path $env:BTC_DATA_DIR 'schemas/trace_log.schema.json'
python -m dataloader_offline --data-dir $env:BTC_DATA_DIR --only-postgres --isolated-db --eval-crm-overlay "$set/_crm_seed.json"
python run_eval.py --scenarios $set --trace-schema $schema --config full --out eval/runs/team_harness_v1_full.jsonl --isolated-db
```

Khôi phục trạng thái DB eval về cùng seed trước baseline. Dùng cùng model,
tham số, tool và scenario, chỉ thay cấu hình bộ nhớ.

```powershell
python run_eval.py --scenarios $set --trace-schema $schema --config baseline_no_memory --out eval/runs/team_harness_v1_baseline.jsonl --isolated-db
python (Join-Path $env:BTC_DATA_DIR 'eval/reference_eval.py') --scenarios $set --trace eval/runs/team_harness_v1_full.jsonl --baseline eval/runs/team_harness_v1_baseline.jsonl --out eval/runs/team_harness_v1_report.json
```
