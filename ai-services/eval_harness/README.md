# Benchmark Dataset & Eval Harness — AI TeleSale SudoCode 2026

CLI so sánh **No memory K0 / Full K0 / Full K1** với duyệt knowledge tự động sau K0,
không chạy baseline lần thứ tư: [hướng dẫn Knowledge Triplet](KNOWLEDGE_TRIPLET.md).

## Hợp đồng BTC tháng 11 và cập nhật database

Các entrypoint chạy eval tạo snapshot đầy đủ từ `--btc-root` và bản vá
`BTC-cap-nhat-11-2026/`: giữ catalog/policy/schema nền, thay đúng ba file BTC
`eval/mock_tools.py`, `eval/reference_eval.py`, `schemas/tools.schema.json`.
Không sửa hai thư mục nguồn. Snapshot chứa `btc_release.json` với hash từng
file; report/manifest ghi `btc_contract`. Snapshot đã bị sửa bị từ chối khi
tái sử dụng. Khi replay kết quả cũ, dùng đúng BTC root đã ghi trong artifact.

Trước khi triển khai code này, chạy migration bằng quy trình migration hiện có:

- `backend/migrations/0006_order_lines.sql`: lưu các dòng đơn và backfill đơn scalar.
- `ai-services/migrations/0004_memory_job_order.sql`: index hàng đợi theo khách hàng.

Các migration trên chỉ được kiểm tra trên database tạm, chưa áp dụng vào database triển khai.
Catalog/order cần cùng schema mới; memory worker và MCP memory cần cùng phiên
bản code để giữ thứ tự revision giữa các phiên của một khách hàng.

Kiểm các thay đổi này từ root repo, không gọi model:

```bash
PYTHONPATH=ai-services:ai-services/test:. ai-services/.venv/bin/python -m pytest -q \
  ai-services/test/test_basket_harness.py ai-services/test/test_basket_runtime.py \
  ai-services/test/test_operational_memory.py ai-services/eval_harness/test_memory_readiness.py
```

SQL/lease/concurrency có test riêng tại `ai-services/test/test_memory_postgres_integration.py`.
Đặt `MEMORY_INTEGRATION_ADMIN_DSN` trỏ PostgreSQL kiểm thử có quyền CREATEDB;
test tạo và xóa database riêng cho từng ca. Không đặt DSN này về database triển khai.

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

Cấu hình runtime dùng `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`,
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

Eval transcript dùng `AgentHarnessRuntime` của triển khai text/voice:
`prepare_session → [run → commit trạng thái thiết yếu] × số lượt → drain enrichment`.
Prepare chạy một lần trước lượt đầu mỗi cuộc. Text commit trong `run`; voice gọi
`record_playback` sau `run`. Eval voice giả lập phát hết **câu trả lời gốc**, không bị ngắt.
Chỉ chuyển lượt khi kết quả commit có `turn_saved=True`; không chờ LangMem giữa
các lượt. Cuối mỗi cuộc, harness đợi các job đã commit rồi thu memory writes theo
source turn trước khi chuyển phiên/chấm điểm. Lỗi worker được giữ trong artifact.
Memory đọc trạng thái đã commit và bằng chứng tool ngay khi worker còn pending;
LangMem bổ sung phần trích xuất ngữ nghĩa và tóm tắt ở nền.
Lỗi prepare dừng trước inference; lỗi playback giữ response trong partial trace nhưng
dừng cuộc gọi, không chấm điểm với lịch sử chưa xác nhận. Input mode vẫn lấy từ dataset.

Latency dùng monotonic và tách theo phạm vi:
- `response_ms`: transcript → câu trả lời đầy đủ; `total_ms` là alias tương thích BTC.
- `prepare_ms`: chuẩn bị session, chỉ ghi ở lượt đầu; các lượt sau bằng 0.
- `essential_commit_ms`: thời gian lưu trạng thái thiết yếu. Với text, đây là một phần
  của `response_ms`; với voice, đo ở bước xác nhận playback sau response.
- `background_finalize_ms`: thời gian đợi enrichment cuối cuộc, gán về từng source turn.
- `memory_finalize_ms`: tổng hai trường trên để tương thích báo cáo cũ. Không cộng
  trường này vào response vì sẽ tính trùng commit của text.
- `ttft_ms`: **proxy bằng response**, có `ttft_is_proxy=true` vì schema BTC bắt buộc số
  nguyên; chưa đo token đầu tiên cho voice. Báo cáo đánh dấu proxy, không diễn giải là TTFT thật.

