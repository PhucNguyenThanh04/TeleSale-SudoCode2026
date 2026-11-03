# Knowledge Gap Loop — thiết kế M1

Trạng thái: phạm vi, nghiệm thu và kế hoạch đã được duyệt; mã đã triển khai và kiểm tra offline. Kích hoạt PostgreSQL/stack thật và số liệu C.5 còn chờ ủy quyền/kiểm chứng.

## 1. Mục tiêu và quyết định đã thống nhất

Xây chức năng tích hợp vào sản phẩm, sử dụng được trên nhiều hội thoại: thu
feedback, quản lý vấn đề, soạn bản sửa có nguồn, duyệt, kiểm thử, phát hành vào
agent và đo tác động. Không giới hạn vào một ca demo.

Các quyết định đã được người dùng duyệt:

- Thu feedback vận hành và nhập kết quả eval; có giao diện xử lý.
- Phân loại nguyên nhân trước khi bổ sung tri thức.
- Bản đầu phát hành hai loại: FAQ có nguồn và cách hỏi bổ sung để tìm đúng
  tài liệu. Lỗi prompt/code/tool được chuyển sang việc kỹ thuật.
- Giữ nguồn nghiệp vụ BTC, scenario và scorer nguyên vẹn.
- Có lịch sử duyệt, phiên bản, khả năng khôi phục, xử lý retry và bảo vệ PII.
- Bàn giao cả chức năng sử dụng thật, bằng chứng hai vòng cải tiến và chế độ
  chạy chấm BTC với phiên bản cố định.

Các lựa chọn chi tiết bên dưới là đề xuất của người thiết kế, cần được review
như một phần của bản thiết kế này.

## 2. Hợp đồng nghiệm thu theo BTC

Nguồn đối chiếu: đề gốc C.5, BTC `README.md` phần chấm chéo,
`DIEU-CHINH-DE.md` mục 2/7/9/10 và `GIAI-DAP-MENTOR.md` phần Team 8.

- Có ít nhất hai nguồn feedback độc lập: đánh giá nhân viên và điểm/assertion
  từ bộ eval. Kết quả nghiệp vụ xác thực là nguồn bổ sung.
- Tự ghi nhận câu chưa trả lời được, bổ sung nội dung có căn cứ sau duyệt,
  tự tạo bản nháp regression test và đưa test đã duyệt vào bộ regression.
- Chạy vòng 0/vòng 1 trên cùng bộ test cố định, có báo cáo tái lập và phân
  tích ca tốt lên/xấu đi; không fine-tune.
- Full/baseline trên bộ BTC cùng tri thức chung, model, tham số và tools;
  chỉ khác việc nạp bộ nhớ phiên trước.
- Không sửa dữ liệu BTC để hợp thức hóa câu trả lời; không đưa nhãn chấm
  hoặc expected output vào đầu vào của agent.
- Script BTC không chấm trực tiếp lifecycle của gap. Bằng chứng C.5 gồm chức
  năng chạy được, lịch sử thao tác và artifact so sánh; không cam kết điểm số.
- Không tự đặt ngưỡng delta C.5 là quy định BTC. Các ngưỡng RQR/TSR/HR của
  đề được báo riêng cùng kết quả thực tế.

## 3. Phạm vi và người sử dụng

Nhân viên nội bộ gửi feedback trên câu trả lời hoặc từ lịch sử cuộc gọi.
Người phụ trách tri thức xem bằng chứng đã che PII, phân loại/gộp/tách vấn
đề, sửa bản nháp, duyệt nội dung và test, phát hành hoặc khôi phục.

Backend hiện có cookie session nội bộ và public visitor session. Bổ sung
quyền `knowledge_review` được cấp phía server cho danh tính nội bộ. Visitor
không được cấp quyền này và không được xem hàng đợi hoặc bằng chứng nội bộ.
Một người có thể vừa gửi vừa duyệt; M1 không bắt buộc quy trình hai người.
Môi trường local có bootstrap reviewer được cấu hình rõ; triển khai ngoài
local cần provision quyền server-side, không nhận role do trình duyệt gửi.

Không xây mới hệ thống tài khoản doanh nghiệp, dashboard tổng quát,
customer simulator hay cơ chế tự sửa code. Không thêm MCP server riêng chỉ
để tăng số server.

