# Khởi động demo mới; eval trên hạ tầng đang chạy

Đường demo được quản lý là **`python run_system.py demo ...` từ root repo**.
Nó khởi tạo cả nhóm server, không yêu cầu chạy migration hay setup store riêng.
`run_system.py eval` chỉ gọi runner trên dịch vụ đã chạy, không dùng Docker hay
bootstrap; runtime/memory vẫn reset độc lập trước mỗi cấu hình eval.
Đừng mở thêm các server bằng lệnh cũ cùng lúc với managed demo.
Launcher dùng host Linux/Ubuntu như môi trường hiện tại.

## 1. Dữ liệu BTC: nạp riêng

PostgreSQL phải chạy trước lần import đầu tiên:

```bash
docker compose up -d postgres
ai-services/.venv/bin/python -m dataloader_offline \
  --data-dir ../BTC-Data-Vong1-TEAMS --only-postgres
```

Loader tạo bảng và insert nguồn BTC vào `btc_source`. Các lần khởi động sau
**không import lại, không thêm khách/sản phẩm/fact, không xóa nguồn BTC**.
DATABASE_URL dùng khi import phải cùng DB với AI/backend. PostgreSQL và cấu hình
credentials/secret files vẫn theo hướng dẫn cài dependency của repo.

## 2. Cấu hình trước khi khởi động

- Cài requirements vào `ai-services/.venv` và `backend/.venv`.
- `ai-services/.env`: `DATABASE_URL` có quyền quản trị schema/role trên DB demo;
  các URL `KNOWLEDGE_DATABASE_URL`, `KNOWLEDGE_WORKER_DATABASE_URL` cùng DB/server;
  policy source/config, Cloudflare, Qdrant, LLM và internal tokens như hiện có.
  Login reviewer/worker chưa tồn tại sẽ được tạo từ username/password trong các
  URL này và gán group role; không cần chạy psql/migration thủ công. Login đã có
  được giữ mật khẩu từ cấu hình hiện tại, không tự đổi mật khẩu của tài khoản khác.
  Với `knowledge-eval`, bật `KNOWLEDGE_ENABLED=true` và `AGENT_GUARDRAILS_ENABLED=true`.
- `backend/.env`: cùng DB, cùng `AI_INTERNAL_TOKEN`, `DEMO_JWT_SECRET`, hai bộ
  `DEMO_USER_1_*`, `DEMO_USER_2_*`. Customer ID phải có trong nguồn BTC gốc.
  `KNOWLEDGE_REVIEWER_ID` (mặc định `local-reviewer`) được cấp quyền lại mỗi boot.
- Secret files MCP/PostgreSQL và tokenizer asset được chuẩn bị như repo hiện có.
  Script startup tự chạy provision role sau khi tạo đủ bảng, không chạy bằng tay.

Đây là đường fresh demo, không chạy trên cấu hình production. Lệnh cần DB
đích khai báo rõ. Backend và AI phải dùng cùng DB; không tự tạo một DB demo khác.

## 3. Demo: một lệnh

Tắt gateway/AI/knowledge worker đang mở bằng terminal cũ, rồi chạy:

```bash
python run_system.py demo --expected-database telesale
```

Nếu máy vẫn cần `sudo docker`, thêm `--sudo-docker` vào lệnh launcher. Chỉ các
lệnh Docker dùng sudo; Python/backend/AI vẫn chạy bằng user hiện tại.

Launcher giữ khóa suốt lượt chạy và thực hiện lần lượt:

1. Dừng MCP/LangMem worker của Compose; bật PostgreSQL/Redis/Qdrant.
2. Kiểm tra cấu hình, DB đích và nguồn BTC; lấy khóa bootstrap trong PostgreSQL.
3. Xóa/tạo lại `runtime`, `knowledge` và các schema operational legacy của app.
   DDL hiện hành nằm trong `ai-services/app/bootstrap/schema.sql`; các SQL migration
   cũ là lịch sử, không phải một bước người vận hành phải chạy.
4. Tự setup LangGraph store, quyền DB/MCP, tài khoản demo và quyền reviewer.
5. Khôi phục policy **chỉ chứa BTC**, không có revision đã duyệt. Cache vector
   BTC chỉ được dùng khi nội dung/config/hash và index đều còn đúng; nếu không
   thì build lại, có thể gọi Cloudflare embedding và tiêu quota. Các collection
   knowledge phát sinh được ghi nhận ở DB cũ được dọn khỏi Qdrant.
6. Đánh dấu schema/policy ready; xóa dữ liệu Redis trong container của stack demo
   trước khi khởi động các dịch vụ ứng dụng.
7. Build/start MCP/worker rồi chạy AI API, knowledge worker và gateway. Chờ cổng
   dịch vụ sẵn sàng trước khi thông báo URL `/chat`.

Các process nhận chung `SYSTEM_BOOT_ID`. Chỉ initializer tạo/reset, server khác
kiểm tra marker ready rồi mới chạy; server khởi động sau không xóa server trước.
Pin release cũ trong `.env` được bỏ qua trong boot quản lý: API dùng release
đang active, còn mỗi cấu hình eval vẫn ghim release cụ thể của nó. Vì vậy sau
khi duyệt/phát hành trong demo, API có thể dùng knowledge mới ở cùng boot.
Một marker điều phối ở `system_boot.current` được thay thế mỗi boot, không chứa
lịch sử khách hàng. LangGraph có ledger nội bộ phục vụ setup schema của thư viện.

