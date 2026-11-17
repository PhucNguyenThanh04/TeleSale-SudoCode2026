# Eval thường và file Full + Knowledge riêng

## Luồng duyệt trên frontend

Có hai lệnh độc lập. Lệnh đầu hoàn tất eval thường (No memory và Full), tạo
đề xuất gap rồi kết thúc phần đánh giá. Bạn duyệt và phát hành trên frontend;
sau đó tự chạy file thứ hai, chỉ đánh giá Full với knowledge mới.
Không dùng `--manual-review` hoặc lệnh resume cho luồng này.

### 1. Chạy eval bình thường

Từ root, với model, DB, MCP và frontend đã chạy sẵn:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python run_system.py eval --expected-database telesale -- \
  --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS
```

Lệnh này chỉ gọi runner eval trên hạ tầng sẵn có. Không cần quyền Docker,
không build/restart container, tạo tài khoản hay reset schema/knowledge. Trước
mỗi cấu hình, runner reset runtime/memory bằng cùng cơ chế, giữ BTC, knowledge
và tài khoản. Full giữ memory giữa các cuộc gọi của chính lượt đó; No memory
không đọc memory liên phiên. Sau khi chấm và detect, lệnh kết thúc bình thường.
Giữ các dịch vụ/frontend đang chạy để duyệt gap và đánh giá K1.

Cũng có thể gọi trực tiếp cùng paired runner:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true PYTHONPATH=.:ai-services \
ai-services/.venv/bin/python -m eval_harness.run_official \
  --btc-root ../BTC-Data-Vong1-TEAMS --scenarios ai-services/eval_harness/scenarios \
  --expected-database telesale
```

CLI này in kết quả hai cấu hình và kết thúc. Sau metrics, hook detect lấy lỗi BTC
và tín hiệu policy.search thực sự trả no_evidence từ Full K0; chạy worker offline
đúng các event đó. Không tự approve, build/publish knowledge hoặc chạy Full K1.
Cần KNOWLEDGE_ENABLED=true và reviewer/worker DB URLs. Thiếu cấu hình thì báo rõ
không detect; lỗi detect được báo riêng, không sửa kết quả cặp eval đã hoàn tất.
Bản thân hook detect không gọi LLM hay embedding. Eval hội thoại vẫn là LIVE.

Artifacts cặp eval vẫn ở `RUN/`. Phần review được đặt ở thư mục **bên cạnh**:
`RUN.knowledge/`, tránh thay đổi bộ artifact cặp K0 đã đóng băng.

### 2. Duyệt đề xuất

Mở đúng link được in: `/knowledge?run_id=<mã-scope>`.
Đọc bằng chứng, nguồn và test. Bấm Duyệt và phát hành, chọn đề xuất muốn nhận,
nhập lý do, xác nhận đã đối chiếu rồi bấm Duyệt và phát hành các mục đã chọn.
Các revision K0 được giữ lại. Bước chuẩn bị chỉ mục có thể gọi embedding.
Cũng có thể sửa/từ chối từng bản hoặc dùng tab Phát hành riêng. Thiếu nguồn/lỗi
generation không cần bịa FAQ để đủ C.
Actor trong log là reviewer do gateway cấu hình, không chứng minh danh tính
cá nhân khi dùng chung actor.

### 3. Chạy file riêng chỉ đánh giá Full + Knowledge

