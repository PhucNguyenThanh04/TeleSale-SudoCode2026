# Hồ sơ bàn giao BTC M1

| Hạng mục | File hoặc cách tái lập |
|---|---|
| Mã nguồn, môi trường, setup dữ liệu | Repo chứa Compose chạy server, `Dockerfile`, script host `seed_btc.py`, `run_eval.py`, lock `config/requirements/host.txt` dùng chung lock AI với image và [README](../README.md). |
| Kiến trúc và tool | [Kiến trúc M1](m1-architecture.md) và [hợp đồng harness](../ai-services/docs/text-harness-contract.md). |
| Corpus và bộ test hội thoại | Dataset ZIP có transcript, audio gốc, manifest và báo cáo validator. [Mô tả corpus](../dataset/M1-CORPUS.md) và [bộ scenario team](../eval/scenario_final/). BTC truyền bộ ẩn khi chấm. |
| Eval tự động và chấm chéo | `python run_eval.py` chạy cả cặp và in bảng; thêm `--scenarios`, `--config`, `--out` để xuất một trace theo BTC. Chạy trên host, không gọi Docker. Output chuẩn nằm trong `RESULTS_DIR`. |
| ASR local | CLI `python -m speech` trên host xử lý audio và tính WER/CER/Entity Accuracy. Model weights được cấp ngoài source. |
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

Kiểm tra luồng seed Python trên host ngày 24/11/2026:

- Cài lock `config/requirements/seed.txt` trong virtualenv Python 3.13 mới; import được toàn bộ module bootstrap/account và `pip check` không báo xung đột.
- Chạy bằng user thường với PostgreSQL 16.15 tạm, xác thực SCRAM. Nhập được 40 sản phẩm, 96 biến thể, 50 khách và 99 policy chunks; bốn role MCP đăng nhập được và hai tài khoản demo được tạo.
- Dựng policy bằng Qdrant local và embedding giả lập cục bộ cho 93 chunks; kiểm tra dùng tokenizer thật có checksum. Không gọi API model/embedding bên ngoài.
- Chạy seed lần hai giữ nguyên tài khoản và lượt runtime đã thêm, không encode lại policy; kiểm tra fingerprint nguồn khớp database. Các cổng health trong phép kiểm tra này là HTTP/TCP giả lập, chưa phải container AI/MCP/backend thật.

Các diễn tập Docker/ZIP ở trên thuộc quy trình trước. Chúng không thay cho kiểm tra Docker thực tế của luồng host seed mới. Bản nộp qua GitHub và cấu hình đi kèm theo [README](../README.md).

Kiểm tra luồng server Docker, seed/eval host ngày 25/11/2026:

- Compose mặc định và toàn bộ profile chỉ còn 11 server/worker; không có job seed, eval, knowledge-eval hoặc ASR. Hai image AI/backend giữ lock server; `config/requirements/host.txt` dùng lại lock AI và bổ sung thư viện tạo tài khoản.
- Cài lock host vào virtualenv Python 3.13; `pip check` qua. Chạy lại seed với PostgreSQL 16.15 tạm, Qdrant local và embedding giả lập: số bản ghi đúng, bốn role MCP xác thực được, hai tài khoản tồn tại; seed lần hai giữ runtime và không encode lại policy.
- 44 test tập trung qua cho CLI BTC, đường dẫn/cổng, cấu hình root, kiểm tra nguồn, chờ seed, Compose chỉ chứa server, hướng dẫn K1 và ASR host. Ba test context Docker và một test archive cũng qua; không chạy toàn bộ suite.
- Khởi chạy tiến trình Python thật cho Full, baseline và paired khi PATH không chứa Docker/sudo. MCP knowledge giả lập chủ động từ chối identity tại preflight; cả ba trả lỗi đúng service/code, tạo báo cáo do UID 1000 sở hữu, chưa warm-up/reset/chạy hội thoại. Đây là kiểm tra luồng và xử lý lỗi, không phải kết quả đánh giá chất lượng.
- Preflight chỉ đọc qua ba MCP Docker đang chạy và một MCP knowledge HTTP tạm dùng đúng PostgreSQL/Qdrant đã qua: identity của bốn MCP khớp runner, release khớp database. Không gọi API model/embedding.
- Chưa build/up lại image Docker mới trong phiên này vì không có quyền Docker socket. MCP knowledge ở stack Docker cũ chưa truy cập được tại thời điểm kiểm tra; cần log container để xác định lỗi đó. Kiểm tra server knowledge tạm không thay cho nghiệm thu cả bốn container Docker thật.

### Kiểm tra tích hợp luồng thống nhất ngày 25/11/2026

- Nạp BTC vào PostgreSQL 16.15 cách ly và dựng chỉ mục trên Qdrant 1.19.1. Kiểm tra lại checksum tokenizer, phiên bản policy, hai lần seed, đăng nhập demo và reset runtime. Database chứa 40 sản phẩm, 96 biến thể, 50 khách và 99 đoạn chính sách.
- Chạy bốn MCP, AI, backend và các worker từ mã nguồn. Replay một kịch bản hai phiên qua Full và Baseline. Scorer BTC đọc được hai trace, mỗi trace hai lượt, và báo cáo ghi trạng thái thực thi `healthy`.
- Replay bản trả lời cố ý sai giá đã dừng ở lượt đầu và lưu cả hai mã `price_without_quote` trong báo cáo cặp. Chạy này dùng model và embedding giả lập trên máy, phục vụ kiểm tra tích hợp. Nghiệm thu Docker, chỉ số hội thoại và ASR của bản nộp vẫn cần bằng chứng riêng.