## 4. Luồng sử dụng

1. Nhân viên đánh giá một câu trả lời, nhập lý do và tùy chọn bản sửa đề nghị.
   Gửi lại cùng idempotency key không tạo phản ánh trùng.
2. Runtime ghi sự kiện không có bằng chứng, fallback hoặc guardrail rejection;
   importer nhận lỗi/điểm từ artifact eval đã kiểm tra nguồn và coverage.
3. Worker nhận sự kiện, thu gói bằng chứng giới hạn, đề xuất nguyên nhân và
   nhóm vấn đề. Feedback được lưu ngay cả khi model phân tích đang lỗi.
4. Người phụ trách xem các lượt liên quan và nguồn, xác nhận phân loại:
   thiếu nội dung, retrieval, nguồn mâu thuẫn/cũ, generation, technical,
   từ chối đúng hoặc chưa đủ bằng chứng. Có thể gộp/tách bằng thao tác rõ.
5. Với hai loại bản sửa trong phạm vi, worker tạo FAQ/cách hỏi cùng nguồn và
   regression test nháp. Người duyệt sửa hoặc từ chối từng đề xuất.
6. Khi nội dung và test được duyệt, chạy kiểm tra offline. Chạy model/eval
   hoặc reset DB là thao tác riêng cần ủy quyền, không tự khởi chạy.
7. Bản sửa đạt kiểm tra được đóng gói thành release ứng viên, kiểm tra index
   sẵn sàng rồi kích hoạt. Agent sử dụng release trong truy hồi thật.
8. Gap chuyển sang chờ xác minh sau phát hành. Chỉ đóng là đã giải quyết
   khi có kết quả xác minh liên kết; phát hành không đồng nghĩa cải thiện.
9. Có thể khôi phục release trước; giữ toàn bộ quyết định và kết quả xấu đi.

## 5. Thu tín hiệu và bằng chứng

Hai nguồn bắt buộc có provenance riêng: `operator_feedback` và
`evaluation_result`. Tín hiệu runtime và kết quả tool không tự thay thế hai
nguồn đó. Không mua hàng không đồng nghĩa lỗi; tạo đơn không chứng minh
mọi tư vấn đều đúng. Không có feedback không được tính là đánh giá tích cực.

Gói bằng chứng chứa lượt hỏi đã mask, ngữ cảnh tối thiểu, câu trả lời thực
tế, tool/results cần thiết đã lọc, nguồn truy hồi, ngày nghiệp vụ, phiên
bản agent/tri thức, tín hiệu và reference về lượt gốc. Không sao chép nguyên
hồ sơ khách hoặc toàn bộ transcript. Mask theo field path và giữ tên tool,
call id cùng các trường scorer so sánh theo contract hiện có.

Không chỉ đọc top-k rồi kết luận kho thiếu kiến thức. Trước khi duyệt gap
thiếu nội dung, phải có bước kiểm tra nguồn rộng hơn và kết luận của reviewer.
`no_evidence` khác lỗi transport hoặc `degraded_lexical`.

Trên lượt chat, chỉ ghi sự kiện nhỏ qua outbox bền vững; không chờ phân tích
LLM. Outbox cùng transaction với dữ liệu liên quan ở nơi có thể bảo đảm
atomicity; qua ranh giới service phải có acknowledgement/retry và sự kiện
lỗi vận hành, không dùng fire-and-forget trong request.

## 6. Nội dung được phát hành

### FAQ có nguồn

Gồm câu hỏi, câu trả lời, phạm vi áp dụng và danh sách chunk nguồn cùng hash.
Chỉ diễn giải/tổng hợp nguồn công khai hợp lệ; không tạo quyền lợi mới, số
tiền động hoặc chính sách mới. Giá/KM/tồn kho hiện hành vẫn lấy từ tool.

### Cách hỏi bổ sung

Gồm các cách diễn đạt hoặc từ đồng nghĩa và chunk nguồn đích. Chỉ ảnh hưởng
khả năng tìm nguồn; không chèn câu trả lời mẫu theo scenario ID, khách hàng
hoặc nhãn chấm. Giữ phân biệt sản phẩm, mốc thời gian và điều kiện nghiệp vụ.

### Ràng buộc nguồn chung

