# Báo cáo đánh giá trợ lý telesale đa phiên

## 1. Kết quả chấm hội thoại

Kết quả dưới đây là số liệu chính thức từ run `20261127T113656Z-0cb1b876` (nhánh `khoi_fix_ttft`, commit `323dd6e`) trên bộ 48 kịch bản `eval/scenario_final` (118 cuộc gọi, 323 lượt mỗi cấu hình), chấm bằng `reference_eval.py` của gói BTC v2 (28/28 tệp khớp hash manifest).

| Chỉ số (scorer BTC) | Baseline không bộ nhớ | Hệ thống (Full) | Chênh lệch | Ngưỡng M1 | Trạng thái |
|---|---:|---:|---:|---|---|
| Repeat-Question Rate (RQR) ↓ | 26,6% (21/79) | 3,0% (2/66) | giảm 88,7% tương đối | Giảm ≥ 40% | Đạt |
| Context Carryover Rate (CCR) ↑ | 13,5% (13/96) | 65,6% (63/96) | +52,1 điểm % | — | — |
| Task Success Rate (TSR) ↑ | 62,5% (30/48) | 81,2% (39/48) | +18,7 điểm % | ≥ 70% | Đạt |
| TSR riêng ca khó (38 ca) ↑ | 55,3% | 78,9% | +23,6 điểm % | — | — |
| Hallucination Rate (HR) ↓ | 0,0% (0/71) | 3,8% (4/105) | +3,8 điểm % | — | — |
| Hallucination Rate giá & KM ↓ | 0,0% (0/49) | 0,0% (0/75) | 0 | ≤ 5% | Đạt |
| Vi phạm guardrail (số ca) ↓ | 0 | 0 | 0 | — | — |
| Số lượt TB / cuộc gọi | 2,74 | 2,74 | 0 | — | — |
| Calls-to-Close | 1,93 | 1,94 | +0,01 | — | — |
| TTFT p50 / p95 (ms) | 3.380 / 6.405 | 3.355 / 6.399 | — | p95 ≤ 3.000 ms | **Chưa đạt** |
| Total latency p50 / p95 (ms) | 3.380 / 6.405 | 3.355 / 6.399 | — | p95 ≤ 8.000 ms | Đạt |
| Call Brief p50 / p95 (ms) | Không áp dụng | 182 / 287 (69 phiên quay lại) | — | ≤ 5.000 ms | Đạt |

**Đối chiếu ngưỡng BTC.** Full đạt 5/6 tiêu chí M1: RQR giảm 88,7% tương đối so với Baseline (vượt ngưỡng giảm ≥ 40%), TSR đạt 81,2% (39/48 kịch bản, vượt ngưỡng 70%), HR giá/khuyến mãi đạt 0,0% (0/75 phát ngôn, dưới ngưỡng 5%), Call Brief p95 đạt 287 ms (dưới ngưỡng 5 s) và Total latency p95 đạt 6,4 s (dưới ngưỡng 8 s). Chỉ tiêu duy nhất chưa đạt là TTFT p95 (6,4 s so với ngưỡng ≤ 3 s). Mẫu A.6 trong đề dùng đơn vị lượt/kịch bản (323/48 = 6,73 cho cả hai cấu hình), còn bảng trên ghi lượt/cuộc gọi (323/118 = 2,74).

## 2. Phạm vi và cơ sở chấm

| | Full | Baseline không bộ nhớ |
|---|---|---|
| Dữ liệu agent được dùng | Lịch sử trong phiên, công cụ nghiệp vụ và bộ nhớ đa phiên (profile + episodic) | Lịch sử trong phiên và cùng bộ công cụ; tắt profile và episodic của các phiên trước |
| Model & tham số | `gemma4:31b` qua Ollama Cloud, temperature 0,2, seed 7, thinking tắt | Cùng model, tham số, seed, kịch bản và knowledge release |
| Máy & trạng thái run | Windows 11, 16 luồng CPU, 15,6 GB RAM, RTX 3050 Laptop 4 GB, Docker Desktop (WSL2); `validated`, execution `healthy`, chạy độc lập trên stack | Cùng máy và cùng cặp run `20261127T113656Z-0cb1b876` |
| Mẫu hội thoại | 48 kịch bản, gồm 38 ca khó · 118 cuộc gọi · 323 lượt | Cùng 48 kịch bản, 118 cuộc gọi, 323 lượt |

