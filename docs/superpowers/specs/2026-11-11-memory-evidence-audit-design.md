# Kiểm chứng memory xuyên phiên và hỏi lại thừa

User đồng ý thực hiện đề xuất: đối chiếu từng fact bắt buộc từ phiên nguồn → memory → context phiên quay lại → hành vi agent; review extraction; kiểm trên bộ khoảng 22 kịch bản team trước khi chuyển sang frontend Knowledge Gap Loop.

Nguồn chính: run `ai-services/eval_harness/results/20261111T031614Z-d8c7ccfc`, cặp full/baseline và scorer BTC bất biến. Mục tiêu là xác định đã đạt gì và chưa đạt gì bằng bằng chứng, không tăng điểm bằng sửa nhãn/scorer hoặc ép agent nhắc lại mọi fact.

Bảng audit phải bao phủ 21 fact requirements của 6 cuộc gọi quay lại, kèm coordinate source/return, writes quan sát được, context key, facts_used và giới hạn quan sát. Phân biệt: không có bằng chứng nguồn, có write, có key trong read, có dùng được scorer ghi nhận. Key có mặt không tự chứng minh đúng value/source; key vắng trong stages không tự chứng minh durable store mất dữ liệu. Không coi tool hiện tại tra ra dữ kiện mới là recall khi thiếu nguồn phiên trước. Giá cũ phải phân biệt với giá hiện tại.

RQR so full/baseline theo scorer, kiểm lại các câu hỏi được tính và phần uncertain extraction; fallback/model failures được báo riêng. CCR giữ số chính thức, diagnostic evidence chỉ giải thích, không thay thế score. Review code facts_used bằng focused offline tests; chỉ sửa bug nếu có phản ví dụ tái hiện được và còn đúng ranh giới provenance/scope/customer repetition.

Review bộ team khi tìm thấy: định dạng, identity/ngày/đa phiên, nhãn không mâu thuẫn lời khách, success_if/giá/KM theo nguồn. Không tự bịa hoặc thay thế bộ 22 khi thiếu file. Hỏi người dùng vị trí và tiếp tục audit sample độc lập.

Giữ checkout và thay đổi người dùng, không subagent/worktree/commit, không UI, Redis, dashboard hoặc migration. Chưa live inference/eval/reset DB trong giai đoạn audit; mọi live run phải có dataset và đích DB rõ ràng trước khi thực hiện. Dùng tool/schema/pytest hiện có; báo rõ giới hạn của snapshot artifact và sample nhỏ.

Hoàn tất khi có báo cáo 21 dòng, extraction review với bằng chứng/kiểm thử, kết luận metric có điều kiện và review/kế hoạch kiểm chứng bộ team đúng dữ liệu được cung cấp. Nếu chưa có bộ team thì để goal active, không đánh dấu hoàn tất toàn bộ.