Sau khi K1 đã active, trong terminal thứ hai chạy nguyên lệnh được in sau detect,
hoặc dùng mẫu sau với đường dẫn RUN thật:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
ai-services/.venv/bin/python run_knowledge_eval.py --base-run /duong-dan-tuyet-doi/RUN
```

Đây là một lần Full K1, không chạy lại No memory/Full K0. File đọc metadata,
proposals và review của cặp trước; giữ cùng code/model/seed/dataset/scorer và boot,
kiểm K1 giữ K0 và chỉ thêm revision đã duyệt thuộc gap của cặp đó. Nếu chưa publish
thì báo lỗi và kết thúc, không chờ hoặc gọi model. Nếu không có gap hay từ chối
hết, không chạy C và không khẳng định cải thiện. Gọi lại sau khi đã hoàn tất chỉ
kiểm artifact, không chạy thêm model. Chặn hai tiến trình cùng đánh giá một cặp.

Runtime memory được reset trước Full K1 bằng runner chuẩn; knowledge và BTC vẫn
được giữ. Không chạy fresh startup, thao tác chat hay eval khác trên DB này giữa
hai lệnh. Không sửa code/settings/model/nguồn/artifact giữa hai bước. Lệnh được
in sau detect giữ đúng release pin/config/boot của cặp đầu khi có cấu hình đó.
Giữ hạ tầng đang chạy; terminal eval không sở hữu hoặc dừng các dịch vụ này.

`RUN.knowledge/` có proposals.json, review.json (actor/reason/decision/source và
hash test), k1/, comparison.json/md. Báo cáo gồm ba cột No memory K0 / Full K0 /
Full K1. A/B là official pair; C là cross-release experiment trên cùng dataset.
Retrieval không chứng minh answer correctness; test tự sinh không là ground truth.
Không tự báo gap-answer accuracy hay đánh dấu gap resolved.

`run_eval.py` dành BTC không gọi hook detect hoặc file thứ hai: vẫn chạy đúng
một cấu hình được truyền vào rồi xuất trace. Các lệnh phía trên là workflow đánh
giá của đội. Knowledge release đang active vẫn cần được công bố rõ khi nộp bài.

## Chế độ tự động cũ (thí nghiệm riêng)


Muốn mỗi thí nghiệm bắt đầu bằng hệ thống sạch (tự tạo bảng, reset cả knowledge),
dùng `python run_system.py knowledge-eval ...` từ root. Khi resume một thí nghiệm
managed, dùng launcher với `--resume` để giữ boot ID; không bắt đầu boot mới.
[Hướng dẫn fresh-system](../../docs/fresh-system-startup.md) có lệnh đầy đủ.

Lệnh này chạy đúng ba cấu hình hội thoại theo thứ tự:

1. **A — No memory K0**.
2. **B — Full memory K0**, cùng release với A.
3. Phân tích các lượt policy lookup trong B, tạo đề xuất bằng worker thật,
   tự duyệt những đề xuất đạt kiểm tra nguồn và phát hành K1.
4. **C — Full memory K1**. Không chạy thêm baseline K1.

Mỗi cấu hình dùng vòng đời reset/warmup/runtime thật của harness. C không mang
memory đã tích lũy trong lần B sang. Không thay đổi dữ liệu `btc_source` hay
file BTC. Knowledge/review/release được lưu riêng; reset runtime giữ các bảng này.

Mặc định không cần biết trước gap hay có file kế hoạch. Chế độ này ghi rõ
`automatic_source_checked`: **duyệt tự động trong thí nghiệm, không phải người
duyệt**. Nó không dùng đáp án/test tự sinh làm đáp án chuẩn để chấm chính nó.
Số liệu BTC vẫn tính trên cùng dataset/tiêu chí gốc; có thể tăng hoặc giảm.

## Một lệnh từ hệ thống sạch

Từ root repo, tắt các server thủ công cũ trước khi chạy:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python run_system.py knowledge-eval --expected-database telesale -- \
  --auto-review --delivery-mode text --agent deep --seed 7 \
  --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --actor local-reviewer \
  --out-root ai-services/eval_harness/results/knowledge-triplet-final
```

Không cần frontend hoặc knowledge worker riêng. Launcher tự tạo bảng/reset
operational state và knowledge cũ, giữ BTC, cấp quyền mặc định cho reviewer theo
cấu hình backend, rồi bật MCP/LangMem worker. Nếu cần sudo cho Docker, thêm
`--sudo-docker` trước dấu `--`. Không chạy lệnh fresh demo/eval khác giữa K0/K1.
Lệnh live có gọi LLM và embedding; không chạy chỉ để kiểm tra cú pháp.

## Tự duyệt sau K0 hoạt động thế nào

- Chỉ xét các lượt Full K0 có policy lookup khỏe (`ok` hoặc `no_evidence`);
  baseline, lỗi tool, evidence conditional/conflict và chủ đề giá/KM/tồn kho
  không được tự duyệt. Không tạo nhãn trả lời sai từ điểm số hay đáp án model.
