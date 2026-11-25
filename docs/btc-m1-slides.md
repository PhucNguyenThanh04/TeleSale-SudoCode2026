---
title: TeleSale SudoCode
subtitle: 'M1 · Tư vấn qua chat có bộ nhớ đa phiên'
date: 22/11/2026
lang: vi-VN
---

## Hai phiên, một khách hàng

- Phiên đầu ghi nhu cầu, báo giá có nguồn và điều khách muốn cân nhắc.
- Vài ngày sau, CRM nhận diện lại khách. Call Brief và timeline đưa lịch sử vào phiên mới.
- Agent kiểm tra lại giá, khuyến mãi và tồn kho trước khi xác nhận đơn.
- M1 trình diễn bằng chat text và xử lý file ghi âm bằng ASR local.

## Vòng lặp harness

**Chat → Gateway → Xác minh khách và nạp Call Brief → Harness → Trả lời.**

- Harness đọc context, cho agent gọi tool trong giới hạn, kiểm tra câu trả lời và lưu lượt.
- ASR local chuyển file thành transcript. Replay có mapping khách và phiên để đi qua cùng harness.
- PostgreSQL giữ nguồn BTC và trạng thái vận hành. Qdrant giữ chỉ mục policy.

## Ba tầng bộ nhớ

- **Working** giữ diễn biến và kết quả tool trong phiên hiện tại.
- **Episodic** ghi tư vấn, trở ngại và kết quả của các phiên trước.
- **Profile** lưu nhu cầu bền vững có phạm vi và bằng chứng theo lượt.
- LangMem đề xuất ghi nhớ. Kiểm tra bằng chứng và định danh trước khi ghi. Khi khách đổi ý, cập nhật đúng phạm vi.

## Tool và kiểm soát nghiệp vụ

Schema, xác nhận mua và bằng chứng tool kiểm soát giá, quyền ghi và thông tin được phép đưa ra.

| MCP | Vai trò |
|---|---|
| Catalog / CRM | Xác minh khách, tìm SKU, kiểm tồn và báo giá |
| Order | Tạo, cập nhật đơn, hẹn gọi lại và bàn giao |
| Memory | Đọc bối cảnh, lưu lượt và cung cấp timeline |
| Knowledge | Truy hồi chính sách theo ngày và phạm vi nguồn |

## Corpus và tiếng Việt

- 121 transcript, 39 nhóm khách đa phiên, 10 nhóm dùng cả hotline và chat; phiên bổ sung là dữ liệu tổng hợp.
- Thoại gồm khách do dự hỏi người nhà, khách so giá và khách đổi size.
- 22 WAV Edge TTS, khoảng 19 phút 33 giây. Hai vùng giọng và 1 giờ audio còn cần bổ sung bằng chứng.
- ASR local xử lý thoại Việt, từ mượn, số tiền và thực thể. WER, CER và Entity Accuracy báo riêng cho bộ team và BTC.

## Đo Full và baseline

- Dùng chung model, tham số, seed, dữ liệu BTC, bộ test và knowledge release.
- Baseline giảm quyền truy xuất bộ nhớ giữa các phiên, vẫn giữ diễn biến trong phiên.
- Eval chạy hai cấu hình, lưu trace theo schema BTC và in bảng từ scorer tham chiếu.
- BTC chạy riêng từng cấu hình bằng `run_eval.py` với bộ scenario chấm chéo.

## Kết quả lịch sử ngày 18/11

Run trên bộ team dùng 29 scenario và 170 lượt mỗi cấu hình. Bản release cần chạy và review extractor lại.

| Chỉ số | Full | Baseline |
|---|---:|---:|
| RQR ↓ | 0,0% | 51,4% |
| CCR ↑ | 67,1% | 16,5% |
| TSR ↑ | 100,0% | 75,9% |
| HR ↓ | 0,0% | 0,0% |
| Lượt TB/cuộc | 2,54 | 2,54 |

## Vòng cải tiến tri thức

**Feedback → Phân loại gap → Đề xuất → Người duyệt → Release → Chạy lại.**

- Hai vòng ngày 12/11 giữ cùng model, source, seed, bộ test và scorer.
- K1 tăng TSR 3,5 điểm %, giảm HR 0,4 điểm % và tăng RQR 7,7 điểm %.
- RQR hồi quy và extraction còn chờ review. Chưa có bằng chứng đạt vòng cải tiến của bản nộp.

## Lỗi quan sát được

- Giá của SKU trước xuất hiện khi khách chuyển sang SKU mới.
- Query đổi size mất ngữ cảnh, dẫn đến trích chính sách phí ship chung.
- Nhầm phụ thu biến thể với giá ưu đãi và tự suy thành điều kiện áp dụng.
- Báo cáo 15 ca lưu vị trí trace và hướng kiểm hồi quy. Chi phí/cuộc cần đo token cho cả agent và worker rồi đối chiếu giá provider.

## Demo hai phiên

- Dùng tài khoản demo liên kết cùng khách. Chọn ngày nghiệp vụ phù hợp với kịch bản BTC.
- Phiên 1 tư vấn và báo giá kèm khuyến mãi. Khách nói cần hỏi người nhà.
- Phiên 2 mở bằng Call Brief và timeline. Agent tiếp nối nhu cầu, kiểm tra báo giá hiện tại và xác nhận đơn.
- Mở kết quả Full/baseline do runner sinh. Chỉ trình chiếu kết quả đã gắn với đúng run.

## Gói chạy và trạng thái nghiệm thu

- BTC clone nhánh `main` của repo GitHub và đối chiếu SHA commit nộp bài. Demo và eval dùng cùng stack Compose đã seed. Eval reset dữ liệu hội thoại trước mỗi cấu hình, nên tạm dừng demo khi chạy eval.
- Đã rehearsal offline trên PostgreSQL, Qdrant và bốn MCP. Paired eval và chấm chéo đã sinh trace với model giả lập.
- Cần chạy thật từ ZIP trên Docker, chốt corpus đủ audio, điểm ASR, vòng cải tiến và video 5–8 phút.