**Phạm vi kết luận.** BTC yêu cầu bảng A.6 trên bộ test riêng của đội với tối thiểu 20 kịch bản đa phiên và ít nhất 5 ca khó. Bộ riêng của đội (`eval/scenario_final`) có 48 kịch bản, 118 cuộc gọi, 323 lượt và 38 ca khó. Điểm xếp hạng chính thức do BTC chấm trên bộ ẩn. Chi tiết đối chiếu và bản bàn giao kỹ thuật nằm ở [báo cáo đánh giá M1](btc-m1-evaluation-report.md) và [tài liệu bàn giao `khoi_fix_ttft`](BAN-GIAO-khoi_fix_ttft-20261127.md). [Bộ riêng của đội](../eval/scenario_final/_manifest.json)

Căn cứ chấm gồm mục C.4, C.5, F và phụ lục A của đề, bản điều chỉnh Vòng 1 và văn bản giải đáp tháng 11. Bảng hội thoại dùng script tham chiếu trong gói BTC v2. Mục 7 ghi cách tái lập. [Đề dự án](<../../SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>) · [Điều chỉnh đề](../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md) · [Giải đáp tháng 11](../../BTC-tra-loi-thac-mac-11-2026.docx) · [Script chấm BTC](../../BTC-Data-Vong1-TEAMS/eval/reference_eval.py)

**Lưu ý về HR và extraction.** Toàn bộ 4 claim sai của Full (HR tổng 3,8%, 4/105) là lỗi nói "miễn phí giao hàng" ở `TEAM-33` (model báo giá theo địa chỉ cũ "Cần Thơ" trong bộ nhớ sau khi khách đổi sang "Hà Nội"); HR giá/khuyến mãi là 0,0% (0/75). HR tổng phụ thuộc lần chạy (run `084346Z` trên cùng code nền đạt HR tổng 0,9%). Dữ liệu `questions` và `claims` do extractor của đội sinh, còn cần người duyệt (`extraction_review`); BTC đối chiếu thủ công trên mẫu trace.

**Cách tạo dữ liệu chấm.** Từ lời agent, bộ trích xuất nhận diện câu hỏi, gán trường thông tin được hỏi và phân biệt hỏi mới với xác nhận (`questions`). Với dữ kiện thương mại, bộ trích xuất tách mệnh đề và gán cặp trường–giá trị (`claims`). Khi tính RQR, script chỉ xét các cuộc gọi có danh sách trường không được hỏi lại (`must_not_ask`). Hỏi xác nhận lần đầu được miễn, xác nhận lại cùng trường trong cùng phiên bị tính thừa. CCR đối chiếu các dữ kiện phải mang sang với `facts_used` và tham số công cụ. HR chỉ đếm phát ngôn có đáp án trong `ground_truth_facts`. TSR xét điều kiện của từng kịch bản, kể cả chuyển nhân viên kèm bản bàn giao hợp lệ khi đó là kết quả được yêu cầu. [Bộ trích xuất](../ai-services/eval_harness/extractor.py) · [Quy tắc chấm BTC](../../BTC-Data-Vong1-TEAMS/eval/reference_eval.py)

## 3. Nhận dạng tiếng nói — chỉ số M1 theo phụ lục A.5

