# Sửa lỗi từ paired run 20261117T050609Z-2042b75f

Phạm vi: các lỗi giỏ hàng, thiếu thông số TDS, extraction/review và các vòng gọi model đã phân tích trong trace. Làm trực tiếp trong checkout hiện tại; không thay BTC scorer, ngưỡng nghiệm thu, dữ liệu kịch bản hoặc số liệu lịch sử.

## Runtime

- Nhận diện cả `Pigeon PPSU 240ml` lẫn `Fatz 4` để tra đủ catalog, tồn kho và quote giỏ trước khi khách xác nhận. Hai sản phẩm không bị chuyển thành hai chiếc Fatz.
- Khi khách tham chiếu tổng giỏ, verifier đối chiếu các SKU trong quote giỏ, thay vì tự giới hạn vào focus một SKU. Giá sai, sản phẩm ngoài giỏ và câu hỏi chỉ về một sản phẩm vẫn bị từ chối.
- Chỉ định dạng dấu phân cách hàng nghìn trên số tiền; giữ dấu phẩy phân cách tên hai món trong câu báo tổng.
- Nhận diện TDS. Thiếu `tds_output_ppm` thì nói rõ “chưa có thông tin xác minh”; số ppm không khớp nguồn bị guardrail từ chối.
- Giữ riêng câu hỏi giá (“bao nhiêu tiền”) và câu hỏi đại lượng (“TDS bao nhiêu ppm”). Mẫu hết hàng vẫn có thể được báo giá theo tool khi khách hỏi.
- Chạy continuation sẵn có trước inference nếu consent, lựa chọn, quote và tồn kho đã đủ. Trả lời câu hỏi thông số/tồn kho từ dữ liệu đã chuẩn bị khi câu trả lời đầy đủ và qua verifier; blocked purchase vẫn tiếp tục luồng xử lý riêng.
- Tra tên model mới bằng chuỗi tên/SKU cụ thể; một thương hiệu chung với sản phẩm cũ không đủ để bỏ qua lookup. Regression giỏ đổi sản phẩm kiểm rằng đơn chỉ được tạo sau khi giá mới được nói và khách xác nhận.

## Extraction và review

- Mảnh câu chủ đề như “Khi cần bảo hành” không còn là claim chưa phân giải. Hỏi đã trao đổi với người nhà và quyết định chọn mẫu đã biết được phân loại là theo dõi blocker.
- Giữ nguyên qualifier và các loại không biểu diễn được bằng schema BTC phẳng. Không đồng nhất miễn phí COD với miễn phí vận chuyển hoặc biến stock của một size thành stock chung.
- Thêm `eval_harness.extraction_review` để tạo template pending và kiểm review có tác giả, nhận xét, quyết định và tham chiếu evidence. Evidence bị ràng buộc bằng hash tới đúng trace/candidate, cùng cấu hình/kịch bản và không nằm sau lượt được review. Lời agent tự nói không được dùng làm nguồn chứng minh chính nó.
- `m1_acceptance --extraction-review FILE` chỉ chấp nhận review đầy đủ, hợp lệ. Pending, contradicted hoặc unverifiable không qua; review không thay các mẫu số/điểm BTC và không làm các gate latency hay độ phủ tự qua.
- Review của trợ lý được ghi rõ là assistant, không được trình bày thành kiểm tay độc lập của BTC. Hash chỉ xác nhận nguồn được trích, không chứng minh phán đoán ngữ nghĩa của người review.

## Replay được bảo toàn

Replay offline: `ai-services/eval_harness/results/measurement-audit/20261117-m1-acceptance-repairs/replay_manifest.json`.

Replay đã kiểm lại scorer/provenance gốc, giữ nguyên speech/tool/memory/latency và hash toàn bộ source run. RQR Full đổi từ 1/27 thành 0/27 do sửa phân loại câu hỏi; đây chỉ là delta annotation trên lời thoại cũ, không phải kết quả runtime mới. Còn 136 candidate cần phán định trong template bên ngoài thư mục replay đã niêm phong:

`ai-services/eval_harness/results/measurement-audit/20261117-m1-acceptance-repairs-review.pending.json`.

Đã lưu đối chiếu nguồn của trợ lý tại `20261117-m1-acceptance-repairs-review.assistant.json` cùng thư mục cha: 71 candidate có nội dung/giá trị được hỗ trợ trực tiếp bởi nguồn, 7 mảnh câu không phải phát biểu độc lập, 58 trường hợp chưa kết luận. Đây không có nghĩa 58 phát biểu sai. File summary xác nhận `complete: false`; chưa gán phần chưa xác minh thành đúng. Trace cũ vẫn giữ nguyên hai ca TSR fail và latency cũ. Các cải thiện runtime chỉ được chứng minh bằng test offline cho tới khi có run thật mới.

