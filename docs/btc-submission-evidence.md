# Hồ sơ bàn giao BTC M1

| Hạng mục | File hoặc cách tái lập |
|---|---|
| Mã nguồn, môi trường, setup dữ liệu | Repo chứa `compose.submission.yml`, `Dockerfile.submission`, lock Python cho mỗi image và [README](../README.md). |
| Kiến trúc và tool | [Kiến trúc M1](m1-architecture.md) và [hợp đồng harness](../ai-services/docs/text-harness-contract.md). |
| Corpus và bộ test hội thoại | Dataset ZIP có transcript, audio gốc, manifest và báo cáo validator. [Mô tả corpus](../dataset/M1-CORPUS.md) và [bộ scenario team](../eval/scenario_final/). BTC truyền bộ ẩn khi chấm. |
| Eval tự động và chấm chéo | `eval` chạy cả cặp và in bảng. `eval-trace` chạy `run_eval.py` cho một cấu hình. Output chuẩn nằm trong `RESULTS_DIR`. |
| ASR local | Image `asr` có CLI xử lý audio và tính WER/CER/Entity Accuracy. Model weights được cấp ngoài source. |
| Web demo | Compose service `backend`, các trang `/chat` và `/knowledge`, hai tài khoản gắn hồ sơ BTC. |
| Báo cáo và vòng cải tiến | [Báo cáo đánh giá](btc-m1-evaluation-report.md) có bảng Full/baseline, K0/K1 lịch sử và phân tích 15 lỗi. |
| Video và slide | Có [nội dung slide](btc-m1-slides.md) và PPTX 12 slide. Video còn thiếu trong hồ sơ diễn tập. |

Corpus hiện có 121 transcript, 39 nhóm đa phiên, 10 nhóm có cuộc gọi và chat; phiên T31-S05 là dữ liệu tổng hợp bổ sung. Hai ZIP Edge TTS gốc chứa 22 WAV, khoảng 19 phút 33 giây. Bộ `team22-edge-clone` đánh dấu `team_preview=true`. Còn thiếu ít nhất 18 file audio và khoảng 40 phút 27 giây. Theo giải đáp mới, không bắt đủ vùng giọng nhưng phải công bố hạn chế giọng của bộ hiện có. [Mô tả corpus](../dataset/M1-CORPUS.md) · [Rà soát audio](../dataset/BAO_CAO_RÀ_SOAT_DATASET_2026-11-03.md)

Hồ sơ cuối còn cần dataset đủ audio và kết quả chạy gắn với bản phát hành. Video 5–8 phút có hai cuộc gọi và slide với số liệu của bản nộp cần chuẩn bị cho buổi bảo vệ; theo thông báo BTC, hai mục này không bắt buộc nộp vào ngày 20/11. Team tự tạo audio public D01–D04 để chứng minh pipeline. BTC giữ audio private và bộ test ẩn để chạy ngày chấm bằng key của BTC; điểm xếp hạng ASR chỉ lấy trên audio private.

## Artifact diễn tập hiện có

- Dataset `dist/telesale-btc-m1-dataset-20261122-rc2.zip` có 121 transcript, gồm T31-S05, hai ZIP audio Edge và báo cáo validator. SHA-256: `06dbf764bb376a8855ee7848d12aaa9a814703ee00c30429701f38bd288af698`. Đây là snapshot phát triển chưa đủ 40 audio/1 giờ và chưa chứng minh hai vùng giọng; file nằm ngoài Git nên phải cấp riêng. Bản dataset `rc1` cũ chưa có T31-S05.
- Bộ scenario của đợt diễn tập được preflight offline xác nhận có 29 ca, 67 phiên, 170 lượt, trong đó 28 ca đa phiên và 15 ca khó; kiểm tra nhãn memory và task đều qua. Các số liệu này áp dụng cho bộ của đợt diễn tập. BTC đã đính chính validate_scenarios.py là công cụ nội bộ, team không cần đợi hoặc nộp kết quả validator này.

## Mức kiểm chứng của mã nguồn

- Kiểm tra `MANIFEST.json`, checksum, cấu hình Compose và CLI `run_eval.py` trên bản giải nén. Bộ team qua kiểm độ phủ hội thoại với 29 scenario, gồm 28 đa phiên và 15 ca khó, tổng cộng 67 cuộc gọi và 170 lượt. Phần độ phủ này áp dụng cho bộ chạy hội thoại.
- Chạy ứng dụng trực tiếp từ bản giải nén với PostgreSQL 16 và Qdrant 1.19.1 tạm. Bootstrap nạp nguồn BTC, dựng policy bằng embedding giả lập cục bộ và dùng lại dữ liệu khi chạy setup lần hai. Bốn MCP truy cập đúng DB, AI và hai worker khởi động, backend phục vụ `/chat`, `/knowledge`, `/login` và đăng nhập được bằng tài khoản seed.
- Chạy paired runner với provider giả lập cục bộ trên 1 scenario BTC, 2 cuộc gọi, 7 lượt mỗi cấu hình. Runner xuất hai trace, gọi scorer BTC, in bảng và tạo đề xuất K1. Dùng kết quả này để xác nhận luồng thực thi; đo chất lượng trên corpus đầy đủ với model thực tế.
- Sau khi có quyền Docker, build ba image AI, backend và ASR từ ZIP giải nén. Hai project Compose riêng khởi động được với model và embedding giả lập cục bộ. Eval đi qua scorer BTC, còn image ASR tải được thư viện và chọn được CPU `int8`. Dữ liệu chấm cuối cần kết quả hội thoại trên corpus đủ quy mô và điểm ASR của hai bộ dữ liệu.
- Gateway Docker qua kiểm thử đăng nhập, hai phiên WebSocket có streaming, lưu lượt và timeline. Sau khi chạy job với UID/GID của người vận hành, host đọc trực tiếp `run.json`, `btc_score.json`, hai trace của lệnh eval và trace chấm chéo. Image ASR ghi được vào cả thư mục kết quả và cache model bằng UID/GID đó.

Bản ZIP mã nguồn được dùng để diễn tập từ thư mục sạch. Bản nộp qua GitHub và cấu hình đi kèm theo [README](../README.md#6-hồ-sơ-nộp).
