# M1 lượt 1: extraction và 6 ca TSR — 15/11/2026

Đã review và sửa phép trích xuất, replay offline bằng scorer BTC. Chưa sửa hành vi agent, chưa có run live mới. Sáu ca TSR vẫn fail đúng theo trace; không sửa scenario/scorer để cho qua.

## Nguồn và phạm vi

- Run agent nguồn: `ai-services/eval_harness/results/knowledge-triplet-final/20261113T194849Z-e1e46a43/k0/20261113T194849Z-e62e734b/` (13/11).
- Đối chiếu extraction trước lượt này: `results/measurement-audit/20261115-m1-extraction-v2/`.
- Replay cuối lượt này: [20261115-m1-round1-final](../ai-services/eval_harness/results/measurement-audit/20261115-m1-round1-final/replay_manifest.json).
- [Biên bản JSON](m1-round1-review-20261115.json) lưu nguồn/hash, quyết định riêng cho **106 candidate** tồn đọng: full 51 claim; baseline 52 claim + 3 câu hỏi không chắc. Có đủ 6 ca TSR, lời khách/agent, tool và diagnostics liên quan.
- Chọn ngẫu nhiên **20/170 lượt full**, seed `20261115`, rồi kiểm cùng 20 lượt baseline (40 record). Nhãn projection được ghi riêng và so với output; biên bản cũng ghi các loại claim chưa được đo, không tính precision/recall từ sample này.

**Đây là assistant self-review**, không phải kiểm tay độc lập của người/BTC. Không tự ghi `independent_human_review=true` hoặc đổi acceptance gate. Biên bản là tài liệu review, không được dùng làm input sửa nhãn theo điểm mong muốn.

## Những lỗi đã sửa

| Lỗi quan sát được | Cách xử lý |
|---|---|
| Hỏi màu xuất `preferred_color`, còn BTC public sample dùng `color`; RQR so tên chính xác nên bỏ sót hỏi thừa | Xuất `color`, sửa nhãn regression tương ứng; thêm test trực tiếp với scorer BTC chứng minh câu hỏi màu đã biết bị phạt. Không đổi dữ liệu scenario. |
| “Không phát sinh thêm chi phí nào”, “Khi nào cần… chị báo em nhé” bị nhận thành câu hỏi | Nhận câu kể/lời mời khi không có dấu hỏi; câu hỏi thật vẫn giữ. |
| “Tổng giá 779.000đ” bị nhận thành `price_vnd` | Giữ candidate `unsupported_mapping/category=total`, không coi tổng giỏ là đơn giá. |
| “Đơn từ 500.000đ… miễn phí vận chuyển” thành freeship/KM vô điều kiện | Giữ điều kiện trong sidecar; không gán quyền lợi chung cho mọi đơn/ngành. |
| Mất phạm vi “Từ lần đổi thứ hai trở đi” ở dấu phẩy | Giữ điều kiện cùng khoản phí; không chiếu thành phí đổi vô điều kiện. |
| Miễn phí thu hộ COD, ngày giao ISO bị lẫn vào nhóm parse fail | Nhận diện rõ `cod_fee`/`calendar_delivery`, giữ sidecar, không gán freeship hoặc delivery_days. |
| Một số tiêu đề, lời xin đợi kiểm tra, yêu cầu xác nhận báo giá bị coi là claim chưa parse | Nhận `not_assertion`; không loại các claim bảo hành loại trừ/trạng thái đơn/giá so sánh thật. |
| Mất thời hạn “đổi trả cho các đơn hàng mới… 7 ngày”, “14 → 7 ngày” | Trích đúng `return_days=7`. |
| Mất cách nói “có sẵn trong kho” | Nhận positive/negative; giữ phạm vi size số trong sidecar thay vì gán tồn chung. |
| Hỏi khóa trẻ em có bắt buộc bị gán `has_children`; xin điều chỉnh mức chi bị gán `blocker` | Tách đúng `product_requirements` và `budget_consent`; không coi hỏi yêu cầu sản phẩm là hỏi lại hồ sơ gia đình. |

Tool, ground truth, scenario ID và điểm không được đưa vào quyết định extractor. Các test thêm dùng lời nói làm đầu vào; tool không sửa lời agent.

## Kết quả replay so với extraction-v2

| Chỉ số | Trước | Sau |
|---|---:|---:|
| Full claim unresolved | 51 | 27 |
| Baseline claim unresolved | 52 | 19 |
| Baseline câu hỏi emitted còn uncertainty | 3 | 1 |
| Full claim emitted | 145 | 135 |
| Baseline claim emitted | 125 | 118 |
| Full RQR | 3,7% (1/27) | 3,7% (1/27) |
| Baseline RQR | 31,6% (12/38) | 40,5% (15/37) |
| RQR giảm tương đối theo scorer BTC | 88,3% | 90,9% |
| Full CCR | 63,3% | 63,3% |
| Full TSR | 79,3% (23/29) | 79,3% (23/29) |
| Full HR giá/KM | 0/38 | 0/38 |
| Full HR trên claim scorer kiểm | 0/52 | 0/52 |
| Baseline HR trên claim scorer kiểm | 0/40 | 0/41 |
| TTFT / Total p95 full | 4.068 ms | 4.068 ms |

RQR baseline tăng do sửa vocabulary màu và bỏ một câu kể khỏi mẫu số các call được chấm, không phải baseline được chạy lại. Delta này là **sửa đo lường**, không phải bằng chứng cải tiến agent C.5. Ít unresolved/emitted hơn không chứng minh recall tốt hơn. Các claim điều kiện/không có mapping vẫn hiện trong sidecar; không loại khó để tự nhận HR bằng 0 trên toàn bộ lời nói.

