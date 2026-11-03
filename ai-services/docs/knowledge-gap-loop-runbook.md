# Knowledge Gap Loop — vận hành và bằng chứng BTC

## Trạng thái và giới hạn kiểm chứng

Chức năng gồm feedback trên hội thoại/lịch sử, outbox giao nhận, worker phân
loại/đề xuất nhóm và bản nháp, reviewer chỉnh/duyệt nội dung cùng test, release
FAQ/aliases, truy hồi qua MCP, rollback, xóa dữ liệu và báo cáo hai vòng.
Worker mặc định dùng phân tích lexical và tạo bản nháp extractive, không gọi
LLM. Phán đoán ngữ nghĩa cuối cùng thuộc reviewer; một nguồn có hash đúng
không tự chứng minh bản diễn giải đúng. Thiết kế cho M1 một phiên demo; các
mutation knowledge được serialize bằng advisory lock, không phải thiết kế
throughput lớn.

Kiểm tra offline dùng repository transactional giả lập, MCP in-process và
Chrome với API giả lập. Không được coi chúng là bằng chứng migration/grants
hoặc toàn bộ stack PostgreSQL/MCP/model đã vận hành. Chỉ ghi C.5 đã đạt khi
có hai vòng đánh giá thật hoàn chỉnh và cải tiến được chứng minh.

## 1. Chuẩn bị hạ tầng — cần được cho phép trước khi thực hiện

Không chạy migration hoặc reset vào DB chưa xác nhận danh tính. Migration
mới là `ai-services/migrations/0002_knowledge_gap_loop.sql`, áp dụng sau schema
runtime và memory hiện có. Migration chỉ tạo schema/tables/role groups;
không sửa `btc_source`, không truncate dữ liệu. Chạy với tài khoản quản trị
trên DB đã thống nhất rồi rerun `scripts/provision_mcp_roles.sh` bằng cách
triển khai secrets hiện có, không đưa password vào command line hay log.

Provision các login qua kênh quản trị hiện có; không dùng chung login worker
và reviewer. Ví dụ các GRANT dưới đây dùng tên login do người vận hành thay:

```sql
GRANT knowledge_reviewer TO "<ai_knowledge_api_login>";
GRANT knowledge_worker TO "<analysis_worker_login>";
GRANT knowledge_backend TO "<backend_login>";
```

`knowledge_reviewer` có quyền lifecycle; `knowledge_worker` không có quyền
INSERT/UPDATE vào decisions, releases, active hoặc permissions. Backend cần quyền outbox và đọc tombstone erasure ngoài quyền chat hiện có; các process phải trỏ cùng database. MCP catalog chỉ đọc release;
MCP memory có quyền ghi event và xóa evidence theo yêu cầu đã xác minh.

Cấu hình trong `ai-services/.env` hoặc environment, không commit credentials:

```text
KNOWLEDGE_ENABLED=true
KNOWLEDGE_DATABASE_URL=<SQLAlchemy asyncpg DSN, login thuộc knowledge_reviewer>
KNOWLEDGE_WORKER_DATABASE_URL=<SQLAlchemy asyncpg DSN, login thuộc knowledge_worker>
KNOWLEDGE_ADMIN_DATABASE_URL=<DSN quản trị, chỉ cần khi cấp/thu hồi quyền>
```

KNOWLEDGE_ENABLED cần cùng giá trị ở AI API, catalog và memory process. API
quản trị chỉ hoạt động khi có KNOWLEDGE_DATABASE_URL. Backend dispatcher dùng
cấu hình DB và AI_INTERNAL_TOKEN của backend; không gửi token về trình duyệt.

## 2. Quyền reviewer

Mở UI nội bộ `/app/`, mở Cải tiến tri thức; màn hình hiển thị actor ID từ
cookie server. Đối với actor chưa có quyền, API danh sách trả 403. Cấp quyền
bằng CLI quản trị (không qua browser):

```bash
# Chạy ở ai-services, lấy đúng actor ID đang sử dụng.
.venv/bin/python -m app.knowledge.cli grant --actor '<internal-actor-id>'
.venv/bin/python -m app.knowledge.cli revoke --actor '<internal-actor-id>'
```

Đây là quyền ứng dụng bên cạnh quyền DB; không trao login DB cho nhân viên.
Actor `web-visitor:*` bị từ chối kể cả khi bị ghi nhầm vào bảng permission.
Local cookie hết hạn có thể tạo actor mới và cần provision lại; không giả
định một local actor là danh tính nhân viên lâu dài.

## 3. Chạy các process

