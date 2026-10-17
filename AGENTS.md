# TeleSale-SudoCode2026 — hướng dẫn cho coding agent

Cập nhật: 2026-10-15. Dữ liệu BTC: gói Vòng 1, `reference_date=2026-10-15`; gói không có mã phiên bản độc lập được khai báo. Khi gói hoặc code đổi, kiểm lại các bản chụp ở `docs/`.

## Cách làm việc và nguồn chuẩn

- Đọc file liên quan và `git status` trước khi sửa; giữ thay đổi sẵn có. Người dùng hỏi kiến trúc/đánh giá thì chỉ phân tích; chỉ viết code khi được yêu cầu triển khai cụ thể.
- Đề PDF và gói BTC mặc định ở thư mục cha repo: `../SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf`, `../BTC-Data-Vong1-TEAMS/`. Dataloader có thể nhận `BTC_DATA_DIR`/`--data-dir`; không hard-code `/home/...`. Nếu file không có ở đường dẫn mặc định, tìm đường dẫn thực trước khi kết luận.
- Thứ tự nguồn: `DIEU-CHINH-DE.md` và `GIAI-DAP-MENTOR.md` của BTC ưu tiên hơn PDF ở điểm đã sửa; `schemas/tools.schema.json` là chuẩn tên/tham số, `eval/mock_tools.py` là chuẩn kết quả, `eval/reference_eval.py` là chuẩn phép chấm. Sample và `asr/ground_truth.json` dùng để kiểm thử, không phải dữ liệu đầu vào runtime. Không sửa dữ liệu BTC gốc khi chưa được yêu cầu.
- Ngày của cuộc gọi là `2026-10-15` mặc định hoặc tính từ `call_date`/`days_later`; truyền qua `on` cho tool. Không dùng ngày máy để tính giá, KM, tồn kho, chính sách, hẹn hoặc giao hàng.

## Tránh overfit vào test và public sample

- Trước khi sửa lỗi, nêu hành vi sai, quy tắc nghiệp vụ hoặc hợp đồng bị vi phạm, và nguyên nhân ở đúng lớp xử lý. Dùng test để tái hiện lỗi; không lấy một input, output hay điểm chấm làm đặc tả đầy đủ.
- Thiết kế theo dữ liệu và tham số runtime: không rẽ nhánh theo `scenario_id`, tên sample, nhãn đáp án, câu thoại nguyên văn, tên khách, SKU/ID hoặc ngày chỉ xuất hiện trong fixture. Chỉ dùng ngoại lệ cụ thể khi nguồn nghiệp vụ có thẩm quyền quy định và ghi rõ nguồn đó.
- Khi sửa prompt, chuẩn hóa đầu vào, routing hoặc luật tool, kiểm tra ít nhất một trường hợp cùng lớp lỗi nhưng khác cách diễn đạt hoặc sản phẩm, và một trường hợp đối chứng không được đổi hành vi. Giữ các điều kiện có cấu trúc của khách khi mở rộng truy vấn; không âm thầm nới giá, diện tích, quyền sở hữu hay ngày hiệu lực để có kết quả.
- Đặt luật nghiệp vụ xác định được trong service/harness theo đúng ranh giới; prompt chỉ hướng dẫn model. Không thêm danh sách từ khóa, regex hay fallback chỉ khớp câu của một sample nếu không giải thích được phạm vi áp dụng và tác dụng phụ trên dữ liệu khác.
- Test với mock BTC để giữ hợp đồng, rồi kiểm luồng liên quan trên dữ liệu/biến thể ngoài ca tái hiện. Nếu nhãn sample mâu thuẫn với schema, mock, tài liệu điều chỉnh hoặc lời khách, giữ hành vi đúng nguồn chuẩn, ghi lại mâu thuẫn và không sửa runtime/trace để đạt điểm.
- Khi báo hoàn tất, tách rõ điều đã kiểm bằng unit/mock, public sample và hệ thống thật; nêu giới hạn còn lại. Một test xanh hoặc điểm eval cao không tự chứng minh hành vi tổng quát.

## Ranh giới hệ thống

- `backend/` xác thực frontend, quản lý phiên và chuẩn hóa request gửi AI; nghiệp vụ CRM/catalog/order nằm ở `ai-services/`. Luồng text-to-text và memory xuyên phiên đi trước audio/voice.
- `ai-services/` dùng LangGraph `StateGraph` tường minh. Ba MCP hiện có: catalog (CRM/sản phẩm/tồn kho/quote), order (đơn/callback/handoff), memory; mỗi server có repo/pool/role PostgreSQL riêng. Giữ tool mỏng, service chứa nghiệp vụ, SQL ở repo. PostgreSQL là nguồn chính; Redis/Qdrant không thay thế fact có cấu trúc.
- M1 tra chính sách có hiệu lực qua `policy.search` trong `mcp-catalog`, đọc `btc_source.policy_chunks` và lọc quyền/ngày trước khi trả cho agent. Không thêm MCP server chỉ để tra chính sách M1. Qdrant và tìm kiếm ngữ nghĩa chưa nối runtime.
- Fact/slot và điều kiện gọi tool do code quản lý; LLM diễn đạt và có thể đề xuất ứng viên. Giá đã báo chỉ là lịch sử, mọi giá/KM/tồn kho phải lấy lại từ tool theo ngày gọi. `order_id`/`ticket_id` chỉ lấy từ kết quả tool thành công; không hard-code nhãn sample vào runtime. Xem [harness-spec](docs/harness-spec.md), [tool-contract](docs/tool-contract.md) và [public-sample-traps](docs/public-sample-traps.md) khi sửa phần tương ứng.
- Địa chỉ/PII có thể đi tới nghiệp vụ giao hàng qua kho có kiểm soát; prompt, checkpoint, vector store và trace chỉ dùng ref/bản che. `address_ref` là thiết kế đề xuất, **chưa triển khai**. Không ghi API key/DSN có mật khẩu; không dùng dữ liệu khách thật chưa được phép.

