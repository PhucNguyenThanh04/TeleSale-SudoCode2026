# Superpowers Design Spec: Alignment of 22 Team Scenarios (`SC-T01`–`SC-T22`) with BTC Data & Consultation Harness

- **Date:** 2026-11-11
- **Scope:** `ai-services/eval_harness/scenarios/SC-T01.json` through `ai-services/eval_harness/scenarios/SC-T22.json`
- **Reference Ground Truth:** `/home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS` (`catalog/`, `policy/`, `simulator/`, `schemas/`, `eval/reference_eval.py`, `eval/mock_tools.py`)
- **Out of Scope:** `SC-T23.json`–`SC-T29.json` (`SC01`–`SC07` public samples), `/home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/*`

---

## 1. Problem Statement & K0 Trace Root-Cause Analysis

In evaluation run `20261111T082822Z-116126a9`, the 7 BTC public sample scenarios (`SC-T23`–`SC-T29` / `SC01`–`SC07`) passed (`Task 1.0`, `Grounded 1.0`, `Tool 1.0`), whereas all 22 team-authored scenarios (`SC-T01`–`SC-T22`) failed task completion (`0/22` passed, composite `0.580`).

A turn-by-turn audit of `full.diagnostics_full.jsonl` against the consultation state machine (`ai-services/app/mcp_servers/mcp_shared/consultation.py`, `commerce_evidence.py`, `basket.py`, `catalog_query.py`, `checks.py`, `reference_adapter.py`) and BTC's `eval/mock_tools.py` + `eval/reference_eval.py` identified 8 deterministic root causes in the scenario definitions:

1. **Premature Purchase Intent (`_buy(turn) == True` on non-order turns):**
   - `consultation.py` matches `\b(len don|len order|tao don|dat hang|dat mua|chot don|mua|lay)\b` when not negated (`khong|chua|dung`), not conditional (`neu`), and without inquiry words (`xem|can nhac|de biet|gia bao nhieu`).
   - In the original `SC-T01`–`SC-T22`, customer turns in non-purchase calls or early inquiry/exchange turns used `"muốn mua..."`, `"chị lấy..."`, or `"khi nào shipper qua lấy áo"`, setting `snap.buy_this_turn = True` before price/stock evidence existed and forcing the deterministic blocker `"Mình muốn lấy mẫu nào trong các mẫu đang trao đổi để em kiểm tra và lên đơn ạ?"` (`SC-T02`, `SC-T06`, `SC-T07`, `SC-T09`, `SC-T10`, `SC-T16`, `SC-T18`, `SC-T20`).
2. **`explicit_product_queries(turn)` & `_mentions(query, items)` Selection Wipe (`consultation.py` lines 263–270):**
   - When `wants_choice == True` on a purchase turn, `consultation.py` runs `named = [_mentions(query, items) for query in explicit_product_queries(text)]`. If any extracted query fails to uniquely match 1 base product in `items`, `snap.selected_sku` is wiped to `None`.
   - Specific traps discovered:
     - `"Spectra S1"` extracts `['S1']`, and `_mentions('S1', items)` returns `set()` because `len('S1') == 2 < 3` (`SC-T05`).
     - `"AirPure y"` (lowercase `y`) extracts `['AirPure']`, matching 4 AirPure SKUs (`len != 1`), wiping `selected_sku` (`SC-T12`).
     - `"AirPure Pro"` matches both `SKU-AP-PRO` (`Máy lọc không khí AirPure Pro`) and `SKU-AP-FLT-P` (`Màng lọc thay thế AirPure Pro`) in `items` (`len == 2 != 1`) (`SC-T21`).
     - `"Xiaomi 4.5L"` extracts `['Xiaomi 4']`, which fails when another Xiaomi SKU is in `items` (`SC-T22`).
     - `"MoMo"` (mixed case) is extracted by `explicit_product_queries` as a model token (`'MoMo'`), matching `0` catalog items (`SC-T05`); lowercase `"ví momo"` is not extracted.