Ngoài API, backend, MCP và LangMem worker hiện có, chạy thêm:

```bash
# ai-services, phân tích/gom vấn đề và tạo bản nháp, không gọi model mặc định.
.venv/bin/python -m app.knowledge.worker
# backend, giao outbox đã mask tới AI và chỉ đánh dấu delivered sau ACK.
../ai-services/.venv/bin/python -m app.services.knowledge_service
```

Backend feedback kiểm ownership session + turn, không dùng câu trả lời hoặc
actor do client tự khai. Outbox cùng transaction với feedback. AI ghi event
và analysis job cùng transaction. Retry cùng key không tạo dữ liệu trùng;
cùng key khác payload trả conflict. Dispatcher dùng lease 30 giây, thả row lock trước HTTP và kiểm lease/status khi ACK để không tái tạo outbox đã xóa. Dispatcher thử tối đa 5 lần, sau đó hiện
failed trong mục Đồng bộ feedback; reviewer có thể gửi lại. Worker có lease
300 giây, backoff 5/30/120/600 giây rồi failed; có thao tác thử lại trên UI.

Nếu thiếu quyền/schema khi KNOWLEDGE_ENABLED=true, lỗi enqueue nằm trong
transaction commit turn nên request không được giả báo đã ghi thành công.
Không bật flag trước khi provision. Triển khai nhiều process cần restart sau
thay đổi settings; active release không được cache vô hạn.

## 4. Sử dụng toàn bộ luồng

1. Từ một hoặc nhiều hội thoại, gửi feedback kèm lý do; có thể gửi từ lịch
   sử cuộc gọi. Đánh giá tích cực được giữ như evidence, không tự tạo gap.
2. Worker xử lý tín hiệu runtime và feedback tiêu cực. Không mặc định lỗi
   tool hoặc chuyển máy là thiếu kiến thức. Kết quả nghiệp vụ đơn lẻ không
   được coi là chất lượng câu trả lời.
3. Reviewer xem bằng chứng, nguồn công khai (kể cả bản cũ để so sánh), đề
   xuất nhóm; phân loại/gộp/tách. Không có nguồn phù hợp thì chờ nguồn.
4. Chọn FAQ hoặc aliases. Chọn chunk nguồn thật, kiểm điều kiện/ngày và nhập
   ghi chú rà nguồn. Nội dung theo order_date chỉ phục vụ khi có ngày đơn đã
   được xác thực ở luồng tool hiện có; không tự lấy lời khách làm bằng chứng.
5. Xem input/expected output và các variation của test. Sửa test hoặc nội
   dung tạo bản nháp mới; phải duyệt lại. Cần xác nhận rõ đã review test và
   nhập lý do khi approve. Không lấy câu trả lời sai làm ground truth.
6. Gom các revision đã duyệt vào danh sách đầy đủ cho release mới. Prepare
   chạy source/hash/approval/test-hash checks và lexical regression trên
   corpus công khai. Kết quả ghi trong manifest; không phải LLM evaluation.
7. Activate CAS theo active ID. Release lexical là một generation sẵn sàng
   trong PostgreSQL; không cần tải model hay build dense index mới. Source
   vẫn lấy từ PostgreSQL, aliases có thể tham gia lexical của hybrid rank.
8. Chat bình thường pin release đầu lượt; FAQ có ID KG riêng và dẫn nguồn,
   alias truy hồi chunk BTC thật. Không sửa ID scorer để tăng Recall@k.
9. Muốn quay lui, chọn release còn hợp lệ hoặc Khôi phục chỉ nguồn BTC.
   Nguồn đã đổi hash/quyền bị loại, rollback không được phục hồi source sai.
10. Gap sau publish là awaiting_verification. Sau khi có báo cáo hai vòng
    đã đăng ký, reviewer nhập mã báo cáo và lý do dựa trên case/trace liên
    quan để xác nhận resolved. Không tự đóng vì đã publish hoặc TSR tăng.

## 5. Nhập lỗi từ eval đã hoàn chỉnh (offline)

```bash
.venv/bin/python -m eval_harness.knowledge_feedback --run eval_harness/results/<validated-run>
```

Importer kiểm run status, cặp manifests, hash trace/report/scorer, schema và
coverage dựa trên scenario/BTC source gốc. Di chuyển artifact cần giữ hoặc
cập nhật đường dẫn nguồn một cách có kiểm soát; không bỏ audit khi thiếu
nguồn. Import nhiều lần không tạo phản ánh trùng. Chỉ input quan sát thực tế
vào event; kỳ vọng scorer không được đưa vào model input hoặc source KB.

