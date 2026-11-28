# Báo cáo đánh giá TeleSale M1

Số liệu chính thức của bản nộp: run `20261127T113656Z-0cb1b876` trên nhánh `khoi_fix_ttft` (commit `323dd6e`), bộ 48 kịch bản `eval/scenario_final` (118 cuộc gọi, 323 lượt mỗi cấu hình), chấm bằng `reference_eval.py` của gói BTC v2 (28/28 file khớp hash manifest).

## Cấu hình đo

| Mục | Giá trị |
|---|---|
| Model | `gemma4:31b` qua Ollama Cloud, temperature 0,2, seed 7, thinking tắt |
| Cấu hình | Full (bộ nhớ đa phiên) và baseline không bộ nhớ: cùng model, tham số, seed, kịch bản, knowledge release; baseline tắt profile và episodic của các phiên trước |
| Đo latency | Ranh giới harness, chat streaming; TTFT đến delta trả lời đầu tiên đã qua kiểm tra, Total đến delta cuối; bỏ 3 lượt warm-up |
| Máy | Windows 11, 16 luồng CPU, 15,6 GB RAM, RTX 3050 Laptop 4 GB, Docker Desktop (WSL2) |
| Trạng thái run | `validated`, execution `healthy`, chạy một mình trên stack |

## Kết quả Full so với baseline

| Chỉ số (scorer BTC) | Full | Baseline không bộ nhớ | Chênh lệch |
|---|---:|---:|---:|
| Repeat-Question Rate ↓ | 3,0% (2/66) | 26,6% (21/79) | giảm 88,7% tương đối |
| Context Carryover Rate ↑ | 65,6% (63/96) | 13,5% (13/96) | +52,1 điểm % |
| Task Success Rate ↑ | 81,2% (39/48) | 62,5% (30/48) | +18,7 điểm % |
| TSR ca khó ↑ | 78,9% (38 ca) | 55,3% | +23,6 điểm % |
| Hallucination Rate ↓ | 3,8% (4/105) | 0,0% (0/71) | +3,8 điểm % |
| HR giá/khuyến mãi ↓ | 0,0% (0/75) | 0,0% (0/49) | 0 |
| Guardrail violations ↓ | 0 | 0 | 0 |
| Số lượt TB/cuộc | 2,74 | 2,74 | 0 |
| Calls-to-close | 1,94 | 1,93 | +0,01 |
| TTFT p50 / p95 | 3.355 / 6.399 ms | 3.380 / 6.405 ms | |
| Total p50 / p95 | 3.355 / 6.399 ms | 3.380 / 6.405 ms | |
| Call Brief p50 / p95 | 182 / 287 ms (69 phiên quay lại) | không áp dụng | |

Đối chiếu ngưỡng M1:

| Tiêu chí | Ngưỡng | Kết quả |
|---|---|---|
| RQR giảm so với baseline | ≥ 40% | Đạt (88,7%) |
| TSR | ≥ 70% | Đạt (81,2%) |
| HR giá/khuyến mãi | ≤ 5% | Đạt (0,0%) |
| Call Brief | ≤ 5 s | Đạt (p95 287 ms) |
| Total latency p95 | ≤ 8 s | Đạt (6,4 s) |
| TTFT p95 | ≤ 3 s | **Chưa đạt (6,4 s)** |

TTFT bằng Total vì câu trả lời chỉ được phát sau khi qua kiểm tra toàn câu (không phát từng phần rồi sửa). Phần lớn thời gian là các lần gọi model nối tiếp: mỗi lần gọi `gemma4:31b` qua Ollama Cloud mất p50 ~1 s, p95 ~1,8 s, một lượt thường cần 2–3 lần (chọn tool, trả lời, sửa bản nháp nếu bị chặn), cộng bước LLM duyệt câu trả lời (~0,8 s). Phân tích chi tiết và số đo bật/tắt bước duyệt ở [tài liệu bàn giao](BAN-GIAO-khoi_fix_ttft-20261127.md).

## Trước và sau cải tiến

Ba run cùng bộ 48 kịch bản, cùng model và máy:

| Chỉ số Full | Code ngày 26/11 (`065208Z`) | Code 27/11 trước cải tiến latency (`084346Z`) | Sau cải tiến (`113656Z`) |
|---|---:|---:|---:|
| Execution | degraded (1 `GraphRecursionError`) | healthy | healthy |
| RQR ↓ | 4,5% | 1,5% | 3,0% |
| CCR ↑ | 49,0% | 61,5% | 65,6% |
| TSR ↑ | 77,1% | 81,2% | 81,2% |
| HR ↓ (giá/KM) | 2,1% (2,8%) | 0,9% (0,0%) | 3,8% (0,0%) |
| TTFT p50 / p95 | 2,6 / 6,5 s | 3,6 / 7,4 s | 3,4 / 6,4 s |
| Tổng số lần gọi model | — | 703 | 597 |
| Lượt phải trả lời bằng câu xin lỗi chung | 62 | 70 | 52 |

Các cải tiến giữa `084346Z` và `113656Z`:

1. Guardrail nhận biên nhận `order.create` và kết quả `order.status` (cả của lượt trước trong phiên) làm bằng chứng, nên không còn chặn nhầm câu trả lời về đơn hàng: lượt bị chặn `order_creation_unverified` giảm 24 → 3.
2. Khi bản nháp bị chặn vì thiếu báo giá/tồn kho, harness tự tra bổ sung rồi kiểm tra lại bản nháp trước khi gọi model viết lại.
3. Xác nhận đơn từ biên nhận `order.create` mà không gọi model thêm.
4. `catalog.search` ra đúng một sản phẩm thì tra kèm giá và tồn kho trong cùng bước.

Kết quả: số lần gọi model giảm 15%, TTFT p95 giảm 7,4 → 6,4 s, lượt xin lỗi chung giảm 70 → 52; TSR giữ 81,2%, CCR tăng.

## Phân tích 14 trường hợp sai (run `113656Z`, cấu hình Full)

| # | Vị trí | Lỗi quan sát | Nguyên nhân | Hướng xử lý |
|---|---|---|---|---|
| 1 | TEAM-33 call_2 lượt 1–2, call_3 lượt 1 | Nói "miễn phí giao hàng" sau khi khách đổi nơi nhận sang Hà Nội (sự thật: không freeship). 4 claim sai, toàn bộ HR của run | Model gọi `pricing.get_quote(address="Cần Thơ")` theo địa chỉ cũ trong bộ nhớ; báo giá Cần Thơ có freeship nên guardrail coi là có bằng chứng | Guardrail đối chiếu địa chỉ báo giá với địa chỉ khách nói gần nhất; ưu tiên lời khách mới hơn fact trong bộ nhớ |
| 2 | TEAM-02 call_2 lượt 3 | Khách yêu cầu đổi size, agent trả câu xin lỗi chung, không gọi `order.update` | Bản nháp bị chặn, hai lần sửa đều không đạt, rơi về fallback | Khi yêu cầu thao tác rõ và đủ bằng chứng (đã tra tồn kho, chính sách), cho model gọi lại `order.update` thay vì fallback |
| 3 | TEAM-20 call_2 lượt 2–3 | Đã gọi `order.update` nhưng vẫn trả câu xin lỗi chung; TSR fail vì args không khớp | Câu trả lời về chênh lệch giá/chính sách đổi bị chặn; tham số cập nhật sai biến thể | Kiểm tham số `order.update` với biến thể khách chọn; giữ bằng chứng giá chênh lệch ở lượt trước |
| 4 | TEAM-12 call_2 | Không gọi `order.status` theo đúng tham số kịch bản (gọi không có `order_id`) | Model tra đơn qua danh tính thay vì mã đơn | Truyền mã đơn từ Call Brief vào lời gọi |
| 5 | TEAM-13 call_1 lượt 1–2 | Hỏi máy lọc trong ngân sách 3 triệu và khóa trẻ em, cả hai lượt trả câu xin lỗi chung | Bản nháp nêu giá/thông số bị chặn (`price_without_quote`, `unsupported_product_spec`) | Rà guardrail giá cho trường hợp so ngân sách; lưu bản nháp bị chặn để phân loại chặn nhầm |
| 6 | TEAM-13 call_2–3 | Không gọi `catalog.search` với tham số kịch bản (ngân sách 5,5 triệu, diện tích) | Model tìm theo từ khóa chung, không truyền bộ lọc | Mô tả tool nhấn mạnh truyền ngân sách và diện tích bằng tham số riêng |
| 7 | TEAM-15 call_1 | Không nói rõ "không có thông tin" về TDS đầu ra | Câu trả lời diễn đạt "không cung cấp thông tin chi tiết", không khớp cụm từ kịch bản | Câu mẫu cho thông số không có trong catalog |
| 8 | TEAM-25 call_2 lượt 3 | Khách xác nhận tạo đơn thứ hai, agent không gọi `order.create` | Agent xin thêm bước xác nhận dù khách đã đồng ý giá, COD, khu vực | Bổ sung trường hợp "đơn mới cùng sản phẩm" vào bộ duyệt đồng ý nhanh |
| 9 | TEAM-28 call_1 | Khách dùng số điện thoại chung xin tạo combo, agent từ chối vì chưa xác minh danh tính | Chính sách danh tính chặn đặt hàng với số dùng chung | Kịch bản kỳ vọng tạo đơn sau khi khách tự giới thiệu; cần bước xác minh nhẹ thay vì từ chối |
| 10 | TEAM-28 call_2 lượt 1, 3 | Câu hỏi chính sách trả riêng món trong combo, trả câu xin lỗi chung | Câu trả lời chính sách bị chặn `unsupported_policy_or_internal_claim` dù đã gọi `policy.search` | Rà khớp nguồn chính sách combo |
| 11 | TEAM-31 call_1 lượt 3 | Khách chỉ nói "giữ phương án màng cho máy nhà chị", agent trả câu xin lỗi chung | Bản nháp nhắc lại giá bị chặn | Cho phép nhắc lại báo giá cùng phiên còn hiệu lực |
| 12 | TEAM-36 call_1 | TSR fail vì không gọi `catalog.search` đúng tham số, dù câu trả lời bảo hành 24 tháng đúng | Khác biệt tham số tìm kiếm | Như #6 |
| 13 | TEAM-06 call_3 lượt 1 | Hỏi lại size dù đã biết (RQR) | Agent hỏi xác nhận "đổi size 42" thay vì làm luôn | Dùng slot đã có để đề xuất thao tác trực tiếp |
| 14 | TEAM-41 call_2 lượt 2 | Hỏi lại ngân sách đã biết (RQR) | Đề xuất tìm thêm mẫu kèm nhắc ngân sách dưới dạng câu hỏi | Nêu ngân sách như thông tin đã biết, không hỏi lại |