`extraction_status=needs_review` vẫn đúng. Còn 27/19 claim chưa phân giải (bảo hành loại trừ, điều kiện đổi, số lần giao, trạng thái đơn, câu so sánh, fragment/masked span...) và một câu baseline xin làm rõ điều kiện chưa rõ slot. Các loại qualified/unsupported cũng chưa được scorer phẳng chấm đầy đủ. Mẫu review ghi thêm lỗ hổng độ phủ: lời đã tạo đơn, trạng thái/mã vận đơn, đặc tính, điều kiện tem mác và suy luận thời hạn không được bao phủ toàn bộ bởi HR hiện tại.

## Kết luận từng ca TSR và việc chuyển lượt 2

| Ca/call | Bằng chứng và phân loại | Việc cần tái hiện/sửa ở lượt 2 |
|---|---|---|
| SC-T06 / call_3 | Chỉ kiểm tồn `SKU-SN-TRK` gốc, quote size 42 xám nhưng không kiểm tồn `SKU-SN-TRK-42-XAM`. Lượt 2 nói có sẵn mà không gọi thêm tool. **Thiếu evidence đúng biến thể**, không phải lỗi extractor. | Điều phối kiểm tồn đúng biến thể khách yêu cầu; phân biệt hỏi điều kiện đổi với tư vấn mua mới. Không tạo yêu cầu đổi khi khách chưa đồng ý. |
| SC-T09 / call_1 | Khách đã hỏi tồn nhưng agent chỉ catalog/quote rồi hỏi có muốn kiểm tồn. Không có `inventory.check` trong cả call. **Bỏ sót yêu cầu read-only**. | Thực hiện kiểm tồn đã được khách yêu cầu và trả lời các phần hỏi; không xin consent giao dịch cho một thao tác đọc. |
| SC-T18 / call_2 | Quote giỏ 779.000 có trong tool, nhưng lượt 1 chỉ nói Fatz 490.000. Khi khách nói đồng ý tổng giá, agent mới đọc tổng và xin xác nhận. **Luồng báo giỏ/nhận consent chưa hoàn chỉnh**. | Giữ đủ hai SKU/qty, kiểm tồn và đưa tổng giỏ ra trước khi nhận consent. Không bỏ gate vì kịch bản cố định nói “đồng ý tổng giá”. |
| SC-T19 / call_1 | Giá 1.890.000 và tồn đã được trả ở lượt 1. Khách yêu cầu một chiếc/chuyển khoản ở lượt 3 nhưng agent vẫn xin xác nhận lại; không tạo đơn. **State offer/consent cần tái hiện**, chưa thể chốt nguyên nhân nội bộ chỉ từ public trace. | Kiểm offer/qty/payment và ảnh hưởng policy.search; cho phép consent hợp lệ với offer đã trình bày, giữ xác nhận khi điều khoản thực sự đổi. |
| SC-T20 / call_2 | **Đã gọi tool**, nhưng `action=exchange_product`, BTC yêu cầu `exchange_size`. Tool trả `pickup_scheduled`, chênh 40.000; verifier `price_without_quote`, recovery hết đường và gửi fallback. | Chọn đúng action cho đổi biến thể cùng sản phẩm; dựng câu trả lời từ kết quả exchange/price_diff đúng trường. Không retry giao dịch đã thành công chỉ vì câu trả lời bị verifier từ chối. |
| SC04 / call_2 | Lượt 3 có quote/tồn đúng `SKU-SN-RUN2-41-DEN` cùng ngày, nhưng không create và trả thiếu evidence. Giá cho lựa chọn chưa được trình bày rõ trước đó. **Điều phối/gate cần tái hiện**, không chứng minh chính xác gate nào chỉ bằng trace. | Kiểm selection/evidence/qty/offer theo biến thể; dùng lượt sớm để báo giá. Không hạ guardrail freshness/consent để ép pass. |

Scorer so `tool_calls/args_match` trực tiếp nên sửa `questions/claims` không thể tự làm 6 ca này pass. Không có lỗi extractor làm mất tool trong replay. Các diagnostics khác phần lớn ghi model/verify thành công; riêng SC-T20 ghi fallback/recovery thất bại. Không dùng trạng thái “model succeeded” để khẳng định nghiệp vụ đã đúng.

## Kiểm chứng

**311 focused tests qua trong 9,19 giây**, dùng wrapper chặn mạng/credentials/`.env`. Gồm semantics, tiền/ngân sách, candidate contract/labels, sidecar integrity, facts-used, scorer alignment, acceptance, reporting, replay và audit trace/score. Test mới được chạy fail trước khi sửa. Không chạy full suite, model/DB/ASR hoặc benchmark.

Replay dùng nguyên `btc-release/eval/reference_eval.py` trong snapshot run nguồn. Manifest ghi `source_preserved=true`, `source_integrity_issues=[]`; annotation replay chỉ thay `questions/claims`, giữ nguyên agent/user/tool/memory/facts_used/latency cho cả 340 lượt.

Lệnh replay (thư mục output phải mới, không ghi đè):

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.reextract_trace \
  --source-run ai-services/eval_harness/results/knowledge-triplet-final/20261113T194849Z-e1e46a43/k0/20261113T194849Z-e62e734b \
  --output-dir <thu-muc-output-moi> \
  --btc-root ai-services/eval_harness/results/knowledge-triplet-final/20261113T194849Z-e1e46a43/k0/20261113T194849Z-e62e734b/btc-release
```

Lượt 1 hoàn tất phần review/sửa đánh giá xác định được. Chưa chứng nhận extraction hoàn hảo hoặc đạt M1; kiểm tay độc lập và đo latency code mới vẫn là bằng chứng còn thiếu. ASR thuộc người phụ trách khác, không thực hiện trong lượt này.
