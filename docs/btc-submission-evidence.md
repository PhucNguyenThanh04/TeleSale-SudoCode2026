# Hồ sơ bàn giao BTC M1

| Hạng mục | File hoặc cách tái lập |
|---|---|
| Mã nguồn, môi trường, setup dữ liệu | URL repo GitHub, branch hoặc tag để clone và commit để đối chiếu. Repo chứa `compose.submission.yml`, `Dockerfile.submission`, lock Python cho mỗi image và [hướng dẫn bắt đầu](../START_HERE.md). |
| Kiến trúc và tool | [Kiến trúc M1](m1-architecture.md), [hợp đồng harness](../ai-services/docs/text-harness-contract.md). |
| Corpus và bộ test hội thoại | Dataset ZIP có transcript, audio gốc, manifest và báo cáo validator. [Mô tả corpus](../dataset/M1-CORPUS.md) và [bộ scenario team](../ai-services/eval_harness/scenarios/README.md). BTC truyền bộ ẩn khi chấm. |
| Eval tự động và chấm chéo | `eval` chạy cả cặp và in bảng. `eval-trace` chạy `run_eval.py` cho một cấu hình. Output chuẩn nằm trong `RESULTS_DIR`. |
| ASR local | Image `asr` có CLI xử lý audio và tính WER/CER/Entity Accuracy. Model weights được cấp ngoài source. |
| Web demo | Compose service `backend`, các trang `/chat` và `/knowledge`, hai tài khoản gắn hồ sơ BTC. |
| Báo cáo và vòng cải tiến | [Báo cáo đánh giá](btc-m1-evaluation-report.md) có bảng Full/baseline, K0/K1 lịch sử và phân tích 15 lỗi. [Quy trình chạy hai vòng](m1-acceptance.md#5-knowledge-gap-loop-hai-vòng) dùng cho kết quả của bản nộp. |
| Video và slide | [Kịch bản quay 6 phút 40 giây](../START_HERE.md#3-demo-chat-trên-một-project-riêng), [nội dung slide](btc-m1-slides.md) và PPTX 12 slide. Cập nhật số liệu và quay video sau khi kiểm với stack thật. |

Corpus hiện có 120 transcript, 39 nhóm đa phiên, 9 nhóm có cuộc gọi và chat. Hai ZIP Edge TTS gốc chứa 22 WAV, khoảng 19 phút 33 giây. Bộ `team22-edge-clone` đánh dấu `team_preview=true`. Còn thiếu 1 nhóm đa kênh, ít nhất 18 file audio, khoảng 40 phút 27 giây và bằng chứng hai vùng giọng. [Mô tả corpus](../dataset/M1-CORPUS.md) · [Rà soát audio](../dataset/BAO_CAO_RÀ_SOAT_DATASET_2026-11-03.md)

Hồ sơ cuối còn cần video 5–8 phút có hai cuộc gọi, slide với số liệu của bản nộp, dataset đủ audio và kết quả chạy gắn với bản phát hành. Bộ audio BTC đầy đủ và bộ test ẩn đến từ BTC. Bảng hội thoại có thể xuất trước, rồi đính kèm điểm ASR khi nhận được audio.

## Mức kiểm chứng của mã nguồn

- Kiểm tra `MANIFEST.json`, checksum, cấu hình Compose và CLI `run_eval.py` trên bản giải nén. Bộ team qua kiểm độ phủ hội thoại với 29 scenario, gồm 28 đa phiên và 15 ca khó, tổng cộng 67 cuộc gọi và 170 lượt. Phần độ phủ này áp dụng cho bộ chạy hội thoại.
- Chạy ứng dụng trực tiếp từ bản giải nén với PostgreSQL 16 và Qdrant 1.19.1 tạm. Bootstrap nạp nguồn BTC, dựng policy bằng embedding giả lập cục bộ và dùng lại dữ liệu khi chạy setup lần hai. Bốn MCP truy cập đúng DB, AI và hai worker khởi động, backend phục vụ `/chat`, `/knowledge`, `/login` và đăng nhập được bằng tài khoản seed.
- Chạy paired runner với provider giả lập cục bộ trên 1 scenario BTC, 2 cuộc gọi, 7 lượt mỗi cấu hình. Runner xuất hai trace, gọi scorer BTC, in bảng và tạo đề xuất K1. Dùng kết quả này để xác nhận luồng thực thi; đo chất lượng trên corpus đầy đủ với model thực tế.
- Sau khi có quyền Docker, build ba image AI, backend và ASR từ ZIP giải nén. Hai project Compose riêng khởi động được với model và embedding giả lập cục bộ. Eval đi qua scorer BTC, còn image ASR tải được thư viện và chọn được CPU `int8`. Dữ liệu chấm cuối cần kết quả hội thoại trên corpus đủ quy mô và điểm ASR của hai bộ dữ liệu.
- Gateway Docker qua kiểm thử đăng nhập, hai phiên WebSocket có streaming, lưu lượt và timeline. Sau khi chạy job với UID/GID của người vận hành, host đọc trực tiếp `run.json`, `btc_score.json`, hai trace của lệnh eval và trace chấm chéo. Image ASR ghi được vào cả thư mục kết quả và cache model bằng UID/GID đó.

## Chốt commit trên GitHub

Commit của bản nộp cần chứa đủ code runtime, hướng dẫn và cấu hình mẫu. Đối chiếu nội dung tại branch hoặc tag đã push trước khi gửi URL cho BTC. Bản ZIP mã nguồn được dùng cho kiểm thử nội bộ từ thư mục sạch. Corpus, video và slide đi theo hồ sơ nộp. Thông tin truy cập provider được cấp qua kênh riêng.

Khi kiểm lại bản clone, đối chiếu `git rev-parse HEAD` với commit đã chốt, chạy setup bằng dữ liệu BTC và kiểm cả hai lệnh eval trong README. File `.env.submission`, secret, model weights, audio lớn và trace chạy thật được cấp hoặc tạo theo đường dẫn trong hướng dẫn chạy.