Không tính extractor/file/scoring, ASR/TTS, thời gian phát âm thanh hoặc HTTP transport
vào response. Đây là parity của runtime từ transcript, chưa phải phép đo voice đầu cuối.
Single report và paired `run.json` ghi `conversation_measurement`; manifest của pair ghi
cùng thông tin trong `model_params`. Chỉ so sánh các lần chạy cùng lifecycle, model,
cấu hình, câu hỏi và lịch sử; trace cũ dùng text delivery không tương đương.
Brief chỉ ghi phép đo thực ở turn 1 call_2/call_3 (ưu tiên brief từ prepare), có freshness.
Ba warm-up riêng mỗi cấu hình không được ghi vào scored trace; gateway warm-up chặn
ghi memory/đơn/ticket, runtime scored được reset sau warm-up. Dưới 100 lượt phải ghi
thiếu quy mô latency BTC; không bỏ ba lượt scenario để tạo warm-up.

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

SC02 trong bộ scenario local đã sửa `promo_active=true` cho cuộc gọi ngày
18/10/2026, khớp quote có `GIFT-FILTER` đến 22/10/2026. Test offline đối chiếu
nhãn này bằng logic pricing và catalog nguồn. Snapshot/scorer/điểm các run cũ
giữ nguyên; thay nhãn không phải bằng chứng hành vi agent đã cải thiện.
Bảng `report_metrics` giải thích các ví dụ HR bằng quote cùng lượt, đúng SKU
và ngày trong snapshot. Claim khớp quote nhưng khác SKU kỳ vọng vẫn giữ lỗi
chọn sản phẩm. Quote lỗi, cũ, mơ hồ hoặc không chứng minh đúng quyền lợi được
đánh dấu chưa đủ bằng chứng; không sửa claims hay tạo HR thay thế.

Yêu cầu giao đúng hạn của SC02 chưa có bằng chứng xác nhận được đáp ứng.
Ngày dự kiến từ quote local không tự cho phép đặt đơn theo thời hạn đó, kể cả
khi khách đồng ý ngày dự kiến. Agent giữ yêu cầu và làm rõ/kiểm tra khả năng
đáp ứng; không tự tạo handoff chung chỉ vì cần làm rõ. Không thêm lượt khách
đồng ý ngày cố định để làm scenario đạt; giữ 39 lượt và snapshot các run cũ.

`facts_used`/CCR không thể tái dựng đầy đủ từ trace public cũ vì thiếu hồ sơ
và provenance trước call. Replay giữ nguyên field này. Các run mới giữ
snapshot fact đầu call và chỉ tính sử dụng có nguồn từ session trước, đúng
scope và nghĩa của tham số/phát ngôn. Việc khách nhắc lại giá trị không tự
chứng minh agent nhớ. Memory recall/precision là diagnostic khớp expected
slot/value theo call; danh sách expected không đầy đủ và `written` không
phải số record vật lý hay số fact rác. ID đơn động khác nhãn cố định vẫn là
discrepancy khi chưa có ánh xạ được xác minh.

`facts_used` nhận diện tên sản phẩm/alias không mơ hồ từ catalog của phiên,
không buộc agent đọc mã SKU. Metadata được giữ giữa các lượt của cùng call;
không dùng metadata này để tạo fact hoặc nguồn memory mới. Cách nói giá cao/
quá đắt có thể khớp objection `dat_qua`, nhưng vẫn kiểm sản phẩm và phủ định.
Chỉ có key trong profile/scoped facts không được cộng vào sử dụng. Chỉ số
phản ánh khớp quan sát được với fact phiên trước, không chứng minh quan hệ
nhân quả rằng model lấy giá từ memory thay vì quote mới có cùng giá trị.
Không tính lại CCR run cũ khi thiếu snapshot nguồn/provenance trước call.

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

## Replay cặp và diagnostics extraction

Chạy từ `ai-services/`, không cần model, MCP hay DB:

```bash
.venv/bin/python -m eval_harness.reextract_trace \
  --source-run eval_harness/results/20261104T160748Z-61e423c9 \
  --output-dir eval_harness/results/20261104T160748Z-extraction-replay-NEW \
  --btc-root /home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS
```

