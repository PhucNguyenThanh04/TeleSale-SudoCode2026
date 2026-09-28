# BTC offline data loader

Nạp bản phát hành BTC vào schema PostgreSQL `btc_source` và hai collection Qdrant
`btc_policy_v1`, `btc_products_v1`. Chạy từ thư mục gốc repo. Không sửa dữ liệu BTC.

## Chạy

Chỉ nạp PostgreSQL trước (không cài model embedding hoặc kết nối Qdrant):

```bash
python -m dataloader_offline --dry-run
python -m venv .venv-dataloader
.venv-dataloader/bin/pip install -r dataloader_offline/requirements-postgres.txt
.venv-dataloader/bin/python -m dataloader_offline --only-postgres
.venv-dataloader/bin/python -m dataloader_offline --verify-postgres
```

Khi cần nạp thêm Qdrant, cài đủ dependency và chạy lại pipeline. Phần
PostgreSQL dùng upsert nên chạy lại an toàn:

```bash
.venv-dataloader/bin/pip install -r dataloader_offline/requirements.txt
.venv-dataloader/bin/python -m dataloader_offline
```

Đặt `DATABASE_URL` trong môi trường hoặc `backend/.env` (định dạng
`postgresql+asyncpg://...`). Mặc định kết nối Qdrant tại
`http://127.0.0.1:6333`; đổi bằng `QDRANT_URL`. Mặc định đọc bộ BTC ở thư mục
anh em `../BTC-Data-Vong1-TEAMS`; đổi bằng `BTC_DATA_DIR` hoặc `--data-dir`.

Model embedding mặc định là `intfloat/multilingual-e5-small`. Lần chạy đầu
cần tải model; các lần sau dùng cache Hugging Face. Có thể đặt
`EMBEDDING_MODEL` hoặc `--embedding-model` thành đường dẫn model đã tải sẵn.
Model chạy cục bộ; pipeline không gửi dữ liệu CRM hoặc tài liệu BTC tới API
embedding bên ngoài. Khi truy vấn từ agent, dùng **cùng model** và tiền tố
`query: `; pipeline dùng `passage: ` cho điểm trong Qdrant.

## Dữ liệu và ranh giới quyền truy cập

- PostgreSQL lưu sản phẩm, biến thể, khuyến mãi, timeline tồn kho, CRM seed,
  đơn/phiên seed và từng mục policy. `customers.phone` được đánh index nhưng
  **không unique** vì BTC có hai khách dùng chung số điện thoại.
- Qdrant chỉ lưu mô tả sản phẩm và policy. Không lưu CRM, số điện thoại, giá,
  tồn kho hoặc khuyến mãi dưới dạng vector. Giá/tồn kho phải do backend tính
  theo ngày kịch bản và đối chiếu `eval/mock_tools.py`.
- Nội dung của `ghi-chu-nhap-hang-NOI-BO.md`, `noi-quy-nhan-vien.md` và
  `playbook-telesale.md` được thay bằng dấu hiệu hạn chế truy cập cả trong
  PostgreSQL lẫn Qdrant. File policy mới chưa được phân loại cũng mặc định
  `restricted`. Chỉ metadata/mã chunk được lập chỉ mục để phục vụ đánh giá
  truy hồi; MCP knowledge phải lọc `access_level=public` **trước** khi trả
  nội dung cho agent.
- Mỗi policy chunk giữ nguyên mã `[XX-nn]` để đối chiếu `rag/qa_labeled.json`.
  Bản đổi trả cũ có `effective_until=2026-09-30`, bản mới bắt đầu 2026-10-01;
  dùng **ngày tạo đơn** cho hai bản này. Metadata thời gian không thay cho
  kiểm tra hiệu lực ở MCP knowledge.

PostgreSQL được ghi trong một transaction; Qdrant upsert bằng UUID ổn định và
chỉ encode lại điểm có metadata hoặc nội dung thay đổi. Nếu Qdrant lỗi sau
khi PostgreSQL đã commit, chạy lại cùng lệnh để hoàn tất. Pipeline không xóa
điểm cũ khi nguồn bị rút bớt; cần quy trình kiểm duyệt riêng trước khi prune.

Sau khi chạy, có thể kiểm tra số bản ghi:

```sql
SELECT count(*) FROM btc_source.products;
SELECT count(*) FROM btc_source.variants;
SELECT count(*) FROM btc_source.customers;
SELECT count(*) FROM btc_source.policy_chunks;
```

Schema `btc_source` là snapshot nguồn BTC. Backend/MCP cần lớp service riêng
để tính giá, kiểm tra tồn kho, chọn phiên bản chính sách và giới hạn truy cập;
pipeline không triển khai các nghiệp vụ đó.
