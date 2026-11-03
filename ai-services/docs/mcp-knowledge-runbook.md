# MCP Knowledge — vận hành và kiểm thử chức năng

Cơ sở: [spec](superpowers/specs/2026-11-03-mcp-knowledge-rag-design.md) và
[plan](superpowers/plans/2026-11-03-mcp-knowledge-rag.md). Mã đã được kiểm bằng
fake model/repo và Qdrant trong bộ nhớ; không coi đây là số liệu chất lượng RAG,
khả năng GPU 4 GB hoặc kết quả nghiệm thu BTC. Tài liệu này không cho phép tự
cài dependency, chạy model, migrate/reset DB hoặc thay đổi dịch vụ đang chạy.

## Kiến trúc thư mục

Xem [bản đồ module](../app/knowledge/README.md) để tìm nhanh owner của schema,
repository, service, nguồn policy và workflow feedback/phát hành. MCP có cấu trúc
`schemas.py`, `repos/`, `services/`, `tools/`; `server.py` chỉ khởi tạo thành phần.
Domain dùng chung nằm trong `knowledge/policy`, `events`, `services` và `repos`.
Lệnh CLI/worker, JSON contract và hành vi giữ nguyên sau khi chuyển thư mục.

## Thành phần và quyền

- `policy.search` chỉ đăng ký ở `app/mcp_servers/mcp_knowledge`; catalog không
  giữ implementation hay fallback lexical.
- `mcp_knowledge` chỉ đọc serving snapshots, tombstones, manifest và active pointer.
  Không cấp quyền đọc CRM, raw policy, audit, reviewer decisions hoặc ghi release.
- Chuẩn bị/kích hoạt dùng kết nối reviewer và actor có `knowledge_review` đã được
  cấp qua workflow hiện có. Quyền tool đọc không cấp quyền phát hành.
- Migration mới: `migrations/0003_mcp_knowledge_rag.sql`, sau migrations 0001/0002.
  Chỉ áp dụng khi được phép. Sau migration, provision lại role/grants bằng quy trình
  hiện có; tạo secret `secrets/mcp_knowledge_password` cùng định dạng hex như các role khác.
- `scripts/provision_mcp_roles.sh` và launcher nhận thêm role knowledge. Không dùng
  DSN admin cho tiến trình phục vụ. Erasure executor vẫn cần grants ghi tombstone/
  redact snapshot; kiểm grants trên DB test trước khi vận hành thật.

## Cấu hình bắt buộc

Trong môi trường AI, cấu hình bốn MCP URL, token nội bộ, `MCP_KNOWLEDGE_PORT`
(mặc định 8014), `KNOWLEDGE_POLICY_CONFIG_FILE` và
`KNOWLEDGE_POLICY_SOURCE_DIR` trỏ tới thư mục policy BTC nguyên bản.
`QDRANT_URL` trỏ tới Qdrant CPU. `KNOWLEDGE_ENABLED` chỉ điều khiển dùng supplement/
Knowledge Gap Loop; không tắt tra cứu corpus BTC hoặc ghim release.

File runtime JSON được kiểm bằng `PolicyRuntimeConfig` trong
`app/mcp_servers/mcp_knowledge/schemas.py`. Các trường phải khai báo tường minh:

- Model/tokenizer revision, max token, dense dimension, batch, thiết bị CUDA.
  Revision thực phải là commit hash bất biến, model/tokenizer cùng snapshot.
- Candidate depths cho dense/sparse, hard limit evidence, ngưỡng từng nhánh và
  trạng thái xác nhận cấu hình relevance.
- Queue capacity, deadline tổng, timeout phụ thuộc, breaker failures/cooldown.

Model là BGE-M3 FP16, dense+sparse, không ColBERT; dense được L2 normalize.
Không có giá trị benchmark/threshold production mặc định được suy ra từ fixture.
`relevance_verified=false` làm readiness thất bại; bản build tương ứng chỉ là
`prepared`, không phải `ready`. Việc phát triển/test chức năng vẫn hoàn tất được
mà không chạy calibration hoặc bật serving bằng cấu hình chưa xác minh.

FlagEmbedding chỉ nạp snapshot đã có trong cache bằng `local_files_only=True`;
không tải model khi khởi động. Model thiếu, sai CUDA/fingerprint hoặc encode
warmup lỗi sẽ làm startup thất bại. Một tiến trình giữ một model/worker; không
nhân bản theo web workers. Không chạy CLI build và server cùng lúc trên GPU 4 GB
khi chưa xác minh đủ tài nguyên; dùng quy trình bảo trì hoặc thiết bị nạp riêng.
Không hỗ trợ hot swap model hoặc giữ hai model mặc định trong VRAM.

`Dockerfile.knowledge` là artifact CUDA riêng; chưa build/kiểm trên GPU thật.
Compose service `mcp-knowledge` thuộc profile `knowledge`, cần NVIDIA runtime,
file config và cache model read-only được mount. Các image catalog/order/memory
không cài FlagEmbedding/Torch. Các bước build/start chỉ thực hiện khi được phép.
Launcher local dùng `python -m app.mcp_servers.run`, kiểm đủ port/secret/config
trước khi tạo child; khởi chạy bốn MCP và LangMem worker, không tự provision DB.

