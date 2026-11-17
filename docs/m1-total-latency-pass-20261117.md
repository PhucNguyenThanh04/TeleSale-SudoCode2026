# Kết quả vòng tối ưu Total M1 — 17/11/2026

Vòng được duyệt gồm sửa routing, giảm vòng model có bằng chứng trong trace và đo một cặp Full/Baseline để quyết định bước tiếp theo. **Kết quả: Full vẫn chưa đạt TTFT; chuyển sang thiết kế streaming là bước tiếp theo có cơ sở. Chưa nghiệm thu M1.**

## Phép đo

- Trước: `20261117T070242Z-849d1e51`.
- Sau: [20261117T080357Z-d1f6f8e2/run.json](../ai-services/eval_harness/results/paired-knowledge/20261117T080357Z-d1f6f8e2/run.json).
- Mỗi nhánh đủ 29 kịch bản, 67 cuộc, 170 lượt; 3 warmup. Execution healthy, artifact integrity pass, pipeline validated.
- Cùng frozen scenarios và BTC snapshot `7579dfa19ee0413a79545435724c16d9cea819c637deb78c31696aaaa8130544`; model `gemma4:31b`, provider `ollama.com`, temperature 0.2, max_tokens 256, seed 7, deep agent, history 6, tool budget 5, text không streaming.
- Preflight xác nhận runner và bốn MCP cùng DB eval `telesale`, cùng knowledge release. Canonical `run_pair` reset runtime trước mỗi nhánh như được duyệt; không phát hành K1, không đổi model/scorer/threshold và không chạy thêm cặp live.
- Report nhận BTC root thực được ghi trong run, thay vì giả định có thư mục `btc-release` ở run mới.

| Chỉ số | Full trước → sau | Baseline trước → sau |
|---|---:|---:|
| TTFT/Total p50 (ms) | 1407 → 1158 | 1429 → 955 |
| TTFT/Total p95 (ms) | 3396 → 3410 | 3627 → 2921 |
| Số request model | 168 → 125 | 194 → 141 |
| Lượt không gọi model | 38 → 67 | 32 → 60 |
| TSR | 26/29 → 28/29 | 23/29 → 23/29 |
| RQR | 0/27 → 0/28 | 17/37 → 20/39 |
| CCR | 53/79 → 52/79 | 13/79 → 13/79 |
| HR giá/KM | 0/38 → 0/35 | 0/32 → 0/31 |
| Guardrail violations | 0 → 0 | 0 → 0 |

Full vượt ngưỡng TTFT p95 3000 ms; Baseline đạt. Cả hai đạt Total p95 8000 ms. Full Call Brief p95 272 ms, đạt 5000 ms. Thay đổi CCR không tự chứng minh memory quên; số câu hỏi và claim thay đổi theo nội dung trả lời, nên các mẫu số cũng thay đổi.

## Thay đổi đã thực hiện

- Callback: phủ định ở mệnh đề “chưa trao đổi kỹ” không hủy yêu cầu hẹn gọi lại ở mệnh đề tiếp theo. Vẫn chặn callback bị phủ định, giả định, thời điểm mơ hồ.
- Policy: nhận câu hỏi tem mác/thu hồi; giữ ràng buộc ownership và ngày tạo đơn. Không bịa số ngày thu hồi khi nguồn không có.
- TDS: dùng lời từ chối có căn cứ khi catalog thiếu chỉ số; chuyển focus thông tin UF → RO mà không cấp quyền mua. Yêu cầu báo giá vẫn được xử lý khi khách nói sẽ cân nhắc thêm.
- Chuẩn bị đọc có giới hạn từ tên sản phẩm khách thực sự nói. Giá/tồn kho/bảo hành đã đủ bằng chứng được trả qua verifier hiện hữu, tránh model chỉ để gọi lại các tool đã biết. Không dùng kết quả catalog làm purchase consent và không trả một giá để thay cho câu hỏi nhiều sản phẩm.