Output phải là thư mục chưa tồn tại, nằm ngoài nguồn. Công cụ audit hai trace,
manifest, snapshot, schema và scorer; chấm lại trace gốc offline và so giá trị
JSON trước khi tính delta. Lỗi hash score lịch sử chỉ được ghi nhận khi bản chấm
lại khớp giá trị JSON và hash scorer đã ghi. Nguồn không bị sửa. Trace replay
chỉ thay `questions`/`claims`; giữ nguyên `facts_used`, tools, memory và latency.
`replay_manifest.json` có loại `offline-extraction-replay`, hashes nguồn/output,
điểm gốc/replay và delta. Đây là thay phép đo lời thoại cũ, không phải cải thiện
agent hoặc một live run mới. CLI đơn-file vẫn dùng được nhưng không tạo cặp đã
kiểm provenance.

Runner mới và replay dùng cùng core `extract_detailed(agent_text)` trên lời
agent đã che PII, không nhận scenario hay tool truth. Câu hỏi nhiều slot tạo
một candidate cho mỗi slot; câu hỏi chưa rõ slot dùng `other/open` có cờ bất
định. Claim rõ nhưng thiếu mapping hoặc mất điều kiện khi project được giữ
ở diagnostics, không gán thành một quyền lợi khác để scorer chấm.

Mỗi lượt, kể cả lượt không có candidate, có một row trong
`full.extraction.jsonl` hoặc `baseline.extraction.jsonl`. `extraction_report.json`
ràng buộc hash hai trace/sidecars và fingerprint bytes `extractor.py` cùng
`extraction_report.py` (mapping/normalize đều nằm trong extractor). Hàm
`verify_extraction_report(Path(...))` kiểm lại đầy đủ với đúng phiên bản code;
đổi extractor sẽ làm fingerprint khác báo cáo cũ.

`extraction_status=needs_review` nghĩa là có unresolved, emitted có uncertainty,
hoặc claim không project được vì thiếu mapping/qualifier. `complete` chỉ nói
không có các trường hợp đó trong candidates đã phát hiện. Counter này không
phải recall toàn bộ lời thoại; tỷ lệ không có mẫu số là `null`. `btc_checked`
giữ nguyên dữ liệu scorer, không suy từ số emitted. Bộ nhãn fixture là tự review,
không phải hiệu chuẩn độc lập hay bằng chứng đạt test ẩn.

Run chính thức mới chỉ được `validated` sau khi đọc lại score bytes, manifests
và diagnostics; `run.json` ghi tên/hash summary cùng extraction_status riêng.
Safety-invalid hoặc lỗi integrity không được công bố thành run validated.
Atomic áp dụng từng file; lỗi giữa chừng có thể để lại artifact để điều tra.
Không dùng riêng việc có file score để kết luận run hoàn tất.

## Carryover và bằng chứng fallback (đợt 2)

`facts_used` chỉ tính khi có `current_session_id`, source hợp lệ thuộc phiên
khác, và lời nói/tham số tool dùng đúng giá trị với đúng scope. Room scope có
alias loại phòng tổng quát như `bedroom` ↔ “phòng ngủ”, `living_room` ↔ “phòng
khách”; nhãn phòng tùy ý không được tự đoán. Product scope vẫn dùng định danh
chính xác. Nhiều phòng trong cùng câu không được mượn diện tích của nhau.
Khách vừa cung cấp lại giá trị, phủ định, câu hỏi mở/giá trị chưa rõ hoặc tool
thất bại không tự chứng minh agent nhớ. Xác nhận một giá trị đã biết, khớp scope
và nguồn phiên trước vẫn là sử dụng fact, giữ cách tính carryover hiện có. Snapshot đầu call vẫn là căn cứ, không dùng expected
labels BTC. Helper không có current session trả `[]` vì chưa kiểm được nguồn.

Root CLI và official runner dùng chung collector. Với trace `NAME.jsonl`,
runner ghi `NAME.stages.json` và `NAME.events.json`, mỗi file có một record
mỗi lượt, kể cả lượt không có event hoặc runtime lỗi. Định danh và hash lời
agent phải khớp trace cuối; report của child ghi `turn_diagnostics` gồm rows,
trace SHA256 và tên/hash hai sidecars. Official publisher và coordinator
kiểm lại rồi mới ghi các tham chiếu đó vào `run.json` validated. File thiếu,
trùng, lệch thứ tự/hash hoặc payload thừa không được coi là diagnostics hợp lệ.
Không ghi đè sidecar cũ; chọn output mới cho mỗi run.

