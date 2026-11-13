# Chạy ba cấu hình và duyệt knowledge mô phỏng bằng CLI

Muốn mỗi thí nghiệm bắt đầu bằng hệ thống sạch (tự tạo bảng, reset cả knowledge),
dùng `python run_system.py knowledge-eval ...` từ root. Khi resume một thí nghiệm
managed, dùng launcher với `--resume` để giữ boot ID; không bắt đầu boot mới.
[Hướng dẫn fresh-system](../../docs/fresh-system-startup.md) có lệnh đầy đủ.

Lệnh này chạy đúng ba cấu hình hội thoại theo thứ tự:

1. **A — No memory K0**.
2. **B — Full memory K0**, cùng release với A.
3. Phân tích feedback từ những lượt B được chỉ định, duyệt **mô phỏng** theo
   kế hoạch có nguồn đã được kiểm tra trước, phát hành K1.
4. **C — Full memory K1**. Không chạy thêm baseline K1.

Mỗi cấu hình dùng vòng đời reset/warmup/runtime thật của harness. C không mang
memory đã tích lũy trong lần B sang. Không thay đổi dữ liệu `btc_source` hay
file BTC. Knowledge/review/release được lưu riêng; reset runtime giữ các bảng này.

Đây là **thí nghiệm có người xác nhận nội dung trước**, không phải model tự tạo
đáp án rồi tự xác nhận đáp án của nó đúng. Mọi output ghi rõ
`simulated_pre_reviewed_plan`. Nó chứng minh cơ chế và đo số liệu của một lần
chạy; không tự chứng minh chất lượng của người duyệt hoặc ý nghĩa thống kê.

## Chuẩn bị một lần

Chạy từ root repo. Cần môi trường eval hiện có: PostgreSQL, MCP catalog/order/
memory/knowledge, LangMem worker, release policy hybrid đang active và model đã
cấu hình. Không cần gateway/frontend/đăng nhập. Không bắt buộc mở knowledge worker
riêng: CLI gọi worker thật trong tiến trình và chỉ claim job của thí nghiệm.

Trong `ai-services/.env` cần `KNOWLEDGE_DATABASE_URL` (reviewer role) và
`KNOWLEDGE_WORKER_DATABASE_URL` (restricted worker role), cùng database/server với
runtime. Actor phải đã được admin cấp quyền `knowledge_review` bằng CLI hiện có.
Lệnh không tự cấp quyền. Không dùng cấu hình production.

Xuất catalog nguồn public để đọc nội dung, hiệu lực, `chunk_id`, `source_hash`:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.knowledge_triplet \
  --actor local-reviewer \
  --export-sources /tmp/knowledge-public-sources.json
```

Lệnh này chỉ đọc DB, không gọi model/index/worker, không ghi đè file đã tồn tại.

Tạo `review-plan.json` riêng, ví dụ cấu trúc sau. Thay locator/câu hỏi bằng lượt
thật trong **dataset của đội**, nguồn/hash bằng export vừa đọc, và nội dung bằng
đáp án đã đối chiếu nguồn. Giá trị `COPY_SOURCE_HASH` cố ý không hợp lệ để không
vô tình chạy example như một bản duyệt thật.

```json
{
  "schema_version": 1,
  "reviewed_by": "nguoi-da-doi-chieu-nguon",
  "review_note": "Đã kiểm tra nội dung, hiệu lực nguồn và các câu hỏi kiểm chứng.",
  "cases": [
    {
      "id": "exchange-conditions",
      "scenario_id": "YOUR-SCENARIO",
      "call": "call_1",
      "turn": 1,
      "question": "Đổi hàng cần giữ nguyên tem nhãn và hộp không?",
      "kind": "faq",
      "category": "content",
      "answer": "Sản phẩm phải còn nguyên tem, nhãn, hộp, chưa qua sử dụng và có hóa đơn hoặc mã đơn hàng.",
      "aliases": [],
      "sources": [{"chunk_id": "DT-02", "source_hash": "COPY_SOURCE_HASH"}],
      "variations": ["Đổi hàng phải giữ hộp không?"],
      "must_say": ["nguyên tem", "hộp"],
      "must_not_say": ["không cần giữ", "bỏ hộp"]
    }
  ]
}
```

Một case chỉ định chính xác một lượt hỏi. Câu hỏi phải khớp dataset, kể cả đầu
vào ASR nếu kịch bản sử dụng ASR. Đánh giá cùng locator và cùng assertions trên
cả A/B/C; không chọn lại tiêu chí sau khi thấy kết quả K1. `must_say` là tất cả
cụm từ phải có, `must_not_say` là các cụm cấm. Đây là kiểm tra literal được người
duyệt xác nhận trước, không phải LLM judge hay kiểm chứng ngữ nghĩa đầy đủ.
Nên có cả tiêu chí chống câu trả lời phủ định/sai điều kiện.

`kind: aliases`, `category: retrieval` dùng để bổ sung cách hỏi vào nguồn có sẵn;
phải có 1–20 `aliases`. `kind: faq` dùng đáp án tĩnh được nguồn chứng minh, không
chấp nhận cam kết giá động. Không thêm fact không có nguồn chỉ để tăng điểm.
`variations` chạy kiểm tra retrieval offline khi duyệt; chúng **không tự tạo thêm
lượt hội thoại LLM**. Muốn đo paraphrase bằng model, đưa lượt đó vào dataset và
thêm case/tiêu chí tương ứng trước khi bắt đầu.

Nguồn có `date_basis: order_date` cần ngày đơn đã xác minh trong trace policy;
không tự dùng ngày gọi hay ngày khách nói để lách điều kiện hiệu lực.

## Một lệnh live

**Có gọi model và build index/embedding khi phát hành; reset dữ liệu runtime của
DB chỉ định.** Không chạy đồng thời demo/eval khác trên cùng runtime. Dùng bộ
3–5 gap nhỏ trước khi cần chạy 29 kịch bản. Knowledge K1 sẽ trở thành release
active thật của DB này; CLI không tự rollback sau khi so sánh.

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
PYTHONPATH=.:ai-services \
ai-services/.venv/bin/python -m eval_harness.knowledge_triplet \
  --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --expected-database telesale \
  --actor local-reviewer \
  --approval-plan /duong-dan/review-plan.json \
  --out-root ai-services/eval_harness/results/knowledge-triplet
```