Ngoài các ca trên: 52/323 lượt Full trả câu xin lỗi chung sau khi bản nháp bị chặn hai lần, lý do chính `price_without_quote` (21), `unsupported_policy_or_internal_claim` (11), `unsupported_product_spec` (6). Đây là đánh đổi có chủ đích (thà không trả lời còn hơn nói sai giá), nhưng làm giảm TSR.

## Giới hạn

- Extraction (`questions`, `claims`) do extractor của team sinh, `extraction_review` còn cần người duyệt; BTC đối chiếu thủ công trên mẫu trace.
- HR phụ thuộc lần chạy: run `084346Z` cùng code nền có HR 0,9%; lỗi #1 xuất hiện tùy model có báo giá lại theo địa chỉ mới hay không.
- `call_brief_max` của bộ tự kiểm báo 69/70: TEAM-48 call_2 là khách mới định danh, chưa có phiên trước nên không có brief. `reference_eval.py` chỉ tính giá trị có đo.
- Vòng Knowledge K0 → K1: run này đã sinh proposals (`results-submission/20261127T113656Z-0cb1b876.knowledge/`), chưa duyệt và phát hành K1. Kết quả hai vòng lịch sử ngày 12/11 (K0 `20261112T093027Z-f42a59c5`, K1 `20261112T095815Z-369b9c88`): TSR 79,3% → 82,8%, HR 7,5% → 7,1%, RQR 0% → 7,7%; bộ kiểm đánh dấu `improvement_demonstrated=false`.
- ASR đo riêng, không tính vào TTFT: whisper-turbo CPU int8, B2 trên 120 file của nhóm WER 8,4 / CER 5,2 / Entity 78,1; 4 hội thoại BTC đọc bằng VieNeu WER 10,7 / CER 5,8 / Entity 75,9; diarization theo lượt 83,5% (120 file), 97,1% (BTC).

## Chạy lại

```powershell
python scripts/compose_up.py
python seed_btc.py --data-dir ..\BTC-Data-Vong1-TEAMS
python run_eval.py
```

Kết quả ở `results-submission/<run-id>/` (`run.json`, `btc_score.json`, `m1_conversation_acceptance.json`, trace). Chấm chéo bằng `reference_eval.py` theo [README](../README.md).
