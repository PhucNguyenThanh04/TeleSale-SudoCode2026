# d1c — số tiền trả lời ngắn cho câu hỏi ngân sách

Phạm vi đọc: bảy `test_set/public_sample/SAMPLE-*.json` của BTC và 50 ca
`eval/memory_facts_v1.jsonl` (bản development). Với public sample, dùng
`customer_turns_asr` khi có, đúng như đầu vào eval; chỉ đọc lời khách, không
coi `customer_goal` hoặc `facts_established` là lời khách. Bộ 50 là các lượt
độc lập, không chứa câu hỏi ngay trước đó của agent.

| Nguồn | Số lượt khách chỉ nêu số tiền ngắn sau câu hỏi ngân sách | Ca / ghi `budget_vnd` hiện tại |
|---|---:|---|
| 7 public sample | 0 | Không có ca tương ứng để kiểm ghi. Trong các lượt có ngân sách, khách đều nêu rõ “ngân sách”. |
| Bộ 50 | 0 | Không có ca tương ứng; bộ này cũng không lưu câu hỏi agent trước lượt. |

Các chuỗi như “4 triệu thôi”, “tầm 5 củ” không xuất hiện dưới dạng câu trả lời
ngắn trong hai nguồn này. Vì vậy không thể đo tỷ lệ ghi nhớ của loại câu này từ
bộ dữ liệu hiện có. Parser hiện cần dấu hiệu ngân sách/trần chi tiêu trong
**lời khách**; một câu tiền trần trụi riêng lẻ không đủ bằng chứng cho
`budget_vnd` theo quy tắc hiện tại.

Đề xuất chưa triển khai: chỉ dùng **câu hỏi agent ngay trước đó trong cùng
phiên** để xác định lượt khách đang trả lời về giới hạn chi tiêu của họ. Câu
hỏi phải hỏi mức ngân sách/trần chi của khách, không chỉ báo giá, nhắc khuyến
mãi hoặc hỏi có chấp nhận một giá cụ thể không. Số tiền vẫn phải được trích và
trích dẫn từ chính lời khách; câu agent chỉ là ngữ cảnh diễn giải, không phải
`evidence_quote`. Giới hạn ngữ cảnh ở một cặp hỏi–đáp và không suy số tiền từ
tool/agent. Kiểm âm tính với giá sản phẩm, giá đối thủ, mức giảm và câu hỏi
tu từ. Rủi ro tự củng cố: agent hỏi dựa trên ngân sách đã đoán sai, rồi câu
đáp ngắn bị diễn giải như xác nhận và ghi lại thành fact. Cần ca nhiều lượt
được gắn nhãn độc lập trước khi triển khai.