## Chuẩn bị và kích hoạt

Các lệnh sau dành cho reviewer sau khi môi trường/model/index đã được cho phép
sử dụng; không phải lệnh cần chạy để kiểm thử chức năng.
Chạy từ `ai-services/` bằng interpreter có dependency phù hợp.

```bash
python -m app.knowledge.cli policy-prepare --actor REVIEWER \
  --source-dir /path/to/BTC/policy --runtime-config /path/to/reviewed-runtime.json
```

Lần đầu không truyền `--expected-active`; các lần sau truyền active ID đã đọc.
Nguồn bổ sung phải được duyệt nội dung và regression case trong workflow hiện có;
truyền `--revision-id ID` cho mỗi revision cần đưa vào bản mới. Nếu dùng metadata
khác registry mặc định, truyền `--metadata PATH` đã được review nguồn.

Parse giữ 99 mục BTC được đối chiếu, trong đó 93 mục có bản phục vụ an toàn;
5 mục hành chính và NB-04 bị loại. NB-01/NB-03 là bằng chứng giới hạn tiết lộ,
NB-02 chỉ giữ ngày dự kiến, KM-06 loại giá sàn. Hash nguồn khớp raw section body;
source document hash và safe content hash theo dõi phần lời dẫn/biến đổi.
FAQ có ID `KG-...`; aliases chỉ tăng khả năng tìm chunk gốc và không đổi evidence
thành đáp án mẫu của QA. Nguồn bổ sung dùng hash đúng với file/source đã duyệt.

Encode/upsert/verify nằm ngoài transaction duyệt; trước khi chuyển ready phải
kiểm lại approval/test/source/revocation và CAS active. Chạy lại cùng nguồn,
revision, config và base ID không tạo release/point trùng. Build không tự kích hoạt.
Manifest/index thiếu hoặc cấu hình relevance chưa xác nhận không được phục vụ.

```bash
python -m app.knowledge.cli policy-activate --actor REVIEWER \
  --release-id POLICY_RELEASE --expected-active CURRENT_RELEASE \
  --runtime-config /path/to/reviewed-runtime.json
python -m app.knowledge.cli policy-rollback --actor REVIEWER \
  --release-id PREVIOUS_RELEASE --expected-active CURRENT_RELEASE \
  --runtime-config /path/to/reviewed-runtime.json
python -m app.knowledge.cli policy-revoke --actor REVIEWER --section-id SECTION_ID
```

Lần kích hoạt đầu bỏ `--expected-active`. Dùng cùng runtime fingerprint/config
với tiến trình phục vụ; khác model phải dừng/nạp/warmup có kiểm soát. Collection
cũ được giữ, không có auto prune/GC. Sentinel `btc-only` resolve tới hybrid release
BTC-only đã build và kích hoạt; không trở về retriever lexical.
Tombstone và erasure được kiểm cả với request ghim release và rollback; thu hồi
một nguồn liên quan làm bản đó không đủ điều kiện phục vụ. Không sửa raw BTC.

## Request, lỗi và tracing

Gateway ký context bằng HMAC gắn với toàn bộ request; handler xác minh chữ ký,
principal, ngày nghiệp vụ và nguồn ngày đơn trước khi gọi service. LLM không có
signing key hoặc quyền tự chọn release. Token auth còn bảo vệ endpoint HTTP.
Ngày khách khai là trường riêng và chỉ dùng giải thích có điều kiện.

`top_k` là số mong muốn, nhóm policy/ngoại lệ có thể vượt đến hard limit. Thiếu
phụ thuộc phải được báo trong applicability/evidence_set; `truncated=false`
không chứng nhận tập evidence đầy đủ. Trả lời thiếu căn cứ bị chặn; câu hỏi làm
rõ/giải thích có điều kiện không được biến thành xác nhận quyền lợi của đơn.
Agent không tự hẹn gọi lại do thiếu thông tin, handoff theo nghiệp vụ hiện có.

Lỗi phụ thuộc trả `unavailable`/`timeout`/`overloaded` với evidence rỗng; input sai
trả validation error. Không retry OOM/hash/quyền/config sai, retry tạm thời tối đa
một lần trong cùng deadline. Hủy chờ không làm worker chạy chồng GPU encode;
tác vụ queued đã hết hạn bị bỏ. Không có fallback.

Log chỉ thành phần/reason type/request ID/release ID và thời gian xử lý, không
raw query, signed context hoặc content. Diagnostics/Knowledge Gap Loop giữ ID
và thứ tự evidence. Lỗi kỹ thuật được phân loại technical, không tự thành content gap.

## Kiểm thử và giới hạn bàn giao

Chỉ chạy focused tests chức năng cho module thay đổi, dùng fake/scripted model,
repo fake, Qdrant `:memory:` và HTTP ASGI trong tiến trình. Full regression unit/mock
chạy tối đa một lần cuối; không gọi runner eval hoặc live model.
GPU/model thật, SQL role grants, Docker build, dữ liệu/index thật và chất lượng/
latency BTC phải được ghi là chưa xác minh nếu chưa kiểm trên môi trường phù hợp.
Không tạo collector eval, benchmark hoặc tự xin chạy các phép đo ngoài phạm vi.