Events chỉ lưu reason/type code trong vocabulary cho phép, grounding verdict,
trạng thái lỗi tool/retrieval, model error và các sự kiện recovery attempted,
unavailable, rejected, succeeded hoặc exhausted. Không lưu raw draft, prompt,
claim values/source_evidence hay exception message. Capture hoạt động độc lập
log level và nằm trong context riêng của lượt; warmup không được tính vào lượt
đo. Các sự kiện recovery chỉ quan sát nhánh hiện có, không đổi thứ tự recovery,
guardrails hoặc kết quả trả khách.

`model.status=failed` cần sự kiện model_failed; `runtime_error` là lỗi thoát
ra ngoài runtime, không tự quy thành lỗi model. Grounding rejected và verifier
rejected được báo riêng. Recovery failed cần sự kiện exhausted; nếu không có
bằng chứng tương ứng thì trạng thái là `unknown`. `fallback_observed` chỉ đánh
dấu câu fallback trong trace, không suy nguyên nhân từ câu đó. Một lượt có thể
vừa model lỗi vừa recovery thành công; không ép mọi lượt vào một nguyên nhân.

Run cũ thiếu prior snapshot hoặc các sự kiện này không thể được bổ sung bằng
cách suy từ lời thoại/tool outputs. Không tự tính lại CCR hay phân loại nguyên
nhân fallback cho run `20261104T160748Z-61e423c9`. Kiểm đợt 2 dùng fixtures và
runtime scripted offline; live evaluation cần được người dùng ủy quyền riêng.

Sự kiện `model_failed` được phát trong khối xử lý agent hiện có, vốn bao gồm
cả một số bước hậu xử lý/refresh quote. Code này xác nhận khối đó gặp exception;
không đủ để quy lỗi riêng phía provider/model khi thiếu bằng chứng chi tiết hơn.

## Luồng tư vấn, lựa chọn và quote (đợt 3)

Runtime phân biệt danh sách tìm được, mẫu đề xuất, lựa chọn khách đã xác nhận,
quote và quyền mua hiện tại. `consultation` trong prompt là dữ liệu đã suy từ
bằng chứng; catalog/quote không tự là sự đồng ý. Quote được chuẩn bị qua read
tools có giới hạn: một ứng viên chính và một phương án thay thế, trong tool
budget/cache hiện có; không quét quote toàn catalog. Khi giá niêm yết lọc mất
ứng viên, có thể đọc bổ sung bỏ riêng bộ lọc giá để kiểm quote, không tự nới
ngân sách. Thuộc tính bắt buộc phải có dữ liệu đáp ứng; “có bé nhỏ” không tự
thành bắt buộc child lock.

Ngân sách tầm/khoảng và trần cứng đều không được tự cộng biên độ. Đồng ý xem
mẫu đắt hơn khác đồng ý chi tiêu/mua. Consent cho một offer không đổi trần
chung; đơn giá, tổng và số lượng phải rõ khi ảnh hưởng quyết định. “Đồng ý”
chỉ nối thành mua khi ngay trước đó là câu xác nhận mua với một mẫu/giá rõ.
Giá khách nói trực tiếp không bị ghi đè bằng giá offer khác đang là trọng tâm.

Trước `order.create`, BusinessTools kiểm permission/selection và giữ điều
kiện identity/variant/stock/quote hiện có. Quote/stock phải thuộc phiên mua
hiện tại, đúng SKU/qty/ngày/điều kiện. Tăng giá hoặc mất quà/freeship cần xác
nhận lại; giảm giá và giữ quyền lợi được tiếp tục với quyền mua còn hiệu lực.
Cùng một write thành công bị retry trong lượt sẽ trả receipt, không tạo đơn
lặp. Recovery chỉ dựng lời từ bằng chứng, không gọi tool hoặc ghi giao dịch.

Trạng thái lưu tại optional `topics[*].consultation` của topic global trong
JSON episode hiện có, không có migration. Source refs gắn customer/session/
turn/role và evidence đã mask. Worker tự dựng từ committed evidence (kể cả khi
LLM không đề xuất snapshot), rồi admission trước persist. Trường vắng không
xóa trạng thái cũ; null có nguồn là revoke. `product_advised` legacy không
được coi là customer selection. Quyền mua hiện tại nằm ở ConsultationDecision,
không nằm trong snapshot; quyền chọn hộ từ phiên cũ không tự kích hoạt mua.
Cùng ngày không rõ thứ tự mà source mâu thuẫn thì giữ unknown.

