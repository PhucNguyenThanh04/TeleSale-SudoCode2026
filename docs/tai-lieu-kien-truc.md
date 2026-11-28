# Kiến trúc trợ lý telesale đa phiên

TeleSale SudoCode 2026 là trợ lý telesale tiếng Việt, dùng chung bộ điều phối hội thoại (*harness*) cho chat, thoại và đánh giá.

## 1. Sơ đồ hệ thống

[Mở sơ đồ hệ thống](so-do-he-thong.html)

Backend chuyển tin nhắn chat và bản chép lời từ Speech vào cùng một harness. Runner đánh giá gọi trực tiếp harness. Harness dùng LLM để điều phối và gọi bốn dịch vụ qua MCP (Model Context Protocol) gồm Catalog, Order, Memory và Knowledge. PostgreSQL lưu dữ liệu nghiệp vụ, bộ nhớ và văn bản chính sách. Qdrant giữ chỉ mục tra cứu chính sách. [Cấu hình triển khai](../docker-compose.yml)

## 2. Vòng lặp harness

[Mở sơ đồ vòng lặp harness](vong-lap-harness.html)

Runtime khóa theo phiên, tra định danh khách qua CRM và kiểm tra yêu cầu gửi lại trước khi chạy LangGraph. Lượt đã lưu có thể phát lại câu trả lời nếu định danh lượt và nội dung yêu cầu khớp. [Runtime](../ai-services/app/agent/harness/runtime.py)

1. **`accept` và `retrieve_context`.** Che thông tin cá nhân, rồi nạp lịch sử, hồ sơ và Call Brief theo phạm vi khách đã xác minh.
2. **`run_agent`.** Agent đề xuất gọi công cụ khi cần bằng chứng. Kết quả hoặc lỗi quay lại agent để quyết định gọi tiếp hay soạn câu trả lời. Với thao tác ghi, harness kiểm yêu cầu hiện tại và bằng chứng trước khi cấp quyền, rồi Order MCP kiểm quyền lần nữa.
3. **`verify`.** Đối chiếu bản nháp với dữ liệu và biên nhận từ công cụ. Harness có thể tra bổ sung hoặc sửa câu trong giới hạn, sau đó kiểm lại. Khi hết cách phục hồi, runtime dùng câu dự phòng đã kiểm nếu có hoặc báo lỗi lượt.

Runtime phát câu đã duyệt và ghi lượt vào bộ nhớ. Với thoại, xác nhận phát giúp runtime lưu đúng phần khách đã nghe khi bị ngắt lời. [LangGraph](../ai-services/app/agent/graph.py) · [Xử lý từng bước](../ai-services/app/agent/harness/agent_nodes.py)

## 3. Thiết kế bộ nhớ giữa các phiên

| Tầng | Khóa và nơi lưu | Dữ liệu được dùng ở lượt sau |
|---|---|---|
| Hội thoại (*working*) | PostgreSQL, bảng `runtime.turns`, khóa theo `session_id` và `turn_no`. | Lời khách, phần trả lời đã phát, kết quả công cụ và kết quả nghiệp vụ. |
| Lần tư vấn (*episodic*) | LangMem trong PostgreSQL, namespace `customers/{customer_id}/episodes`. | Sản phẩm từng tư vấn, trở ngại, câu hỏi còn mở và hành động tiếp theo theo từng phiên. |
| Hồ sơ (*profile*) | LangMem trong PostgreSQL, namespace `customers/{customer_id}/facts`. | Nhu cầu, ngân sách, diện tích và sở thích, kèm phạm vi, lượt nguồn, phiên bản và thời hạn. |

**Ghi và cập nhật.** Memory MCP lưu lượt và xếp tác vụ trích xuất cho khách đã xác minh trong cùng giao dịch. Worker LangMem đối chiếu dữ kiện với lượt nguồn trước khi cập nhật hồ sơ. Dữ kiện mới đã duyệt thay thế giá trị cũ trong cùng phạm vi, chẳng hạn ngân sách của một phòng. Dữ kiện hết hạn được lọc khi đọc. Trong lúc worker xử lý, lượt kế tiếp vẫn đọc được hội thoại đã lưu. [Ghi và đọc bộ nhớ](../ai-services/app/mcp_servers/mcp_memory/services/memory.py) · [Phiên bản LangMem](../ai-services/app/mcp_servers/mcp_memory/repos/langmem_projection.py)

**Đọc ở phiên sau.** Khi xác minh được khách quay lại, runtime dùng hồ sơ và các phiên liên quan để dựng Call Brief gồm sản phẩm từng tư vấn, giá đã báo, trở ngại và hành động tiếp theo. Agent tra lại giá và tồn kho theo ngày hiện tại trước khi giao dịch. [Dựng ngữ cảnh](../ai-services/app/agent/harness/context.py) · [Call Brief](../ai-services/app/schemas/brief.py)

## 4. Danh sách công cụ

Agent có thể đề xuất 12 công cụ nghiệp vụ qua `BusinessTools`. Bảng dùng tên chuẩn trong trace. Harness bổ sung định danh tin cậy, ngày giao dịch và khóa chống ghi trùng khi công cụ yêu cầu. [Ánh xạ tên công cụ](../ai-services/app/agent/implementations/tool_names.py) · [Gateway MCP](../ai-services/app/agent/mcp/gateway.py)

