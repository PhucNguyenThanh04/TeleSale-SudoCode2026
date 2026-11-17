# Tối ưu đường trả lời chat M1 — 15/11/2026

Phạm vi: giảm thao tác lặp/chờ tuần tự trong đường trả lời hiện có. Không đổi model, tham số, prompt content, guardrail, consent, baseline, chuẩn đo BTC hoặc chuyển sang streaming.

## Thay đổi

| Vị trí | Trước | Sau |
|---|---|---|
| BusinessTools | Tạo lại các lớp schema Pydantic mỗi lần dựng tool cho lượt mới | Schema tĩnh tạo một lần khi nạp module; coroutine/gateway/state của tool vẫn riêng mỗi lượt. Không cache dữ liệu khách, quote, stock hoặc compiled agent. |
| Memory read | Đọc fact versions xong mới đọc episode versions, mỗi hàm dùng kết nối riêng | Hai lần đọc độc lập chạy đồng thời trong TaskGroup, vẫn bên trong khóa khách và timeout 2 giây. Nếu lỗi/cancel, join/cancel cả hai trước khi transaction nhả khóa. Các bước lọc revision hoàn tất, tombstone và ownership giữ nguyên. |
| Chuẩn bị lượt | Đợi chuẩn bị tool xong mới lấy prompt chỉ đọc | Hai bước chạy đồng thời. Không bắt đầu model trước khi cả hai xong; lỗi đơn vẫn giữ exception gốc để diagnostics nhận diện. |
| Diagnostics | Duration node chỉ có trong log; chưa lưu duration LLM/tool vào sidecar | Lưu duration node, từng lời gọi LLM và từng lời gọi tool thực vào `.events.json` hiện có, chỉ số/enum/tên tool hợp lệ. Không thêm dashboard hoặc đổi metrics BTC. |

Hai lần đọc projection có thể dùng hai kết nối đồng thời, thay vì mở lần lượt. Chưa kiểm tải DB thật. Prompt fetch chạy trong thread như trước; khi coroutine bị cancel, request chỉ đọc trong thread có thể hoàn tất sau đó theo timeout có sẵn. Không chuyển state của khách vào prompt cache.

## Bằng chứng offline

**232 focused tests qua**, trong wrapper `eval_harness/offline_tests.py` chặn mạng và loại credentials/`.env`; có một warning deprecation thư viện. Không chạy full suite, benchmark hoặc model/DB/ASR thật.

Test mới ở [test_chat_latency.py](../ai-services/test/test_chat_latency.py) kiểm:

- Schema được dùng lại nhưng hai lượt/gateway không chia sẻ lời gọi hoặc state.
- Barrier xác nhận hai projection read bắt đầu trước khi bên kia hoàn tất; lỗi và caller cancellation đều kết thúc task trước khi nhả transaction.
- Barrier xác nhận prompt read không còn phải đợi tool preparation; lỗi chuẩn bị không gọi model và giữ loại exception gốc.
- Thời gian LLM được ghi cả khi request lỗi; duration tool tách riêng.
- Sidecar ghi/đọc lại được timing, từ chối metadata sai kiểu và không chứa payload/PII.

Kiểm hồi quy gồm memory ownership/erasure/projection/retrieval/freshness, model/tool contract, tool budget, prompt fallback, consent/commerce, price grounding, session state, text lifecycle và eval diagnostics. Hai fixture chẩn đoán cũ thiếu `request.on` đã được bổ sung để thực sự tới nhánh model cần kiểm.

## Đọc bằng chứng ở lần chạy thật tiếp theo

Runner đã có `full.diagnostics_full.events.json` và file tương ứng baseline. Trong từng record, đọc `runtime_events`:

- `event=completed`, `step=retrieve_context/run_agent/verify/persist/accept`: thời gian node.
- `event=model_timing`, `step=run_agent`: thời gian mỗi request LLM qua middleware, gồm request lỗi/cancel.
- `event=tool_timing`, `step=call_tool`, `tool=<tên tool>`: thời gian lời gọi nghiệp vụ thực tế; cache hit không bị ghi như network call mới.

Các node chứa span con; các tác vụ song song chồng thời gian nhau. **Không cộng các duration này để thay Total.** Dùng `latency.ttft_ms/total_ms` của runner để chấm BTC như trước.

Đo lại cùng model/phần cứng, đủ ≥100 lượt mỗi cấu hình sau 3 warmup. Chat hiện không streaming nên TTFT=Total theo quy tắc 7 BTC; mục tiêu TTFT p95≤3 giây, Total p95≤8 giây, Call Brief≤5 giây.

## Chưa được kết luận

- Chưa có p95 mới hoặc số millisecond tiết kiệm trên model/DB thật; không suy tỷ lệ giảm 26% từ test giả lập.
- Không gọi kết quả này là đã đạt ngưỡng BTC. Mốc lịch sử 4.068 ms vẫn chỉ là phép đo code cũ.
- Nếu lần đo sau vẫn chậm ở LLM, dùng timing mới để quyết định tối ưu tiếp hoặc thiết kế streaming sau guardrail; không gửi draft chưa kiểm ra khách.
