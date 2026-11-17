# Phân tích và sửa run streaming 20261117T092200Z-17b3f18d

Run do người dùng chạy: pipeline validated, artifact integrity pass, execution degraded. Full TSR 29/29, RQR 1/22, HR giá/KM 0/39; TTFT p95 Full/Baseline 3807/3207 ms, Total p95 3874/3472 ms. Ba gate fail: execution health, extraction review, TTFT. TSR cuối kịch bản không chứng minh tất cả câu hỏi ở các lượt trước đều được trả lời đầy đủ.

## Nguyên nhân từ trace

- Cả hai nhánh lỗi duy nhất SC-T11/call_1/turn2: khách yêu cầu mã vận đơn, đơn vị giao hàng và quy định giao lại. Parser chưa nhận ra phần quy định giao lại. Stream phát phần tracking trước khi câu hỏi được trả lời đủ, sau đó khóa tool. Model cố gọi policy tool lặp lại và chạm GraphRecursionError: 12 request model, Total 9459/9600 ms.
- Full có 154/170 lượt chỉ một delta; Baseline 158/170. Mỗi nhánh có 11 lượt TTFT >3000 ms. Phần chậm gồm nhiều vòng đọc model/tool, phản đối giá có dữ liệu sẵn nhưng vẫn chờ model diễn đạt, câu tồn kho/size chưa được chuẩn bị, và câu báo tình trạng tem mác bị hiểu nhầm thành hỏi chính sách.
- Knowledge detection yêu cầu validated **healthy** pair nên dừng trước khi tạo thư mục/checkpoint. Vì vậy `.knowledge/experiment.json` được console gợi ý thực tế không tồn tại trong lần này. Giữ nguyên điều kiện healthy, không bật detection bằng cách bỏ kiểm tra lỗi thực thi.

## Sửa sau phép đo

- Nhận câu hỏi quy định giao lại và yêu cầu trả lời cả tracking/policy trước khi coi là đủ. Mệnh đề “nếu shipper gọi…” không xóa yêu cầu tra tracking ở phía trước.
- Ghép trạng thái/mã vận đơn đã xác minh với toàn bộ quy định giao lại. Không suy tên hãng vận chuyển chỉ từ prefix tracking; khi tool thiếu trường carrier thì nói rõ chưa xác minh được đơn vị giao hàng.
- Hỗ trợ `date` của đơn nguồn BTC trong hai nơi lấy ngày tạo đơn, vẫn chỉ lấy từ kết quả `order.status` đã xác minh, không nhận ngày/order ID do model tự cấp để xác nhận quyền lợi.
- Khi đã phát câu trả lời độc lập, đủ yêu cầu và đã kiểm tra, kết thúc business phase nếu model tiếp tục yêu cầu tool; không đưa lỗi tool bị khóa ngược vào một vòng model lặp. Các lỗi model thật vẫn được ghi nhận; không đổi định nghĩa execution health hoặc bắt GraphRecursionError để gán healthy.
- Giữ các câu xác nhận thao tác ngắn như “Ok em làm đi” trong buffer để không phát một lời xác nhận chung rồi chặn giao dịch cần thực hiện.
- Trả lời phản đối giá trực tiếp từ quote/quyền lợi tương thích qua verifier khi đã đủ dữ liệu. Nhận câu hỏi “còn size 39…” và tên giày khách nói để chuẩn bị đúng variant; không tạo đơn hoặc cấp consent từ catalog.
- Báo hàng còn tem mác trước câu hỏi tồn kho không tự trở thành yêu cầu tra chính sách. Khách có thể từ chối tra quy định giao lại.

## Bằng chứng

- Tám regression mới trong `ai-services/test/test_streaming_live_regressions.py` được quan sát RED rồi GREEN, gồm graph thật với inference/storage giả lập. Test vòng tool sau đáp án xác nhận chỉ một request model và không có execution failure; test shipping kiểm đủ tracking, quy định 3 lần giao/đặt lại và không bịa carrier.
- **274 focused tests passed trong 8.72 s**, [log](../ai-services/eval_harness/results/measurement-audit/20261117-streaming-live-repairs-tests.txt). Phạm vi gồm streaming, followup/policy, nguồn thương mại, variant/consent, voice persistence, model contract, execution diagnostics và hợp đồng đo TTFT. Không chạy full suite.
- [Phân tích artifact](../ai-services/eval_harness/results/measurement-audit/20261117-streaming-live-repair-analysis.json) chứa metrics gốc, lỗi theo lượt, số delta, danh sách lượt >3 giây và source digest sau sửa. Trace, score và manifest của run gốc không bị sửa.
- `git diff --check` đạt. Chỉ self-review inline, không dùng subagent theo quy định người dùng.

**Chưa có live eval sau các sửa trên.** Những số 3807/3207 ms vẫn là số đo của phiên bản trước sửa, không phải bằng chứng latency của checkout mới. Không đổi model, tool budget, BTC scorer/threshold hoặc đặt lại timestamp để biến kết quả thành pass. Chạy lại lệnh `run_system.py eval ...` (streaming hiện là mặc định; bỏ các cờ cũ `--streaming`, `--delivery-mode`, `--agent`) để đo và đối chiếu actual health, TTFT/Total và chất lượng; extraction review và bằng chứng M1 khác vẫn cần hoàn thiện riêng.