| MCP | Công cụ | Quyền | Đầu vào chính → kết quả dùng được |
|---|---|---|---|
| Catalog | `catalog.search` | Đọc | Tên, loại hoặc bộ lọc → danh sách mẫu và biến thể phù hợp. |
| Catalog | `catalog.get_details` | Đọc | SKU hoặc mã biến thể → thông số và nguồn kỹ thuật của đúng mẫu. |
| Catalog | `inventory.check` | Đọc | SKU và ngày → trạng thái, số lượng còn trong kho. |
| Catalog | `pricing.get_quote` | Đọc | SKU, ngày, địa điểm nếu cần → giá cuối, ưu đãi và điều kiện giao hàng cho sản phẩm. |
| Catalog | `pricing.quote_order` | Đọc | Các dòng hàng và số lượng → giá từng đơn vị, tổng tiền và ưu đãi của giỏ. |
| Order | `order.status` | Đọc | Định danh khách, mã đơn nếu có → trạng thái đơn thuộc khách. |
| Order | `order.preview_update` | Đọc | Đơn, phương án đổi/trả, dòng hàng → phương án và số tiền dự kiến. |
| Order | `order.create` | Ghi | Sản phẩm hoặc giỏ đã xác nhận, giá và phương thức thanh toán → mã đơn khi tạo thành công. |
| Order | `order.update` | Ghi | Đơn thuộc khách và yêu cầu thay đổi → biên nhận, trạng thái xử lý. Với `review_pending`, agent chỉ báo đã gửi yêu cầu chờ duyệt. |
| Order | `schedule.callback` | Ghi | Thời điểm khách hẹn và ghi chú → thời điểm gọi lại thực tế theo lịch làm việc. |
| Order | `handoff.transfer` | Ghi | Bản bàn giao có nguồn → mã phiếu và trạng thái vào hàng đợi. |
| Knowledge | `policy.search` | Đọc | Câu hỏi, ngày và ngữ cảnh đơn/sản phẩm nếu có → đoạn nguồn, điều kiện áp dụng, ngoại lệ và phiên bản chính sách. |

**Công cụ nội bộ**

| MCP | Công cụ | Vai trò |
|---|---|---|
| Catalog | `crm.get_customer` | Tra khách theo điện thoại, Facebook hoặc Zalo. |
| Memory | `memory.read`, `memory.timeline`, `memory.write`, `memory.turn_status`, `memory.replay` | Nạp ngữ cảnh, đọc lịch sử, lưu lượt, kiểm trạng thái cập nhật bộ nhớ và xử lý yêu cầu gửi lại. |
| Cả bốn MCP | `eval.database_identity` | Xác nhận cơ sở dữ liệu từng MCP dùng khi đánh giá. |
| Knowledge | `eval.knowledge_release` | Lấy phiên bản và mã băm của bộ chính sách. |

## 5. Quyết định thiết kế và lý do lựa chọn

| Quyết định | Lý do lựa chọn và đánh đổi |
|---|---|
| Dùng một harness cho chat, thoại và đánh giá | Áp dụng cùng quy tắc kiểm tra hội thoại và giao dịch cho cả văn bản lẫn bản chép lời. Runner gọi trực tiếp nên độ trễ đo được chỉ bao phủ một phần đường đi thực tế của thoại. |
| Tách bốn miền nghiệp vụ bằng MCP | Hợp đồng có kiểu dữ liệu cho từng miền. Order kiểm quyền ghi tại nơi thực hiện giao dịch. Các cuộc gọi giữa dịch vụ cần xử lý timeout và lỗi. |
| Lưu bộ nhớ và nguồn chính sách ở PostgreSQL, lập chỉ mục chính sách ở Qdrant | PostgreSQL hỗ trợ giao dịch, định danh và phiên bản. Qdrant hỗ trợ tìm theo ngữ nghĩa và từ khóa. Chỉ mục cần khớp với phiên bản văn bản nguồn. |
| Kiểm bằng chứng và quyền ghi theo từng lượt | Agent dùng ký ức để tiếp tục tư vấn. Việc đặt hàng hoặc đổi đơn cần có yêu cầu hợp lệ ở lượt hiện tại. Kiểm thêm có thể tăng độ trễ hoặc phải hỏi lại. |
| Trích xuất trí nhớ ở nền | Khách có thể nhận câu trả lời trước khi cập nhật hồ sơ hoàn tất. Worker cần xử lý đúng phiên bản và chạy lại tác vụ khi cần. |
| Duyệt toàn câu trước khi phát | Giảm nguy cơ phát giá, ưu đãi hoặc kết quả giao dịch sai. Khách phải đợi bước kiểm tra bản nháp hoàn tất. |
| Duyệt cập nhật tri thức trước khi phát hành | Worker tạo đề xuất gắn nguồn từ phản hồi. Người duyệt kiểm nội dung và ca hồi quy trước khi phát hành để giữ chính sách có căn cứ. [Vòng đời tri thức](../ai-services/app/knowledge/services/lifecycle.py) |
| Khóa phiên trong tiến trình, lưu lượt bền vững | Tuần tự hóa các lượt cùng phiên trong một tiến trình và hỗ trợ phát lại lượt đã ghi. Cần kiểm chứng điều phối phiên và biên nhận thoại khi triển khai nhiều worker AI. |
