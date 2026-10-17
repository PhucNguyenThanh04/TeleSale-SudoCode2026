# Quy tắc ghi bộ nhớ khách hàng

Fact trong `ai_memory.facts` là thông tin có nguồn, không phải lời đoán của model.
Mỗi lượt được ghi qua `mcp-memory`; `source_session_id`, `source_turn_id` và
`on_date` giữ provenance. Giá, KM và tồn kho trong memory chỉ là lịch sử.

| Key | Bằng chứng để ghi | Vòng đời |
|---|---|---|
| `room_area_m2`, `budget_vnd` | Lời khách khẳng định về mình; số/đơn vị được chuẩn hóa | Supersede khi khách sửa |
| `has_children` | Lời khách khẳng định có/không; thiếu thông tin không thành `false` | Supersede khi thay đổi |
| `preferred_size`, `preferred_color` | Sở thích khách tự nêu | Supersede khi đổi sở thích |
| `size`, `color` | Lựa chọn trong cuộc trao đổi hiện tại | Supersede khi đổi sản phẩm/biến thể |
| `payment` | Khách chọn phương thức cụ thể | Lịch sử; đơn mới vẫn cần xác nhận hợp lệ |
| `competitor_price_vnd`, `objection` | Lời khách về đối thủ hoặc phản đối | Supersede hoặc đóng khi giải quyết |
| `blocker` | Khách nêu trở ngại | `delete` khi khách nói rõ đã giải quyết |
| `product_advised` | Catalog xác nhận SKU và câu cuối thật sự nhắc sản phẩm | Supersede khi tư vấn sản phẩm khác |
| `price_quoted_vnd` | Quote thành công và câu cuối thật sự báo đúng giá | Lịch sử; quote lại mỗi cuộc gọi |
| `promo_code` | Quote trả KM áp dụng và câu cuối báo mã đó | Lịch sử; kiểm lại mỗi cuộc gọi |
| `promo_expiry` | Metadata `valid_until` của KM đã báo từ catalog | Không suy từ lời khách/model |
| `variant_sku` | Catalog xác nhận biến thể; khách chọn hoặc tạo đơn thành công | Supersede khi đổi |
| `order_id` | Chỉ từ `order.create` trả `status: created` và ID | Giữ lịch sử, đọc trạng thái từ order tool |
| `in_stock` | Kết quả `inventory.check` thành công | Quan sát có ngày; kiểm lại trước khi báo/tạo đơn |

Agent chỉ đề xuất; `fact_evidence` kiểm lời khách hoặc kết quả tool. Với các
fact về điều shop đã **nói** (`product_advised`, `price_quoted_vnd`, KM), bước
ghi còn kiểm trên `agent_text` cuối sau guardrail. Nếu không chuẩn hóa được giá
trong câu cuối một cách chắc chắn, bỏ qua fact lịch sử đó.

Khi danh tính chưa rõ, fact hợp lệ được che PII và giữ trong `pending_facts`
theo phiên/lượt tối đa 24 giờ. Khách tự đọc số điện thoại không đủ để gắn
profile. Backend chỉ chuyển pending sau khi operator xác minh riêng hoặc
định danh kênh tin cậy xác nhận đúng khách. SĐT chung chưa phân biệt được
người nói thì không nạp profile ứng viên. Việc ghi `commit_turn` và
`claim_pending` có operation key để retry không tạo bản trùng. Key claim gồm
phiên, khách và `client_msg_id`; lượt mới không phát lại `memory_writes` của lượt cũ.
Lịch sử cùng phiên được đọc lại qua MCP mỗi lượt, kể cả sau khi khởi động lại
process; prompt dùng tối đa 12 lượt. Episode từ memory ưu tiên hơn CRM khi
trùng session và được giới hạn sau khi gộp.

`expected_outcome`, `facts_established`, `ground_truth_facts` và
`memory_expectation` là nhãn chấm, không đi vào runtime. `eval/run_eval.py`
ghi trace từ lượt thật và ghi rõ TTFT bằng total latency khi API không stream.
Full/baseline phải dùng DB eval cùng seed nhưng tách trạng thái. Đo lặp lại để
đánh giá RQR/CCR/TSR/HR, recall của fallback so với always và p95 latency.
