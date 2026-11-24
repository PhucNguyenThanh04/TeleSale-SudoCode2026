# Đặc tả sửa bộ đánh giá harness M2

Đặc tả này thuộc mục tiêu M2 trước đây. Goal đang thực hiện sau khi người dùng xóa goal cũ là sửa tương thích thay đổi BTC, theo phần đầu m2-plan.md; simulator để sau. Các tiêu chí cần model thật/người chấm dưới đây vẫn là điều kiện nghiệm thu M2 thực nghiệm, không phải bằng chứng đã đạt khi hoàn tất sửa tương thích offline.

Yêu cầu: sửa các thiếu sót trong rà soát scenario_final và hỗ trợ đánh giá M2 theo đề cùng điều chỉnh BTC. Làm trong checkout hiện tại, không dùng Superpowers hoặc subagent. Không sửa gói/scorer BTC, không thay điểm lịch sử, không sửa agent theo đáp án test.

## Tiêu chí hoàn thành

1. Bộ cuối có ít nhất 40 ca đa phiên; persona chuẩn BTC, nhãn memory và mục tiêu nhất quán; có ca ASR/teencode, riêng tư, AI trung thực, xóa dữ liệu, nội bộ, danh tính mơ hồ, TTL và khách gọi lần ba hết kiên nhẫn. Có căn cứ theo nguồn BTC, kiểm tra offline và manifest phát hiện thay đổi.
2. Kiểm tra bổ sung của nhóm tách khỏi điểm BTC, phát hiện tra sai/không tìm thấy đơn, expected tool thất bại, brief sai schema, sai giỏ/số đơn và tình huống chưa có đánh giá ngữ nghĩa. Không coi thiếu review là đạt. Đầu vào và kết quả gắn hash; không ghi đè bằng chứng.
3. Simulator theo 8 quy tắc BTC, persona/patience chuẩn, 3 seed, log bắt buộc, cùng pipeline agent và không truyền nhãn chấm vào agent. Có kiểm thử offline cho phản ứng, kết thúc, giới hạn lượt và cách ly nhãn.
4. Judge dùng rubric PASS/FAIL BTC, nguồn kiểm chứng và tiêu chí từng phiên; có đối chiếu ít nhất 20 nhãn người, phần trăm đồng thuận/Cohen kappa; không gán nhãn người bằng assistant. Có CLI, cấu hình và kiểm thử bằng stub.
5. Báo cáo M2 phân biệt dataset, thực thi, semantic review, simulator, TCA, RAG, latency và chi phí; chỉ công bố bằng chứng thật. Các hạn chế/khác biệt mock BTC được lưu riêng, không tự sửa nguồn BTC.
6. Chạy kiểm thử tập trung; đánh giá live/tác vụ tốn kém chỉ sau khi có quyền rõ ràng. Nếu chưa có audio/BTC hoặc nhãn người/quyền chạy, không tuyên bố nghiệm thu M2 hoàn chỉnh.

Audio/corpus do thành viên khác phụ trách. Không dựng dashboard, refactor agent hoặc thêm hệ nghiệp vụ ngoài yêu cầu. Các ca đã dùng để sửa bộ kiểm tra không còn được quảng bá là held-out độc lập.
