# Benchmark Dataset & Eval Harness — AI TeleSale SudoCode 2026

## Chạy text-to-text theo contract BTC

Chạy lệnh dưới từ `ai-services/`. Các lệnh live gọi model và reset runtime;
chỉ thực hiện sau khi người vận hành cho phép riêng. Spec/plan được duyệt
không tự cấp phép chạy live. Cần PostgreSQL, **bốn MCP** catalog/order/memory/
knowledge, LangMem worker và knowledge release/index thực sự sẵn sàng.

Kiểm file thuần offline (không đọc Settings, không gọi DB/MCP/model):

```bash
.venv/bin/python -m eval_harness.preflight --offline-check \
  --btc-root ../../BTC-Data-Vong1-TEAMS --scenarios eval_harness/scenarios
```

Test chức năng offline, chặn mạng và `.env` cả trong Python subprocess:

```bash
.venv/bin/python eval_harness/offline_tests.py eval_harness/test_offline_end_to_end.py -q
```

Một cặp live, với DB đích khai báo rõ (ví dụ DB thử nghiệm `telesale` đã được duyệt):

```bash
.venv/bin/python -m eval_harness.run_official --btc-root ../../BTC-Data-Vong1-TEAMS \
  --scenarios eval_harness/scenarios --expected-database telesale --agent deep --seed 7
```

Xuất riêng một cấu hình từ root repo, cũng gọi model và reset runtime:

```bash
ai-services/.venv/bin/python run_eval.py --btc-root ../BTC-Data-Vong1-TEAMS \
  --scenarios ai-services/eval_harness/scenarios --config full \
  --out eval/runs/NEW-full.jsonl --isolated-db --expected-database telesale
```

Đổi `full` thành `baseline_no_memory` và dùng output mới cho baseline.
`--isolated-db` giữ vai trò xác nhận của người chạy; cả hai CLI dùng cùng
preflight bốn MCP và reset trước từng cấu hình. Chỉ reset dữ liệu runtime/
sequence, giữ `btc_source`, knowledge và migration metadata; chặn production.
Không có yêu cầu tên DB phải kết thúc bằng `_eval`. Có thể khai báo đích qua
`EVAL_EXPECTED_DATABASE`; flag `--expected-database` ưu tiên hơn env.

Cấu hình runtime dùng `LLM_API_KEY`, `LLM_MODEL`, `OLLAMA_BASE_URL`,
`DATABASE_URL` hoặc cấu hình MCP DB hiện có, `MCP_CATALOG_URL`, `MCP_ORDER_URL`,
`MCP_MEMORY_URL`, `MCP_KNOWLEDGE_URL`, `MCP_INTERNAL_TOKEN`; worker phải dùng
cùng DB. Không đưa credentials vào manifest/log. `KNOWLEDGE_RELEASE_ID` nếu
đặt phải trỏ release sẵn sàng; coordinator ghim cùng ID/hash cho cặp.
Không bật raw content capture trong quá trình chạy harness.

Terminal in tiến độ ngay: bắt đầu full/baseline, preflight, từng warm-up, reset,
scenario/turn, chờ memory và chấm BTC. Chỉ forward stdout tiến độ; stderr của
provider/worker vẫn được giữ riêng để tránh lộ raw request/PII.

Mỗi cặp tạo thư mục unique dưới `eval_harness/results/`. Đọc `run.json` trước:
`running` là chưa hoàn tất; `failed` là lỗi thực thi/contract; `invalid` là mất
bằng chứng do redaction; chỉ `validated` có report BTC đầy đủ. Report của một cấu hình riêng chỉ có
trạng thái `completed`, chưa phải cặp đã được chấm chính thức. CLI thoát khác
0 cho failed/invalid. `validated` không bảo đảm agent đạt ngưỡng chất lượng.
Hai JSONL, `.report.json`, manifest và `.inputs.json` ghi coverage/provenance;
trace lỗi được giữ an toàn. Output riêng có sẵn bị từ chối để tránh lẫn run cũ.
Report invalid không được quảng bá thành điểm sạch sau khi che PII.

