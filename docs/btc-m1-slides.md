---
title: TeleSale SudoCode
subtitle: 'M1 · Tư vấn qua chat có bộ nhớ đa phiên'
date: 28/11/2026
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

- 48 kịch bản eval (118 cuộc gọi), khách đa phiên và đa kênh; dữ liệu tổng hợp, không dùng dữ liệu khách thật.
- 120 cuộc audio VieNeu-TTS, 134 phút, giọng Bắc và Nam, 31 cuộc trộn nhiễu.
- ASR local whisper-turbo (B2): WER 8,4%, CER 5,2%, Entity 78,1% trên 120 file; BTC 4 hội thoại WER 10,7%.
- Diarization theo lượt: 83,5% (120 file), 97,1% (BTC).

## Đo Full và baseline

- Dùng chung model, tham số, seed, dữ liệu BTC, bộ test và knowledge release.
- Baseline giảm quyền truy xuất bộ nhớ giữa các phiên, vẫn giữ diễn biến trong phiên.
- Eval chạy hai cấu hình, lưu trace theo schema BTC và in bảng từ scorer tham chiếu.
- BTC chạy riêng từng cấu hình bằng `run_eval.py` với bộ scenario chấm chéo.

## Kết quả 48 kịch bản (27/11)

Run `113656Z`, 323 lượt mỗi cấu hình, scorer `reference_eval.py` của BTC.

| Chỉ số | Full | Baseline |
|---|---:|---:|
| RQR ↓ | 3,0% | 26,6% |
| CCR ↑ | 65,6% | 13,5% |
| TSR ↑ | 81,2% | 62,5% |
| HR giá/KM ↓ | 0,0% | 0,0% |
| Call Brief p95 | 287 ms | — |
| TTFT / Total p95 | 6,4 s | 6,4 s |

Đạt: RQR giảm 88,7%, TSR ≥ 70%, HR giá/KM ≤ 5%, Total ≤ 8 s. Chưa đạt: TTFT p95 ≤ 3 s.

## Cải tiến latency

- Mỗi lần gọi `gemma4:31b` mất ~1 s; một lượt cần 2–3 lần gọi nối tiếp.
- Tra kèm giá và tồn kho khi tìm thấy đúng một sản phẩm; xác nhận đơn từ biên nhận; kiểm lại bản nháp sau khi tự bổ sung bằng chứng.
- Guardrail nhận bằng chứng từ đơn đã tạo và tra cứu đơn, bớt chặn nhầm.
- Số lần gọi model giảm 15%, TTFT p95 7,4 → 6,4 s, lượt trả lời xin lỗi chung 70 → 52, TSR giữ 81,2%.

## Vòng cải tiến tri thức

**Feedback → Phân loại gap → Đề xuất → Người duyệt → Release → Chạy lại.**

- Hai vòng ngày 12/11 giữ cùng model, source, seed, bộ test và scorer.
- K1 tăng TSR 3,5 điểm %, giảm HR 0,4 điểm % và tăng RQR 7,7 điểm %.
- RQR hồi quy và extraction còn chờ review. Chưa có bằng chứng đạt vòng cải tiến của bản nộp.

## Lỗi quan sát được

- Báo giá theo địa chỉ cũ trong bộ nhớ sau khi khách đổi nơi nhận, dẫn đến nói sai freeship (TEAM-33, toàn bộ HR 3,8%).
- 16% lượt trả câu xin lỗi chung vì bản nháp bị chặn hai lần, chủ yếu `price_without_quote`.
- Gọi tool thiếu tham số kịch bản: tìm sản phẩm không truyền ngân sách, tra đơn không truyền mã đơn.
- Báo cáo phân tích 14 ca kèm vị trí trace và hướng xử lý.

## Demo ba cuộc gọi

- Cuộc 1: tư vấn, báo giá kèm khuyến mãi, khách hẹn hỏi người nhà.
- Cuộc 2 (vài ngày sau): Call Brief hiện ra, agent mở đầu bằng xác nhận tiếp nối, không hỏi lại, chốt đơn.
- Cuộc 3: khách gọi lại đổi size, agent tra đơn, kiểm tồn và cập nhật đơn.
- Timeline bộ nhớ của khách hiển thị trên giao diện sau mỗi cuộc.

## Gói chạy và trạng thái nghiệm thu

- Chạy trên Linux, macOS và Windows: `compose_up.py` → `seed_btc.py` → `run_eval.py`.
- Run 48 kịch bản validated, execution healthy; trace theo schema BTC.
- Còn lại: TTFT p95, duyệt extraction, phát hành K1 cho vòng cải tiến tri thức.
