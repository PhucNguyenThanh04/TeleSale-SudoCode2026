# Tool-Call Accuracy và kiểm chứng rollback offline

## Phạm vi đã được giao

Người dùng yêu cầu tự thực hiện spec → plan → executor cho hai hạng mục đã
thảo luận: Tool-Call Accuracy (TCA) và kịch bản kiểm chứng rollback. Không làm
Exemplar Bank, ASR/dataset, sửa agent, thay scorer BTC hoặc chạy live model/DB.
Làm tại checkout hiện tại, không worktree/subagent; giữ các thay đổi có sẵn.

## 1. Tool-Call Accuracy

Một CLI offline đọc trace JSONL BTC và file nhãn JSON độc lập. Mỗi case là một
lượt `(scenario_id, call, turn)`, ràng buộc SHA256 của `user_text`. Nhãn khai báo
danh sách `scored_tools` và toàn bộ `expected_calls` trong phạm vi đó. Các tool
ngoài phạm vi được đếm là không chấm, không mặc định đúng. `expected_calls=[]`
nghĩa là không được gọi tool thuộc phạm vi tại lượt đó.

`tool_call_accuracy = số lượt khớp hoàn toàn / tổng lượt có nhãn × 100`.
Khớp hoàn toàn: mỗi expected call ghép được với một actual call cùng tên và
`args_match` là tập con đệ quy của args; mỗi actual call chỉ dùng một lần, và
không còn actual call thuộc phạm vi chưa ghép. Tool thiếu, sai tham số, thừa,
hoặc gọi trùng đều làm lượt fail. Thứ tự tool không được chấm; list trong args
so khớp theo thứ tự. Trạng thái trả về của tool không quyết định TCA: đây là đo
lựa chọn tool/tham số, không phải tỷ lệ execution thành công hoặc TSR.

Report có tử/mẫu, matched/missing/unexpected call counts, kết quả từng case,
coverage lượt có/không nhãn, tool ngoài phạm vi, số expectation chỉ kiểm tên,
hash trace/nhãn và mô tả công thức/giới hạn. Không đưa câu nói, args/result hay
PII vào report; dùng locator và index để tra ngược input. Mỗi trace chỉ một
config/run nếu có các trường đó. Nhãn hoặc trace thiếu/sai/duplicate locator,
hash câu hỏi lệch, tool_calls sai cấu trúc phải bị từ chối, không âm thầm bỏ.
CLI tạo thư mục output mới với JSON và Markdown; không ghi đè.

File nhãn mẫu dùng tình huống synthetic: kiểm tồn đúng biến thể, đổi size đúng
action, và không tạo đơn khi chỉ hỏi. Đây là ví dụ contract, không tự nhận người
đã duyệt nhãn hoặc số liệu model. Nhãn thật phải được xác định từ yêu cầu/ngữ
cảnh hợp lệ trước khi nhìn kết quả mong muốn; không sinh từ tool agent đã gọi.

## 2. Rollback rehearsal

CLI standalone nhận `--btc-root`, `--out`. Dùng policy BTC thật, lifecycle
create/approve/build/activate/rollback thật, hybrid Qdrant trong RAM, PolicyEncoder
với dense backend xác định giả lập, PolicyRepository đọc snapshot trong RAM và
MCP `policy.search` thật (signed trusted context qua in-process MCP client).
Không import code test. Không đọc credentials/.env hoặc mở kết nối mạng/DB.

Kịch bản cố định:

1. Build/activate K0 (BTC-only), search và lưu release/evidence.
2. Tạo FAQ DT-02 có nguồn; build trước duyệt phải bị chặn.
3. Duyệt mô phỏng bằng actor offline; build K1. K1 chưa active không xuất hiện.
4. Activate K1: search phải thấy FAQ mới và nguồn gốc; pin K0 vẫn không thấy FAQ.
5. Rollback sai expected-active và actor không có quyền phải bị chặn, active
   không đổi và không sinh audit rollback thành công.
6. Rollback đúng K0 từ K1: search không pin trở về K0, FAQ biến mất, audit ghi
   đúng actor/previous/target. Pin K1 vẫn truy cập snapshot bất biến: rollback
   đổi release mặc định, không thu hồi release đã pin.
7. Corpus nguồn không đổi; gap không tự chuyển resolved.

Report JSON/Markdown chứa checks, source/config hashes, revision, review/test,
manifest references, search observations và audit. Ghi rõ
`offline_rehearsal`, `simulated_not_human`, dense giả lập/storage RAM;
không có số cải thiện LLM, latency sản phẩm, rollout production hoặc người duyệt
thật. Bất cứ check nào không đạt làm CLI fail, không xuất báo cáo passed.

## Bàn giao và nghiệm thu

- Spec, plan và biên bản execution/verification.
- Hai CLI, nhãn/trace mẫu synthetic, hướng dẫn công thức và lệnh offline.
- Test tập trung: TCA thiếu/thừa/sai/duplicate/nested args/matching/coverage;
  rollback thực đi qua MCP, quyền/CAS/audit/pinning và không mạng.
- Chạy CLI thực offline, kiểm artifact được tạo, kiểm không ghi đè và không đổi
  source BTC. Không full suite, không thêm dependency, không commit thay người dùng.