Chấm lại nguyên bản BTC từ root (thay đường dẫn trace đúng theo `run.json`):

```bash
ai-services/.venv/bin/python ../BTC-Data-Vong1-TEAMS/eval/reference_eval.py \
  --scenarios ai-services/eval_harness/results/RUN/scenarios \
  --trace ai-services/eval_harness/results/RUN/full.diagnostics_full.jsonl \
  --baseline ai-services/eval_harness/results/RUN/baseline.diagnostics_baseline.jsonl \
  --out /tmp/NEW-btc-rescore.json
```

`scenarios/` của run là snapshot đầu vào chấm, giữ nguyên nội dung và nhãn;
đây là dữ liệu đầu vào, không phải trace đã mask. Giữ quyền truy cập như nguồn
ban đầu, không publish thư mục run chứa dữ liệu riêng tư. Chỉ sử dụng public/
synthetic dataset nếu cần chia sẻ snapshot. Không dùng nhãn để tạo câu trả lời.
CLI nhận directory hoặc bundle `{scenarios: [...]}`/list/single scenario.
`--limit-scenarios N` của paired runner là **smoke live** trên snapshot subset,
không phải offline check. `benchmark_runner --dry-run N` đã bị loại bằng lỗi
hướng dẫn, không âm thầm chạy thật.

Directory `eval_harness/scenarios` hiện có **7 sample** (13 call/39 turn),
`benchmark_dataset.json` có 19 scenario; luôn lấy số đếm từ dataset chọn thực
sự. Không coi bảy sample là toàn bộ test BTC hoặc đạt quy mô M1.
Baseline giữ CRM identity/context trong phiên và ghi memory; chỉ chặn đọc
memory phiên trước. Hai nhánh đều chờ đúng job và thu accepted writes, kể cả
backfill khi nhận diện khách muộn; JSONL cuối ghi lại attribution đầy đủ.

`seed_history` hỗ trợ list session CRM `{session_id, date, channel, summary,
outcome?}`; ngày ISO phải trước call. Ví dụ synthetic:

```json
[{"session_id":"OLD-1","date":"2026-02-01","channel":"hotline","summary":"Đã tư vấn mẫu gia dụng.","outcome":"khac"}]
```

History được bổ sung vào CRM sessions sau resolve đúng identity, không sửa
`btc_source`, không tạo scored turns/writes giả, và bị chặn đọc ở baseline.
ID trùng cùng nội dung được deduplicate; nội dung xung đột/format chưa hỗ trợ
bị chặn preflight. Không chuyển `facts_established` thành history.

Extractor theo quy tắc, cùng một implementation cho CLI và replay. Questions
bao gồm yêu cầu dữ kiện không dấu hỏi; câu chưa xác định slot giữ `other` và
vẫn được tính trong RQR/`max_agent_questions`. Claims lấy giá trị từ lời agent,
không sửa theo tool; có field policy BTC và `is_human` với kiểm phủ định/câu
hỏi/trích dẫn. Số viết bằng chữ được hỗ trợ trong các dạng fixture; diễn đạt
mới, phạm vi nhiều sản phẩm/phủ định phức tạp vẫn cần BTC đối chiếu tay.
Các claim không có field ground truth tương ứng không được scorer kiểm chứng;
không diễn giải chúng thành đúng. Evidence/memory chỉ xuất sau mask; mất bằng
chứng chấm → invalid, không sửa điểm hoặc tạo claim bù.

Latency dùng monotonic, nonstream TTFT=Total. Ba warm-up riêng mỗi cấu hình
không được ghi vào scored trace; gateway warm-up chặn ghi memory/đơn/ticket,
runtime scored được reset sau warm-up. Không tính extractor/file/scoring hoặc
chờ worker sau response vào response latency. Brief chỉ ghi phép đo thực ở
turn 1 call_2/call_3, có freshness. Dưới 100 lượt phải ghi thiếu quy mô latency
BTC; không bỏ ba lượt scenario để tạo warm-up.

## 1. Tổng quan Bộ Dữ Liệu (19 Scenarios, 116 Turns)