Full và Baseline khác nhau ở bộ nhớ hội thoại; ASR được đo riêng trên âm thanh đầu vào và không tính vào TTFT. Bảng dưới dùng kết quả Whisper-turbo chạy local CPU `int8` (cấu hình B2, có bộ từ vựng sản phẩm và chuẩn hóa văn bản) trên 120 tệp audio của đội (134 phút, giọng Bắc và Nam tạo bằng VieNeu-TTS, gồm 31 tệp trộn nhiễu) và 4 hội thoại mẫu BTC đọc bằng VieNeu. BTC dùng audio riêng để xếp hạng. [Báo cáo ASR trước đó ngày 10/11](../speech/asr-benchmark-report.html) · [Giải đáp của BTC](../../BTC-tra-loi-thac-mac-11-2026.docx)

| Chỉ số | Bộ audio của đội · 120 file (134 phút) | 4 hội thoại BTC đọc bằng VieNeu |
|---|---:|---:|
| WER · Tỷ lệ lỗi theo từ | 8,4% | 10,7% |
| CER · Tỷ lệ lỗi theo ký tự | 5,2% | 5,8% |
| Độ chính xác thực thể, gộp các loại | 78,1% | 75,9% |
| Độ chính xác **riêng số tiền** | Chưa tách riêng trong bảng tổng hợp | Chưa tách riêng |
| Độ chính xác **riêng số điện thoại** | Chưa tách riêng trong bảng tổng hợp | Chưa tách riêng |
| Diarization theo lượt | 83,5% | 97,1% |

WER và CER lấy tổng số phép thay, xóa, chèn chia cho tổng số từ hoặc ký tự chuẩn. Pipeline đưa số về dạng đọc bằng chữ để so với bản chép lời. Bộ chấm chuyển chữ thường, chuẩn Unicode NFC, bỏ dấu câu, gộp khoảng trắng và bỏ khoảng trắng khi tính CER. Số tiền và số điện thoại được xét khớp chính xác sau chuẩn hóa. [Chuẩn hóa](../speech/normalize.py) · [Chấm ASR và thực thể](../speech/evaluate.py)

## 4. Hiệu năng theo mục C.2 đã điều chỉnh

| Chỉ số | Full | Baseline | Yêu cầu BTC | Đối chiếu lần đo |
|---|---:|---:|---|---|
| Từ lúc nhận lượt chat đến phần trả lời đầu tiên (TTFT), p50 / p95 | 3.355 / 6.399 ms | 3.380 / 6.405 ms | M1: p95 ≤ 3.000 ms | **Chưa đạt** (cả hai vượt ngưỡng) |
| Từ lúc nhận lượt chat đến hết câu trả lời (Total), p50 / p95 | 3.355 / 6.399 ms | 3.380 / 6.405 ms | M1: p95 ≤ 8.000 ms | Đạt (cả hai dưới ngưỡng) |
| Từ nhận diện khách đến khi tóm tắt phiên sẵn sàng (Call Brief), p50 / p95 | 182 / 287 ms (69 phiên quay lại) | Không áp dụng | M1: ≤ 5 giây · M2: ≤ 3 giây | Đạt cả hai mốc |
| Từ khi khách ngừng nói đến âm thanh trả lời đầu tiên (TTFA), p95 | Chưa đo | Chưa đo | M2: ≤ 2,5 giây | Cần đo trên luồng thoại |
| Số phiên xử lý đồng thời khi demo | 1 phiên độc lập trên stack | 1 phiên độc lập trên stack | M1: 1 · M2: ≥ 2 | Đạt M1; M2 chưa xác minh |

p50 là trung vị, p95 là phân vị thứ 95. Phép đo đạt yêu cầu tối thiểu 100 lượt của BTC (323 lượt mỗi cấu hình, bỏ 3 lượt warm-up), đo tại ranh giới harness qua chat streaming (TTFT đến delta trả lời đầu tiên đã qua kiểm tra, Total đến delta cuối).

