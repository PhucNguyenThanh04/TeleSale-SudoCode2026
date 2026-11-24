# Corpus TeleSale M1

Bản bàn giao dữ liệu phát triển dựa trên catalog, CRM seed, policy và mock tool BTC với ngày tham chiếu 15/10/2026. Gói giữ nguyên năm file transcript và hai ZIP audio gốc. `corpus-stats.json` ghi số lượng và thời lượng đo từ WAV. `speech-validation.md` lưu kết quả đối chiếu transcript với nguồn BTC.

| Nhóm transcript | Số cuộc | Cách xây dựng |
|---|---:|---|
| `team_synthetic.json` và `team_clone.template.json` | 22 | Phiên đầu của T01–T22, soạn theo catalog và chính sách BTC |
| `team_session2.json` và `team_session3.json` | 30 | Phiên nối tiếp của T01–T22, gồm 22 phiên hai và 8 phiên ba |
| `team_new_customers.json` | 69 | Claude soạn 4 phiên cho mỗi nhóm T30–T46; bổ sung phiên chat tổng hợp T31-S05, liên kết 17 ID trong CRM seed BTC |
| **Tổng** | **121** | **39 nhóm đa phiên, 10 nhóm có cả hotline và chat** |

Ví dụ persona gồm khách hỏi ý người nhà (T30-S01), khách so giá đối thủ (T21) và khách quay lại đổi size (T02). Phân nhóm dùng `source_dialogue_id` khi có, rồi kiểm số thứ tự phiên liên tục và ngày không lùi. Các phiên gốc dùng ID hội thoại làm khóa. Corpus có hotline, Fanpage và Zalo OA. Các nhóm T01–T22 nối theo ID nội bộ của corpus. Nhóm T30–T46 có tham chiếu CRM BTC tường minh.

Hai bộ Edge TTS chứa tổng cộng 22 WAV, khoảng 19 phút 33 giây. Mỗi bộ có annotation và ground truth. Bộ có tên `team22-edge-clone` mang cờ `team_preview=true`. Các nhãn `bac` và `nam` trong transcript mô tả giọng dự kiến. Manifest audio hiện có dùng chung voice ID cho hai vùng nên bằng chứng giọng hai vùng còn thiếu. Phần thoại thuộc 99 mục còn lại được lưu ở dạng transcript.

Video và slide cần dùng dữ liệu minh họa đã rà. Gói này chứa thoại soạn cho diễn tập, tham chiếu ID CRM BTC và audio do TTS tạo. Giữ dữ liệu CRM, ký hiệu theo dõi và audio nội bộ tách khỏi log công khai. Runtime có bước che thông tin nhận dạng trước khi gửi context ra LLM và ghi log nghiệp vụ.

| Mốc M1 | Có trong gói |
|---|---|
| 120 transcript | 121 ID khác nhau |
| 30 khách đa phiên | 39 nhóm có ít nhất hai phiên |
| 10 khách gọi và chat | 10 nhóm |
| 40 audio, ít nhất 1 giờ | 22 WAV, khoảng 19 phút 33 giây, thiếu ít nhất 18 file và khoảng 40 phút 27 giây |
| ASR public BTC và ít nhất 20 file team | Team tự tạo audio D01–D04 từ kịch bản/ground truth mới để chứng minh pipeline; audio private do BTC giữ và đo ngày chấm. Cần bộ team đã rà và báo cáo riêng. |

Validator báo 0 lỗi và 58 cảnh báo. Các cảnh báo gồm thời lượng hoặc số lượt ngoài khoảng mẫu BTC, ngữ cảnh thiếu SKU để đối chiếu giá/tồn kho và một số trường hợp chuẩn hóa thực thể. Mốc một giờ được đối chiếu trên thời lượng WAV. Bộ scenario hội thoại dùng khi `eval` là một bộ riêng có nhãn chấm Full/baseline.

Lệnh kiểm lại năm tệp transcript nằm trong [README](../README.md#5-asr-local-và-chấm-điểm).