Tập dữ liệu được tổng hợp từ 3 nguồn trụ cột, bao quát đầy đủ các mức nghiệp vụ (M1, M2) và các tình huống kiểm thử trong Đề bài & [DIEU-CHINH-DE.md](../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md):

| Nhóm kịch bản | Mã ID | Số lượng | Mô tả trọng tâm |
|---|---|---|---|
| **Public Samples BTC** | `SC01` – `SC07` | 7 kịch bản (39 turns) | 7 sample công khai chuẩn hóa theo `scenario_format.md` của BTC. Bao gồm nhớ phòng/trẻ nhỏ, mã KM, đổi size giày, hỏi nhiều không mua, hẹn gọi lại, kiểm tra đơn, handoff ngoài phạm vi. |
| **Memory Contract Cases** | `SC08` – `SC13` | 6 kịch bản (44 turns) | Các ca hợp đồng bộ nhớ đa phiên phức tạp: sửa thuộc tính sau khi chốt (đen $\to$ trắng), 2 người dùng chung SĐT, đa kênh Fanpage $\to$ Hotline, 16 lượt hỏi 4 SKU liên tục, quay lại sau 8 tháng (SKU ngừng bán, địa chỉ hết TTL), yêu cầu xóa dữ liệu cá nhân (GDPR handoff). |
| **Hard Hidden Cases** | `SC14` – `SC19` | 6 kịch bản (33 turns) | Các ca khó mô phỏng từ Mục 11 của Bộ ẩn BTC: 3 kênh lệch giá, KM loại trừ biến thể size 43 (`exclude_variant_size`), ép giá & dò giá nhập nội bộ (Guardrail), từ chối tư vấn y tế (Handoff), khách gọi lần 3 hết kiên nhẫn (Patience=0), hẹn gọi lại rơi vào ngày nghỉ tổng đài (`schedule.callback`). |

**Tổng cộng:** 19 Scenarios | 116 Customer Turns | 100% Validated against BTC Schemas & Catalog.

---

## 2. Bảng Chỉ Mục Chi Tiết (Dataset Index)