- Lưu `source_chunk_ids`, hash, `date_basis`, khoảng hiệu lực và phạm vi.
- Các nguồn hỗ trợ một FAQ phải đồng thời hợp lệ; hiệu lực là giao các
  khoảng, không phải hợp. Nguồn có date basis không tương thích phải tách
  FAQ hoặc yêu cầu điều kiện rõ, không tự gộp.
- Dữ kiện theo ngày đơn hàng chỉ dùng khi có ngày đơn từ nguồn đã xác thực.
  Không suy ra ngày đơn từ lời khẳng định chưa kiểm chứng của khách.
- Nguồn đổi hash, mất quyền công khai hoặc bị gỡ làm nội dung phụ thuộc
  ngừng đủ điều kiện phục vụ và được đánh dấu cần review lại.
- Không đổi BTC source; nội dung bổ sung có ID riêng và dẫn nguồn thật.
  Kiểm tra schema/metadata không thay thế duyệt đúng sai ngữ nghĩa.

## 7. Dữ liệu và nơi lưu

Đề xuất schema PostgreSQL `knowledge`, tách `runtime` vì eval reset mọi
bảng mutable trong `runtime`. Migrations đánh số và quyền DB tối thiểu theo
service; không cấp quyền ghi cho MCP catalog khi chỉ cần đọc release.

Các thực thể chính:

| Thực thể | Trách nhiệm |
| --- | --- |
| feedback_events / evidence | Sự kiện bất biến, nguồn, payload đã mask, idempotency key |
| gaps / gap_events | Chủ đề, phân loại, trạng thái và liên kết bằng chứng |
| revisions / decisions | Nội dung/version, nguồn/hash, reviewer, quyết định và lý do |
| regression_cases | Input, kỳ vọng tách biệt, nguồn kỳ vọng, trạng thái duyệt |
| releases / release_items | Manifest bất biến, các revision và index generation |
| jobs / audit_events | Queue bền vững, retry, lease, lỗi và lịch sử thao tác |
| verification_runs | Dataset/config hashes, release IDs và artifact kết quả |

Không đặt FK bắt buộc sang dữ liệu runtime sẽ bị reset. Giữ snapshot bằng
chứng đã mask và reference có thể không còn tồn tại. Cơ chế xóa dữ liệu
khách hiện có phải được mở rộng để xóa/redact bằng chứng, queued payload và
bản nháp chứa dữ liệu liên quan; FAQ phát hành không được chứa dữ liệu cá
nhân. Metadata audit còn lại không chứa raw PII.

Sự kiện nghiệp vụ và decision dùng idempotency key. Duyệt/phát hành dùng
optimistic revision check: nội dung đổi sau duyệt phải duyệt lại. Trạng
thái gap, revision và release độc lập, không ép thành một enum duy nhất.

## 8. Ranh giới dịch vụ và truy hồi

- Backend cung cấp API được xác thực cho UI, kiểm tra quyền và quyền xem
  feedback/cuộc gọi; không tin message ID hoặc actor ID từ client.
- Business rules về gap/revision/release đặt trong service dùng chung bên
  AI/MCP, không nằm trong route hoặc JavaScript. Kênh nội bộ được xác thực.
- Worker dùng service đó để phân tích, tạo bản nháp và retry; không có quyền
  tự duyệt/phát hành. Output model được kiểm tra schema và coi là dữ liệu.
- MCP catalog mở rộng `policy.search` để dùng release đã chọn cùng nguồn
  BTC. Lọc quyền/ngày/nguồn còn hợp lệ trước khi nội dung ra khỏi PostgreSQL.
- FAQ và aliases được đưa vào ranking có giới hạn; deduplicate nguồn và giữ
  giới hạn context. Lỗi supplement quay về nguồn BTC và ghi trạng thái suy
  giảm; không lấy index cũ không khớp hash làm nguồn sự thật.
- Release phát hành theo generation: chuẩn bị manifest/index, kiểm readiness,
  rồi đổi active pointer atomically. Process không giữ active pointer vô hạn.
  Rollback đổi về generation trước còn hợp lệ, không sửa manifest cũ.