## 6. Chứng minh vòng 0/vòng 1 — chạy live cần ủy quyền riêng

Chốt frozen scenario directory trước vòng 0, đủ độ phủ M1; bảy public sample
chỉ là sample contract. Giữ nguyên source code, dataset, model/sampling/seed,
nguồn nghiệp vụ và scorer. Thay đổi giữa hai vòng ở phạm vi chức năng này là
release tri thức. Nếu cần sửa code/tool, đây là đợt thay đổi khác, không trộn
vào so sánh knowledge-only.

```bash
# Chạy ở ai-services; các lệnh run_official gọi model và reset runtime.
KNOWLEDGE_RELEASE_ID=btc-only .venv/bin/python -m eval_harness.run_official \
  --btc-root '<BTC-root>' --scenarios '<frozen-scenarios>' --agent deep --seed 7 --skip-rag
# Thu/import feedback, xử lý/duyệt và phát hành R1 qua chức năng thật.
KNOWLEDGE_RELEASE_ID='<release-R1>' .venv/bin/python -m eval_harness.run_official \
  --btc-root '<BTC-root>' --scenarios '<same-frozen-scenarios>' --agent deep --seed 7 --skip-rag
# Không gọi model: kiểm hai artifact, xuất bảng delta và đăng ký bằng chứng.
.venv/bin/python -m eval_harness.knowledge_comparison \
  --round0 '<validated-run-0>' --round1 '<validated-run-1>' \
  --out '<new-comparison-directory>' --register
```

Báo cáo gồm số đo/mẫu số/trạng thái, delta điểm phần trăm, ca tốt lên/xấu đi
và cảnh báo. Các ca thất bại liệt kê dựa trên coverage báo cáo BTC (script có
cắt số ví dụ); kiểm trace khi phân tích đầy đủ. Không chuyển null thành 0,
không tuyên bố cải thiện khi số liệu chưa có hoặc xấu đi. Full và baseline
trong mỗi run giữ cùng release bằng trusted context và subprocess env;
model không chọn được release. Runtime reset không xóa schema knowledge.

Test sinh từ gap được export thành bộ regression version riêng. Không thêm
vào mẫu số riêng vòng 1. Không thay đổi scenario/validator BTC và không dùng
bộ ẩn làm dữ liệu học trong run chấm. READMEs vẫn cung cấp runner nhận thư
mục scenario tùy ý; phiên bản đã pin được ghi vào manifest và pair audit.

## 7. Xóa dữ liệu và export

Dùng quy trình xác minh/đăng ký erasure hiện có trước khi chạy
`scripts.execute_memory_erasure`. Executor memory xóa evidence/jobs/drafts
liên quan, giữ tombstone ngăn worker tái tạo, vô hiệu release có nội dung
liên quan và trở về BTC-only nếu cần. Khi knowledge purge lỗi, kết quả là
partial để retry; không báo đã xóa mọi store. Backend chats, trace artifact
và backup tiếp tục là các store riêng theo scope erasure hiện có. Bằng chứng
không có FK sang runtime; snapshot đã mask được giữ sau eval reset.

```bash
.venv/bin/python -m app.knowledge.cli export --actor '<reviewer-id>' --out '<new-private-evidence.json>'
```

File export chỉ tạo mới, không ghi đè. Artifact sau export là một bản sao
riêng, phải được xử lý theo scope traces/backups khi có yêu cầu xóa; xóa DB
không tự xóa file đã tải xuống. Không đưa file evidence vào public repo.

## 8. Kiểm tra và giới hạn vận hành

Focused AI: `python -m pytest test/test_knowledge_*.py eval_harness/test_knowledge_*.py`.
Backend chạy riêng từ backend: `../ai-services/.venv/bin/python -m pytest test/test_knowledge_api.py test/test_knowledge_feedback.py`.
Chrome smoke dùng API synthetic, không phải UI nối DB/model thật. Test DB
opt-in cần KNOWLEDGE_TEST_DSN và KNOWLEDGE_EXPECTED_TEST_DATABASE trỏ database đã provision và được xác nhận; không chạy
mặc định. Không cài dependency hay tạo/reset DB trong test mặc định.

Trước bàn giao thực nghiệm: kiểm migration/grants trên DB test, restart các
process có cấu hình mới, kiểm nhiều hội thoại và cả hai loại nội dung trên
stack thật, sau đó chạy hai vòng được phép. Phân biệt rõ ba trạng thái:
code kiểm offline, stack tích hợp đã xác minh, và C.5 đã có số liệu cải tiến.