| ID | File kịch bản | Level | Persona BTC | Ca khó / Đặc tính chính | Target SKU |
|---|---|---|---|---|---|
| `SC01` | [SC01_sample_01.json](scenarios/SC01_sample_01.json) | M1 | `khach_do_du_hoi_nguoi_nha` | Mang facts phòng 25m2, có trẻ nhỏ sang cuộc 2; chốt đơn | `SKU-AP-Y` |
| `SC02` | [SC02_sample_02.json](scenarios/SC02_sample_02.json) | M1 | `khach_so_gia` | Mã KM `AIR-OCT` giảm 300k, áp dụng đúng điều kiện | `SKU-AP-PRO` |
| `SC03` | [SC03_sample_03.json](scenarios/SC03_sample_03.json) | M2 | `khach_da_mua_doi_size` | Đổi size giày từ 40 sang 41; không tính phí đổi theo chính sách | `SKU-SN-CAS-41-TRANG` |
| `SC04` | [SC04_sample_04.json](scenarios/SC04_sample_04.json) | M1 | `khach_hoi_nhieu_khong_mua` | Khách hỏi nhiều nhưng không mua; ghi nhớ lịch sử cuộc gọi | `SKU-AP-X` |
| `SC05` | [SC05_sample_05.json](scenarios/SC05_sample_05.json) | M1 | `khach_do_du_hoi_nguoi_nha` | Hẹn gọi lại vào ngày kế tiếp qua `schedule.callback` | `SKU-WF-RO9` |
| `SC06` | [SC06_sample_06.json](scenarios/SC06_sample_06.json) | M1 | `khach_so_gia` | Tra cứu trạng thái đơn hàng đã đặt qua `order.status` | `SKU-AP-MINI` |
| `SC07` | [SC07_sample_07.json](scenarios/SC07_sample_07.json) | M1 | `khach_ngoai_pham_vi_chuyen_may` | Hỏi sản phẩm không thuộc catalog; handoff chuyên viên | — |
| `SC08` | [SC08_contract_correction.json](scenarios/SC08_contract_correction.json) | M2 | `khach_hoi_nhieu_khong_mua` | Sửa thuộc tính từ đen $\to$ trắng; câu hỏi thăm dò không ghi đè | `SKU-SN-CAS-40-TRANG` |
| `SC09` | [SC09_contract_shared_phone.json](scenarios/SC09_contract_shared_phone.json) | M2 | `hai_nguoi_chung_sdt` | 2 người chung SĐT; cấm lộ đơn người kia; xác minh đúng người | `SKU-FAN-DC1` |
| `SC10` | [SC10_contract_cross_channel.json](scenarios/SC10_contract_cross_channel.json) | M1 | `khach_da_kenh_fb_hotline` | Đa kênh Fanpage $\to$ Hotline; mang diện tích 12m2 sang cuộc gọi | `SKU-AP-MINI` |
| `SC11` | [SC11_contract_many_products_16_turns.json](scenarios/SC11_contract_many_products_16_turns.json) | M2 | `khach_mua_nhieu_mon` | 16 turns liên tiếp hỏi 4 SKU; không nhầm lẫn giá chéo | `SKU-FAN-DC1` |
| `SC12` | [SC12_contract_return_after_months.json](scenarios/SC12_contract_return_after_months.json) | M2 | `khach_quay_lai_sau_8_thang` | Quay lại sau 8 tháng; SKU ngừng bán; TTL địa chỉ hết hạn | `SKU-SN-RUN1-OLD` |
| `SC13` | [SC13_contract_erasure_request.json](scenarios/SC13_contract_erasure_request.json) | M1 | `khach_ngoai_pham_vi_chuyen_may` | Yêu cầu xóa dữ liệu cá nhân (GDPR); kích hoạt `handoff.transfer` | — |
| `SC14` | [SC14_hard_multi_channel_price.json](scenarios/SC14_hard_multi_channel_price.json) | M2 | `khach_da_kenh_mau_thuan` | 3 kênh lệch giá; bảo vệ giá niêm yết hotline 5tr2 + quà | `SKU-AP-Y` |
| `SC15` | [SC15_hard_promo_size_exclusion.json](scenarios/SC15_hard_promo_size_exclusion.json) | M2 | `khach_so_gia` | KM `RUN-10` loại trừ size 43 (`exclude_variant_size: [43]`) | `SKU-SN-RUN1-43-DEN` |
| `SC16` | [SC16_hard_cost_price_guardrail.json](scenarios/SC16_hard_cost_price_guardrail.json) | M2 | `khach_hoi_ngoai_tai_lieu` | Ép giá và dò giá nhập nội bộ; Guardrail bảo vệ bí mật kinh doanh | `SKU-AP-X` |
| `SC17` | [SC17_hard_medical_handoff.json](scenarios/SC17_hard_medical_handoff.json) | M1 | `khach_ngoai_pham_vi_chuyen_may` | Hỏi máy lọc chữa hen suyễn & thuốc xông; từ chối y khoa & handoff | `SKU-AP-X` |
| `SC18` | [SC18_hard_impatient_3rd_call.json](scenarios/SC18_hard_impatient_3rd_call.json) | M2 | `khach_goi_lan_3_het_kien_nhan` | 3 cuộc gọi liên tiếp; khách hết kiên nhẫn; tra cứu đơn & xoa dịu | `SKU-AP-MINI` |
| `SC19` | [SC19_hard_holiday_callback.json](scenarios/SC19_hard_holiday_callback.json) | M1 | `khach_do_du_hoi_nguoi_nha` | Hẹn gọi Chủ Nhật (nghỉ); dời sang Thứ Hai qua `schedule.callback` | `SKU-FAN-DC1` |

---

## 3. Cấu trúc Thư mục

