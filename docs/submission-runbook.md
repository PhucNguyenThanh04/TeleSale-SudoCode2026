# Chạy bản nộp M1 và chấm chéo BTC

Nguồn yêu cầu: `BTC-Data-Vong1-TEAMS/README.md` (Quy trình chấm chéo),
`DIEU-CHINH-DE.md` và `GIAI-DAP-MENTOR.md`. Deadline cụ thể không nằm trong gói;
BTC thông báo riêng. Hướng dẫn này chốt đường M1: chat text + ASR local offline.
Voice/TTS và simulator/LLM judge M2 không phải điều kiện khởi động M1.

## 1. Những gì người chấm cần nhận

- Checkout đủ source, migrations, `config/policy-runtime.json`, metadata policy,
  `BTC-cap-nhat-11-2026/` và lệnh root `run_eval.py`. Không bỏ file mới chưa track.
- Gói BTC gốc bên cạnh repo hoặc đường dẫn riêng do `--btc-root` chỉ định.
  Hidden scenarios do BTC cấp qua `--scenarios`, không hardcode 7 sample.
- Python **3.12** cho AI/backend/speech; Docker Compose, PostgreSQL client và
  Internet khi cài dependency/build policy. Không dùng `pip install .` ở root
  thay cho requirements từng service; pyproject root không khai dependencies runtime.
- Credentials LLM (nếu API), Cloudflare Workers AI cho Knowledge, cùng hướng dẫn
  cấp qua kênh riêng. Không commit .env, secrets, model weights hoặc token.
  LLM local cần server tương thích và model/GPU do máy chạy provision riêng.
- Bộ audio/transcript/nhãn của team và kết quả eval được bàn giao ở artifact bundle
  riêng có hash/link tải. `.gitignore` loại `dataset/`, model và `eval/runs/`;
  có file trên máy dev không có nghĩa người chấm đã nhận được.

## 2. Cài trên checkout mới

Các lệnh setup phía dưới dành cho **DB/volume mới, chuyên dụng**. Không chạy loop
migration hay import vào DB đang có dữ liệu thật. Không dùng `docker compose down -v`
để sửa lỗi setup. Compose hiện chỉ chạy hạ tầng + MCP/worker; AI và gateway chạy host.

```bash
python3.12 -m venv ai-services/.venv
ai-services/.venv/bin/python -m pip install -r ai-services/requirements.txt
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cp -n .env.example .env
cp -n ai-services/.env.example ai-services/.env
cp -n backend/.env.example backend/.env
```

Requirements hiện là version ranges, chưa phải môi trường clean-machine đã seal.
Trước đóng gói nên xuất lock từ môi trường đã kiểm chứng, không hứa tái lập tuyệt
đối chỉ từ các ranges. Không dùng dependency của root thay cho hai venv.

Tạo sáu secret file khi chưa tồn tại, không in secret lên console:

```bash
python3.12 - <<'PY'
from pathlib import Path
import os, secrets
root = Path('secrets'); root.mkdir(exist_ok=True, mode=0o700)
for name in ('postgres_password', 'mcp_catalog_password', 'mcp_order_password',
             'mcp_memory_password', 'mcp_knowledge_password', 'mcp_internal_token'):
    path = root / name
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_hex(32) + '\n')
PY
```

Đặt cấu hình (không dùng nguyên placeholder):

