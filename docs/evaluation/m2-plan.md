# Kế hoạch thực hiện M2

## Goal tương thích bản giải đáp BTC tháng 11

1. Đồng bộ ground truth đúng tên và lưu provenance; giữ nguyên scorer/tool BTC. Kiểm: D01 list entity, D02 cùng khách, hash nguồn.
2. Hỗ trợ seed_history facts tùy chọn, phone và ngày as_of; nạp phiên/fact có provenance trước hội thoại qua cơ chế eval nội bộ, không mở quyền ghi cho agent. Kiểm: ví dụ DOCX, summary-only, thứ tự ngày, xung đột, idempotency, cách ly khách và baseline.
3. Xuất args tool đúng giá trị đã thực thi trong trace chấm; giữ che PII ở log/prompt và chặn CCCD/STK. Regex cấm chỉ quét lời agent/bộ nhớ. Kiểm: trace round-trip, lỗi tool/guardrail, ca PII và chính xác memory.
4. Hiển thị RQR zero-baseline không áp dụng và CCR cần BGK xem; phân biệt ASR public/private, đồng bộ any-match/per-turn entity. Kiểm: regression 0/0, 0/>0, dữ liệu thiếu, public4/private12 và entity list.
5. Hoàn chỉnh env/model/endpoint/phần cứng và hướng dẫn audio mới, kiểm lại nguồn rồi chốt manifest. Kiểm: focused tests, preflight 48 ca, cấu hình Compose, diff và audit từng yêu cầu. Không dùng điểm lịch sử làm bằng chứng bản mới.

Phạm vi goal là tương thích hành vi/hợp đồng và bàn giao theo thay đổi BTC, kiểm chứng offline. Không lấy mục tiêu đạt các chỉ số M2 thực nghiệm làm điều kiện hoàn tất sửa tương thích; eval live, chi phí API, audio và nhãn người tiếp tục cần quyền/tài nguyên riêng. Simulator vẫn để sau. Trạng thái: bước 1–5 đã hoàn tất triển khai và kiểm chứng offline, audit các yêu cầu tương thích đã qua. Preflight 48/118/323/38 và Compose config qua; các nhóm test compatibility/lifecycle/seed qua. Chưa build/chạy lại Docker hoặc kiểm SQL thật vì giới hạn môi trường; xem btc-data-issues.md cho bằng chứng và giới hạn cụ thể. Chưa có điểm model thật hoặc nghiệm thu M2 thực nghiệm.

## Triển khai M2 trước bản giải đáp

Ưu tiên theo yêu cầu mới của người dùng: để simulator sau. Trước mắt chốt bộ scenario và kiểm tra bổ sung, chạy Full/baseline bằng lời khách cố định khi được phép, tiếp đến judge/người chấm và báo cáo chỉ số. Giữ phần simulator đã triển khai để tiếp tục sau; yêu cầu simulator của M2 vẫn còn, chưa nghiệm thu.

1. Viết test âm/dương cho kiểm tra tool/result, order receipt, schema handoff, cấu trúc giỏ và yêu cầu review; viết bộ kiểm tra bổ sung và nối với đường chạy paired.
2. Sửa nhãn/scenario đã có, bổ sung ca an toàn còn thiếu; ghi căn cứ, kỳ vọng từng phiên và manifest; kiểm toàn bộ dữ liệu với schema/mock BTC.
3. Viết test 8 quy tắc simulator; triển khai runner 3 seed với đầu ra log và provenance, dùng runtime harness hiện tại.
4. Viết test judge/đồng thuận và ràng buộc evidence; triển khai CLI judge với rubric chuẩn, xuất mẫu người chấm và tính agreement.
5. Cập nhật hướng dẫn, kiểm thử tích hợp offline, rà diff và đối chiếu từng tiêu chí spec trước khi báo hoàn thành. Ghi riêng bằng chứng live/human còn thiếu.

Trạng thái: bước 1–5 đã hoàn tất phần triển khai, tài liệu và kiểm chứng offline: 58 test dataset/judge/pipeline và 19 test simulator/lifecycle đều qua; preflight xác nhận 48 ca, 118 phiên, 323 lượt, 38 ca khó. Bộ cuối đã chốt manifest, nguồn chính sách, tiêu chí rubric BTC và nhãn hotline TEAM-28. Chưa có run model thật trên bộ cuối hoặc nhãn người; không đánh dấu nghiệm thu M2 hoàn thành. Xem m2-readiness.md để biết bằng chứng còn thiếu.