K0 vẫn dùng `run_official` và được audit/chấm theo BTC. K1 gọi cấu hình Full
riêng, ghim release mới, kiểm coverage/diagnostics/DB/source/seed. Điểm K1 được
tính bởi scorer BTC với baseline K0; báo cáo đánh dấu rõ **cross-release
experiment**, không giả làm một cặp official cùng release. Số liệu HR/CCR vẫn
phụ thuộc extractor và được ghi trạng thái review riêng cho K0/K1.

Không phải gap nào cũng được duyệt: CLI bỏ qua lượt đã trả lời đạt tiêu chí,
không tra policy, lookup lỗi, nguồn hết hiệu lực/chưa đủ ngày xác minh, hoặc
nguồn cần thiết đã được truy xuất (lỗi generation). Không duyệt gap ngoài plan,
feedback baseline hay tất cả draft đang có trong DB. Worker và các service
permission/source/test/hash/CAS vẫn chạy như luồng thật.

K1 giữ lại các revision đang active ở K0. Giới hạn release hiện có là 100 bản;
CLI không tự xóa revision cũ để nhét bản mới. Nếu không có gap hợp lệ, dừng với
`status: no_eligible_gaps`, có lý do trong `review.json`, không bịa cột C hay
khẳng định cải thiện (CLI trả exit code 2). Không thể đảm bảo dataset hiện tại
sẽ tạo được gap hợp lệ. Trước kích hoạt, CLI cũng đối chiếu hash nguồn/nội dung
nền và config embedding/metadata của K0/K1: chỉ cho phép thêm FAQ dự kiến hoặc
alias đã duyệt, không âm thầm đổi corpus nền hay bỏ revision cũ.

## Kết quả và chạy tiếp

Thư mục kết quả chứa:

- `experiment.json`: checkpoint, hash source/settings/plan/artifact và release IDs.
- `review-plan.json`, `review.json`: kế hoạch đã đóng băng, event/gap/revision IDs,
  hash nội dung/test và lý do bỏ qua từng case.
- `k0/<run>/`: cặp official A/B, snapshot dataset/BTC và provenance gốc.
- `k1/`: trace Full, manifest, diagnostics, extraction report và điểm cross-release.
- `comparison.json`, `comparison.md`: ba cột BTC; đáp án A/B/C của mọi case trong
  plan; số đáp án sửa được, số regression và số case vừa truy xuất revision mới
  vừa đạt các assertions. Truy xuất một mình không được tính là trả lời đúng.

Sau khi K0 đã hoàn tất, lỗi review/build/activation có thể chạy tiếp:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true PYTHONPATH=.:ai-services \
ai-services/.venv/bin/python -m eval_harness.knowledge_triplet \
  --resume /duong-dan/thu-muc-thi-nghiem
```

Resume dùng tham số/plan đã lưu, không chạy lại K0; kiểm source, settings,
snapshot và seed trước khi tiếp tục. Nếu kích hoạt K1 thành công nhưng tiến trình
ngắt trước checkpoint, CAS/idempotency của service xử lý lần tiếp theo. Trace K1
đã hoàn chỉnh có thể tiếp tục chấm offline; trace K1/K0 còn dở không bị ghi đè
hay tự chạy lại âm thầm. Phải kiểm tra artifact lỗi trước khi quyết định trả phí
cho một lần chạy mới. Không sửa code/model/plan giữa hai nửa thí nghiệm.

## Kiểm thử không gọi API

```bash
PYTHONPATH=.:ai-services:ai-services/test ai-services/.venv/bin/python -m pytest -q \
  ai-services/eval_harness/test_knowledge_auto_review.py \
  ai-services/eval_harness/test_knowledge_triplet.py \
  ai-services/eval_harness/test_run_official.py \
  ai-services/test/test_knowledge_publish_search_loop.py
```

Test dùng storage/index/embedding adapter trong bộ nhớ và model giả lập; không
chạy live eval, không phát hành vào DB của người dùng. Chưa chạy model thật thì
không có số liệu cải thiện thật để báo cáo.
