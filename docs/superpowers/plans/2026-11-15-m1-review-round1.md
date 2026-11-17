# M1 lượt 1 — review extraction và 6 ca TSR

Phạm vi: trace full/baseline mới nhất đã lưu, replay offline; không đổi scorer BTC, scenario, lời agent, tool, memory, latency hoặc hành vi agent. Không chạy model/DB/ASR.

- [x] Đọc toàn bộ candidate unresolved/uncertain của cả hai mode; lưu quyết định review có nguồn/hash và giới hạn self-review.
- [x] Kiểm các câu emitted và 20 lượt chọn bằng seed cố định; phân biệt lỗi parser với giới hạn biểu diễn/chấm của scorer.
- [x] Thêm regression trước khi sửa lỗi extraction rõ ràng; giữ các claim mơ hồ/điều kiện trong sidecar, không tự nâng gate lên complete.
- [x] Đối chiếu success_if, user/agent/tool và diagnostics của đủ 6 ca TSR; ghi nguyên nhân quan sát được và việc cần chuyển sang lượt 2.
- [x] Chạy focused tests, replay pair sang thư mục mới bằng scorer snapshot nguồn; chứng minh nguồn bất biến và báo delta thật.
- [x] Báo cáo kết quả/giới hạn, không gọi self-review là kiểm tay độc lập BTC.

## Kết quả

311 focused tests qua; replay cuối `20261115-m1-round1-final` giữ nguyên 340 lượt ngoài questions/claims. Biên bản review 106 candidate, 20 lượt full + 20 lượt baseline tương ứng và 6 ca TSR đã kiểm hash/coverage. Chi tiết: `docs/m1-round1-review-20261115.md`. Gate vẫn needs_review, không giả kiểm tay độc lập và không chạy live.
