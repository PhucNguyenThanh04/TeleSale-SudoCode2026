# Chạy bản nộp M1 và chấm chéo BTC

Nguồn yêu cầu: `BTC-Data-Vong1-TEAMS/README.md` (Quy trình chấm chéo),
`DIEU-CHINH-DE.md` và `GIAI-DAP-MENTOR.md`. Deadline cụ thể không nằm trong gói;
BTC thông báo riêng. Hướng dẫn này chốt đường M1: chat text + ASR local offline.
Voice/TTS và simulator/LLM judge M2 không phải điều kiện khởi động M1.

## 1. Những gì người chấm cần nhận

- Checkout đủ source, `ai-services/app/bootstrap/schema.sql`, `config/policy-runtime.json`, metadata policy
  và lệnh root `run_eval.py`. Không bỏ file mới chưa track.
- Gói BTC đầy đủ, đã cập nhật scorer/mock tools/schema, bên cạnh repo hoặc đường
  dẫn riêng do `--btc-root` chỉ định; không cần thư mục patch riêng.
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

Các lệnh setup phía dưới dành cho **DB/volume mới, chuyên dụng**. Không import hay khởi động fresh-system vào DB đang có dữ liệu thật. Không dùng `docker compose down -v`
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
| `ai-services/.env` | LLM_API_KEY/LLM_MODEL/LLM_BASE_URL + LANGMEM_MODEL, AGENT_GUARDRAILS_ENABLED=true, KNOWLEDGE_POLICY_CONFIG_FILE là đường dẫn tuyệt đối tới config đã review; KNOWLEDGE_POLICY_SOURCE_DIR là đường dẫn tuyệt đối tới policy/ BTC |
| `backend/.env` | AI_SERVICE_URL=http://127.0.0.1:8001, AI_INTERNAL_TOKEN giống AI; AI_SERVICE_TIMEOUT_SECONDS=120 cho demo |
| `ai-services/.env` | CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN; QDRANT_URL=http://127.0.0.1:6333 |
| Knowledge workflow | KNOWLEDGE_DATABASE_URL là login reviewer, KNOWLEDGE_WORKER_DATABASE_URL là login worker riêng, KNOWLEDGE_ADMIN_DATABASE_URL chỉ cho setup/CLI grant; cùng DB với btc_source |

DSN SQLAlchemy có dạng `postgresql+asyncpg://USER:PASSWORD@127.0.0.1:PORT/telesale_eval_m1`.
MCP containers tự dùng password file và hostname `postgres`; không đưa DSN localhost
của host vào container. AI_INTERNAL_TOKEN khác MCP_INTERNAL_TOKEN. Với UI review,
đặt KNOWLEDGE_REVIEWER_ID ở backend như
[frontend README](../frontend/README.md). Trang mở trực tiếp, không cần mã UI;
AI_INTERNAL_TOKEN vẫn dùng cho xác thực nội bộ giữa gateway và AI.

Giữ nguyên profile API cho full/baseline: LLM_BASE_URL/LLM_MODEL/LLM_API_KEY và
LANGMEM_MODEL phải được ghi lại để tái lập; không tự đổi model giữa hai cấu hình.
Deep Agent và streaming có guardrails là luồng text duy nhất. Eval pair, warmup
và Full K1 cùng dùng luồng này. Không còn chọn local LLM, ReAct hoặc text không
streaming. Voice/ASR vẫn được giữ cho demo và kiểm chứng M1 riêng.

Tokenizer bắt buộc bị Git ignore; chuẩn bị **trước build MCP image**:

```bash
python3.12 scripts/prepare_knowledge_tokenizer.py --download
python3.12 scripts/prepare_knowledge_tokenizer.py
```

Chỉ `--download` mới được phép HTTPS. Helper ghim revision/hash từ config, không
thay file khác hash và không tải model weights. Lệnh không có flag chỉ kiểm file.
Knowledge hiện dùng Cloudflare embedding nên không mô tả toàn bộ hệ thống là
all-local chỉ vì LLM/ASR chạy local.

## 3. Nạp nguồn BTC một lần

```bash
docker compose up -d postgres
ai-services/.venv/bin/python -m dataloader_offline --data-dir ../BTC-Data-Vong1-TEAMS --only-postgres
```

Loader tạo/insert `btc_source` và không tự invent CRM. DATABASE_URL của loader,
AI và backend phải cùng DB đích. Không chạy vòng lặp migration/setup store/grant
bằng tay nữa: đường khởi động mới tự tạo schema hiện hành và các quyền cần thiết.

## 4. Khởi động hệ thống một lần trước demo/eval

Sau khi điền cấu hình/secret và tokenizer ở bước 2:

```bash
python run_system.py demo --expected-database telesale_eval_m1
```

Nếu Docker cần sudo, thêm `--sudo-docker`. Lệnh tự tạo/reset operational schema
của backend + AI, cả knowledge đã duyệt; setup LangGraph store, login DB từ cấu
hình, quyền MCP/reviewer, hai tài khoản demo và policy BTC nền, rồi bật các server.
Không phải mở thêm uvicorn/API/knowledge worker ở terminal khác. Không thêm dữ
liệu vào BTC và không xóa kết quả eval đã xuất. Policy index BTC được khôi phục
nếu cache còn đúng hash; lần chưa có cache cần Cloudflare embedding/quota.

Khởi động demo mới tạo boot ID và reset knowledge. Eval thường dùng hạ tầng
đang chạy, chỉ reset runtime/memory trước mỗi cấu hình; `run_system.py eval`
không gọi Docker hoặc tạo boot mới. Giữ cùng hệ thống giữa K0 → duyệt → K1,
không chạy lại fresh demo. Các service có thể tiếp tục chạy để dùng frontend,
nhưng không thao tác chat/eval khác trên DB trong lúc đo.
Cấu hình account, phạm vi reset và recovery:
[xem hướng dẫn fresh-system](fresh-system-startup.md).

Các command thấp hơn ở phần tiếp theo dành cho BTC/kiểm chứng độc lập trên stack
đã khởi tạo; chúng không thay thế ranh giới boot của cả hệ thống.

## 5. Lệnh BTC chấm chéo

Các lệnh dưới **gọi model và reset runtime của DB eval** trước mỗi cấu hình.
Cần hạ tầng MCP và DB eval tách riêng, cùng DB identity với runner, không trỏ
vào demo đang phục vụ. `--isolated-db` là xác nhận của người vận hành, không tự
tạo DB. Mỗi lần chọn output path mới; runner từ chối ghi đè kết quả.

```bash
ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --config full --isolated-db --expected-database telesale_eval_m1 --out eval/runs/submission-01/full.jsonl
ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --config baseline_no_memory --isolated-db --expected-database telesale_eval_m1 --out eval/runs/submission-01/baseline.jsonl
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
AGENT_GUARDRAILS_ENABLED=true PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.run_official --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale_eval_m1 --out-root ai-services/eval_harness/results
```

Text mặc định streaming có guardrails: TTFT tới delta trả lời đầu tiên đã qua
kiểm tra; Total gồm hoàn tất nội dung và persistence. Báo cáo không streaming
cũ vẫn theo mục 7 hướng dẫn BTC (`TTFT=Total`). Không dùng voice TTFT proxy để
tuyên bố đạt chat M1. Ít nhất 100 lượt/cấu hình sau 3 warmup mới đủ quy mô p95.
7 sample chỉ là smoke; không thay thế bộ team/hidden.

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