Scorer/schema/scenario BTC và artifact run cũ giữ nguyên. Không có score mới
hoặc kết luận đạt test ẩn từ unit/scripted runtime; mâu thuẫn ngân sách/expected
của sample vẫn phải báo riêng, không ép agent chọn SKU mà scorer mong đợi.

### Bằng chứng và continuation sau run 20261105T041922Z

`commerce_evidence.build_commerce_evidence` chọn view đọc thương mại từ
observations của phiên hiện tại theo ngày, SKU/variant, qty và đầu vào quote;
view không được ghi lại thành tool calls. Refresh mới lỗi không hồi sinh
kết quả cũ. Current policy/write calls giữ semantics riêng; không tái sử dụng
policy hoặc receipt phiên trước để chứng minh một thao tác hiện tại.

Read preparation có thể hydrate catalog trước khi kết luận thiếu lựa chọn,
rồi đánh giá lại lời khách; SKU model đề xuất không cấp quyền mua. Khi khách
đã đủ quyền, `BusinessTools.complete_purchase_if_ready` hoàn tất tối đa một
continuation qua gate/gateway hiện có sau lượt model, thay việc chỉ nhắc model
gọi order lần nữa. Không tự retry write lỗi/không chắc; receipt thành công
được tái sử dụng theo idempotency hiện có.

Recovery dùng cùng view hợp lệ và giải thích điều còn thiếu: mẫu, variant,
cơ sở ngân sách, payment hoặc consent cho offer mới. Câu hỏi quà/ưu đãi không
bị thay bằng một câu giá chung. Helpers vẫn thuần, không ghi giao dịch.
History read trả thêm source_turn_id khi có client_msg_id hiện hữu; cache
observations của runtime gắn owner/session/source turn. Không có migration.

Focused regression: `test/test_commerce_evidence.py`,
`test/test_purchase_continuation.py`, `test/test_consultation_response.py`,
`eval_harness/test_evidence_continuation_end_to_end.py`. E2E dùng AgentNodes,
BusinessTools, admission và JSON readback thật với model/tools scripted;
không chứng minh chất lượng live model hoặc đạt test ẩn. Không rescore lời
cũ để tuyên bố agent đã cải thiện; giữ discrepancy BTC riêng.

## Trace quyết định bổ sung (opt-in)

Thêm `--decision-diagnostics` vào lệnh `eval_harness.run_official` đang dùng;
hoặc đặt `EVAL_DECISION_DIAGNOSTICS=1` trong môi trường harness. Cả full và
baseline sẽ được thu thập. Đây vẫn là lệnh live hiện có, không phải replay.

Memory MCP và LangMem worker cũng cần chạy **code mới** với
`EVAL_DECISION_DIAGNOSTICS=1`. Compose mount `ai-services/.env` read-only
vào `/config/service.env`; `scripts/container_start.py` đọc cờ này khi mỗi
service khởi động. Đặt cờ trong file đó trước khi người vận hành rebuild/
khởi động lại các service cho lần eval được phép tiếp theo.
Nếu chạy Python trực tiếp, truyền biến vào từng process. Cờ ở harness không
thay đổi môi trường của các server đang chạy. Chưa có log remote sẽ hiện
`missing_components`, không được xem là bằng chứng memory/worker không chạy.
Mặc định tắt; môi trường `APP_ENV=production` không bật capture remote.

File để gửi phân tích là `results/<run_id>/decision_diagnostics.jsonl` cùng
trace và `run.json`. Các file `<trace>.decisions.jsonl` là phần theo config
được coordinator gom nguyên tử, không có nhiều process cùng append. Run và
manifest liên kết checksum file này với checksum hai trace; chúng không đổi
contract hoặc điểm BTC. Lỗi xuất diagnostics được báo riêng, không retry
mua hàng hoặc đổi kết quả scoring.

Đọc dòng cuối (`kind=summary`) trước: `complete`, `missing_components`,
`missing_checkpoints`, `truncated`, `errors` cho biết có thể kết luận đến đâu.
Checkpoint bị bỏ qua ở nhánh không áp dụng cũng xuất hiện trong danh sách
thiếu; `complete=false` không tự có nghĩa agent lỗi. Chỉ kết luận theo event
thực tế, ví dụ `gate_result.reason`, `tool_attempt`/`tool_result`, snapshot
admission/projection/read/context và `final_commit`. `worker_projection`
quan sát bên trong transaction; `job_readback.status=success` xác nhận job
đã commit. Event từ các process có producer ID/sequence riêng; dùng turn,
attempt và revision để nối, không so thứ tự timestamp giữa process.

