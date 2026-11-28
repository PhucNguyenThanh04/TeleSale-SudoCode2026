# Báo cáo đánh giá TeleSale

Phép đo hội thoại dùng bộ test riêng của đội gồm **48 kịch bản**, trong đó có **38 ca khó**. Mỗi lượt Full có 118 cuộc gọi và 323 lượt khách. Full K0 và Full K1 đều bật bộ nhớ liên phiên. K1 dùng release tri thức sau khi duyệt và phát hành các đề xuất từ vòng Knowledge Gap Loop.

## 1. Bảng điểm ba cấu hình

| Chỉ số BTC | Baseline không bộ nhớ (mốc đối chiếu) | Full K0 | Full + Knowledge Gap Loop K1 |
|---|---:|---:|---:|
| Tỷ lệ hỏi lại (RQR) ↓ | 26,6% (21/79) | 1,9% (1/53) | 2,1% (1/48) |
| Tỷ lệ giữ ngữ cảnh (CCR) ↑ | 13,5% (13/96) | 69,8% (67/96) | 63,5% (61/96) |
| Tỷ lệ hoàn thành tác vụ (TSR) ↑ | 62,5% (30/48) | 79,2% (38/48) | 81,2% (39/48) |
| TSR riêng ca khó ↑ | 55,3% (21/38) | 76,3% (29/38) | 78,9% (30/38) |
| Tỷ lệ mệnh đề sai (HR) tổng ↓ | 0,0% (0/71) | 8,2% (8/98) | 0,0% (0/86) |
| HR giá và khuyến mãi ↓ | 0,0% (0/49) | 0,0% (0/65) | 0,0% (0/62) |
| Vi phạm guardrail theo scorer | 0 | 0 | 0 |
| Số lượt trung bình mỗi kịch bản | 6,73 | 6,73 | 6,73 |
| Số lượt trung bình mỗi cuộc gọi | 2,74 | 2,74 | 2,74 |
| Calls-to-Close | 1,93 | 1,94 (35 kịch bản có chốt) | 1,94 (35 kịch bản có chốt) |
| TTFT p50 / p95 (ms) ↓ | 3.380 / 6.405 | 2.591 / 5.126 | 2.590 / 5.046 |
| Total latency p50 / p95 (ms) ↓ | 3.380 / 6.405 | 2.591 / 5.126 | 2.590 / 5.046 |
| Call Brief p50 / p95 (ms) ↓ | Không áp dụng | 167 / 285 (69 phiên) | 159 / 261 (69 phiên) |

### Đối chiếu có kiểm soát theo Phụ lục A.6