TTFT bằng Total vì câu trả lời chỉ được phát sau khi qua kiểm tra toàn câu (không phát từng phần rồi sửa). Phần lớn độ trễ đến từ các lần gọi model nối tiếp: mỗi lần gọi `gemma4:31b` qua Ollama Cloud mất p50 ~1 s, p95 ~1,8 s; một lượt thường cần 2–3 lần gọi (chọn công cụ, trả lời, sửa bản nháp nếu bị chặn) cộng bước LLM semantic review (~0,8 s). Thử nghiệm tắt semantic review (run `124247Z`) ước tính giảm TTFT p50 xuống ~2,5 s và p95 xuống ~5,8 s (vẫn trên 3 s) nhưng TSR Full giảm còn 77,1% và phát sinh 1 lỗi over-escalation; chi tiết ở [tài liệu bàn giao](BAN-GIAO-khoi_fix_ttft-20261127.md). Bộ tự kiểm `call_brief_max` báo 69/70 vì `TEAM-48` call_2 là khách mới định danh, chưa có phiên trước; `reference_eval.py` chỉ tính các giá trị có đo. [Quy tắc đo](../../BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md)

## 5. Trước và sau cải tiến trên cùng bộ mẫu

Ba run Full trên cùng bộ 48 kịch bản (`eval/scenario_final`), cùng model `gemma4:31b` và cùng máy:

| Chỉ số Full | Code ngày 26/11 (`065208Z`) | Code 27/11 trước cải tiến latency (`084346Z`) | Sau cải tiến (`113656Z`) |
|---|---:|---:|---:|
| Execution | degraded (1 `GraphRecursionError`) | healthy | healthy |
| RQR ↓ | 4,5% | 1,5% | 3,0% |
| CCR ↑ | 49,0% | 61,5% | 65,6% |
| TSR ↑ | 77,1% | 81,2% | 81,2% |
| HR tổng ↓ (giá/KM) | 2,1% (2,8%) | 0,9% (0,0%) | 3,8% (0,0%) |
| TTFT p50 / p95 | 2,6 / 6,5 s | 3,6 / 7,4 s | 3,4 / 6,4 s |
| Tổng số lần gọi model | — | 703 | 597 |
| Lượt phải trả lời câu xin lỗi chung | 62 | 70 | 52 |

Các cải tiến giữa `084346Z` và `113656Z`:

1. Guardrail nhận biên nhận `order.create` và kết quả `order.status` (kể cả của lượt trước trong phiên) làm bằng chứng, giảm lượt bị chặn `order_creation_unverified` từ 24 xuống 3.
2. Khi bản nháp bị chặn vì thiếu báo giá hoặc tồn kho, harness tự tra bổ sung rồi kiểm tra lại bản nháp trước khi gọi model viết lại.
3. Xác nhận đơn trực tiếp từ biên nhận `order.create` mà không gọi thêm model.
4. Khi `catalog.search` trả về đúng một sản phẩm không biến thể, hệ thống tra kèm giá và tồn kho trong cùng bước.

Kết quả: số lần gọi model giảm 15% (703 → 597), TTFT p95 giảm 7,4 → 6,4 s, lượt xin lỗi chung giảm 70 → 52, TSR giữ 81,2% và CCR tăng lên 65,6%. [Lịch sử cải tiến](../REPORT.md)

## 6. Phân tích lỗi trên 14 trường hợp (run `113656Z`, cấu hình Full)

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

Ngoài 14 trường hợp trên, 52/323 lượt Full (16%) rơi về câu xin lỗi chung sau khi bản nháp bị chặn hai lần, chủ yếu do `price_without_quote` (21), `unsupported_policy_or_internal_claim` (11) và `unsupported_product_spec` (6). Đây là đánh đổi có chủ đích để giữ HR giá/khuyến mãi ở mức 0,0%, nhưng làm giảm TSR.

## 7. Tái lập điểm hội thoại và phạm vi M2

Chạy từ thư mục gốc dự án để tái lập run eval 48 kịch bản:

```powershell
python scripts/compose_up.py
python seed_btc.py --data-dir ..\BTC-Data-Vong1-TEAMS
python run_eval.py
```