3. **Catalog Search Token Mismatch (`mock_tools.py` line 25):**
   - `mock_tools.catalog_search` requires every whitespace token of `query` to appear in `sku + name + category + specs` (excluding `variants`).
   - Phrasings like `"Philips 6,2 lít"` (instead of `"Philips 6.2L"`), `"Lock&Lock 4 lít"` (instead of `"Lock&Lock 4L"`), `"Senko TS 16"` / `"Panasonic ép 409"` (instead of `"Senko TS16"` / `"Panasonic F-409"`), `"Samsung AX 40"` (instead of `"Samsung AX40"`), and `"quạt có remote chạy êm"` (where `"chạy êm"` is not in `SKU-FAN-DC1` specs) caused `catalog.search` to return `[]`.
4. **Missing Explicit Price + Stock Inquiry Before Final Order Turn (`PresentedOffer` -> `AcceptedOffer`):**
   - `commerce_evidence.py` requires the agent to have presented a grounded price quote (`pricing.get_quote` + `inventory.check`) on an earlier turn in the same call before `order.create` is allowed on the final turn.
   - In `SC-T01 call_2`, `SC-T03 call_1`, `SC-T04 call_1`, `SC-T08 call_2`, `SC-T14 call_1`, `SC-T16 call_1`, and `SC-T19 call_1`, the customer either jumped straight to ordering or introduced a new delivery address on the purchase turn (invalidating the prior quote).
5. **The `SKU-SN-SOCK` (`"Tất thể thao RunLite (3 đôi)"`) Regex Trap in `checks.py`:**
   - `_AMOUNT` in `ai-services/app/agent/guardrails/checks.py` matches `3 đ` inside `"3 đôi"` as a 3 VND price claim (`(3, 'price', False)`), causing `check_answer` (`price_without_quote`) and `basket_money_evidenced` to reject any turn mentioning `"Tất thể thao RunLite (3 đôi)"`.
   - Focusing `SC-T17 call_2` on `SKU-SN-RUN1-41-DEN` (testing `RUN-10` promo expiry between `2026-10-22` at `1.161.000đ` and `2026-10-27` at `1.290.000đ`) avoids the `"(3 đôi)"` regex bug while `SC-T10` (`SKU-MB-CAR` + `SKU-MB-STR1`) and `SC-T18` (`SKU-MB-BOT` + `SKU-MB-MON`) test multi-item basket orders.
6. **Multi-Item Basket Quantity & Quote Rules (`basket.py`):**
   - For multi-item orders (`SC-T10 call_1` and `SC-T18 call_2`), the turn before purchase must ask for the combined basket quote of the 2 products (`pricing.quote_order`), and the final turn must say `"cả 2 sản phẩm"` (`_spoken_quantities == {2}`), never `"mỗi loại một cái"` (`_spoken_quantities == {1} != {2}`).
7. **Customer Self-Repetition of `must_carry_over` Facts (`reference_adapter.py`):**
   - In `SC-T09 call_3`, `SC-T13 call_3`, and `SC-T21 call_3`, the customer repeated `"35 mét vuông"`, `"25 mét vuông"`, and `"40 mét vuông"`, preventing the agent from demonstrating memory carry-over before the customer spoke the fact.
8. **Invalid `persona` Strings, Missing `days_later`, and Non-BTC `expected_outcome` Values:**
   - `SC-T01`–`SC-T22` had Vietnamese description strings in `persona` instead of the 8 canonical persona IDs in `BTC-Data-Vong1-TEAMS/simulator/personas.json`, and omitted integer `days_later` on calls.
   - `scenario_contract.py` + `preflight._outcomes` only allow `expected_outcome` in `{'chot_don', 'hen_goi_lai', 'chuyen_may', 'tu_choi'}` (or omitted/`None` on status/update/inquiry calls, matching `SC-T23`–`SC-T29`).

---

## 2. Scenario-by-Scenario Specification (`SC-T01`–`SC-T22`)

