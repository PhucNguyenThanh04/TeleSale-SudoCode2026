# MCP Knowledge — Cloudflare dense + BM25 CPU

Cơ sở: [spec](superpowers/specs/2026-11-03-mcp-knowledge-rag-design.md) và
[plan 04/11](superpowers/plans/2026-11-04-cloudflare-bm25-knowledge.md).
Unit/mock tests không chứng minh API thật, Docker trên máy sạch, điểm RAG hay latency BTC.
Các lệnh ghi/gọi API bên dưới là hướng dẫn vận hành, không tự được chạy khi test.

## Thành phần và quyền

- `policy.search` nằm tại `app/mcp_servers/mcp_knowledge`, theo [module map](../app/knowledge/README.md).
- Cloudflare `@cf/baai/bge-m3` tạo dense; ứng dụng L2 normalize. BM25 CPU dùng
  Unicode NFC/casefold, giữ dấu và mã ghép, k1=1.2, b=0.75; không thêm model tách từ.
- Vocabulary/avgdl cố định theo release, giữ trong manifest PostgreSQL. Qdrant một
  shard áp dụng IDF một lần ở sparse query, hợp nhất dense/BM25 bằng RRF.
- PostgreSQL giữ snapshot và active pointer có thẩm quyền. Qdrant payload chỉ là
  bản inspection an toàn: giữ content/title/source/date/conditions của BTC;
  supplement không sao chép nội dung/aliases/source references của khách vào payload.
- Role `mcp_knowledge` chỉ đọc snapshot/tombstone/manifest/active; reviewer/loader
  có quyền nạp và actor `knowledge_review` riêng. Không dùng DSN admin cho serving.
- Giữ migrations 0001/0002/0003, role provisioning và secret files như phần setup
  trong [README AI](../README.md). Chuyển provider không thêm migration SQL.

## Cấu hình

Trong `ai-services/.env` có:

```dotenv
CLOUDFLARE_ACCOUNT_ID=<account_id_32_hex>
CLOUDFLARE_API_TOKEN=<workers_ai_token>
```

Đây là chỗ điền giá trị cục bộ, không đưa token lên chat/Git. Token đã lộ phải
thu hồi và thay mới. Settings và manifest không log token; không dùng Global API Key.

Dùng runtime JSON thực tại `config/policy-runtime.json`. File chứa provider/model,
tokenizer revision/hash, max input 4096, dimension 1024, normalization, BM25,
candidates, queue/deadline/breaker. Không ghi credentials, device hoặc CUDA dtype.
Giới hạn API/chiều/schema thật vẫn cần smoke riêng được cho phép trước bàn giao.
Cloudflare quản lý weights; tokenizer revision là asset kiểm độ dài của ứng dụng,
không giả provider giữ đúng Hugging Face commit. Không âm thầm truncate đầu vào.

