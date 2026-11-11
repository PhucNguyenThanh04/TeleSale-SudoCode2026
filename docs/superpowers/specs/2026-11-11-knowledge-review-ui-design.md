# Knowledge Gap Review UI

User giao tự chốt spec/plan ngắn và thực thi frontend. Dùng HTML/CSS/ES modules hiện có, cùng FastAPI demo gateway tại /knowledge; không thêm framework/dependency, dashboard hay sửa model/memory.

Trang có danh sách/filter/pagination gap, chi tiết evidence đã mask và nguồn feedback, phân loại kỹ thuật/generation/refusal riêng. Reviewer tạo/sửa FAQ hoặc alias có source public, đọc nội dung nguồn/điều kiện áp dụng, xem/sửa regression draft, nhập lý do và xác nhận đã review test trước approve/reject. Revision edits tạo version mới theo API hiện có. Không giả có câu trả lời đề xuất tự động khi backend chỉ tạo gap analysis.

Tab release riêng: chọn approved revision(s), prepare rồi hiển thị checks (lexical không phải LLM quality), activate và rollback bằng thao tác xác nhận riêng với expected_active_id. Release ready/active không đồng nghĩa gap resolved; giữ awaiting_verification tới khi có evidence. Hiển thị verification evidence nếu có, không tạo kết quả eval giả.

Gateway proxy allowlist /api/knowledge; internal AI token chỉ ở server. Bật quản trị bằng KNOWLEDGE_REVIEW_TOKEN và KNOWLEDGE_REVIEWER_ID trong backend; reviewer identity không do browser gửi. UI nhập access token riêng, giữ trong RAM, logout xóa; không local/sessionStorage. API cần auth cả reads/writes, kiểm Origin khi mutate, không proxy đường tùy ý hoặc ghi token trong lỗi. Upstream permission/source validation/hash/CAS là authoritative. Hiển thị 401/403/409/503 và empty/loading/error rõ; lỗi không bị coi là thành công. Text render textContent tránh HTML injection; responsive/keyboard labels. Không auto publish hoặc gọi inference/DB trong triển khai.

Kiểm chứng: focused gateway tests auth/actor injection/origin/allowlist/errors/proxy payload; lifecycle gap filter test; real headless Chrome với upstream giả cho list/detail/source/revision/test/approval/release và lỗi conflict/auth/XSS. Docs hướng dẫn cấu hình/grant/chạy trang, không tự cấp quyền hay publish thật. Current checkout, không subagents/worktrees/commit.