## Bản đồ repo và trạng thái hiện tại

| Vị trí | Trách nhiệm / trạng thái ngày 2026-10-15 |
|---|---|
| `ai-services/app/agent/` | `chat.py` là entrypoint một lượt; `factory.py` chọn Deep hoặc ReAct agent; `graph.py` nối các node trong `harness/`. `memory/` và `guardrails/` là các khối riêng, `mcp/gateway.py` nối tới ba MCP server. Lock/idempotency của runtime chỉ trong một worker. |
| `ai-services/app/mcp_servers/` | Ba server `mcp_catalog`, `mcp_order`, `mcp_memory` có `tools/`, `services/`, `repos/`; catalog có `policy.search`. |
| `ai-services/app/api/`, `backend/app/api/` | AI nhận `/v1/chat/turns`; backend là đầu vào frontend, không sở hữu business tool. |
| `dataloader_offline/`, `ai-services/migrations/`, `backend/migrations/` | Dataloader hỗ trợ nạp BTC, gồm `policy_chunks`, vào `btc_source`; migration tạo runtime/memory tables. Chưa xác minh DB hiện tại đã nạp đủ. |
| `run_eval.py` | Entrypoint hiện import `eval.run_eval` nhưng package `eval/` không có trong checkout này; lệnh eval full/baseline chưa chạy được. |

Đây là ảnh chụp, không phải luật: kiểm tra code trước khi dựa vào trạng thái trên. `config/*.yml` là cấu hình khai báo; runtime dùng `.env`/biến môi trường.

## Lệnh thực tế

Chạy từ gốc repo, với Python 3.12 cho AI/backend. `pyproject.toml` ở gốc chưa khai báo dependency của hai service; dùng `requirements.txt` của từng service:

```bash
python3.12 -m venv ai-services/.venv
ai-services/.venv/bin/pip install -r ai-services/requirements.txt
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
docker compose up -d postgres redis
python3.12 -m venv .venv-dataloader
.venv-dataloader/bin/pip install -r dataloader_offline/requirements-postgres.txt
.venv-dataloader/bin/python -m dataloader_offline --only-postgres
```

Áp migration theo đúng thứ tự và cấu hình môi trường trong `ai-services/README.md`; sau đó chạy `docker compose --env-file .env --env-file ai-services/.env up -d --build mcp-catalog mcp-order mcp-memory` và `(cd ai-services && .venv/bin/python -m app)` cho demo. Lệnh kiểm tra import ở `dataloader_offline/README.md`.

```bash
(cd ai-services && .venv/bin/python -m unittest discover -s test -v)
(cd backend && .venv/bin/python -m unittest discover -s test -v)
ai-services/.venv/bin/python -m unittest discover -s eval -v
git diff --check
```

Repo chưa có cấu hình lint thống nhất; `git diff --check` chỉ kiểm tra whitespace. Không báo “lint xanh” nếu chưa chạy linter thật. Sau khi khôi phục package `eval/`, dùng `ai-services/.venv/bin/python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config full --out eval/runs/full.jsonl` và lặp lại với `baseline_no_memory`. Dùng DB eval tách biệt và reset bảng runtime có trạng thái giữa hai cấu hình; chạy `../BTC-Data-Vong1-TEAMS/eval/reference_eval.py` trên hai trace. Chi tiết ở `README.md`.

## Khi coi là xong

- Test tập trung cho phần sửa qua, test của service liên quan qua; thay đổi memory/tool/giá/routing phải chạy public sample đa phiên liên quan. Trace JSONL phải hợp lệ theo `schemas/trace_log.schema.json` và phản ánh tool/memory write thật.
- Khi sửa hợp đồng tool hoặc clock nghiệp vụ, bổ sung kiểm tra tự động cho tên/tham số BTC và việc không dùng wall clock trong tính toán; khi sửa harness/eval, kiểm tra không có nhánh runtime đọc `scenario_id`/nhãn đáp án. Hiện chưa có gate lint/AST chung, nên không khẳng định các luật này đã được máy enforce.
- Full và baseline dùng cùng model, dữ liệu, tham số và tool; baseline chỉ bỏ memory từ phiên trước. Đối chiếu RQR/CCR/TSR/HR với `reference_eval.py`; kiểm WER/CER/Entity Accuracy khi sửa ASR.
- Báo file đã sửa, hành vi mới, lệnh đã chạy và giới hạn kiểm chứng. Nếu chưa chạy PostgreSQL, MCP HTTP hoặc LLM thật thì nói rõ phần nào chỉ kiểm bằng mock.