Với `policy.search`, đọc `retrieval_status` và `evidence_count` ở
`tool_result`; `no_evidence` khác lỗi `unavailable`/`timeout`/`overloaded`.
`query_present` ở `tool_attempt` xác nhận có query mà không ghi nội dung
khách vào diagnostics. `args={}` có thể chỉ là kết quả lọc dữ liệu.
`receipt_present` chỉ áp dụng cho `order.create`/`handoff.transfer`; log mới
không xuất trường này cho truy xuất. Giá trị `false` của trường này trong
log policy cũ không chứng minh truy xuất thất bại. Trạng thái truy xuất tốt
và số evidence chưa đủ chứng minh agent đã chọn hoặc trả lời đúng chính sách;
vẫn phải đối chiếu evidence và câu trả lời trong trace nghiệp vụ.

Source UUID chỉ giữ ở metadata đã định kiểu; customer/session dùng alias
HMAC với khóa ngẫu nhiên của run, không lưu khóa hoặc raw PII trong file.
`process_start=unknown` là chưa có bằng chứng thời điểm khởi động; timestamp
`diagnostics_initialized_at` chỉ là lúc module diagnostics khởi tạo.
Fingerprint mô tả code Python đã nạp (kể cả implementation được decorator
bọc), không phải hash file hiện tại trên đĩa; so theo cùng component.
Không có raw prompt/draft/evidence quote, exception text hoặc địa chỉ.
Run cũ không được bổ sung ngược các snapshot chưa từng thu thập.


## Contract tên tool và sức khỏe thực thi model

Model nhận alias như `catalog_search`, `pricing_get_quote`, `order_create`.
BusinessTools, MCP, memory evidence và trace BTC vẫn dùng `catalog.search`,
`pricing.get_quote`, `order.create`. Deep/ReAct dùng cùng mapping; các chỉ dẫn
local/managed được render tên tool ở boundary, không sửa dữ liệu hội thoại.

Event sidecar bổ sung `execution/phase_result` version 1, ghi phase, trạng thái
và lỗi có cấu trúc đã lọc: exception class, HTTP status, code/param trong
vocabulary cho phép. Không ghi raw message, body hoặc stderr. Event cũ
`model_failed` có thể bao gồm lỗi hậu xử lý; dùng execution phase của run mới
để phân biệt. Run cũ thiếu evidence được giữ nguyên, không backfill success.

Warm-up yêu cầu bằng chứng invoke thành công. Lỗi hoặc thiếu evidence dừng
trước scored turns và các bước reset sau warm-up; cặp chưa hoàn tất không có
score chính thức. Warm-up thành công chưa chứng minh tool roundtrip live.

Report/manifest mới ghi `execution_health`: `healthy` khi evidence đủ và không
có lỗi thực thi, `degraded` khi quan sát lỗi, `unknown` khi thiếu evidence.
Một pair chỉ healthy khi cả hai nhánh healthy. Run đủ lượt có thể vừa
`validated` vừa `degraded`: score BTC vẫn giữ nguyên, không loại lượt xấu.
CLI in health riêng với trạng thái audit/scoring.

Extractor phân biệt bản chính sách hiện hành với bản bị thay thế, kể cả
quan hệ chủ động/bị động. Những khẳng định hiện hành sai vẫn được xuất để BTC
chấm. Điều kiện/mơ hồ chưa biểu diễn được giữ trong extraction report; không
coi excluded/unresolved là đúng. Replay vào output mới chỉ sửa cách đo trên
lời thoại cũ, không phải bằng chứng agent live đã cải thiện.

## In bảng chỉ số BTC của run đã lưu

Từ `ai-services`:

```bash
.venv/bin/python -m eval_harness.report_metrics eval_harness/results/<run_id>
```

Lệnh chỉ đọc `run.json` và `btc_score.json`, không gọi model, không reset DB,
không sửa kết quả. Từ đợt sửa M1 2026-11-06, `run_official` tự in bảng sau khi
validated. Bảng ghi rõ mẫu số, ngưỡng, extraction cần review, độ phủ latency và
WER/CER chưa đo trong eval text. Chi tiết sửa logic và chênh lệch sample:
[`m1-repair-review-2026-11-06.md`](../docs/m1-repair-review-2026-11-06.md).
