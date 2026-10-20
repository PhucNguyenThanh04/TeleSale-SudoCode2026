# Quy tắc ghi bộ nhớ khách hàng

Các ca kiểm xuyên phiên và trạng thái nghiệm thu nằm ở
[hợp đồng memory đa phiên v1](memory-contract-v1.md).
Phạm vi và điều kiện xử lý xóa toàn hồ sơ được đề xuất trong
[hợp đồng xóa dữ liệu](erasure-contract.md); cần chốt các kho giữ lại trước khi
chạy thao tác xóa trên dữ liệu thật.

Fact trong `ai_memory.facts` là thông tin có nguồn, không phải lời đoán của model.
Mỗi lượt được ghi qua `mcp-memory`; `source_session_id`, `source_turn_id` và
`on_date` giữ provenance. Giá, KM và tồn kho trong memory chỉ là lịch sử.
Fact có phạm vi `global`, `product` (SKU từ tool) hoặc `room` (phòng gắn với
diện tích khách nêu). Fact đang hoạt động là duy nhất theo
`customer_id/scope_type/scope_id/key`; sửa một phòng hay một SKU không ghi đè
phòng/SKU khác. Fact legacy không đủ nguồn để xác định phạm vi vẫn ở `global`;
không tự suy SKU/phòng từ giá trị cũ. Call Brief trình bày nhiều sản phẩm riêng;
SKU được nhắc trong lượt mới được lấy lại giá/tồn kho theo `on` của lượt đó.

Khi đọc memory, harness chỉ đưa slot thuộc registry với giá trị đúng kiểu và
không chứa PII nhận diện được vào profile cho agent/Call Brief; history và
episode được che lại. Đây là lớp bảo vệ cho dữ liệu legacy, chưa thay cho kho
`address_ref` và không chứng minh mọi dạng địa chỉ đều được phát hiện.
Yêu cầu xóa toàn hồ sơ được chuyển qua `handoff.transfer` khi kênh có số điện
thoại tin cậy; chỉ kết quả `queued` kèm ticket mới được thông báo là đã chuyển.
Chưa có thao tác xóa vật lý toàn bộ dữ liệu khách, nên agent không được nói
đã xóa. Yêu cầu xóa riêng một sở thích không kích hoạt luồng toàn hồ sơ.

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

Miền đóng trong `SlotSpec` hiện được kiểm trước khi ghi: `payment` dùng đúng
`COD|bank|momo|zalopay` của tool đặt đơn; `has_children`/`in_stock` là bool;
tiền và diện tích là số nguyên dương; `promo_expiry` là ngày ISO hợp lệ. Giá
trị ngoài miền bị từ chối có mã lý do, không được ghi dưới dạng text tự do.
`objection` là miền mở: cụm chê giá đã biết thành `dat_qua`; phản đối khác có
quote nguyên văn thành `khac`. Quote được kiểm trong lời khách, che PII và lưu
ở `ai_memory.facts.evidence_quote` khi đã xác định được khách; số `khac` được
log riêng. Cân nhắc trung tính giữa các lựa chọn không
phải phản đối. `blocker` vẫn giữ cụm ngắn, chưa ép enum vì BTC chưa công bố.

## Khoản nợ thiết kế: trạng thái của blocker

Hiện blocker chỉ có fact active; khi khách xác nhận người ra quyết định đã đồng
ý, runtime phát lệnh `delete`. Nếu cùng lượt xuất hiện trở ngại mới, lệnh gỡ
được ghi trước fact mới. Chưa có trạng thái `open/resolved` hay lịch sử giải
quyết riêng trong Call Brief. Chỉ thiết kế trạng thái này khi phép đo end-to-end
cho thấy blocker cũ còn active khiến agent hỏi lại hoặc trì hoãn chốt đơn.
Bí danh “nhà tôi” có thể mơ hồ giữa vợ/chồng; cần kiểm lời khách trong đánh giá
end-to-end trước khi dựa vào nó để tự động gỡ.

## Khoản nợ thiết kế: sở thích và điều kiện giao nhận

O04 (không thích lắp ráp phức tạp), M03 (không thích giày có dây) là sở thích;
M06 (chỉ nhận hàng sau 18 giờ) là điều kiện giao nhận. Chúng không phải trở
ngại đang chặn quyết định mua, nên `fact_evidence` từ chối ghi chúng vào
`blocker` với `preference_not_blocker` hoặc `delivery_constraint_not_blocker`.
Hiện các thông tin này chỉ còn trong lịch sử lượt có giới hạn, chưa thành fact
dài hạn và có thể không được mang sang cuộc sau. Chưa có category fact mở được
triển khai; không dùng `blocker` làm chỗ lưu tạm vì sẽ làm sai Call Brief và
điều kiện giải quyết blocker.

`objection` chỉ nhận lời e ngại hoặc từ chối việc mua, với bằng chứng ở đúng
mệnh đề khách nói. O01 (đi công tác nhiều ngày) là hoàn cảnh; O02/O08 và phần
không thích giày có dây của M03 là sở thích. Cổng theo `SlotSpec` chủ đích từ
chối ghi chúng thành `objection=khac` với `circumstance_not_objection` hoặc
`preference_not_objection`. Chúng chưa có chỗ lưu dài hạn cho đến khi thiết kế
fact mở được duyệt; không dùng `objection` làm chỗ lưu tạm.

Agent chỉ đề xuất; `fact_evidence` kiểm lời khách hoặc kết quả tool. Với các
fact về điều shop đã **nói** (`product_advised`, `price_quoted_vnd`, KM), bước
ghi còn kiểm trên `agent_text` cuối sau guardrail. Nếu không chuẩn hóa được giá
trong câu cuối một cách chắc chắn, bỏ qua fact lịch sử đó.

Khi danh tính chưa rõ, hệ thống vẫn ghi lịch sử lượt theo phiên nhưng không
ghi fact vào hồ sơ khách. Khi được xác định danh tính ở lượt sau, các fact của
lượt ẩn danh trước đó không được tự chuyển sang hồ sơ, lịch sử đưa cho model
hoặc episode của khách; khách cần xác nhận lại
nếu muốn dùng chúng xuyên phiên. Khách tự đọc số điện thoại không đủ để gắn
profile; SĐT chung chưa phân biệt được người nói thì không nạp profile ứng viên.
`commit_turn` có operation key để retry không tạo bản trùng.
Các hàng `pending_facts` đã có từ phiên bản cũ không được đọc hoặc chuyển
bởi luồng hiện tại; việc dọn dữ liệu cũ cần xử lý riêng khi quản lý lưu trữ.
Lịch sử cùng phiên được đọc lại qua MCP mỗi lượt, kể cả sau khi khởi động lại
process; MCP đọc tối đa 12 lượt, prompt mặc định dùng 6 lượt gần nhất.
Episode từ memory ưu tiên hơn CRM khi
trùng session và được giới hạn sau khi gộp.

`expected_outcome`, `facts_established`, `ground_truth_facts` và
`memory_expectation` là nhãn chấm, không đi vào runtime. `eval/run_eval.py`
ghi trace từ lượt thật và ghi rõ TTFT bằng total latency khi API không stream.
Full/baseline phải dùng DB eval cùng seed nhưng tách trạng thái. Đo lặp lại để
đánh giá RQR/CCR/TSR/HR, recall của fallback so với always và p95 latency.