- Trace chẩn đoán giữ derived ID và nguồn. Với RAG BTC, alias trả chunk ID
  BTC thực sự được truy hồi; FAQ có ID riêng không giả thành BTC chunk.
  Điểm corpus BTC và hiệu quả nội dung bổ sung được báo riêng.

## 9. Giao diện và API contract ở mức hành vi

Trong giao diện hiện tại thêm feedback trên câu trả lời và mục Knowledge
Gaps dành cho nội bộ. Mục này có danh sách/lọc trạng thái và nguồn feedback,
chi tiết bằng chứng, gộp/tách, editor FAQ/aliases, nguồn và hiệu lực, duyệt
test, quyết định duyệt/từ chối, release và kết quả xác minh.

API phải bao phủ các thao tác này, có phân trang, kiểm tra quyền server-side,
idempotency khi ghi và conflict response nếu revision cũ. Không trả raw PII
qua API, không cho public visitor xem danh sách toàn cục. Lỗi AI phân tích,
nguồn stale, kiểm tra thất bại và index chưa sẵn sàng hiển thị rõ; không hiện
thành công khi job mới chỉ được xếp hàng.

## 10. Kiểm chứng và chế độ BTC

- Vòng 0 và vòng 1 dùng cùng test/config/model, ghi code digest, seed data,
  release và source hashes. Bộ regression phát sinh có version riêng.
- Test sinh tự động là bản nháp; reviewer kiểm input, expected output và
  assertion. Expected output không đưa vào model input. Test có biến thể
  cách hỏi, ngày/điều kiện và hành vi từ chối khi thích hợp.
- Runtime nhận phiên bản tri thức từ cấu hình/run context tin cậy, không từ
  lời khách. Mỗi run và toàn bộ cặp full/baseline pin cùng release.
- Cả hai cấu hình dùng cùng nguồn chung và supplement; baseline không đọc
  memory khách từ phiên trước. Supplement không chứa customer memory.
- Feedback có thể ghi trong run nhưng không được thay phiên bản run đang
  dùng. Artifact thiếu/mismatch hoặc run gián đoạn không có điểm hợp lệ.
- Tái sử dụng scorer BTC cho chỉ số có contract; báo cáo thêm số gap phát
  hiện, đã duyệt/phát hành/xác minh như bằng chứng lifecycle, không coi đó
  là điểm BTC. Số liệu bổ sung phải có công thức/mẫu số và nguồn.
- Không bảo đảm có cải thiện trước khi đo; nếu không cải thiện phải báo thật
  và tiếp tục điều tra. Hoàn thành code không tự đồng nghĩa đạt C.5.

## 11. Kiểm thử và bằng chứng bàn giao

Focused tests theo phần thay đổi, full suite tối đa một lần trước báo hoàn
thành theo quy định repository. Không tự chạy eval live, ASR benchmark,
reset DB, cài dependency hoặc deploy. Việc đó cần ủy quyền riêng.

Các nhóm bắt buộc: hai nguồn feedback; ownership/reviewer/visitor; mask PII;
retry/idempotency; phân biệt refusal/tool failure với content gap; gộp/tách;
nguồn/hash/ngày/quyền; stale approval; test nháp và không rò nhãn; publish
atomicity/index failure; rollback; full/baseline cùng release; reset runtime
không mất knowledge; erasure; trace giữ tên tool và contract scorer.

Bàn giao migrations, hướng dẫn provision/quyền, lệnh worker, hướng dẫn UI,
export evidence và runbook hai vòng cùng runbook chấm BTC. Artifact gồm
manifest nguồn/test/config, feedback provenance, các quyết định, revision,
release, regression và báo cáo trước/sau không có raw customer PII.

## 12. Điểm review trước kế hoạch triển khai

1. Dùng một quyền reviewer nội bộ; không bắt buộc hai người duyệt độc lập.
2. Supplement ở schema riêng, hai loại FAQ/aliases, không sửa BTC source.
3. Nội dung thiếu nguồn dừng ở trạng thái chờ; lỗi code/tool chuyển việc kỹ thuật.
4. Quyền phát hành thuộc reviewer sau kiểm tra; worker không tự phát hành.
5. Pin release cho run; live eval và reset là thao tác được ủy quyền riêng.
6. Bằng chứng PII và queued jobs thuộc phạm vi xóa dữ liệu, không chỉ runtime memory.