Không giữ: hội thoại, memory/fact/episodic, đơn cập nhật/lịch hẹn/handoff demo,
promo uses, pending jobs, erasure state, gap/feedback/draft/approval/release bổ sung,
quyền/tài khoản phát sinh thủ công. Tài khoản và quyền mặc định được tạo **mới từ
cấu hình**; cần đăng nhập lại. Không giữ learned knowledge của lần trước.

Giữ: nguồn BTC, cấu hình/credentials, cache index nền đã đối chiếu BTC và các
file artifact eval đã xuất. Không xóa `results/` hay `.env`.

Nhấn Ctrl+C để dừng các process do launcher quản lý và MCP/worker. PostgreSQL,
Redis, Qdrant vẫn có thể chạy; lần chạy launcher tiếp theo luôn tạo boot sạch mới.
Không dùng riêng `docker compose restart`/`uvicorn` để bắt đầu một demo mới: đó
chỉ là thao tác service, không xác định ranh giới reset của cả hệ thống.

## 4. Eval: dùng hạ tầng đang chạy, reset memory mỗi cấu hình

Khi model/DB/MCP đã chạy, chạy một cặp official No-memory/Full:

```bash
python run_system.py eval --expected-database telesale -- \
  --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --out-root ai-services/eval_harness/results/fresh-full
```

Lệnh eval kết thúc sau khi chấm và detect gap (nếu bật Knowledge), không điều
khiển Docker, tạo boot, tạo tài khoản hay reset schema/knowledge. Cả hai cấu hình
dùng cùng reset runtime/memory sau warmup; Full tích lũy memory giữa các cuộc
gọi của nó. Knowledge/BTC được giữ nguyên; Full K1 cũng dùng cùng reset memory.
Worker đang chạy có thể tiếp tục hoạt động: ID job nội bộ không bị dùng lại sau
reset, nên claim cũ không thể ghi vào job mới. Các ID nghiệp vụ vẫn reset như trước.

Với luồng duyệt thủ công, sau cặp thường hãy duyệt/phát hành trên frontend rồi
chạy file `run_knowledge_eval.py --base-run RUN`. Dùng đúng lệnh in sau detect;
giữ các dịch vụ đang chạy và không chạy lại fresh demo giữa hai bước.
Chi tiết: [eval hai bước](../ai-services/eval_harness/KNOWLEDGE_TRIPLET.md#luồng-duyệt-trên-frontend).

Thí nghiệm tự duyệt cũ vẫn quản lý riêng một boot mới:

```bash
python run_system.py knowledge-eval --expected-database telesale -- \
  --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --actor local-reviewer --auto-review \
  --out-root ai-services/eval_harness/results/knowledge-triplet
```

Cơ chế tự duyệt chạy sau K0, không cần `review-plan.json`: CLI dùng worker thật
để tạo đề xuất, kiểm nguồn/hash/ngày, nội dung gắn nguồn và regression trước khi
duyệt/phát hành. Đề xuất không đủ điều kiện được bỏ qua kèm lý do; không có gap
hợp lệ thì dừng trước K1, không ép tạo cải thiện. Đây là duyệt tự động trong
thí nghiệm, không phải duyệt bởi con người hoặc bảo đảm đáp án đúng về ngữ nghĩa.

Cả thí nghiệm dùng **một boot**. Chỉ reset knowledge ở đầu thí nghiệm; giữa
K0 → duyệt/phát hành → K1 giữ nguyên knowledge mới. Memory/runtime vẫn reset
độc lập cho từng cấu hình theo harness. Chi tiết auto-review có kiểm soát:
[Knowledge Triplet](../ai-services/eval_harness/KNOWLEDGE_TRIPLET.md).

Chạy tiếp một thí nghiệm chưa xong, không bắt đầu hệ thống mới:

```bash
python run_system.py knowledge-eval --expected-database telesale \
  --resume /duong-dan/thu-muc-thi-nghiem
```

Đặt `--resume` trước dấu `--`. CLI dùng boot ID trong checkpoint, bật lại MCP
nếu cần và không reset schema/knowledge. Không thể resume nếu đã bắt đầu một
demo/eval mới hoặc thay code/model/source/settings; lúc đó phải chạy thí nghiệm
mới. Trạng thái không có gap hợp lệ vẫn trả mã 2, không bịa số liệu cải thiện.

Các entrypoint service/eval thấp hơn vẫn dùng cho debug và kiểm chứng độc lập;
chúng không tự phát minh một boot/reset riêng khi chạy bên trong launcher.
Muốn đảm bảo sạch toàn bộ theo quy trình này, dùng `run_system.py`.

## Kiểm chứng

Các test offline kiểm tra schema, thứ tự startup, boot marker, cache/index nền,
resume và gateway. Test PostgreSQL tích hợp tạo/xóa DB **tạm tên ngẫu nhiên**,
chứng minh hai initializer đồng thời chỉ reset một lần, xóa hết runtime/knowledge
cũ, tạo quyền login và giữ nguyên fingerprint BTC. Test không reset DB demo thật,
không chạy eval LLM và không gọi Cloudflare.