| Nơi | Giá trị phải thống nhất |
| --- | --- |
| `.env` | POSTGRES_USER, POSTGRES_DB=`telesale_eval_m1`, POSTGRES_PORT (ví dụ 5432) |
| `ai-services/.env` | DATABASE_URL admin đúng DB đó cho runner/setup; AI_INTERNAL_TOKEN; MCP_INTERNAL_TOKEN khớp secret file; URL catalog/order/memory/knowledge trên localhost cổng 8011/8012/8013/8014 |
| `ai-services/.env` | LLM_BACKEND + profile model, AGENT_GUARDRAILS_ENABLED=true, KNOWLEDGE_POLICY_CONFIG_FILE là đường dẫn tuyệt đối tới config đã review; KNOWLEDGE_POLICY_SOURCE_DIR là đường dẫn tuyệt đối tới policy/ BTC |
| `backend/.env` | AI_SERVICE_URL=http://127.0.0.1:8001, AI_INTERNAL_TOKEN giống AI; AI_SERVICE_TIMEOUT_SECONDS=120 cho demo |
| `ai-services/.env` | CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN; QDRANT_URL=http://127.0.0.1:6333 |
| Knowledge workflow | KNOWLEDGE_DATABASE_URL là login reviewer, KNOWLEDGE_WORKER_DATABASE_URL là login worker riêng, KNOWLEDGE_ADMIN_DATABASE_URL chỉ cho setup/CLI grant; cùng DB với btc_source |

DSN SQLAlchemy có dạng `postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/telesale_eval_m1`.
MCP containers tự dùng password file và hostname `postgres`; không đưa DSN localhost
của host vào container. AI_INTERNAL_TOKEN khác MCP_INTERNAL_TOKEN. Với UI review,
đặt KNOWLEDGE_REVIEWER_ID ở backend như
[frontend README](../frontend/README.md). Trang mở trực tiếp, không cần mã UI;
AI_INTERNAL_TOKEN vẫn dùng cho xác thực nội bộ giữa gateway và AI.

Giữ nguyên một profile LLM cho full/baseline. Nếu local: host dùng
LOCAL_LLM_BASE_URL=http://localhost:8081/v1, container worker dùng
LOCAL_LLM_CONTAINER_BASE_URL=http://host.docker.internal:8081/v1. Server model phải
được khởi động trước worker. Nếu API: LLM_BASE_URL/LLM_MODEL/LLM_API_KEY và
LANGMEM_MODEL phải được ghi lại để tái lập; không tự đổi model giữa hai cấu hình.

Tokenizer bắt buộc bị Git ignore; chuẩn bị **trước build MCP image**:

```bash
python3.12 scripts/prepare_knowledge_tokenizer.py --download
python3.12 scripts/prepare_knowledge_tokenizer.py
```

Chỉ `--download` mới được phép HTTPS. Helper ghim revision/hash từ config, không
thay file khác hash và không tải model weights. Lệnh không có flag chỉ kiểm file.
Knowledge hiện dùng Cloudflare embedding nên không mô tả toàn bộ hệ thống là
all-local chỉ vì LLM/ASR chạy local.

## 3. Khởi tạo DB và quyền (thao tác ghi, một lần trên DB mới)

```bash
docker compose up -d postgres qdrant
ai-services/.venv/bin/python -m dataloader_offline --data-dir ../BTC-Data-Vong1-TEAMS --dry-run
ai-services/.venv/bin/python -m dataloader_offline --data-dir ../BTC-Data-Vong1-TEAMS --only-postgres
for sql in backend/migrations/*.sql ai-services/migrations/*.sql; do
  docker compose exec -T postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$sql" || exit 1
done
(cd ai-services && .venv/bin/python -m scripts.setup_langmem_store)
docker compose run --rm mcp-db-roles
```

Loader dùng DATABASE_URL trong shell nếu có, nếu không dùng backend/.env. Đảm bảo
đích đúng trước import. Setup store dùng DATABASE_URL của AI. Migrations gồm cả
`backend/0006_order_lines.sql` và `ai-services/0004_memory_job_order.sql`; không
bỏ qua hai file này theo hướng dẫn cũ. Store setup phải chạy riêng, không bọc DDL
concurrent-index trong transaction. Roles MCP được provision sau khi có bảng/store.

Migration Knowledge tạo group role NOLOGIN, chưa tạo login reviewer/worker.
Quản trị viên dùng psql tương tác (password qua `\password`, không đặt trong lệnh):

```bash
docker compose exec postgres sh -c 'psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
```

Trong psql, trên DB mới:

```sql
CREATE ROLE submission_reviewer LOGIN INHERIT;
\password submission_reviewer
GRANT knowledge_reviewer TO submission_reviewer;
CREATE ROLE submission_knowledge_worker LOGIN INHERIT;
\password submission_knowledge_worker
GRANT knowledge_worker TO submission_knowledge_worker;
GRANT CONNECT ON DATABASE telesale_eval_m1 TO submission_reviewer, submission_knowledge_worker;
```

Điền hai DSN login vào cấu hình đã nêu. Nếu dùng DB name khác thì thay tên trong
GRANT. Với môi trường đã provision, kiểm quyền hiện có, không tạo trùng role.
Cấp quyền ứng dụng cho actor reviewer, qua DSN admin:

```bash
(cd ai-services && .venv/bin/python -m app.knowledge.cli grant --actor submission-reviewer)
```

Không cấp quyền actor từ browser hoặc từ phân tích tự động. Nếu UI review dùng
actor này, đặt KNOWLEDGE_REVIEWER_ID=submission-reviewer tại backend.

## 4. Dựng Knowledge index và khởi động

Chưa có active release thì MCP Knowledge chưa phục vụ được. Import source không
tự xây index. Lệnh prepare sau **gọi Cloudflare, tiêu quota và ghi DB/Qdrant**:

```bash
ai-services/.venv/bin/python -m dataloader_offline --data-dir ../BTC-Data-Vong1-TEAMS --prepare-policy --actor submission-reviewer --runtime-config config/policy-runtime.json
```

Ghi lại release_id trong output, điền vào biến POLICY_RELEASE_ID ở shell (không
phải secret). Kiểm manifest/index trước khi activate; nếu đã có active release,
prepare và activate phải truyền `--expected-active` đúng ID đang chạy.

```bash
(cd ai-services && .venv/bin/python -m app.knowledge.cli policy-activate --actor submission-reviewer --release-id "$POLICY_RELEASE_ID" --runtime-config ../config/policy-runtime.json)
ai-services/.venv/bin/python -m dataloader_offline --data-dir ../BTC-Data-Vong1-TEAMS --verify-ingestion --release-id "$POLICY_RELEASE_ID" --runtime-config config/policy-runtime.json
docker compose --env-file .env --env-file ai-services/.env up --build -d mcp-catalog mcp-order mcp-memory mcp-knowledge
```

Hai env file có key trùng phải cùng giá trị DB/port; file thứ hai được ưu tiên.
Sau đó mở các terminal riêng:

```bash
# Terminal AI API, 1 worker:
(cd ai-services && .venv/bin/python -m app)
# Terminal demo gateway (chat không cần speech server):
backend/.venv/bin/python -m uvicorn app.voice_main:app --app-dir backend --host 127.0.0.1 --port 8000
# Terminal Knowledge Gap worker khi cần demo vòng cải tiến:
(cd ai-services && .venv/bin/python -m app.knowledge.worker)
```

Mở `/chat` để test hội thoại + brief + memory; `/knowledge` để review.
Compose đã chạy langmem-worker theo dependency mcp-memory, không chạy trùng
LangMem worker host chỉ để nạp cùng một job. Bật KNOWLEDGE_ENABLED=true ở AI
khi cần thu runtime feedback. Chạy demo 1 session M1, không claim multi-worker
session locking khi chưa kiểm chứng triển khai đó.

## 5. Lệnh BTC chấm chéo

Các lệnh dưới **gọi model và reset runtime của DB eval** trước mỗi cấu hình.
Cần hạ tầng MCP và DB eval tách riêng, cùng DB identity với runner, không trỏ
vào demo đang phục vụ. `--isolated-db` là xác nhận của người vận hành, không tự
tạo DB. Mỗi lần chọn output path mới; runner từ chối ghi đè kết quả.

