# Knowledge: phần dùng chung và workflow quản trị

Thư mục này chứa xử lý nguồn chính sách dùng chung, feedback và vòng duyệt/phát
hành. Thành phần phục vụ MCP nằm tại
[`../mcp_servers/mcp_knowledge`](../mcp_servers/mcp_knowledge), theo mẫu server khác.

```text
knowledge/
├── schemas.py           # Snapshot/evidence dùng chung, lỗi và giá trị lifecycle
├── config.py            # Cấu hình Knowledge Gap Loop và kết nối quản trị
├── context.py           # Ghim release trong lượt agent/run
├── cli.py               # Entry point quản trị: python -m app.knowledge.cli
├── worker.py            # Entry point worker: python -m app.knowledge.worker
├── policy/
│   ├── source.py        # Parse Markdown, tạo nội dung phục vụ an toàn
│   ├── metadata.json    # Registry quyền, thời gian, liên kết có nguồn
│   └── rules.py         # Xác định điều kiện áp dụng bằng quy tắc hệ thống
├── repos/
│   └── postgres.py      # Transaction/unit of work cho workflow quản trị
├── events/
│   ├── ingest.py        # Nhận feedback, ghi event/job idempotent
│   ├── evidence.py      # Snapshot bằng chứng và che PII
│   ├── runtime.py       # Thu tín hiệu từ lượt hội thoại
│   ├── analysis.py      # Phân tích feedback
│   └── worker.py        # Claim/retry/xử lý job
└── services/
    ├── lifecycle.py     # Điều phối query/command quản trị
    ├── gaps.py          # Quản lý vấn đề
    ├── revisions.py     # Bản sửa và quyết định duyệt
    ├── releases.py      # Prepare/activate/rollback, CAS và audit
    ├── publish.py       # Build snapshot/index hybrid từ nguồn đã duyệt
    ├── permissions.py   # Quyền reviewer
    ├── source_validation.py # Xác minh nguồn của bản sửa
    ├── regression.py    # Tạo/kiểm regression case offline
    ├── supplements.py   # Đọc nội dung bổ sung của release
    └── erasure.py       # Xóa/redact bằng chứng và thu hồi nội dung phụ thuộc
```

```text
mcp_knowledge/
├── server.py            # Khởi tạo và nối thành phần, chạy MCP
├── config.py            # Đọc/validate cấu hình phục vụ
├── schemas.py           # Input/output tool, trusted context, runtime config
├── assets/
│   └── bge-m3-tokenizer.json # Tokenizer đã pin/hash; không chứa model weights
├── repos/
│   ├── postgres.py      # Đọc serving snapshot, manifest và tombstone
│   └── qdrant.py        # Upsert/query/verify dense+sparse index
├── services/
│   ├── knowledge.py     # Readiness, search, nhóm evidence và pin release
│   ├── embedding.py     # Tokenizer CPU, queue hữu hạn, dense HTTP encoder
│   ├── cloudflare.py    # REST adapter và phân loại lỗi provider an toàn
│   ├── bm25.py          # Tokenizer Unicode, artifact theo release, term weights CPU
│   └── dependencies.py  # Deadline, retry và circuit breaker
└── tools/
    ├── auth.py          # Ký/xác minh trusted context gắn với request
    └── handlers.py      # Đăng ký tool, validation/auth và gọi service
```

Luồng đọc: `tools -> services -> repos`; `server.py` chỉ lắp ghép. Handler không
kiểm tra manifest bằng method private hay tự đóng client DB/index; service sở hữu
vòng đời các tài nguyên của nó. CLI/lifecycle dùng `mcp_knowledge.config`, không
import entrypoint `server.py`.

Các module cũ đã chuyển trực tiếp, không có thư viện shim tại đường dẫn cũ.
Chỉ giữ `cli.py` và `worker.py` làm entry point ổn định. RPC, schema JSON, metadata
và quy tắc nghiệp vụ giữ nguyên. Xem [runbook](../../docs/mcp-knowledge-runbook.md)
cho lệnh vận hành và giới hạn kiểm thử chức năng.
