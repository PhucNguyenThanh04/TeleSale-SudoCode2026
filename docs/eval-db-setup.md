# Dựng DB eval riêng cho 7 public sample

Kịch bản này **chưa được chạy**. Thực hiện từ gốc repo sau khi kiểm tra
PostgreSQL đang dùng và quyền của tài khoản quản trị. Chỉ tạo hoặc xóa database
`telesale_eval`; không chạy dataloader, migration hay eval với DB `telesale`.
Ba MCP eval phải là process riêng, dùng cổng khác MCP demo đang chạy.

## Chuẩn bị một lượt đo

1. Dừng ba MCP **eval** của lượt trước, nếu có. Khi reset, xóa đúng DB eval
   rồi tạo lại để memory, đơn hàng, khuyến mãi một lần và operation key cùng
   quay về trạng thái seed. Dùng tài khoản PostgreSQL quản trị; các lệnh
   `createdb`/`dropdb` sẽ yêu cầu mật khẩu qua cơ chế PostgreSQL thông thường.

   ```bash
   eval_db=telesale_eval
   admin_user=$(sed -n 's/^POSTGRES_USER=//p' .env)
   dropdb --if-exists --force -h 127.0.0.1 -p 5432 -U "$admin_user" "$eval_db"
   createdb -h 127.0.0.1 -p 5432 -U "$admin_user" "$eval_db"
   ```

2. Tạo DSN eval từ DSN quản trị đã cấu hình trong `ai-services/.env` mà
   không in DSN/mật khẩu ra terminal:

   ```bash
   eval_dsn=$(ai-services/.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "ai-services")
from sqlalchemy.engine import make_url
from app.configs import get_settings
url = make_url(get_settings().database_url.get_secret_value())
print(url.set(database="telesale_eval").render_as_string(hide_password=False))
PY
   )
   eval_psql_dsn=${eval_dsn/postgresql+asyncpg/postgresql}
   ```

3. Nạp seed BTC vào DB eval rồi áp migration theo đúng thứ tự:

   ```bash
   DATABASE_URL="$eval_dsn" .venv-dataloader/bin/python -m dataloader_offline --only-postgres
   DATABASE_URL="$eval_dsn" .venv-dataloader/bin/python -m dataloader_offline --verify-postgres
   for migration in backend/migrations/0001_chat.sql backend/migrations/0002_tools.sql backend/migrations/0003_channel_identity.sql ai-services/migrations/0001_memory.sql ai-services/migrations/0002_operations.sql ai-services/migrations/0003_memory_provenance.sql ai-services/migrations/0004_pending_facts.sql; do
       psql "$eval_psql_dsn" -X -v ON_ERROR_STOP=1 -f "$migration"
   done
   docker compose run --rm -e PGDATABASE=telesale_eval mcp-db-roles
   ```

   Lệnh cấp role dùng secret files có sẵn và cấp quyền trên **DB eval**. Kiểm tra
   DB nguồn trong `DATABASE_URL` trước khi chạy. Nếu BTC ở vị trí khác, đặt
   `BTC_DATA_DIR` cho dataloader.

4. Chạy ba MCP eval bằng launcher riêng từ một terminal, dùng cổng 8111–8113:

   ```bash
   cd ai-services
   DATABASE_URL="$eval_dsn" MCP_CATALOG_PORT=8111 MCP_ORDER_PORT=8112 MCP_MEMORY_PORT=8113 .venv/bin/python -m app.mcp_servers.run
   ```

5. Ở terminal khác, từ gốc repo, trỏ runner vào đúng ba MCP eval. Chọn một
   cấu hình `full` hoặc `baseline_no_memory` và một file trace mới:

   ```bash
   EVAL_DB_ALLOWLIST=telesale_eval MCP_CATALOG_URL=http://127.0.0.1:8111/mcp MCP_ORDER_URL=http://127.0.0.1:8112/mcp MCP_MEMORY_URL=http://127.0.0.1:8113/mcp ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config full --out eval/runs/full-1.jsonl --isolated-db
   ```

   Runner hỏi từng MCP về DB thực sự đã kết nối và từ chối trước lượt đầu nếu
   tên DB ngoài allowlist, host/port không xác minh được, hoặc ba server không
   cùng endpoint. Cờ `--isolated-db` vẫn bắt buộc nhưng một mình cờ này không
   đủ để qua chốt chặn.

## Lặp và so sánh

Lặp toàn bộ bước 1–5 **sáu lần**: ba lần `full`, ba lần
`baseline_no_memory`. Giữ nguyên model, tham số, seed BTC và mã nguồn;
đổi tên file trace mỗi lần. Reset DB eval trước **mỗi** lượt chạy để full và
baseline không chia sẻ memory hay trạng thái tool. Sau đó dùng
`../BTC-Data-Vong1-TEAMS/eval/reference_eval.py` với từng cặp trace để
đối chiếu RQR, CCR và `success_if`. Không dùng trace từ DB demo.
