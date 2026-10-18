# Held-out memory set — đề xuất cấu trúc, chưa có nhãn

Mục tiêu là đo trích fact, cập nhật/supersede và sử dụng memory qua lượt/cuộc trên dữ liệu **chưa dùng để chỉnh quy tắc**. Dự kiến khoảng 30 ca tổng hợp, không chứa dữ liệu khách thật hoặc PII thô. Đây chưa phải bộ eval sẵn sàng chạy: chưa viết câu thoại hay nhãn.

| Nhóm ca | Số ca dự kiến | Nội dung cần phủ |
|---|---:|---|
| Một lượt, nhiều cách diễn đạt/sản phẩm | 8 | Số/đơn vị, size/màu, payment, phản đối; biến thể ASR và teencode; cặp khẳng định–câu hỏi |
| Nhiều lượt trong một cuộc | 8 | Khách sửa hoặc phủ định fact cũ, đổi size/màu/phương thức; fact đúng và fact giả định trong cùng lượt |
| Nhiều cuộc cùng khách | 8 | Hai đến ba cuộc, fact được mang sang, fact thay đổi ở cuộc sau, blocker được giải quyết, lịch sử giá/tồn kho phải kiểm lại |
| Ca loại và đối chứng ngữ cảnh | 6 | Câu hỏi, “nếu”, phủ định, người thứ ba, lời agent, sở thích/điều kiện giao hàng không phải blocker; có câu khẳng định gần giống để kiểm bỏ sót |

Mỗi ca nên có `case_id`, sản phẩm/ngữ cảnh, `input_mode`, danh sách `calls`/`turns` có thứ tự và ngày nghiệp vụ, cùng nhãn ở file riêng. Nhãn theo lượt gồm `expected_facts` (`key`, kiểu và giá trị chuẩn, `op`, `source_turn`, `evidence_quote`, và `kind=preference|selection` khi áp dụng cho size/màu), `excluded_candidates` (lý do loại), và khi cần `expected_memory_after_turn`, `must_carry_over`, `must_not_ask`. Giữ nguồn lời khách tách khỏi lời agent và tool; giá shop báo không thành ngân sách khách. Không dùng `scenario_id`, nhãn hoặc câu thoại của set này trong runtime.

**Nguồn nhãn:** người gắn nhãn độc lập sẽ đọc câu thoại tổng hợp và hợp đồng BTC (`schemas/`, `eval/reference_eval.py`, tài liệu điều chỉnh/giải đáp), rồi ghi tên người gắn nhãn, ngày, phiên bản nguồn và căn cứ cho mỗi quyết định. Người thứ hai rà soát ca bất đồng; giữ cả hai ý kiến và quyết định cuối. Không suy nhãn từ output của model hoặc từ bộ 50 lượt đã dùng để phân tích lỗi.

**Tiêu chí gắn nhãn:** chỉ nhận fact do khách trực tiếp khẳng định hoặc tool thành công xác minh đúng loại; câu hỏi, giả định, lời người thứ ba và lời agent không thành fact khách. Xác định rõ fact bền vững so với lựa chọn giao dịch, fact được sửa/thay thế/xóa, và giá trị chuẩn theo nguồn BTC đã công bố. Với slot chưa có enum chính thức (như `objection`, `blocker`, màu), ghi nguyên văn căn cứ và đánh dấu điểm cần phân xử, không tự tạo danh mục hoàn chỉnh từ public sample.

Khi người gắn nhãn độc lập hoàn tất, khóa toàn bộ câu thoại và nhãn bằng manifest SHA-256 cho từng file cùng hash của manifest; lưu mã phiên bản và người phê duyệt. Chỉ chạy held-out **một lần sau khi quy tắc đã chốt**, kiểm hash trước khi chạy và ghi hash vào report. **Không dùng set này để chỉnh quy tắc, prompt, từ điển hay ngưỡng.** Nếu phát hiện lỗi, lưu kết quả và xây tập phát triển mới cho vòng sửa sau; không chạy lại trên chính held-out để chọn thay đổi.