Cặp Baseline–Full dưới đây đến từ cùng một run, dùng cùng 48 kịch bản, model, tham số, seed và release tri thức. Baseline chỉ tắt bộ nhớ từ các phiên trước. Cột Baseline ở bảng trên dùng lại kết quả này làm mốc tham khảo cho hai lượt Full mới. [Nguồn cặp Baseline–Full](btc-m1-evaluation-report.md#kết-quả-full-so-với-baseline)

| Chỉ số A.6 | Baseline không bộ nhớ | Full cùng run đối chứng | Chênh lệch |
|---|---:|---:|---|
| RQR ↓ | 26,6% | 3,0% | Giảm 88,7% tương đối |
| CCR ↑ | 13,5% | 65,6% | Tăng 52,1 điểm phần trăm |
| TSR ↑ | 62,5% | 81,2% | Tăng 18,7 điểm phần trăm |
| HR giá và khuyến mãi ↓ | 0,0% | 0,0% | 0 điểm phần trăm |
| Số lượt trung bình mỗi kịch bản | 6,73 | 6,73 | 0 |

Extractor đọc câu trả lời cuối của agent để gán câu hỏi vào các trường thông tin và đánh dấu câu hỏi xác nhận trong `questions`. Với `claims`, extractor nhận diện mệnh đề thương mại và ghi cặp trường–giá trị để scorer đối chiếu với dữ kiện chuẩn của kịch bản. [Bộ trích xuất](../ai-services/eval_harness/extractor.py)

**Đối chiếu ngưỡng M1.** Cặp đối chứng đạt mức giảm RQR ≥ 40%. Hai lượt Full K0 và K1 đạt ngưỡng TSR ≥ 70%, HR giá và khuyến mãi ≤ 5%, Total p95 ≤ 8.000 ms và Call Brief p95 ≤ 5.000 ms. TTFT p95 vẫn vượt ngưỡng 3.000 ms.

## 2. Trước và sau cải tiến Knowledge Gap Loop

Quy trình gồm chạy Full K0, trích gap từ trace, duyệt đề xuất có nguồn trên giao diện, phát hành K1 và chạy lại Full trên cùng bộ test. Sau phát hành, TSR tăng thêm một kịch bản, HR tổng giảm 8,2 điểm phần trăm và TTFT p95 giảm 80 ms. CCR giảm 6,3 điểm phần trăm. Số câu hỏi thừa vẫn là một, nhưng mẫu số giảm từ 53 xuống 48 nên RQR tăng nhẹ.

| Quan sát từ artifact | Full K0 | Full + Knowledge Gap Loop K1 |
|---|---:|---:|
| Gap được ghi nhận | 82 | 77 |
| Phân loại lỗi sinh câu trả lời (`generation`) | 42 | 45 |
| Phân loại chưa đủ bằng chứng (`insufficient_evidence`) | 40 | 32 |
| Gap có bản nháp | 40 | 32 |
| Số lần gọi `policy.search` trong trace | 34 | 34 |
| Lượt tra cứu trả về đoạn FAQ có mã `KG-` | 0 | 0 |

K1 đạt thêm `TEAM-25` và `TEAM-43`, còn `TEAM-35` chuyển sang trượt. Đây là một lượt đo cho mỗi release, nên chênh lệch phản ánh kết quả quan sát được. Trace K1 xác nhận release đang dùng và các đoạn truy xuất, còn ảnh hưởng của alias bổ sung lên từng câu trả lời chưa được đo riêng.

## 3. Phân tích 10 trường hợp hệ thống làm sai

Các vị trí dưới đây tra được bằng `scenario_id`, `call` và `turn` trong trace. Những lỗi thuộc tiêu chí TSR được đối chiếu với kịch bản và tệp điểm BTC.

| # | Kịch bản và vị trí | Lỗi và bằng chứng quan sát | Hướng xử lý |
|---:|---|---|---|
| 1 | `TEAM-02`, `call_2`, lượt 3 | Cả K0 và K1 đã tra đơn ở lượt trước nhưng dừng ở yêu cầu xác minh bổ sung khi khách đồng ý đổi size. Trace thiếu `order.update` với thao tác `exchange_size` cho size L màu navy. | Kiểm tra điều kiện xác minh để cập nhật đơn. Khi đủ quyền và khách đã xác nhận, gửi đúng thao tác đổi size và thông báo kết quả từ biên nhận. |
| 2 | `TEAM-07`, `call_1`, lượt 2 | Khách hỏi thời hạn và phí đổi size. Truy vấn của cả hai lượt Full làm mất ý hỏi thời hạn. Kết quả có `DT-03` và `CL-01`, thiếu `DT-01` trực tiếp. Cả hai câu trả lời đều bỏ qua thời hạn và phí. | Giữ cả hai ý khi tra chính sách và kiểm tra câu trả lời đã nêu đủ thời hạn lẫn phí trước khi chuyển chủ đề. |
| 3 | `TEAM-13`, `call_2`, lượt 1 ở K0 và lượt 2 ở K1 | Khách nâng ngân sách lên 5,5 triệu. Cả hai lượt Full gọi `catalog.search` bằng từ khóa chung, thiếu bộ lọc `max_price_vnd` mà scorer kiểm tra. | Đưa ngân sách mới nhất vào tham số bộ lọc khi tìm sản phẩm. |
| 4 | `TEAM-20`, `call_2`, lượt 3 | Khách chọn size XL màu navy. Cả K0 và K1 truyền đúng mã biến thể nhưng gọi `order.update` với `exchange_product`. Kịch bản yêu cầu `exchange_size`. | Phân biệt đổi biến thể cùng sản phẩm với đổi sang sản phẩm khác trước khi gọi tool. |
| 5 | `TEAM-22`, `call_2`, lượt 2–3 | K0 dừng ở `order.preview_update`. K1 từ chối vì cho rằng đơn đã quá hạn. Cả hai thiếu thao tác `return` mà kịch bản yêu cầu và thiếu hướng dẫn dùng biểu mẫu hoàn tiền. | Đối chiếu mốc nhận hàng trước khi kết luận về thời hạn. Khi đủ điều kiện và khách đã xác nhận, gửi yêu cầu trả hàng và chỉ rõ kênh nhập thông tin hoàn tiền. |
| 6 | `TEAM-25`, `call_2`, lượt 3 | K0 ghi nhận khách chốt đơn COD nhưng trace thiếu `order.create`. K1 gọi đúng tool và đạt kịch bản. | Sau khi khách chốt, thực hiện thao tác tạo đơn rồi dùng biên nhận để xác nhận. |
| 7 | `TEAM-33`, `call_2`, lượt 1–3 | K0 gọi báo giá theo Cần Thơ sau khi khách đổi địa chỉ sang Hà Nội, rồi nói đơn được miễn phí giao hàng. K1 tra theo Hà Nội nhưng vẫn chưa báo được phí. Toàn bộ 8 mệnh đề sai của Full K0 trong báo cáo HR thuộc trường `freeship` của kịch bản này. | Ràng buộc báo giá với địa chỉ mới nhất và dùng báo giá tương ứng để trả lời về phí. |
| 8 | `TEAM-35`, `call_1`, lượt 2 | Sau khi tra lịch nghỉ, K1 lặp lại mốc từ báo giá cũ và thiếu ngày giao sớm nhất mà kịch bản yêu cầu. K0 có nêu được mốc đó. | Tính lại thời gian giao khi thông tin lịch nghỉ làm thay đổi mốc trong báo giá ban đầu. |
| 9 | `TEAM-36`, `call_1`, lượt 1 | Cả hai lượt Full trả lời bảo hành 24 tháng, nhưng `catalog.search` chỉ tìm theo tên và thiếu tham số SKU chính xác. Scorer đánh trượt tiêu chí gọi tool. | Khi đã xác định được SKU, tra bằng tham số mã sản phẩm để lưu đúng bằng chứng. |
| 10 | `TEAM-43`, `call_2`, lượt 3 | K0 trả lời chung rằng chưa đủ thông tin và không hướng dẫn kênh hoàn tiền. K1 nêu rõ biểu mẫu của hệ thống và đạt tiêu chí. | Khi khách hỏi nơi cung cấp dữ liệu nhạy cảm, hướng dẫn trực tiếp đến biểu mẫu bảo mật. |

## 4. Nguồn số liệu và tái lập

Nguồn là `/home/thanh-phuc/test_final/TeleSale-SudoCode2026/results-submission/btc-eval/`. Hai lượt Full có cùng 323 vị trí lượt và cùng văn bản khách hàng. Cả hai báo `completed`, execution `healthy`, đều dùng chat streaming và loại ba lượt warm-up khỏi điểm. TTFT đo đến phần trả lời đầu tiên đã qua kiểm tra, còn Total đo đến phần cuối. TTFA chưa được đo trong hai lượt này.

| Cấu hình | Run ID | Knowledge release | Trace | Tệp điểm BTC |
|---|---|---|---|---|
| Baseline không bộ nhớ | `20261127T113656Z-0cb1b876` | Release của đợt đo trước | Ngoài thư mục kết quả hiện tại | [Bảng điểm M1](btc-m1-evaluation-report.md#kết-quả-full-so-với-baseline) |
| Full K0 | `704c7426-1d2b-4ca3-b703-50e26675cb77` | `policy-79dd0a921214cb762c5e4514232d9522` | `full-k0.jsonl` | `btc-full-k0.json` |
| Full + Knowledge Gap Loop K1 | `4b2a6781-cf37-47d0-a584-ae86b198a553` | `policy-0dda84a377d562a2f63c2fc972316929` | `full-k1.jsonl` | `btc-k1.json` |

Cả hai bản sao gói BTC có **35/35 tệp khớp manifest** và dùng cùng bản `reference_eval.py`. Hash từng trace khớp với tệp `.report.json` và `.knowledge-gaps.json` tương ứng. Chấm lại hai trace cho kết quả khớp với tệp điểm đã lưu.

Chạy từ thư mục gốc checkout `test_final` để chấm lại trace hiện có. Hai lệnh in kết quả ra terminal và chỉ đọc trace.

```sh
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./eval/scenario_final --trace ./results-submission/btc-eval/full-k0.jsonl
python ./results-submission/btc-eval/full-k0.btc-release/eval/reference_eval.py --scenarios ./eval/scenario_final --trace ./results-submission/btc-eval/full-k1.jsonl
```

Bộ 48 kịch bản là bộ test riêng của đội. [Bộ kịch bản](../eval/scenario_final/README.md) · [Quy trình xuất trace và chấm BTC](../README.md#bước-4-xuất-baseline-và-full-k0) · [Kết quả ASR độc lập](../speech/asr-benchmark-report.html) · [Kết quả RAG độc lập](../results-rag/e2e-score-03/report.json)
