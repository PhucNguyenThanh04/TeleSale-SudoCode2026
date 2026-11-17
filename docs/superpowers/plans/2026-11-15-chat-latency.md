# Tối ưu đường trả lời chat M1

**Goal:** Loại bỏ công việc lặp/chờ tuần tự không cần thiết, giữ chất lượng và chuẩn đo BTC. Không tuyên bố đạt TTFT ≤3 giây khi chưa có run thật.

**Constraints:** Checkout hiện tại; không sub-agent/worktree; không model/benchmark/live DB/ASR. Giữ guardrail, consent, freshness, ownership, erasure, commit và full/baseline. Không cache kết quả nghiệp vụ hoặc trạng thái khách qua lượt.

**Spec:** Hội thoại đã thống nhất ưu tiên Total trước streaming; BTC `eval/huong-dan-do-latency.md`: chat không streaming TTFT=Total; p95 ≥100 lượt, bỏ 3 warmup, TTFT≤3s/Total≤8s/Brief≤5s.

## Công việc và bằng chứng

- [x] Lưu duration node vào diagnostics đang có; thêm duration từng request LLM và lời gọi tool thực tế. Chỉ metadata số/enum, không prompt/text/PII; không cộng các span lồng nhau làm Total.
- [x] Cache riêng schema Pydantic tĩnh của tool. Mỗi tool coroutine vẫn gắn đúng BusinessTools/state của lượt mới. Test schema tái dùng và hai khách không lẫn gateway/state.
- [x] Chạy song song hai lần đọc projection độc lập trong memory.read, giữ lock/revision/owner/timeout và hủy/join cả hai nếu lỗi. Test barrier chứng minh overlap, lỗi/cancel không để task sống sau release lock.
- [x] Chồng thời gian lấy prompt chỉ đọc với chuẩn bị tool chỉ đọc nếu có thể giữ cleanup/error semantics; test bằng barrier, không dùng mốc thời gian giả để nhận KPI.
- [x] Chạy focused tests cho model/tool contract, memory isolation/erasure/read revisions, diagnostics và eval text lifecycle. Không full suite và không live eval.
- [x] Ghi rõ thay đổi giảm số thao tác/chờ nào, giới hạn chưa đo hardware/API và cách xem diagnostics trong run tiếp theo.

## Quyết định

- Không tái dùng compiled agent có closure chứa BusinessTools của khách trước.
- Không bỏ LLM theo classifier mới hoặc streaming trước guardrail chỉ để giảm TTFT; chưa có bằng chứng đủ để thay hành vi hội thoại.
- Không cache quote/stock/memory; đó là dữ liệu phải kiểm mới.

## Kết quả

232 focused tests qua trong wrapper chặn mạng. Chi tiết và giới hạn: `docs/chat-latency-20261115.md`. Không có số p95 mới; không chạy model/DB/ASR/benchmark.
