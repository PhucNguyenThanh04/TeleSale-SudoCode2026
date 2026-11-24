# Rà soát bộ harness theo M2

Đã sửa lỗi nhận lầm số tiền là PII, xuất địa chỉ trong trace chấm, warm-up, seed trên SĐT dùng chung, Call Brief và callback. Preflight xác nhận nguồn và scenario khớp manifest. Chưa có kết quả Full/baseline bằng model trên bộ TEAM mới. Corpus hiện có 22 WAV duy nhất, khoảng 19 phút 33 giây. [Trạng thái kiểm tra](btc-data-issues.md)

Cập nhật ngày 24/11: đã sửa tương thích DOCX giải đáp và scorer mới, đồng bộ ground truth đúng tên, hỗ trợ seed có facts/phone/as_of, chỉnh trace/regex và RQR, phân biệt ASR public/private, cập nhật env/README và chốt manifest mới. Preflight lại qua 48 ca/118 phiên/323 lượt/38 ca khó. Kết quả kiểm chứng chi tiết và giới hạn Docker/DB/audio ở [btc-data-issues.md](btc-data-issues.md). Các con số 58+19 phía dưới thuộc lần triển khai M2 trước; không phải điểm model hoặc kết quả bản mới. Simulator tiếp tục để sau.

Kết luận: bộ scenario cuối đủ số lượng và đã sửa các lỗi nhãn/kiểm tra phát hiện được bằng offline. Chưa có cơ sở tuyên bố toàn bộ harness hoặc dự án đạt M2. Tài liệu này đối chiếu C.4, C.5 và phụ lục của PDF cùng schema, scorer, mock, persona và rubric trong gói BTC cục bộ; không thay hướng dẫn chính thức của BTC.

| Yêu cầu | Bằng chứng hiện tại | Kết luận |
|---|---|---|
| ≥40 kịch bản đa phiên | 48 ca, 118 phiên, 323 lượt, 38 ca có hard_case; mỗi ca 2–3 phiên | Đủ số lượng |
| Kỳ vọng rõ, nguồn BTC | Persona chuẩn; mã đơn có liên kết; giỏ/số đơn chính xác; ngữ nghĩa và chunk nguồn từng phiên | Đã kiểm tra cấu trúc/mock, chờ người rà nhãn |
| Tình huống khó | Đổi ý, giá/khuyến mãi theo ngày, ngân sách, cross-channel, người khác, hết hàng, TTL, SĐT chung; thêm PII, AI, xóa, nội bộ, ASR/teencode, policy cũ | Có fixture; chưa chứng minh agent xử lý đạt |
| Simulator giảm patience, 3 seed | Engine/runner, persona BTC, log bắt buộc, cùng runtime; test stub và kiểm độ đầy đủ từng call | Có triển khai; chưa có run thật hoặc TSR spread ≤10 điểm % |
| Baseline không bộ nhớ | Paired pipeline có Full và baseline; supplemental tách riêng điểm BTC | Chưa có cặp trace trên phiên bản 48 ca này |
| Judge và ≥20 nhãn người | Rubric BTC, binding input, mẫu ngẫu nhiên, agreement/kappa, gate thiếu nhãn | Có công cụ; chưa có judge thật/nhãn người độc lập |
| RQR/CCR/TSR/hallucination và ngưỡng M1 | Công cụ sẵn trong harness; kết quả ID cũ thuộc bộ cũ | Không suy ra điểm cho bộ mới |
| Calls-to-Close, TCA, RAG Recall@k, latency và cost | Có các module đo/đánh giá hiện hành; TCA cần nhãn tool, RAG cần evidence theo bộ BTC | Cần chạy và tổng hợp cùng phiên bản; bảng này chưa nghiệm thu các chỉ số |
| ≥2 cơ chế cải tiến, ≥3 vòng, phân tích cải tiến gây hại | Không được chứng minh bằng tăng số scenario | Cần bằng chứng các vòng thực tế |
| Audio/corpus, WER/CER, demo và hồ sơ nộp | Thành viên riêng phụ trách corpus/audio | Không được thay bằng 48 scenario JSON |

Các sửa dữ liệu: chuẩn hóa persona; khép liên kết đơn tra cứu; sửa carry-over TEAM-15, cân nặng TEAM-29/37, patience TEAM-20; thêm lịch sử địa chỉ thật và facts có ngày TEAM-12; sửa đầu vào và nhãn hotline chung TEAM-28; bổ sung TEAM-43–48. Bảy sample BTC SC01–SC07 không nằm trong bản gộp, bộ nguồn vẫn được giữ. Manifest mới ghi hash 48 ca, bảng nguồn và 28 file BTC, thêm ground truth ASR; thay nguồn sẽ bị loader từ chối tới khi được rà và chốt lại.

Các lỗ hổng chấm đã có kiểm tra bổ sung: tool gọi nhưng thất bại, order.status rỗng/sai đơn, handoff brief thiếu schema, chia nhiều đơn để cộng đúng tổng, sai đơn vị hàng. Match từ khóa chưa xác minh đúng nghĩa sẽ ở trạng thái needs_review. Các bất nhất BTC được ghi tại [btc-data-issues.md](btc-data-issues.md), không sửa scorer hoặc nguồn BTC.

Phân bố tập cuối: 22 ca từ bộ phát triển của nhóm +20 ca bổ sung +6 ca an toàn mới. Các ca và nhãn đã được dùng khi phát triển bộ kiểm tra, không phải held-out độc lập. Nhãn mới do assistant soạn, chưa có người chấm độc lập. Ground truth số có thể rỗng ở phiên chỉ hỏi chính sách; kỳ vọng được ghi ở semantic_requirements cùng nguồn, cần judge/người kiểm tra.

Trình tự lấy bằng chứng còn lại theo ưu tiên mới của người dùng: chạy paired Full/baseline bằng lời khách cố định trên bộ đã chốt; chạy judge trên trace tương ứng; người chấm ≥20 mẫu và rà ca sai; xuất bảng chỉ số cùng TCA/RAG/latency/cost và nối bằng chứng cải tiến thực tế. Simulator ba seed để sau, vẫn cần nếu công bố đủ M2. Các bước gọi provider/reset DB cần được người dùng cho phép theo hướng dẫn làm việc đã cung cấp. Không tự chạy model live trong lượt sửa này.

Kiểm chứng hiện có: preflight offline trả 48/118/323/38; 58 test tập trung cho dataset/manifest, judge/đồng thuận, semantic checks, scenario contract, BTC snapshot và paired pipeline đã qua; 19 test simulator/lifecycle cũng qua sau khi thêm manifest và đóng gói rubric. Kiểm thử không chứng minh TSR, chất lượng ngữ nghĩa hoặc độ lặp lại trên model thật. Không chạy toàn bộ suite.

Lưu ý phạm vi: C.1 còn yêu cầu M2 ≥250 transcript và ≥100 audio/≥3 giờ; đây là dataset hội thoại/audio, khác ≥40 kịch bản C.4. Phần an toàn, bộ nhớ, MCP/A2A, voice latency và ba vòng cải tiến cũng cần bằng chứng riêng khi công bố M2 toàn dự án. Thông báo BTC ngày nộp 20/11/2026 yêu cầu mã nguồn/README/script seed, dataset/mô tả, kiến trúc và báo cáo đánh giá ≥10 ca sai; video 5–8 phút có C.6 và slide ≤15 trang được chuẩn bị sau, buổi bảo vệ 28/11/2026.
