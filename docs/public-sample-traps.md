# Các bẫy trong public sample BTC

Xác minh: 2026-10-03. Nguồn: `../BTC-Data-Vong1-TEAMS/test_set/public_sample/`, `catalog/crm_seed.json`, `eval/mock_tools.py`, `eval/reference_eval.py` và `asr/ground_truth.json`. Đây là bản chụp để viết regression test; **đọc lại nguồn** khi dữ liệu BTC hoặc repo thay đổi. Không cho agent runtime đọc file này như đáp án.

| Mẫu | Bằng chứng và ca cần kiểm |
|---|---|
| SAMPLE-01 | Khách nói ngân sách khoảng 5 triệu; `facts_established` lại ghi 5,7 triệu. D01 cũng ghi 5 triệu. Ưu tiên lời khách trong runtime, đánh dấu lệch nhãn test. C001 không có địa chỉ, đơn hay phiên cũ trong CRM seed; `crm.get_customer` không trả địa chỉ, nên “địa chỉ cũ” chưa có nguồn. Call_2 cần lời mở đầu tiếp nối ngắn, không hỏi mở lại slot đã biết. |
| SAMPLE-02 | `ground_truth_facts.promo_active=false` không có nghĩa “không có quà”: mock quote ngày 2026-10-18 cho `SKU-AP-X` vẫn có `GIFT-FILTER`, giá 4.890.000đ. Không tự giảm thêm hay phủ nhận quà khi tool trả quà. “Lấy cái đó” phải resolve SKU từ phiên trước. |
| SAMPLE-03 | Call_1 phải lưu order ID từ kết quả `order.create` thật. Call_2 đổi size: resolve `SKU-SN-CAS-40-DEN` trong catalog, kiểm tồn trước `order.update` và dùng chính sách theo ngày tạo đơn. |
| SAMPLE-04 | Call_1 dùng `fb.hạnh.274` nhưng C017 trong CRM seed có `fb_id=null`; khách cung cấp SĐT cuối call là tín hiệu liên kết cần xác minh, không phải mapping có sẵn. Hotline call_2 tra bằng SĐT; kiểm lại `RUN-10`, variant size 41 đen và tồn kho. |
| SAMPLE-05 | Báo giá 4.390.000đ ngày 2026-09-25 gắn với `AP-SEP` hết 30/09. Call_2 ngày 2026-10-15 phải re-quote: mock trả 4.890.000đ và quà `GIFT-FILTER`; giải thích KM cũ đã hết, không tự giữ giá cũ. |
| SAMPLE-06 | Call_1 ngày 15/10 hết hàng; call_2 ngày 20/10 có hàng, freeship `NAM-SHIP0` và quà `XM-COMBO` khi quote với vùng HCM. Call_2 là Zalo nhưng thiếu `channel_identity`, C030 có `zalo_id=null`; không suy ra danh tính từ metadata chấm. |
| SAMPLE-07 | Bản đổi trả cũ hết hiệu lực cho đơn mới từ 01/10/2026 nhưng vẫn có thể áp dụng cho đơn tạo trước ngày đó. Với câu hỏi hiện tại, nêu 7 ngày và miễn phí đổi size lần đầu sau khi tra đúng bản. `success_if.tool_called=null` không tự cấm RAG; checker xét `must_not_call_tools` riêng và phạt handoff thừa. |

`SAMPLE-01` và `SAMPLE-04` yêu cầu `order.create` nhưng lời khách ở lượt chốt không nêu payment; schema BTC yêu cầu `payment`, mock mặc định `COD`. Không lén đoán COD để đạt chấm: kiểm hồ sơ/quy tắc được công bố hoặc ghi nhận mâu thuẫn và hỏi BTC khi có kênh. Các nhãn `facts_established`, `success_if` và `ground_truth_facts` chỉ dành cho test, không đưa vào đầu vào harness.

D01–D04 là transcript ASR và entity labels, không phải state machine bắt buộc. Đối chiếu bằng WER/CER và entity sau ITN; với hội thoại, tập trung nhánh do dự/hẹn lại, tiếp nối/chốt đơn, so giá đối thủ và đổi size.
