# Chat streaming có guardrails — 17/11/2026

Đã triển khai streaming từ business agent qua AI API, backend WebSocket và trang chat. **Chưa có số đo model thật cho phiên bản này; chưa kết luận đạt TTFT p95 ≤3 giây hoặc nghiệm thu M1.**

## Cách giữ kiểm tra trước khi phát

- Agent dùng message streaming của LangGraph/LangChain; không thêm một lần gọi model để viết lại câu trả lời. Adapter OpenAI-compatible được kiểm tra bằng SSE giả lập, có barrier giữ provider chưa kết thúc trong khi delta đã tới consumer.
- Runtime giữ các token trong buffer đến khi có đơn vị nội dung hoàn chỉnh. Phần tích lũy phải qua grounding, kiểm tra câu trả lời và kiểm tra đủ yêu cầu trước khi phát. Không lấy tool arguments, reasoning hoặc câu “đang kiểm tra” làm phản hồi đầu tiên.
- Giá/quyền lợi có đủ nguồn có thể được phát trước phần diễn giải tiếp theo. Chính sách, dữ liệu cá nhân, yêu cầu đổi/trả, callback, handoff và mua hàng được giữ đến câu trả lời hoàn chỉnh đã qua verifier; không gửi riêng một cam kết rồi chờ điều kiện ở câu sau.
- Quyền xem đơn, ngày áp dụng chính sách, consent và receipt giao dịch vẫn kiểm trước tool/khẳng định hoàn tất. Sau khi đã phát một phần câu trả lời đủ yêu cầu, business tools bị khóa cho phần còn lại của lượt để tránh thay đổi bằng chứng đang hỗ trợ nội dung đã phát.
- Verifier toàn lượt vẫn chạy. Không thay thế nội dung đã gửi bằng một câu trả lời khác; chỉ nối phần còn lại/khối bổ sung nếu hợp lệ. Khi bản cuối bị loại, phần đã phát độc lập và đủ yêu cầu được giữ lại.
- Streaming yêu cầu bật answer guardrails và chỉ dùng cho text. API text thường và voice vẫn dùng hợp đồng hiện có.

## Ngắt kết nối và memory

Graph hoãn persistence của streaming; runtime lưu phần đã phát tại ranh giới runtime/backend, không lưu draft đang đợi kiểm tra. Đây không phải bằng chứng khách đã đọc/render nội dung. Khi transport ngắt, runtime dừng phát, để thao tác đang chạy kết thúc dưới cùng session lock/timeouts rồi lưu prefix đã phát cùng các tool observations thực.

Retry dùng cùng session/turn/payload không chạy lại model hoặc callback/đơn hàng đã thực hiện. Nếu đã phát prefix, replay prefix đã lưu. Nếu lượt trước bị ngắt trước khi phát bất kỳ nội dung nào, retry streaming báo `turn_interrupted`, không giả vờ đã lưu câu trả lời đầy đủ. Không tự retry model ở backend. Shutdown drain các turn còn chạy.

Giao diện dùng một bong bóng với `textContent`; khi stream bị ngắt, phần đã nhận vẫn giữ lại và có thông báo lỗi. Không hiển thị HTML do model/khách cung cấp như DOM.

## Protocol và cách đo

- AI: `POST /v1/chat/turns/stream`, giữ internal-token authentication và request validation, trả `application/x-ndjson`.
- `delta` gồm session/turn ID, `seq` tăng liên tục và `text`; `done` gồm response hiện hữu sau persistence. `error` chỉ có mã lỗi giới hạn, không gửi exception body.
- Backend kiểm ID/thứ tự/terminal và yêu cầu tổng delta bằng `agent_text` cuối trước khi phát `agent_reply`. Stream sai/truncated thành lỗi, không thành một câu trả lời hoàn tất.
- Canonical paired runner mặc định streaming; Full, baseline, warmup và Full K1 dùng cùng chế độ, không còn cờ chọn chế độ. TTFT bắt đầu từ request đến delta trả lời không rỗng đầu tiên đã qua kiểm tra; Total đến completion/persistence. Prepare/worker wait vẫn đo riêng. Stream thiếu delta hoặc done làm phép đo thất bại; không lấy Total làm TTFT thay thế.
- Trace ghi `streaming`, `answer_delta_count`, `stream_completed`, `ttft_is_proxy=false`; manifest và runner report cùng ghi streaming. M1 evidence checks yêu cầu metadata khớp ở cả hai nhánh. Không đổi scorer BTC, ngưỡng TTFT 3000 ms/Total 8000 ms hoặc artifact lịch sử.