```text
eval_harness/
├── DATASET_GENERATION_PLAN.md   # Kế hoạch chi tiết 5 task đã được duyệt
├── README.md                    # Hướng dẫn và tài liệu đặc tả bộ dataset
├── dataset_index.json           # Metadata chỉ mục của 19 scenarios
├── benchmark_dataset.json       # Tập dữ liệu gộp phục vụ benchmark batch
├── validate_scenarios.py        # Bộ kiểm tra tự động cấu trúc & thực thể BTC
└── scenarios/                   # Thư mục chứa từng file kịch bản độc lập
    ├── SC01_sample_01.json
    ├── SC02_sample_02.json
    ├── ...
    ├── SC18_hard_impatient_3rd_call.json
    └── SC19_hard_holiday_callback.json
```

---

## 4. Kiểm chứng Dữ liệu (Validation)

Để kiểm tra các scenario có mặt trong directory đối chiếu với schema và catalog BTC:

```bash
# Kiểm tra toàn bộ scenarios
python3 ai-services/eval_harness/validate_scenarios.py --all

# Kiểm tra một scenario cụ thể
python3 ai-services/eval_harness/validate_scenarios.py ai-services/eval_harness/scenarios/SC15_hard_promo_size_exclusion.json
```

**Các tiêu chí kiểm tra tự động:**
1. Cấu trúc JSON tuân thủ `schemas/scenario_format.md`.
2. Mọi mã SKU và biến thể (`variant_sku`) phải có thật trong `catalog/products.json`.
3. Mọi mã khuyến mãi (`promo_code`) phải có thật trong `catalog/promotions.json`.
4. Mọi công cụ gọi trong `success_if.tool_called` phải tồn tại trong `schemas/tools.schema.json`.
5. Mọi persona phải nằm trong danh mục 12 personas chuẩn của `simulator/personas.json`.

---

## 5. Ứng dụng trong Benchmark: Deep Agent vs ReAct Agent

Tập dữ liệu này cung cấp đầu vào chuẩn mực để chạy Harness Benchmark đo đạc các chỉ số:
- **TSR (Task Success Rate):** Tỷ lệ chốt đơn, tra cứu và handoff thành công.
- **RQR (Repeat Question Rate):** Tỷ lệ hỏi lại các thông tin khách đã cung cấp ở phiên trước.
- **CCR (Carryover Correctness Rate):** Tỷ lệ mang đúng dữ kiện (diện tích, màu sắc, ngân sách, lý do cản trở) xuyên phiên.
- **TSR riêng Ca Khó (Hard Cases TSR):** Đo khả năng phản xạ của Deep Agent và ReAct Agent trước các bẫy nghiệp vụ (lệch giá, loại trừ size, ngày nghỉ, dò giá nhập).
- **Guardrail Violations:** Số lần để lộ thông tin nội bộ hoặc rò rỉ dữ liệu giữa 2 khách dùng chung SĐT.

## Knowledge feedback và hai vòng cải tiến

Run mới ghi `knowledge_release` vào manifest và kiểm cùng release cho cặp
full/baseline. `KNOWLEDGE_RELEASE_ID=btc-only` chọn nguồn BTC thuần; release
khác phải đã prepare/activate theo [runbook](../docs/knowledge-gap-loop-runbook.md).
`python -m eval_harness.knowledge_feedback --run RUN_DIR` nhập lỗi từ run đã
kiểm chứng, không gọi model. `python -m eval_harness.knowledge_comparison
--round0 RUN0 --round1 RUN1 --out NEW_DIR --register` so sánh hai run cùng
code/test/config và đăng ký bằng chứng, không sửa scorer BTC. Hai lần chạy
model/reset để tạo run vẫn cần ủy quyền riêng. Bộ regression sinh từ gap giữ
riêng với bộ test frozen dùng tính delta.

## Offline re-extraction và giới hạn diễn giải

`python -m eval_harness.reextract_trace --input TRACE.jsonl --output NEW.jsonl`
chỉ tạo lại `questions` và `claims` từ lời agent đã nói. Công cụ không gọi
model/MCP/DB, không tạo official run, không ghi đè output có sẵn. Thêm đồng
thời `--scenarios DIR --btc-root BTC_DIR --config full` (hoặc
`baseline_no_memory`) để audit schema và exact coverage bằng utility hiện có.
Không có ba tùy chọn này thì chỉ kiểm cấu trúc/thứ tự các lượt đầu vào.

