# AI service

Áp dụng dưới `ai-services/`; đọc thêm `../AGENTS.md`, `../docs/harness-spec.md` và `../docs/tool-contract.md` theo phần việc.

- Giữ `app/agent/graph.py` là LangGraph tường minh chỉ nối node; `chat.py` là entrypoint Python một lượt. Model chỉ đề xuất, `harness/policy.py` kiểm precondition, `guardrails/checks.py` kiểm câu trả lời và bằng chứng fact. `ChatRequest.on` là ngày nghiệp vụ, không lấy wall clock.
- Ba MCP server ở `app/mcp_servers/`; tool handler mỏng, service chứa luật, repo chứa SQL và session/transaction. Catalog và order dùng cùng quy tắc giá/tồn kho trong `mcp_shared/`; memory có provenance và supersede.
- Chính sách M1 dùng `policy.search` trong mcp-catalog từ `btc_source.policy_chunks`. Lọc `access_level=public`, `effective_from`, `effective_until` và `date_basis` trước khi đưa nội dung ra model; chính sách đổi trả đơn cũ dùng ngày tạo đơn đã xác minh qua `order.status`. Qdrant chưa nối runtime.
- Không đưa địa chỉ/PII thô từ CRM vào prompt, checkpoint hoặc trace; tool nghiệp vụ nhận dữ liệu cần thiết qua ngữ cảnh đáng tin cậy. `address_ref` là phương án thiết kế chưa triển khai.
- Với lỗi agent gọi tool sai, kiểm đồng thời schema/mô tả tool, bước chuẩn hóa và precondition trong harness, ngữ nghĩa tìm kiếm ở service, cùng kết quả tool thực tế. Chọn quy tắc áp dụng cho nhiều sản phẩm và nhiều cách diễn đạt; không vá riêng câu thoại hoặc SKU của sample. Nếu agent thử lại, giữ các bộ lọc đã xác minh từ yêu cầu khách và ghi đúng mọi lần gọi tool vào trace.
- Test: từ thư mục này chạy `python -m unittest discover -s test -v`. Khi sửa catalog/order/memory, đối chiếu kết quả với mock BTC và ít nhất một sample đa phiên; không sửa trace theo đáp án.