Với các lượt phải giữ toàn bộ câu trả lời, TTFT vẫn có thể gần Total. Streaming này chưa chứng minh loại bỏ hàng đợi/độ trễ provider hoặc chắc chắn đạt ngưỡng; cần phép đo thật.

## Kiểm chứng offline

- AI/runtime/eval: **267 passed, 2 skipped trong 11.46 s**, [log focused batch](../ai-services/eval_harness/results/measurement-audit/20261117-guarded-streaming-ai-tests.txt). Kiểm buffer, nguồn giá/tồn kho, điều kiện policy, PII chia chunk, tool arguments chia chunk, adapter SSE, final recovery, ngắt giữa callback, retry, memory prefix, API auth và hợp đồng đo TTFT.
- Backend/frontend: **24 passed trong 6.25 s**, [log WebSocket và Chrome](../ai-services/eval_harness/results/measurement-audit/20261117-guarded-streaming-backend-tests.txt). Có barrier chứng minh bong bóng xuất hiện trước done, không nhân đôi, không thực thi HTML, và không mất phần trả lời khi stream bị ngắt.
- `git diff --check` đạt. Không chạy full suite; PostgreSQL integration trực tiếp được skip trong wrapper offline.
- Self-review thực hiện inline theo yêu cầu không dùng subagent; chưa có review độc lập. Các vấn đề tìm được đã có regression: máy xuất tool JSON, guardrails bị tắt, dữ liệu liên hệ chưa đủ, graph lifecycle/stream flag, ngắt trong lúc ghi callback và thông báo UI bị ngắt.
- Preflight chỉ đọc xác nhận bốn MCP và runner cùng DB `telesale`, server start `2026-11-17T04:16:16.501978+00:00`, knowledge release `policy-79dd0a921214cb762c5e4514232d9522`. Model/provider/temperature/max_tokens/history khớp run `20261117T080357Z-d1f6f8e2`; guardrails và knowledge bật. Chưa reset DB hoặc gọi model trong goal này.

## Lần đo thật cần được duyệt

Chạy đúng một cặp Full/Baseline, mỗi nhánh 170 lượt và 3 warmup; reset runtime trên DB eval `telesale` trước mỗi nhánh. Giữ model `gemma4:31b`, temperature 0.2, max_tokens 256, seed 7, deep agent, cùng frozen scenarios/BTC snapshot. Không chạy đồng thời chat/eval trên DB này. Lệnh dưới không phát hành K1 hay tự chạy knowledge followup:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true PYTHONPATH=.:ai-services \
ai-services/.venv/bin/python -u - <<'PY'
import asyncio, json
from pathlib import Path
from eval_harness.run_official import run_pair
from eval_harness.report_metrics import render_run

base = Path('ai-services/eval_harness/results/paired-knowledge/20261117T080357Z-d1f6f8e2').resolve()
prior = json.loads((base / 'run.json').read_text())
out = asyncio.run(run_pair(
    scenarios=base / 'scenarios', btc_root=Path(prior['btc_root']),
    agent='deep', seed=7, out_root=base.parent, expected_database='telesale',
    delivery_mode='text', streaming=True,
))
run = json.loads((out / 'run.json').read_text())
print(f"{run['status']}: {out / 'run.json'}", flush=True)
if run['status'] != 'validated':
    raise SystemExit(1)
print(render_run(out, btc_root=Path(run['btc_root'])), flush=True)
PY
```

Sau khi chạy phải kiểm execution health, schema/hash integrity, TTFT/Total của cả hai nhánh và chất lượng RQR/CCR/TSR/HR/guardrail. Extraction review, ASR, demo và chi phí vẫn là bằng chứng riêng của M1.
