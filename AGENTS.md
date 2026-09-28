# Hướng dẫn làm việc trong TeleSale-SudoCode2026

Áp dụng cho AI coding agent làm việc trong repo này. Đọc file liên quan và kiểm tra trạng thái Git trước khi sửa. Khi người dùng chỉ gửi tài liệu hoặc hỏi ý kiến kiến trúc, hãy phân tích và trao đổi; chỉ viết code khi họ yêu cầu triển khai hoặc chỉnh sửa cụ thể. Không ghi đè thay đổi có sẵn của người dùng.

## Nguồn yêu cầu

- Đề gốc: `/home/thanh-phuc/PyProject/sudocode/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf`.
- Dữ liệu BTC: `/home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/`. Đọc `README.md`, `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md`, `schemas/` và `eval/reference_eval.py` khi làm phần liên quan. Điều chỉnh của BTC được ưu tiên hơn bản PDF ở các điểm đã sửa.
- Ngày tham chiếu của dữ liệu BTC là `2026-10-15`; trong kịch bản dùng `call_date` hoặc `days_later` để xét giá, khuyến mãi, tồn kho và chính sách. Không lấy ngày hệ thống thay cho ngày kịch bản.
- Không sửa bộ dữ liệu BTC gốc khi chưa có yêu cầu. Dữ liệu do nhóm tạo phải nhất quán với catalog, chính sách và `eval/mock_tools.py`.

## Phạm vi và kiến trúc đã chọn

- Làm **chat text-to-text và bộ nhớ xuyên phiên** trước. Audio/voice là giai đoạn sau; không để phần đó chặn luồng text.
- `backend/`: FastAPI, xác thực danh tính, CRM, phiên, catalog/giá/tồn kho/đơn hàng, PostgreSQL và Redis. SQLAlchemy async dùng `asyncpg` với DSN `postgresql+asyncpg://`.
- `ai-services/`: Agent API và LangGraph `StateGraph` tường minh. LangChain dùng cho model, messages và tool adapters; không giao toàn bộ harness cho agent dựng sẵn.
- Ba MCP server trong AI service: `mcp-memory`, `mcp-catalog`, `mcp-knowledge`. Agent gọi qua MCP client. Catalog MCP gọi nghiệp vụ backend; không viết lại công thức giá. Knowledge truy hồi tài liệu, lọc bản hết hiệu lực và nội dung nội bộ.
- `langgraph-checkpoint-postgres` dùng `psycopg` riêng; không thay nó bằng `asyncpg`. `thread_id` nên gắn với `session_id`. Checkpointer giữ state trong phiên, không tự tạo bộ nhớ khách hàng xuyên phiên.
- PostgreSQL là nguồn chính cho khách, phiên, episode và profile. Redis dùng cache/khóa/queue; Qdrant dùng tìm kiếm ngữ nghĩa, không là nguồn chính cho fact có cấu trúc.
- `config/*.yml` hiện là cấu hình khai báo; runtime backend đang đọc `backend/.env` qua `app/configs.py`. Đừng giả định YAML đã được nạp tự động.

## Quy tắc nghiệp vụ và bộ nhớ

- Luồng harness phải thể hiện rõ: nhận đầu vào → xác định danh tính → truy hồi → lập kế hoạch → gọi tool → quan sát kết quả → kiểm tra câu trả lời → ghi nhớ. Nhánh fallback và chuyển người thật phải tường minh.
- Tách working state (lượt/phiên hiện tại), episodic memory (tóm tắt từng phiên) và profile memory (fact bền vững theo `customer_id`). Khi khách đổi ý, fact cũ phải bị supersede; lưu nguồn, thời điểm và trạng thái hiệu lực.
- Khách quay lại phải có Call Brief và lời mở đầu tiếp nối. Không hỏi mở lại slot đã biết; chỉ xác nhận khi thật sự cần. Số điện thoại dùng chung không được tự động gộp hai hồ sơ.
- Giá, khuyến mãi, tồn kho, điều kiện COD và ngày giao hàng phải lấy từ công cụ nghiệp vụ theo ngày của cuộc gọi. Không để LLM tự bịa hoặc xem báo giá cũ là giá hiện tại.
- Che CCCD, số tài khoản, địa chỉ và PII khác trước khi ghi log/trace hoặc gửi tới model ngoài. CRM có thể lưu thông tin cần thiết để nhận diện/giao hàng trong kho nghiệp vụ có kiểm soát; không đưa PII thô vào prompt, checkpoint, vector store hoặc log. Không log API key hay DSN có mật khẩu.
- Không dùng ghi âm khách hàng thật chưa ẩn danh và chưa được phép. Không huấn luyện lại hoặc fine-tune model cho bài này.

## Đánh giá và kiểm chứng

- Đặt runner đánh giá ở `eval/` cấp repo; `run_eval.py` là entrypoint theo định dạng BTC: `--scenarios`, `--config full|baseline_no_memory`, `--out`.
- Trace JSONL phải theo `BTC-Data-Vong1-TEAMS/schemas/trace_log.schema.json`. `questions`, `claims`, `facts_used`, tool calls và memory writes phải phản ánh hành vi thật, không điền theo đáp án kịch bản.
- Full và baseline chạy trên cùng bộ kịch bản, model, tham số và tool; baseline chỉ tắt nạp bộ nhớ từ phiên trước. Báo RQR, CCR, TSR, HR, WER/CER bằng code. LangSmith/Langfuse hỗ trợ debug, không thay thế `eval/reference_eval.py` của BTC.
- Với thay đổi ảnh hưởng đến bộ nhớ, tool, giá hoặc routing, kiểm tra kịch bản đa phiên và ca khó liên quan. Với chỉnh sửa nhỏ, chạy kiểm tra tập trung; không tạo test chỉ lặp lại nội dung implementation.

## Cách sửa code

- Giữ API route và MCP tool mỏng; nghiệp vụ nằm trong service/repository hoặc node rõ trách nhiệm. Dùng type hints ở boundary và Pydantic cho schema I/O.
- Không tạo class chỉ để bọc một hàm thuần; dùng hàm cho chuẩn hóa, masking và kiểm tra dữ liệu. Dùng class khi cần giữ dependency hoặc state có vòng đời rõ ràng.
- Không thêm service, framework, worker hoặc abstraction chỉ vì sơ đồ có chỗ trống. Bắt đầu bằng lát cắt chạy được cho khách chat lần đầu và quay lại lần hai.
- Khi báo cáo thay đổi: nêu file đã sửa, hành vi mới, cách đã kiểm tra và giới hạn kiểm chứng. Nếu dịch vụ ngoài chưa chạy, nói rõ phần nào mới kiểm tra bằng mock.