Kết quả được lưu tại `results-submission/<run-id>/` (`run.json`, `btc_score.json`, `m1_conversation_acceptance.json`, trace) và chấm chéo bằng `reference_eval.py` theo [README](../README.md).

| Phép đo M2 hoặc chi phí | Bằng chứng hiện có |
|---|---|
| Truy hồi chính sách, 60 câu (`qa_labeled.json`, 6 loại) | `Recall@3 = 84,7%` (50/59), `Recall@5 = 91,5%` (54/59), `MRR@5 = 0,752`, latency truy hồi p50/p95 = 328 / 544 ms. `multi_hop_full_recall@3/@5 = 41,7% / 50,0%` (12 câu). `by_type_recall@5`: single 96,0%, multi_hop 91,7%, version_conflict 100%, numeric 100%, unanswerable 100%, restricted 40,0% (2/5; trượt Q52, Q54, Q55). |
| Chất lượng câu trả lời & từ chối RAG (`business_judge` + Ragas 0.4.4, `gemma4:31b`, 60/60 câu) | `correctness = 90,0%` (54/60), `version_accuracy = 100,0%` (6/6), `numeric_accuracy = 75,0%` (3/4; Q57 lệch do `mock_tools.py` cộng dồn `AIR-OCT` và `AIR-2ND-50` thành 10.135.000đ khác `expected_answer` 10.435.000đ), `restricted_leakage = 0,0%` (0/5), `faithfulness = 97,9%` (52/52), `factual_correctness_f1 = 0,436`. Trên scorer BTC (`business_judge`): `abstain_rate_restricted = 100,0%` (5/5), `false_abstain_rate = 4,3%` (2/47: Q26, Q37), `abstain_rate_unanswerable = 12,5%` (1/8 — dù 8/8 câu `unanswerable` được judge chấm `correct=true` và không bịa, model judge gán `action="answer"` cho các câu nói "chưa có thông tin" theo `FAQ-03`/`SP-AIR-03`). |
| Đối chiếu LLM-judge với người chấm (M2) | Đã chấm mù 30 câu phân tầng đủ 6 loại ([nhãn người chấm](../results-rag/human_labels-e2e-02.json)): tỷ lệ đồng thuận **96,7%** (29/30), **Cohen's kappa = 0,839** (đạt yêu cầu ≥ 20 mẫu). Ca lệch duy nhất là Q25 (judge trừ điểm do thiếu ý phụ về màng lọc và `TRADE-IN-AP`). Chưa có TSR qua 3 seed cho customer simulator. |
| Vòng cải tiến tri thức (K0 → K1) | Run `113656Z` đã sinh proposals (`results-submission/20261127T113656Z-0cb1b876.knowledge/`), chưa duyệt và phát hành K1. Hai vòng lịch sử ngày 12/11 (K0 `093027Z` → K1 `095815Z`): TSR 79,3% → 82,8%, HR 7,5% → 7,1%, RQR 0% → 7,7%; bộ kiểm đánh dấu `improvement_demonstrated=false`. |
| Tách người nói (Diarization) | Diarization theo lượt đạt 83,5% trên 120 file của đội và 97,1% trên 4 hội thoại BTC đọc bằng VieNeu. |
| Độ chính xác gọi công cụ và chi phí mỗi cuộc | Chưa có số đo tách riêng cho cặp Full/Baseline trong báo cáo. |

Các chỉ số truy hồi, chất lượng câu trả lời và calibration của RAG lấy từ phép đo độc lập của kho chính sách (tái lập được bằng `reference_eval.py --rag`). Calls-to-Close trung bình trên run `113656Z` là 1,94 cuộc với Full và 1,93 cuộc với Baseline. [Điểm RAG đầy đủ kèm judge & calibration](../results-rag/e2e-score-03/report.json) · [Phạm vi bộ test riêng](../eval/scenario_final/README.md)