```bash
ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --config full --delivery-mode text --isolated-db --expected-database telesale_eval_m1 --out eval/runs/submission-01/full.jsonl
ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --config baseline_no_memory --delivery-mode text --isolated-db --expected-database telesale_eval_m1 --out eval/runs/submission-01/baseline.jsonl
python3.12 eval/runs/submission-01/full.btc-release/eval/reference_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --trace eval/runs/submission-01/full.jsonl --baseline eval/runs/submission-01/baseline.jsonl
```

BTC thay duy nhất `--scenarios` bằng thư mục hidden. Root CLI mặc định text M1;
voice chỉ bật tường minh khi đo voice. CLI giữ tên full/baseline_no_memory và
schema trace BTC. Baseline vẫn có working memory trong phiên, không đọc prior
profile/episode giữa phiên. Không bơm facts_established hoặc ground truth vào agent.

Runner ghép gói BTC gốc + bản cập nhật tháng 11 thành `.btc-release` bất biến
cạnh trace; dùng **scorer trong snapshot đó** để không chấm tool semantics mới
bằng scorer cũ. Các source gốc không bị sửa. Toàn bộ full/baseline phải dùng cùng
model/config/source seed/knowledge release. Để có manifest/score có hash và
run.json cuối cùng, ưu tiên paired runner:

```bash
AGENT_GUARDRAILS_ENABLED=true PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.run_official --delivery-mode text --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale_eval_m1 --out-root ai-services/eval_harness/results
```

Quy tắc TTFT không streaming: TTFT=total theo mục 7 hướng dẫn BTC. Không dùng
voice TTFT proxy để tuyên bố đạt chat M1. Ít nhất 100 lượt/cấu hình sau 3 warmup
mới đủ quy mô p95. 7 sample chỉ là smoke; không thay thế bộ team/hidden.

## 6. ASR và hồ sơ chứng minh

ASR M1 chạy local. Theo [speech README](../speech/README.md), cài venv speech
riêng, chuẩn bị model local và audio BTC + >=20 file team; chạy `python -m speech
transcribe` rồi `python -m speech eval`. Không lấy output ASR từ agent hay LLM
cloud. Audio 2 người nói phải giữ tách lời khách để đưa vào cùng harness; dùng
[adapter replay](m1-acceptance.md#3-nhận-dataset-và-asr) với binding session/customer
rõ ràng, không lấy lời nhân viên/đáp án làm input. Các artifact audio/model không
được Git ship mặc định, nên bàn giao link/hash và lệnh tải riêng.

Báo cáo nộp phải có: dataset/corpus theo đề gốc, câu hỏi/claims extractor và các
ca review tay, full/baseline traces + metric BTC, ASR WER/CER/Entity trên hai bộ,
config/hardware/chi phí/cuộc, ít nhất hai vòng Knowledge Gap có nguồn feedback
và so sánh cùng controls; video/demo UI chat/brief/memory và quy trình review.
Frontend review hoạt động không thay bằng chứng chất lượng K0→K1.

Chi tiết nghiệm thu: [M1 acceptance](m1-acceptance.md). Không tự ghi “đạt” khi
run chỉ validated nhưng execution degraded/extraction needs_review. Hiện kết
quả đã xem mới có 7 sample/39 lượt: TSR 57,1%, CCR19%, 17 lỗi model; RQR đạt
trên sample nhưng chưa đủ nghiệm thu toàn bộ. Run còn tắt guardrails và chưa có
bằng chứng loop hai vòng đạt; cần xử lý/đo trước khi ghi số trong báo cáo.

## 7. Trạng thái kiểm chứng bản hướng dẫn

Đã kiểm offline: root CLI import/help, text-default/shared runner bằng stub,
secret/config boundaries trong tests hiện có, helper tokenizer với mock HTTP và
checksum local, loader dry-run. Chưa chạy toàn bộ bootstrap trên máy sạch,
chưa tải tokenizer qua mạng mới, chưa provision/migrate DB, dựng/activate index,
chạy model/eval hay ASR live trong lượt chỉnh này. Không suy thành clean-machine
pass từ việc README có lệnh. Cần một lượt rehearsal trên môi trường tách biệt
sau khi chốt model và credentials.