## Bước đo thật cần được cho phép

Theo yêu cầu của người dùng trong AGENTS.md, không tự chạy live evaluation/benchmark có chi phí. Lệnh đề nghị cho **một cặp Full/baseline**, dùng lại 29 kịch bản và BTC snapshot của run đã phân tích:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
ai-services/.venv/bin/python run_system.py eval --expected-database telesale -- \
  --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/results/paired-knowledge/20261117T050609Z-2042b75f/scenarios \
  --btc-root ai-services/eval_harness/results/paired-knowledge/20261117T050609Z-2042b75f/btc-release \
  --out-root ai-services/eval_harness/results/paired-knowledge
```

Runner thực hiện 170 lượt mỗi cấu hình cùng warmup, gọi model và reset dữ liệu runtime của DB eval trước mỗi cấu hình theo cơ chế hiện có; giữ knowledge và nguồn BTC. Cần chạy riêng trên DB eval, không đồng thời chat/eval khác. Chưa chạy lệnh này trong lượt sửa offline.

Sau run mới: kiểm execution, đọc lại TDS/giỏ hàng, review candidate theo chính lời mới, rồi kiểm p95 của cả hai cấu hình với ngưỡng 3000 ms. M1 toàn bộ còn cần bằng chứng ASR, hai vòng cải tiến được review, demo và chi phí; không suy từ test offline rằng các phần này đã đạt.

## Quyết định và giới hạn

- Thực thi và tự review inline theo yêu cầu không dùng subagent/worktree. Không commit vì checkout có nhiều thay đổi có sẵn của người dùng.
- Không thay model hoặc streaming, không thêm dashboard/benchmark. Chưa chứng minh p95 mới bằng phép đo model thật.
- **540 focused tests passed trong 20,14 giây**, qua `eval_harness/offline_tests.py` (chặn kết nối mạng, không nạp credentials/`.env`). Không chạy full suite. Các nhóm gồm regression mới, basket/consent/price grounding, consultation, pending memory/presented offers, execution/latency diagnostics, extraction/review/replay và M1 acceptance.
- Log được lưu ở `ai-services/eval_harness/results/measurement-audit/20261117-m1-acceptance-repairs-tests.txt`; `git diff --check` qua cho các file tracked thuộc phạm vi sửa. Hash output replay và tất cả file source run đã được đối chiếu lại, khớp manifest.

## Tiếp tục rà extraction trong lúc chờ live eval

- Sửa sáu câu hỏi còn bất định trong trace: phân biệt lời mời liên hệ khi kết thúc với câu hỏi thực, giữ slot sản phẩm khi có “quan tâm đến mẫu”, nhận diện xác nhận tạo đơn, và giữ câu hỏi làm rõ/tiếp tục chung ở `other` thay vì đoán thành profile fact.
- Replay mới tại `results/measurement-audit/20261117-m1-acceptance-repairs-v2/` giữ nguyên bản trước và source run. Hai cấu hình không còn emitted question có uncertainty trong bộ lời đã lưu. Đây vẫn là annotation replay, không phải inference mới.
- Review nguồn đầy đủ hơn tại `results/measurement-audit/20261117-m1-acceptance-repairs-v2-review.assistant.json`: **130 candidate, 106 supported, 9 mảnh câu/abstain, 15 chưa kết luận**. Các câu diễn đạt lại chính sách được đối chiếu cụ thể với DT-01/DT-03/BH-02/BH-03/BH-04/VC-07; không chỉ dựa vào việc có tool call. Summary vẫn `complete: false`.
- Trong phần chưa kết luận có suy diễn vị trí hàng từ trạng thái đơn. Thêm guardrail cho các câu “chưa bàn giao/chưa xuất kho/vẫn ở kho” khi nguồn chỉ là `order.status`; recovery báo trạng thái được xác minh thay vì suy ra vị trí vật lý. Các phát biểu này trong trace lịch sử vẫn được giữ chưa xác minh.
- **261 focused tests passed trong 8,26 giây** sau các sửa tiếp này; trước đó nhóm parser/review/replay đạt 113/113. Đây là những batch chồng phạm vi với 540 test trước, không cộng thành một tổng test độc lập mới. Không lặp full suite hoặc gọi model.
- Lệnh live eval và yêu cầu cho phép ở trên vẫn chưa được thực thi. Goal chưa đạt; cần fresh run và review lời mới để chứng minh latency/chất lượng thực tế.