Run live xác nhận callback đúng 10:00 ngày 22/10; ca tem mác có policy lookup; TDS không đoán và vẫn trả giá RO 6.890.000đ. Ba ca Full từng lỗi SC-T02/SC-T09/SC-T15 đã qua chấm ở run mới. Full còn SC-T22/call_2 thiếu hướng dẫn biểu mẫu hoàn tiền.

Sau phép đo, phát hiện và sửa ba vấn đề trong nhánh policy: chuyển `policy_order_bindings`/`followup_kind` qua ranh giới graph khi trả lời sớm; bỏ đoạn hướng dẫn `chunk_id`/Recall@k khỏi câu trả lời nhưng giữ nguyên điều kiện và ngoại lệ; không coi câu policy là đủ nếu còn thiếu câu trả lời tồn kho.

**Ba sửa cuối chỉ có bằng chứng offline. Số đo trong bảng thuộc phiên bản trước ba sửa này. Không sửa trace/score cũ và không suy ra p95 hoặc TSR live của checkout cuối từ test offline.**

## Kiểm tra và bằng chứng còn thiếu

- Trước live: 335 focused tests passed trong 8.27 s, [log](../ai-services/eval_harness/results/measurement-audit/20261117-total-pass-tests.txt).
- Sau sửa policy cuối: 117 focused tests passed trong 6.41 s, [log](../ai-services/eval_harness/results/measurement-audit/20261117-total-pass-post-run-final-tests.txt). Có test chạy graph/runtime thật với inference/storage giả lập để bắt lỗi mất state giữa node; test giữ ngoại lệ chính sách khi lọc phần hướng dẫn tài liệu.
- Scoped `git diff --check` đạt. Không chạy full suite. Các nhóm test có chồng lặp, không cộng thành một tổng số test khác nhau.
- [Phân tích JSON](../ai-services/eval_harness/results/measurement-audit/20261117-total-pass-analysis.json) đối chiếu saved metrics, model-call timing và gate.
- [Review assistant có dẫn nguồn](../ai-services/eval_harness/results/measurement-audit/20261117-total-pass-review.assistant.json): 152 candidate cần review, 62 supported từ đoạn policy hiện tại, 18 heading/instruction không phải business assertion, 72 pending. Review chưa complete; không phải review độc lập của con người và không thay mẫu số BTC.
- Hai gate còn fail trong run đo: `extraction_review`, `ttft_p95`. ASR, bằng chứng hai vòng cải tiến được review, demo và chi phí vẫn cần được hoàn thiện riêng.

## Quyết định Total hay streaming

Giảm request model khoảng 26–27% chưa đủ giữ Full p95 dưới 3 giây. Full vẫn có 10 lượt trên 3 giây; SC-T04/call_2/turn1 và SC-T19/call_2/turn1 chỉ gọi model một lần nhưng riêng request model mất 6044/6205 ms. Không nên tiếp tục chỉ tối ưu thao tác DB nhỏ hoặc kỳ vọng việc giảm vòng gọi tự bảo đảm TTFT.

Bước tiếp theo là streaming có đo token thực tại backend/harness, giữ cùng model và đo cả hai nhánh. Cần thiết kế cách kiểm tra phần nội dung trước khi phát ra khách, bao gồm giá/KM, PII và xác nhận giao dịch. Graph hiện sinh xong rồi verify; chỉ chia câu đã hoàn tất thành SSE không giảm TTFT thực tế. Không phát draft chưa kiểm, không lấy câu xác nhận chung hoặc token tool-call làm token trả lời đầu tiên.

Trace hiện chưa tách thời gian tới token đầu của từng request model. Request 6 giây có thể gồm hàng đợi, mạng và sinh nội dung; streaming chưa được chứng minh chắc chắn sẽ đạt 3 giây. Cần xác minh bằng transport và trace streaming thật, cùng kiểm tra Total vẫn ≤8 giây.