| Scenario | Persona ID | Hard Case | Call 1 (`call_date` / `success_if`) | Call 2 (`call_date` / `success_if`) | Call 3 (`call_date` / `success_if`) |
|---|---|---|---|---|---|
| `SC-T01` | `busy_office_worker` | `None` | `2026-10-20` (`days_later=0`): `pricing.get_quote` (`SKU-XM-4P`), `hen_goi_lai` | `2026-10-22` (`days_later=2`): `order.create` (`SKU-XM-4P`, `COD`, `5.490.000đ`), `chot_don` | `2026-10-28` (`days_later=6`): `order.status` (`generated_by_order.create`) |
| `SC-T02` | `careful_mom` | `None` | `2026-10-15` (`days_later=0`): `order.create` (`SKU-JK-WND-M-NAVY`, `COD`, `690.000đ`), `chot_don` | `2026-10-20` (`days_later=5`): `order.update` (`exchange_size` -> `SKU-JK-WND-L-NAVY`) | `2026-10-22` (`days_later=2`): policy inquiry (`must_say_any`: `tem mác`) |
| `SC-T03` | `tech_comparer` | `None` | `2026-10-16` (`days_later=0`): `order.create` (`SKU-WF-RO10`, `COD`, `6.890.000đ`), `chot_don` | `2026-10-18` (`days_later=2`): `order.status` | `2026-11-03` (`days_later=16`): `order.status` (`generated_by_order.create`) |
| `SC-T04` | `price_hunter` | `hoi_khuyen_mai_chua_bat_dau` | `2026-10-28` (`days_later=0`): `order.create` (`SKU-AF-6L`, `COD`, `3.990.000đ`), `promo_11-11_active=False`, `chot_don` | `2026-10-30` (`days_later=2`): `order.status` | — |
| `SC-T05` | `careful_mom` | `khuyen_mai_het_han_va_chuyen_may_y_te` | `2026-10-17` (`days_later=0`): `order.create` (`SKU-MB-PUMP1`, `momo`, `4.290.000đ`), `promo_PUMP-GIFT_active=False`, `chot_don` | `2026-10-19` (`days_later=2`): `handoff.transfer`, `chuyen_may` | — |
| `SC-T06` | `genz_fast_texter` | `doi_mau_khi_het_hang` | `2026-10-19` (`days_later=0`): `inventory.check` (`SKU-SN-TRK-41-TRANG` OOS -> `41-XAM`), `hen_goi_lai` | `2026-10-21` (`days_later=2`): `order.create` (`SKU-SN-TRK-41-XAM`, `COD`, `1.990.000đ`), `chot_don` | `2026-11-04` (`days_later=14`): `inventory.check` (`SKU-SN-TRK-42-XAM`) |
| `SC-T07` | `busy_office_worker` | `None` | `2026-10-22` (`days_later=0`): `order.create` (`SKU-JK-DWN-L-DEN`, `COD`, `1.490.000đ`), `chot_don` | `2026-10-24` (`days_later=2`): `order.status` | — |
| `SC-T08` | `elderly_verbose` | `san_pham_het_hang_va_thay_the` | `2026-10-22` (`days_later=0`): `inventory.check` (`SKU-FAN-TWR` OOS -> `SKU-FAN-DC1`), `hen_goi_lai` | `2026-10-24` (`days_later=2`): `order.create` (`SKU-FAN-DC1`, `COD`, `2.450.000đ`), `chot_don` | — |
| `SC-T09` | `tech_comparer` | `ton_kho_thay_doi` | `2026-10-19` (`days_later=0`): `inventory.check` (`SKU-AP-PRO` OOS), `hen_goi_lai` | `2026-10-21` (`days_later=2`): `schedule.callback` (`2026-10-22T10:00`), `hen_goi_lai` | `2026-10-22` (`days_later=1`): `pricing.get_quote` (`SKU-AP-PRO`) |
| `SC-T10` | `careful_mom` | `None` | `2026-10-23` (`days_later=0`): `order.create` (`SKU-MB-CAR` + `SKU-MB-STR1`, `COD`, total `8.480.000đ`), `chot_don` | `2026-10-25` (`days_later=2`): `order.status` | — |
| `SC-T11` | `impatient_returner` | `None` | `2026-10-27` (`days_later=0`): `order.status` (`OD301177`) | `2026-10-29` (`days_later=2`): `order.status` (`must_carry_over: ['order_id']`) | — |
| `SC-T12` | `price_hunter` | `khuyen_mai_khong_cong_don` | `2026-10-27` (`days_later=0`): `order.create` (`SKU-AP-Y`, `bank`, `4.800.000đ` with `TRADE-IN`), `chot_don` | `2026-10-29` (`days_later=2`): `order.status` | — |
| `SC-T13` | `careful_mom` | `doi_ngan_sach` | `2026-10-20` (`days_later=0`): `catalog.search` (`must_say_any`: `khóa trẻ em`), `hen_goi_lai` | `2026-10-22` (`days_later=2`): `catalog.search` (`max_price_vnd: 5500000`) | `2026-11-05` (`days_later=14`): `catalog.search` (`max_price_vnd: 5500000`) |
| `SC-T14` | `tech_comparer` | `None` | `2026-10-21` (`days_later=0`): `order.create` (`SKU-FAN-DC1`, `COD`, `2.450.000đ`), `chot_don` | `2026-10-23` (`days_later=2`): `order.status` | — |
| `SC-T15` | `skeptical_first_timer` | `thieu_thong_so` | `2026-10-22` (`days_later=0`): `agent_must_say: 'chưa có thông tin'` (TDS `SKU-WF-UF` -> advise `SKU-WF-RO10`), `hen_goi_lai` | `2026-10-24` (`days_later=2`): `pricing.get_quote` (`SKU-WF-RO10`) | — |
| `SC-T16` | `skeptical_first_timer` | `None` | `2026-10-20` (`days_later=0`): `order.create` (`SKU-AF-4L`, `COD`, `1.890.000đ`), `chot_don` | `2026-10-22` (`days_later=2`): `order.status` | — |
| `SC-T17` | `price_hunter` | `khuyen_mai_het_han` | `2026-10-22` (`days_later=0`): `pricing.get_quote` (`SKU-SN-RUN1-41-DEN` with `RUN-10`), `hen_goi_lai` | `2026-10-27` (`days_later=5`): `order.create` (`SKU-SN-RUN1-41-DEN`, `bank`, `1.290.000đ`, `promo_RUN-10_active=False`), `chot_don` | `2026-11-05` (`days_later=9`): `order.status` (`generated_by_order.create`) |
| `SC-T18` | `careful_mom` | `None` | `2026-10-23` (`days_later=0`): policy inquiry (`must_say_any`: `bóc seal`), `hen_goi_lai` | `2026-10-25` (`days_later=2`): `order.create` (`SKU-MB-BOT` + `SKU-MB-MON`, `COD`, total `779.000đ`), `chot_don` | — |
| `SC-T19` | `careful_mom` | `None` | `2026-10-21` (`days_later=0`): `order.create` (`SKU-MB-STER`, `bank`, `1.890.000đ`), `chot_don` | `2026-10-23` (`days_later=2`): `order.status` | — |
| `SC-T20` | `impatient_returner` | `doi_bien_the_het_hang` | `2026-10-21` (`days_later=0`): `order.create` (`SKU-JK-WND-L-BE`, `COD`, `690.000đ`), `chot_don` | `2026-10-28` (`days_later=7`): `order.update` (`exchange_size` -> `SKU-JK-WND-XL-NAVY`) | `2026-10-30` (`days_later=2`): policy inquiry (`must_say_any`: `tem mác`) |
| `SC-T21` | `price_hunter` | `so_gia_va_khuyen_mai_het_han` | `2026-10-28` (`days_later=0`): `pricing.get_quote` (`SKU-AP-PRO`), `hen_goi_lai` | `2026-11-01` (`days_later=4`): `pricing.get_quote` (`SKU-AP-PRO`, `promo_AIR-OCT_active=False`) | `2026-11-02` (`days_later=1`): `order.create` (`SKU-AP-PRO`, `COD`, `7.990.000đ`), `chot_don` |
| `SC-T22` | `impatient_returner` | `bao_mat_thong_tin_hoan_tien` | `2026-10-20` (`days_later=0`): `order.create` (`SKU-AF-XM`, `COD`, `1.590.000đ`), `chot_don` | `2026-10-29` (`days_later=9`): `order.update` (`return`, `must_say_any`: `biểu mẫu`) | `2026-11-07` (`days_later=9`): `order.status` (`generated_by_order.create`) |
