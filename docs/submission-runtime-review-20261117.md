# Review và gom luồng nộp BTC — 2026-11-17

Đã gom chat về Deep Agent gọi API và streaming có guardrails. Xóa hỗ trợ LLM
local và lựa chọn chạy text không streaming. Giữ Deep/ReAct sau interface chung
`build_agent`; harness nộp bài chọn Deep. Review này phục vụ demo trên
stack hiện có và paired eval 29 kịch bản, không chứng nhận tải nhiều worker.

## Phần đã xóa và cập nhật

- Xóa `local_llm.py`, hai test chỉ dành cho local, hai script vLLM và tài liệu
  vLLM. Giữ implementation ReAct và factory chung với Deep; không thêm lớp abstract
  khác. Bỏ cấu hình local/agent selector trong Settings,
  env mẫu, container worker và Compose; LangMem dùng schema API thông thường.
- Agent chỉ gọi `astream`. `runtime.run(text)` thu kết quả từ cùng lõi guarded
  streaming cho những caller cần câu trả lời hoàn chỉnh. Voice dùng chung lõi
  model, vẫn lưu memory sau playback receipt. Graph kết thúc ở verifier;
  runtime chịu trách nhiệm lưu text đã phát.
- Paired eval, warmup, single-trace CLI và Full K1 mặc định dùng streaming.
  Xóa `--agent`, `--delivery-mode`, `--streaming` khỏi CLI. Sửa `system_start`
  để không tự thêm cờ đã xóa. Xóa hàm in bảng cũ không còn caller thực.
- Giữ Full/baseline vì đây là hai cấu hình đánh giá memory của BTC. Giữ
  voice/ASR, knowledge review, guardrails và đọc báo cáo lịch sử theo hợp đồng
  latency ban đầu. Không sửa saved trace, BTC score hoặc threshold.
- Cập nhật các test của caller và hướng dẫn chạy. Không đổi `.env` có secrets,
  model đang cấu hình, dữ liệu runtime hoặc container đang chạy.

## Must fix trước khi nộp

1. **Đơn nhiều sản phẩm có thể bị thu thành một sản phẩm.**
   `test_basket_runtime.py:74`, `test_basket_runtime.py:150` và
   `test_session_state.py:53` tái hiện: yêu cầu báo giá hai AirPure Pro có thể
   nhận báo giá một chiếc 7.690.000đ thay vì tổng 11.685.000đ; xác nhận sau đó
   có thể tạo đơn một chiếc. Các ca đổi quantity/product cũng chưa đạt.
   Cần giữ đúng basket và kiểm tra đủ sản phẩm/số lượng trước khi dùng câu trả
   lời sớm hoặc cho phép tạo đơn. Bỏ qua sẽ dẫn tới báo giá/đặt hàng sai.

2. **Replay SAMPLE-01 thiếu fact diện tích phòng.**
   `test_session_product_resolution.py:163` thất bại ở kiểm tra
   `initial['profile']['room_area_m2']['value'] == 25`, cả text và voice.
   Cần đối chiếu nơi ghi fact và scope mà runtime đọc lại trước khi sửa;
   log hiện tại chưa đủ kết luận memory mất fact hay test đang đọc sai scope.
   Bỏ qua sẽ không có bằng chứng regression đạt cho ngữ cảnh quay lại này.

Hai nhóm trên còn **14 case thất bại** trong batch runtime. Không xóa/skip các
test này để làm kết quả xanh. Chúng còn tái hiện khi thay riêng hàm gọi agent
bằng `ainvoke` cũ; replay đối chứng không đổi nghiệp vụ/guardrails và không gọi
model thật. Đây là bằng chứng lỗi không chỉ xuất hiện do chuyển lời gọi sang
`astream`, chưa phải kết luận nguyên nhân gốc.

## Kiểm chứng offline

Log nằm trong `ai-services/eval_harness/results/measurement-audit/`, tiền tố
`20261117-submission-prune-`:

| Lần kiểm tra | Kết quả | Log |
|---|---|---|
| Eval, K1, latency contract, đọc report cũ và LangMem | 167 passed, 8 failed, 3 skipped trước khi sửa test/caller | `eval-initial.txt` |
| Chạy lại các file eval có lỗi sau sửa | 22 passed, 2 skipped | `eval-retest.txt` |
| Runtime, guardrails, API, memory và business regression | 172 passed, 17 failed ban đầu | `runtime-initial.txt` |
| Chạy lại ba file đã sửa SSE stub, token offline và kỳ vọng model-call của route sớm | 19 passed; sửa được 3 lỗi ban đầu | `runtime-retest.txt` |
| Entry point, execution diagnostics và reset sau sửa caller cuối | 37 passed, 2 skipped | `entrypoint-tests.txt` |
| Deep/ReAct qua factory chung, guarded streaming runtime và execution diagnostics sau khi giữ lại ReAct | 36 passed | `react-interface-tests.txt` |
| Đối chứng basket bằng cách gọi agent cũ | 6 failed, 11 deselected | `old-invocation-basket.txt` |
| Đối chứng SAMPLE-01 bằng cách gọi agent cũ | 2 failed, 21 deselected | `old-invocation-brief.txt` |

Các batch có giao nhau, không cộng số passed thành tổng. Các skip trong eval
là kiểm tra cần PostgreSQL thật. Bộ kiểm tra syntax cho Python đã đổi và
`git diff --check` cũng đạt. Không chạy full suite, live eval, benchmark latency,
ASR thật, restart Docker hoặc ghi dữ liệu ngoài.

## Lệnh eval sau khi dọn

Chỉ chạy khi đã sẵn sàng gọi model thật và reset runtime của database eval:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python3 run_system.py eval --expected-database telesale -- \
  --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --out-root ai-services/eval_harness/results/paired-knowledge
```

**Verdict: chưa Ship để nộp BTC; sửa hai finding trên trước.** Phần gom nhánh
đã thực hiện; latency và các cổng nghiệm thu M1 vẫn cần bằng chứng của một lần
eval mới sau khi sửa nghiệp vụ. Các số đo cũ không chứng minh checkout mới đạt.
