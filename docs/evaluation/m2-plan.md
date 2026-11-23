# Kế hoạch thực hiện M2

Ưu tiên theo yêu cầu mới của người dùng: để simulator sau. Trước mắt chốt bộ scenario và kiểm tra bổ sung, chạy Full/baseline bằng lời khách cố định khi được phép, tiếp đến judge/người chấm và báo cáo chỉ số. Giữ phần simulator đã triển khai để tiếp tục sau; yêu cầu simulator của M2 vẫn còn, chưa nghiệm thu.

1. Viết test âm/dương cho kiểm tra tool/result, order receipt, schema handoff, cấu trúc giỏ và yêu cầu review; viết bộ kiểm tra bổ sung và nối với đường chạy paired.
2. Sửa nhãn/scenario đã có, bổ sung ca an toàn còn thiếu; ghi căn cứ, kỳ vọng từng phiên và manifest; kiểm toàn bộ dữ liệu với schema/mock BTC.
3. Viết test 8 quy tắc simulator; triển khai runner 3 seed với đầu ra log và provenance, dùng runtime harness hiện tại.
4. Viết test judge/đồng thuận và ràng buộc evidence; triển khai CLI judge với rubric chuẩn, xuất mẫu người chấm và tính agreement.
5. Cập nhật hướng dẫn, kiểm thử tích hợp offline, rà diff và đối chiếu từng tiêu chí spec trước khi báo hoàn thành. Ghi riêng bằng chứng live/human còn thiếu.

Trạng thái: bước 1–5 đã hoàn tất phần triển khai, tài liệu và kiểm chứng offline: 58 test dataset/judge/pipeline và 19 test simulator/lifecycle đều qua; preflight xác nhận 48 ca, 118 phiên, 323 lượt, 38 ca khó. Bộ cuối đã chốt manifest, nguồn chính sách, tiêu chí rubric BTC và nhãn hotline TEAM-28. Chưa có run model thật trên bộ cuối hoặc nhãn người; không đánh dấu nghiệm thu M2 hoàn thành. Xem m2-readiness.md để biết bằng chứng còn thiếu.
