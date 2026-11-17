# Eval trên hạ tầng đang chạy, reset memory công bằng

`run_system.py eval` giờ gọi thẳng paired runner và kết thúc sau metrics/detect.
Nó không gọi Docker, tạo boot/schema, reset knowledge, khởi động/dừng API/MCP
hay lấy khóa của managed demo. Model, DB và MCP cần đã chạy; frontend đang chạy
được giữ nguyên để duyệt gap. Fresh demo và thí nghiệm auto-review cũ vẫn là
những chế độ riêng, không đổi thành yêu cầu của eval thường.

Lệnh từ root repo, trên DB eval đã cấu hình:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python3 run_system.py eval --expected-database telesale -- \
  --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --out-root ai-services/eval_harness/results/paired-knowledge
```

Trước mỗi cấu hình, canonical runner warmup rồi reset cùng phạm vi runtime:
conversation/turn, memory store, job và trạng thái nghiệp vụ tạm. BTC, knowledge,
tài khoản demo và migration metadata được giữ. No memory không đọc prior liên
phiên; Full bắt đầu sạch rồi tích lũy memory giữa các cuộc gọi trong lượt của nó.
Sau khi người dùng duyệt/phát hành trên frontend, `run_knowledge_eval.py --base-run
RUN` chỉ chạy Full K1, reset runtime bằng cùng cơ chế và giữ knowledge K1.
Không chạy chat/eval khác trên cùng DB trong lúc đánh giá.

Vì worker không bị restart cùng mỗi eval, reset giữ bộ đếm job nội bộ tăng liên
tục. Các bảng runtime được khóa trước khi đọc bộ đếm, truncate rồi phục hồi bộ
đếm job. Job cũ sẽ không trùng ID với job mới và bị kiểm tra claim loại bỏ; ID
nghiệp vụ vẫn reset như cũ. Đây không phải giữ lại memory của khách hàng.

Lệnh file K1 được in sau detect giữ đúng pin/config/boot khi có; không tự ép
KNOWLEDGE_RELEASE_ID thành rỗng nếu cặp đầu không dùng giá trị đó. Như vậy không
tạo khác biệt settings giữa cặp đầu và file K1.

## Đối chiếu yêu cầu

| Yêu cầu | Bằng chứng hiện tại |
|---|---|
| Eval không cần quyền điều khiển Docker | system_start.main dispatch eval trước bootstrap/boot/lock; public CLI test cấm compose, bootstrap, server Popen và get_settings ở launcher |
| Dùng hệ thống đang chạy | Public CLI test giữ khóa demo thật bằng flock, vẫn chạy eval, giữ nguyên boot/release pin, trả đúng exit code khi child thất bại |
| Memory sạch cùng cơ chế cho cả hai cấu hình | execute_configuration → prepare_runtime_for_eval → reset_runtime_database; test thực thi lifecycle/reset SQL với transport RAM ở cả thứ tự Full/No-memory và No-memory/Full |
| Giữ memory giữa các cuộc gọi trong Full | Lifecycle test có hai cuộc gọi, kiểm context call_1 còn ở call_2 và chỉ một reset mỗi cấu hình |
| Full K1 cũng reset nhưng giữ knowledge | Cùng lifecycle test chạy thêm Full với release K1; kiểm knowledge không bị sửa và đủ ba reset |
| Worker cũ không nhận nhầm job mới sau reset | Regression dựng job ID cũ=1: trước sửa next ID cũng=1; sau sửa next ID lớn hơn, và sequence snapshot chỉ đọc sau khóa bảng |
| Không reset nguồn/knowledge/account | SQL scope test loại btc_source, knowledge, demo_users, store_migrations khỏi SQL reset |
| Cặp đầu detect, file khác chỉ Full K1 | Follow-up test dùng worker/approve/collector RAM thật, chỉ ghi ba arm; ba case pin unset/empty/explicit giữ đúng lệnh file K1 |
| BTC vẫn chạy chuẩn một cấu hình | eval/test_run_eval.py cùng canonical runner đạt regression; run_eval.py và eval/run_eval.py không đổi trong lượt này |

## Kiểm thử offline

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/test/test_knowledge_repo.py ai-services/test/test_system_start.py \
  ai-services/eval_harness/test_runtime_reset.py ai-services/eval_harness/test_run_official.py \
  ai-services/eval_harness/test_knowledge_followup.py ai-services/eval_harness/test_knowledge_triplet.py \
  eval/test_run_eval.py --tb=short
```

Kết quả: **105 passed, 2 skipped**. Hai bài PostgreSQL thật được bỏ qua theo phạm
vi offline. Wrapper chặn network và không nạp credentials/.env. Không chạy full
suite. `python3 run_system.py eval --help` đạt, git diff --check đạt cho các file
tracked của thay đổi này.

Chưa chạy LLM/ASR/embedding, Docker, bootstrap hoặc reset DB thật. Bằng chứng ở
đây xác nhận code và kiểm thử offline; chưa có metrics M1 mới hay chứng nhận môi
trường dịch vụ thật đang sẵn sàng.