Câu hỏi được gán slot theo mệnh đề thực sự hỏi; câu nhắc trẻ em rồi hỏi tiến
độ quyết định được gán `blocker`. Một câu có thể hỏi nhiều slot. Claim lấy
truth từ phát ngôn, không lấy từ kết quả tool: giá niêm yết dùng
`list_price_vnd`, giá bán dùng `price_vnd`; promo có mã được nói rõ dùng
`promo_<code>_active`, quà/ưu đãi generic vẫn dùng `promo_active`. Claim lịch
sử được giữ với field historical và text gốc, không biến thành trạng thái
hiện tại. Field scorer không chấm không được hiểu là claim đã đúng.

SC02 trong run `20261101T174223Z-c43720a3` có quà tặng được quote chứng minh
nhưng ground truth generic `promo_active=false`. Giữ discrepancy và score
BTC gốc; không gán mã từ tool vào câu generic để né lỗi chấm. Baseline RQR
bằng 0 vẫn giữ relative reduction `null` và verdict gốc: chưa chứng minh
được giảm 40%, không tự chuyển thành pass.

`facts_used`/CCR không thể tái dựng đầy đủ từ trace public cũ vì thiếu hồ sơ
và provenance trước call. Replay giữ nguyên field này. Các run mới giữ
snapshot fact đầu call và chỉ tính sử dụng có nguồn từ session trước, đúng
scope và nghĩa của tham số/phát ngôn. Việc khách nhắc lại giá trị không tự
chứng minh agent nhớ. Memory recall/precision là diagnostic khớp expected
slot/value theo call; danh sách expected không đầy đủ và `written` không
phải số record vật lý hay số fact rác. ID đơn động khác nhãn cố định vẫn là
discrepancy khi chưa có ánh xạ được xác minh.

## Khi eval dừng vì memory job thất bại

Runner từ chối publish score nếu một lượt có `memory_error`. Thông báo chỉ
rõ scenario/call/turn và loại lỗi; tra worker/job tương ứng để tìm nguyên
nhân. Không bỏ qua readiness check hoặc dùng trace lỗi để báo điểm.

Các MCP service và `langmem-worker` trong compose chạy code đã COPY vào
image, không mount checkout. Sửa Python trên host chưa cập nhật các process
này. Từ thư mục gốc repository, rebuild/recreate những service bị ảnh hưởng:

```bash
docker compose up -d --build --no-deps mcp-catalog mcp-order mcp-memory mcp-knowledge langmem-worker
```

Nếu tài khoản cần quyền Docker, chạy lệnh trên bằng `sudo`. Không restart
PostgreSQL, không xóa volume. Đây là thao tác triển khai service; agent phải
có ủy quyền trước khi tự thực hiện.

Một dấu hiệu worker cũ là delta narrative dùng một
`narrative_evidence_quote` chung cho nhiều trường, gây lỗi
`episode narrative lacks supporting evidence`. Admission hiện tại giữ
`narrative_evidence_quotes` theo từng trường và loại nội dung không được
quote chứng minh. Restart không tự sửa accepted proposal đã lưu hoặc làm
run thất bại trở thành hợp lệ. Giữ artifact run lỗi; chỉ chạy lại eval khi
được cho phép, bằng run mới theo quy trình hiện có, không sửa status/job
hay validator để hợp thức hóa run cũ.

Nếu harness chờ ngay sau lượt chat đầu và job vẫn `pending, attempts=0`,
worker chưa nhận job. Kiểm tra `docker compose ps -a langmem-worker` và log
worker trước khi chạy thêm eval. Compose mặc định có thể truyền
`LANGFUSE_BASE_URL=""`; Settings chuẩn hóa giá trị tùy chọn trống thành None
khi Langfuse tắt, nhưng vẫn từ chối thiếu URL/credentials khi bật Langfuse.
Sau khi cập nhật bản sửa này, rebuild riêng worker từ thư mục gốc:

```bash
docker compose up -d --build --no-deps langmem-worker
docker compose ps -a langmem-worker
```

Không dùng việc API trả lời được để kết luận worker memory đã sẵn sàng.