Tokenizer từ `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`
đã được đóng gói tại `app/mcp_servers/mcp_knowledge/assets/bge-m3-tokenizer.json`;
SHA256 `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08`.
Tham chiếu nguồn: [BAAI model](https://huggingface.co/BAAI/bge-m3).
Không có weights, Torch, FlagEmbedding, torchvision hay NVIDIA dependency trong
requirements knowledge. Setup host cần cài `requirements.txt` và
`requirements-knowledge.txt` khi được phép; startup không cài/tải dependency.

Giữ bốn MCP URL/token và DSN reviewer/source như setup hiện có.
`QDRANT_URL` có precedence process > `ai-services/.env` > localhost.
`KNOWLEDGE_ENABLED` điều khiển supplement/Gap Loop, không tắt corpus BTC.
`relevance_verified=false` chỉ ghi chất lượng chưa đo; không cản integrity/readiness.
Healthcheck/startup kiểm config/tokenizer/artifact/DB/index, không gọi API hoặc
warmup ba lượt. Ready không bảo đảm provider đang phản hồi hoặc quota còn.

## Prepare, verify, activate

Xem [loader guide](../../dataloader_offline/README.md) để nạp một lần cả catalog,
CRM, chính sách và index. Từ root, với actor local đã provision:

```bash
ai-services/.venv/bin/python -m dataloader_offline --dry-run
ai-services/.venv/bin/python -m dataloader_offline \
  --data-dir ../BTC-Data-Vong1-TEAMS \
  --prepare-policy --actor btc-loader --runtime-config config/policy-runtime.json
```

Dry-run không kết nối dịch vụ. Prepare gọi API/tiêu quota và ghi DB/Qdrant; giữ
nguồn BTC nguyên bản. Actor ở máy khác phải được provision trước. Nếu đã có active
release, thêm `--expected-active` đúng ID hiện tại. Có thể thêm `--revision-id`
cho supplement đã được duyệt; không tạo vocabulary/aliases từ đáp án QA.

Khi prepare trả ID mới, gán biến shell `POLICY_RELEASE_ID` bằng ID đó rồi kiểm chỉ đọc:

```bash
ai-services/.venv/bin/python -m dataloader_offline --verify-ingestion \
  --release-id "$POLICY_RELEASE_ID" --runtime-config config/policy-runtime.json
```

Verify kiểm source tables, metadata/expiry, immutable snapshot/manifest,
BM25 artifact, dense/sparse vectors và cấu hình IDF; không gọi embedding API.
Integrity đạt tạo release `ready`, chưa tự active. Đổi active là thao tác ghi riêng:

```bash
cd ai-services
.venv/bin/python -m app.knowledge.cli policy-activate --actor btc-loader \
  --release-id "$POLICY_RELEASE_ID" --runtime-config ../config/policy-runtime.json
```

Lần sau thêm `--expected-active` đúng ID. Approval/source/revocation/CAS được kiểm
lại; không dùng relevance flag để giả đã chạy eval. Build lỗi không đổi active;
nguồn PostgreSQL có thể đã commit trước khi embedding lỗi. Chạy lại release hoàn
chỉnh verify không encode; build dở có thể phải encode lại, chưa resume từng chunk.

Release local CUDA cũ cần dựng collection/release mới, không upsert đè hoặc xóa
collection cũ. Rollback chỉ được tới release tương thích config/runtime; trở lại
local CUDA cần runtime cũ, không chỉ đổi con trỏ DB. Tombstone và erasure tiếp tục
chặn cả request ghim release, artifacts nội bộ và rollback.

## Docker Compose CPU

Từ root, sau khi DB/grants/secrets và active release đã sẵn sàng:

```bash
docker compose --env-file .env --env-file ai-services/.env up --build -d
```

File `.env` root chứa PostgreSQL/Compose settings, file AI chứa credentials;
file sau override key trùng, giữ DB/port thống nhất. Compose chỉ truyền hai biến
Cloudflare cho knowledge, không đưa toàn bộ `.env` vào container.
Qdrant được ghim `v1.19.1`, cùng nhánh với Python client 1.19.x; chưa pull/start
image trong lượt triển khai này. Nếu dữ liệu hiện có được tạo bởi server mới hơn,
kiểm tương thích/backup trước khi thay server; không tự downgrade hoặc xóa storage.
Runtime config mount read-only vào `/config/policy-runtime.json` với fail-fast
nếu thiếu file. Tokenizer đã có trong image; không mount weights hoặc GPU.
Không cần NVIDIA runtime. Bốn MCP server tiếp tục chung vòng đời Compose.
Không chạy `docker compose config` ra log với env thật vì output có thể chứa token.

## Lỗi vận hành

Khi Cloudflare lỗi/hết quota, không search BM25-only, không dùng kiến thức LLM để
đoán. Trả evidence rỗng với `unavailable`/`timeout`; giao diện báo:
“Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.”
Phần độc lập có bằng chứng từ tool khác vẫn có thể trả lời. Không tự đặt lịch
hoặc thêm điều kiện chuyển nhân viên ngoài nghiệp vụ hiện có.

Log ghi `reason=quota_exhausted` khi provider xác nhận, kèm provider/model,
HTTP status/provider code an toàn và request/release ID. HTTP 429 chưa rõ không
đồng nghĩa quota hết. `rate_limited` có Retry-After, transient network/5xx chỉ
retry một lần trong deadline. Quota/auth/input sai không retry; breaker giữ
nguyên nguyên nhân gốc. Không log token, raw response, query PII hoặc nội dung hạn chế.
Lỗi kỹ thuật vào `mcp_unavailable`, không tạo content gap. Không tự nâng gói trả phí.

## Kiểm thử

Chỉ test chức năng với mock HTTP, fake repo, Qdrant `:memory:` và ASGI trong tiến trình;
không chạy eval/benchmark/LLM judge/live API trong phạm vi chuyển đổi này.
API connectivity, quyền token thật, SQL grants, Docker build/start và ingest/activate
thật phải được xác minh riêng khi được phép. Không coi test offline là đã bàn giao
thành công trên máy BTC hoặc đã đạt chất lượng/latency.
