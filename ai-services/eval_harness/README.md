# Benchmark Dataset & Eval Harness — AI TeleSale SudoCode 2026

The benchmark runner now writes `<out>_full.jsonl` and
`<out>_baseline.jsonl` for the BTC `eval/reference_eval.py` script. Run the
two configurations against separate, identically seeded test databases so
orders and promotion usage from one run cannot affect the other. The
no-memory run keeps the same CRM identity and hides prior memory instead of
changing the customer's phone. Since the current chat API is not streaming,
`ttft_ms` is conservatively reported as total response time; do not present
it as a measured first-token time.

## LangMem adoption runbook

Run `current`, `shadow`, and `enabled` against separately seeded test databases
with the same BTC catalog, CRM, model, temperature, max tokens, `--seed`, dates,
and business tools. Start `mcp-memory` and the worker with matching
`LANGMEM_MODE`; the `current` run uses `off` and no worker. Wait until
`ai_memory.langmem_distillation_jobs` has no pending or leased rows before the
next call in a shadow/enabled scenario. Keep traces in ignored `results/`.

For each variant and for both the seven BTC public samples and 19 local
scenarios, run `python -m eval_harness.benchmark_runner --agent deep --config
full --variant VARIANT --seed 7 --scenarios DATASET --out results/VARIANT_DATASET.json`.
Run `--config baseline --variant current` against a separate clone of the
same seed database. The runner emits `*_full.jsonl` or `*_baseline.jsonl`.
`--config both` is useful only for a quick smoke test because it reuses mutable
business tables. Score each pair with
the unmodified BTC script:

```bash
python /home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/eval/reference_eval.py \
  --scenarios /home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace results/current_public_full.jsonl \
  --baseline results/current_public_baseline.jsonl \
  --out results/current_public_reference.json
```

Use matching paths for shadow/enabled; for the local set, use
`eval_harness/scenarios` as `--scenarios`. Compare one dataset at a time with
`python -m eval_harness.compare_langmem --scenarios DATASET_DIR --current REPORT --current-manifest
RUNNER_JSON --shadow REPORT --shadow-manifest RUNNER_JSON --enabled REPORT
--enabled-manifest RUNNER_JSON --out AGGREGATE_JSON`. The output contains
categorized TSR misses and a release gate. Missing denominators, Call Brief
samples, or comparable run metadata fail the gate. `cost_per_call_usd` stays
`null` until a billing source is attached; `ttft_ms` remains a proxy.

Bộ dữ liệu kiểm chuẩn (Benchmark Dataset) và công cụ thẩm định tự động (Validator) phục vụ đo lường, so sánh hiệu năng giữa **Deep Agent** (`deepagents.create_deep_agent`) và **ReAct Agent** (`langchain.agents.create_agent`) trên toàn diện kiến trúc `ai-services`.

---

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

Để kiểm tra tính hợp lệ toàn diện của tất cả 19 scenarios đối chiếu với schema và catalog BTC:

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
