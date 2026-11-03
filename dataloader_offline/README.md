# BTC offline data loader

Nạp bản phát hành BTC vào schema PostgreSQL `btc_source`. Chạy từ thư mục gốc
repo; không sửa dữ liệu BTC. Pipeline embedding/Qdrant cũ đã được gỡ để chuẩn bị
cho [mcp-knowledge](../ai-services/docs/superpowers/specs/2026-11-03-mcp-knowledge-rag-design.md).

## Chạy

```bash
python -m dataloader_offline --dry-run
python -m venv .venv-dataloader
.venv-dataloader/bin/pip install -r dataloader_offline/requirements-postgres.txt
.venv-dataloader/bin/python -m dataloader_offline
.venv-dataloader/bin/python -m dataloader_offline --verify-postgres
```

`--dry-run` chỉ kiểm tra nguồn và đếm bản ghi, không kết nối dịch vụ.
Lệnh nạp ghi PostgreSQL trong một transaction, dùng upsert. `--only-postgres`
được giữ để tương thích lệnh cũ; hiện mọi lần nạp đều chỉ dùng PostgreSQL.
Không còn `--qdrant-url`, `--embedding-model`, tải model hoặc tạo vector.
Việc nạp DB và cài dependency vẫn cần được cho phép theo quy định dự án.

Đặt `DATABASE_URL` trong môi trường hoặc `backend/.env` (định dạng
`postgresql+asyncpg://...`). Mặc định đọc bộ BTC ở thư mục anh em
`../BTC-Data-Vong1-TEAMS`; đổi bằng `BTC_DATA_DIR` hoặc `--data-dir`.

## Dữ liệu và ranh giới quyền truy cập

- PostgreSQL lưu sản phẩm, biến thể, khuyến mãi, timeline tồn kho, CRM seed,
  đơn/phiên seed và từng mục policy. `customers.phone` được đánh index nhưng
  không unique vì BTC có hai khách dùng chung số điện thoại.
- Parser nguồn hiện có giữ nguyên mã BTC và loại nội dung restricted/giá sàn;
  đây là parser nhập snapshot, chưa phải parser/metadata mới của mcp-knowledge.
- Giá, tồn kho, chọn phiên bản chính sách và quyền truy cập thuộc các service
  nghiệp vụ; loader không thực hiện những quyết định đó.
- Cleanup mã không xóa dữ liệu PostgreSQL, collection Qdrant hay cache model
  đã có. Quy trình phát hành index mới sẽ nằm trong mcp-knowledge.

Sau khi được phép nạp, có thể kiểm tra số bản ghi:

```sql
SELECT count(*) FROM btc_source.products;
SELECT count(*) FROM btc_source.variants;
SELECT count(*) FROM btc_source.customers;
SELECT count(*) FROM btc_source.policy_chunks;
```
