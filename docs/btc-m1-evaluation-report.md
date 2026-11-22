# Báo cáo đánh giá TeleSale M1

Các bảng dưới đây ghi kết quả lịch sử trên bộ của team. Bản nộp hiện tại đã qua rehearsal offline với provider giả lập. Điểm chính thức của bản nộp cần được chạy lại với cấu hình chốt và được kiểm phần trích xuất.

## Full và baseline ngày 18/11

Run `20261118T054721Z-ac17f7e7` dùng Gemma 4 31B, chat streaming, 29 scenario, 67 cuộc gọi và 170 lượt cho mỗi cấu hình. Hai cấu hình dùng chung model, tham số, seed, scenario và knowledge release. Baseline giữ working memory trong phiên, tắt truy xuất profile và episodic từ các phiên trước.

| Chỉ số từ scorer BTC | Full | Baseline |
|---|---:|---:|
| Repeat-Question Rate ↓ | 0/22 (0,0%) | 18/35 (51,4%) |
| Context Carryover Rate ↑ | 53/79 (67,1%) | 13/79 (16,5%) |
| Task Success Rate ↑ | 29/29 (100,0%) | 22/29 (75,9%) |
| Hallucination Rate ↓ | 0/60 (0,0%) | 0/49 (0,0%) |
| Số lượt trung bình mỗi cuộc | 2,54 | 2,54 |
| TSR riêng ca khó ↑ | 100,0% | 80,0% |
| HR giá/KM ↓ | 0/37 (0,0%) | 0/30 (0,0%) |
| Guardrail violations ↓ | 0 | 0 |
| TTFT p95 | 2.594 ms | 2.363 ms |
| Total p95 | 2.613 ms | 2.508 ms |
| Call Brief p95 | 244 ms, 38 mẫu | Chưa đo |

SHA-256 của `btc_score.json` là `33f0a6311810ff165c858bde9c55407c687a47ce2ac91598017580812fa8e7e4`. Artifact integrity đạt khi kiểm offline. Theo các điều kiện nghiệm thu hiện tại, run lưu thiếu bằng chứng đầy đủ cho execution health và extraction review. BTC sẽ đối chiếu extractor thủ công trên mẫu trace của lượt chấm.

`questions` và `claims` được sinh từ câu trả lời agent và bằng chứng tool bằng extractor của team. Scorer dùng nhãn scenario để tính RQR, CCR, TSR và HR. Xem [hợp đồng trích xuất và pipeline](m1-acceptance.md#4-chạy-cặp-fullbaseline). Báo cáo ASR local của hai tập và chi phí/cuộc cho cấu hình chốt đang chờ dữ liệu đo.

## Hai vòng Knowledge Gap ngày 12/11

K0 `20261112T093027Z-f42a59c5` và K1 `20261112T095815Z-369b9c88` qua kiểm tra tính so sánh. Hai run có cùng hash bộ test, source, seed và scorer, cùng model/tham số và phần cứng. Hai knowledge release khác nhau.

| Chỉ số Full | K0 | K1 | Thay đổi |
|---|---:|---:|---:|
| RQR ↓ | 0,0% | 7,7% | +7,7 điểm % |
| CCR ↑ | 62,0% | 63,3% | +1,3 điểm % |
| TSR ↑ | 79,3% | 82,8% | +3,5 điểm % |
| HR ↓ | 7,5% | 7,1% | −0,4 điểm % |
| HR giá/KM ↓ | 11,1% | 10,5% | −0,6 điểm % |

K1 có hồi quy RQR và cả hai run còn chờ review trích xuất. Bộ kiểm tra đánh dấu `improvement_demonstrated=false`. Luồng của bản hiện tại giữ bước reviewer duyệt bản sửa, kiểm nguồn và regression test trước khi phát hành knowledge release. [Quy trình chạy lại hai vòng](m1-acceptance.md#5-knowledge-gap-loop-hai-vòng)

## Phân tích lỗi

[Phân tích 15 lỗi trên run 09/11](m1-error-analysis-20261109.md) chỉ ra vị trí trace, lỗi quan sát được và hướng xử lý cho từng ca. [Rà soát sau K0/K1](hr-grounding-repairs-20261112.md) đối chiếu lỗi gán chéo SKU và giá, rồi kiểm hồi quy offline. [Kiểm tra hiện trạng và bằng chứng còn thiếu](btc-submission-evidence.md) dùng để chốt hồ sơ.