- Ghi feedback riêng, chỉ chạy worker cho các event của thí nghiệm. Chỉ xét
  draft do worker gắn vào đúng gap đó; không duyệt các draft cũ không liên quan.
- Nguồn phải public, hash đúng, ngày còn hiệu lực và có ngày đơn đã xác minh
  nếu nguồn dùng `order_date`. Nguồn đã được truy xuất được bỏ qua vì đó có thể
  là lỗi generation. Match từ vựng phải đủ mạnh và không hòa điểm với nguồn khác.
- FAQ chỉ được chép nguyên văn body nguồn; alias chỉ là chính câu hỏi đã che PII.
  Không thêm câu trả lời tĩnh về giá/KM/tồn kho. Kiểm content hash và regression
  retrieval trước khi gọi service approve thật; giới hạn tổng release 100 revision.
- Phát hành bằng prepare/activate thật, giữ nguyên corpus nền và revision K0.
  Full K1 dùng memory sạch độc lập, cùng snapshot dataset/model/settings.

Kiểm từ vựng không chứng minh nguồn trả lời đúng ý câu hỏi. Các điều kiện này là
bộ lọc tự động bảo thủ, vẫn có thể sai; không thay thế review của chuyên gia khi
triển khai thật. Dataset có thể không phát sinh đề xuất đủ điều kiện: khi đó lưu
`review.json`, trả mã 2 với `no_eligible_gaps`, không chạy C hoặc bịa cải thiện.

## Kết quả và tiếp tục khi gián đoạn

Trong thư mục con được tạo dưới `--out-root`:

- `k0/<run>/`: cặp No memory/Full K0, snapshot và điểm BTC.
- `review.json`: event/gap/revision/source/hash, mọi đề xuất được duyệt/bỏ qua và
  lý do. Không đánh dấu là human review.
- `k1/`: Full K1, manifest, diagnostics, extraction và điểm BTC cross-release.
- `comparison.md`, `comparison.json`: ba cột RQR/CCR/TSR/HR và HR giá/KM, đáp án
  cùng lượt ở A/B/C, evidence đích có được truy xuất trong release K1 không.

Với alias, evidence đích là nguồn gốc đã thêm alias; thấy nguồn trong K1 không
tự chứng minh alias gây ra thay đổi. Chế độ tự động **không báo accuracy đáp án
gap**, số câu đã sửa hay grounded success khi thiếu nhãn độc lập. Hãy dùng số
liệu BTC và trace để đánh giá cả cải thiện lẫn regression; một lần chạy không
chứng minh ý nghĩa thống kê. Trạng thái extractor cần review vẫn được giữ nguyên.

Nếu K0 đã hoàn tất nhưng review/phát hành lỗi, dùng cùng boot để chạy tiếp:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python run_system.py knowledge-eval --expected-database telesale \
  --resume /duong-dan/thu-muc-thi-nghiem
```

Resume không chạy lại K0 và không reset knowledge. Không thay code, model, nguồn
BTC, cấu hình hay artifact giữa hai nửa; không resume sau khi đã tạo boot mới.
Trace K1 dở không bị ghi đè hay tự chạy lại âm thầm. Xem checkpoint/log trước
khi quyết định trả phí chạy mới.

## Tùy chọn: kế hoạch có người đối chiếu trước

`--approval-plan FILE` vẫn được hỗ trợ thay cho chế độ tự động; không dùng cùng
`--auto-review`. Chỉ chế độ tùy chọn này ghi `simulated_pre_reviewed_plan`, dùng
literal answer assertions độc lập đã được người duyệt xác nhận trước.

### Chuẩn bị cho chế độ có plan (không bắt buộc với auto-review)

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

### Lệnh service-level cho chế độ có plan

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

### Artifact bổ sung và resume service-level với plan

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
  ai-services/eval_harness/test_knowledge_automatic.py \
  ai-services/eval_harness/test_knowledge_triplet.py \
  ai-services/eval_harness/test_run_official.py \
  ai-services/test/test_knowledge_publish_search_loop.py
```

Test dùng storage/index/embedding adapter trong bộ nhớ và model giả lập; không
chạy live eval, không phát hành vào DB của người dùng. Chưa chạy model thật thì
không có số liệu cải thiện thật để báo cáo.
