# Sự cố LangMem ghi sai sản phẩm đã tư vấn

## Kết luận

Đây là lỗi tại nhánh distillation/admission của LangMem, không phải lỗi định
danh khách hàng và không phát sinh từ nhánh memory xác định (deterministic)
trước đó. LangMem đã biến mọi SKU có trong kết quả `catalog.search` thành
`product_advised`, kể cả sản phẩm không xuất hiện trong câu trả lời cuối của
tư vấn viên.

Sự cố được tái hiện khi khách C007 hỏi lại sản phẩm đã được tư vấn. Danh tính
được ánh xạ đúng tới C007 và lịch sử hội thoại chỉ nhắc AirPure X, nhưng memory
đã chứa cả `SKU-AP-X` và `SKU-BDL-AIR`. Vì vậy lượt sau trả lời rằng cả hai sản
phẩm đã được tư vấn.

## Hành vi sai và hợp đồng bị vi phạm

`product_advised` mô tả điều tư vấn viên thực sự đã nói, không mô tả toàn bộ
ứng viên mà catalog từng trả về. Theo `docs/memory-policy.md`, fact này chỉ được
ghi khi:

1. Catalog xác nhận SKU.
2. Câu trả lời cuối thực sự nhắc SKU hoặc tên sản phẩm tương ứng.

Nhánh deterministic trong `agent/memory/fact_candidates.py` đã áp dụng cả hai
điều kiện qua `reported_tool_fact`. Nhánh LangMem trong
`mcp_memory/services/langmem_admission.py` trước khi sửa chỉ áp dụng điều kiện
đầu tiên: `fact_evidence` chấp nhận một SKU nếu nó có mặt ở bất kỳ item nào của
`catalog.search`. `agent_text` đã được worker truyền vào committed turn nhưng
không được admission dùng để xác minh tool fact.

Đây là lỗi nhiễm memory (false promotion of retrieval candidates), không phải
model tự tạo một SKU không tồn tại. Model ở lượt gọi lại đã sử dụng fact sai đã
được lưu hợp lệ trong kho memory.

## Phạm vi sửa

Admission của LangMem phải chạy cùng cổng `reported_tool_fact` mà nhánh
deterministic đang dùng. Tool fact về nội dung đã báo cho khách chỉ được nhận
khi câu trả lời cuối sau guardrail chứng minh nội dung đó đã được nói. Kết quả
tìm kiếm đơn thuần không đủ để ghi lịch sử tư vấn.

Kiểm thử hồi quy bao gồm:

- Catalog trả hai sản phẩm nhưng câu cuối chỉ tư vấn một sản phẩm: chỉ lưu sản
  phẩm được nhắc.
- Catalog trả hai sản phẩm và câu cuối thực sự so sánh cả hai: lưu cả hai theo
  phạm vi SKU riêng.

## Dữ liệu đã bị nhiễm

Sửa code chỉ ngăn bản ghi sai mới. Fact `product_advised=SKU-BDL-AIR` hiện có
của C007 cần được retract bằng một thao tác sửa dữ liệu riêng sau khi bản sửa
được triển khai. Không xóa fact đó trong migration hoặc trong test để tránh che
giấu nguyên nhân và tránh tác động nhầm dữ liệu môi trường khác.
