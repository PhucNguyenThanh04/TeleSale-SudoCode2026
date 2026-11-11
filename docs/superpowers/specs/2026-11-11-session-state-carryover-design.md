# Trạng thái phiên và tiếp tục tư vấn có bằng chứng

## Mục tiêu và bằng chứng đầu vào

Goal do người dùng giao: tự viết spec/plan và thực thi để giữ thông tin xuyên phiên gọi, cải thiện carryover và giảm hỏi lại thừa. Nguồn lỗi là run `20261110T161747Z-ba44bde7`: full có facts/episode khi vào call_2 nhưng 13/39 lượt model lỗi; SAMPLE-05 khách nêu AirPure X vẫn bị hỏi chọn mẫu hai lần; Call Brief biến mất sau lượt đầu. CCR 4/21 không phải tỷ lệ lưu memory. Không sửa scorer/nhãn để tăng điểm.

## Thiết kế đã chọn

Giữ runtime/graph/MCP hiện có. Bổ sung một SessionState có owner/session/ngày và chế độ full/baseline, chứa view context hiện hành, Call Brief, consultation decision, phần còn thiếu và receipt. Không tạo enum cho từng fact; state machine dùng quyết định nghiệp vụ đã có (search/clarify/quote/purchase/pause/confirm_terms).

Call Brief là phần ngữ cảnh sống của toàn cuộc gọi, không chỉ response đầu tiên. Facts/episodes và diễn biến mới được phản ánh ở mọi lượt. Lời khách mới có nguồn supersede thông tin cũ, gồm budget, variant, lựa chọn và blocker. State giữ đủ dữ liệu phía server; prompt vẫn giới hạn history và chỉ dùng dữ liệu đã mask, có nguồn. Không đổ toàn bộ lịch sử vào prompt hoặc thêm một vòng model để dựng state.

Committed turns/tool observations và memory projection hiện có là nguồn durable để dựng lại SessionState sau runtime restart. Nếu cần bổ sung dữ liệu khôi phục, mở rộng memory read theo owner/session từ chính log đã commit, không mở kho history thứ hai. Cache chỉ giúp tiếp tục phiên, không thay quyền kiểm tra ownership/erasure/TTL ở mỗi lượt. Healthy read mới thay thế view cũ; không merge lại fact bị xóa hoặc hết hạn. Memory lỗi/erasure phải xóa hoặc vô hiệu hóa view cache, không trả brief cũ.

Phân biệt dữ kiện lịch sử với quyền giao dịch: giá cũ trong brief không phải quote hiện tại; tool quote không phải lời đã nghe; draft voice chưa phát không phải offer; receipt mới là bằng chứng đơn đã tạo. Nguồn/customer/session, ngày, SKU/variant, quantity, payment/address và consent vẫn đi qua các boundary hiện tại. Baseline không nhận profile/episode/brief phiên trước; vẫn giữ working state trong phiên hiện tại. Dữ liệu khách/phiên khác không được vào state.

## Tra cứu trước khi hỏi lại

Khi thiếu metadata để hiểu tên sản phẩm khách vừa nêu, dùng catalog search có query cụ thể trước khi hỏi chọn mẫu. Không biến lời chào hoặc “cái hôm trước” mơ hồ thành broad search; không lấy thứ tự catalog để tự chọn. Query lấy từ lời khách hoặc nguồn phiên đã xác minh, không từ nhãn scenario. Một SKU khớp rõ ràng cho phép tiếp tục resolver; nhiều SKU cần câu hỏi phân biệt; rỗng/lỗi phải nói chưa xác minh được, không giả vờ khách chưa nói tên. Refresh lỗi không dùng lại quote cũ. Giữ nguyên giới hạn tool và không retry cùng search thất bại trong một lượt.

Sau khi khách đã nói lựa chọn/size/payment, pending_fields chỉ còn phần thực sự thiếu. Đồng ý sau offer hợp lệ không hỏi lại cùng selection/offer; thay đổi giá hoặc điều kiện vẫn cần reconfirm. Khách hủy hoặc đổi ý phải vô hiệu consent cũ. Việc hỏi/đáp phải dựa trên current decision, không đếm số câu rồi chặn mọi câu hỏi tiếp theo.

## Lỗi model và cấu hình

Giữ loại lỗi và mã lỗi an toàn cho context_length_exceeded, local_tool_output_invalid/truncated, lỗi schema/tool validation và transport. Không ghi raw request/body/PII vào artifact. Không kết luận nguyên nhân 13 lỗi khi chỉ có unknown_error. Thêm replay/mock HTTP để tái hiện lỗi từ adapter tới diagnostics; không mở retry vô hạn. Tôn trọng cấu hình guardrails; run tắt guardrails phải được thể hiện rõ, không lặng lẽ đổi cấu hình người dùng.

## Tiêu chí hoàn tất

- Có spec/plan và nhật ký kết quả; code trong checkout hiện tại, không subagent/worktree/commit tự động.
- Returning caller có brief/facts/episode ở lượt 1, 2 và sau nhiều lượt; sửa dữ kiện thấy ngay; khôi phục runtime không mất tiến trình nguồn đã commit.
- Test text và voice cho phần đã phát, pending worker, retry, baseline, đổi ngày/identity, erasure và memory outage.
- Replay SAMPLE-05 hoặc fixture tương đương: tên AirPure X được tra cứu trước câu hỏi chọn mẫu; không hỏi lại khi đã resolve; ambiguous/no-match không tự tạo consent/đơn.
- Test xác nhận/đổi variant/đổi budget/hủy/đổi giá giữ gate, receipt không tạo trùng.
- Diagnostics phân loại lỗi local cụ thể, không lộ nội dung; dữ liệu eval/scorer cũ giữ nguyên.
- Báo cáo riêng kết quả replay/offline và KPI live. Không hứa tăng CCR hay giảm RQR bằng số liệu chưa đo. Không chạy model/eval live, reset hoặc migrate DB triển khai trong goal này.

## Tự review thiết kế

Người dùng đã yêu cầu tự tạo spec/plan và thực thi, nên không có bước chờ duyệt lại. Chọn phục hồi từ committed evidence để tránh snapshot thứ hai lệch revision; snapshot cache phải luôn thua dữ liệu security/freshness mới. Review do cùng agent thực hiện theo yêu cầu không subagent. Những test cũ khẳng định brief chỉ có lượt đầu phải đổi vì đây là thay đổi hành vi được yêu cầu, không phải compatibility cần giữ.
