# Superpowers Implementation Plan: Repair & BTC Alignment of `SC-T01`–`SC-T22`

- **Date:** 2026-11-11
- **Spec:** [`docs/superpowers/specs/2026-11-11-team-scenarios-btc-alignment-design.md`](../specs/2026-11-11-team-scenarios-btc-alignment-design.md)
- **Target Files:** `ai-services/eval_harness/scenarios/SC-T01.json`..`SC-T22.json`, `ai-services/eval_harness/scenarios/README.md`

---

## Step 1: Metadata & Contract Normalization (`SC-T01`–`SC-T22`)
- **Action:**
  - Map `persona` in all 22 scenarios to canonical persona IDs in `BTC-Data-Vong1-TEAMS/simulator/personas.json` (`busy_office_worker`, `careful_mom`, `tech_comparer`, `price_hunter`, `genz_fast_texter`, `elderly_verbose`, `impatient_returner`, `skeptical_first_timer`).
  - Compute and populate explicit integer `days_later` on every call (`0` on `call_1`, `(call_date - prev_call_date).days` on `call_2` and `call_3`).
  - Normalize `expected_outcome` so only BTC-supported outcomes (`chot_don`, `hen_goi_lai`, `chuyen_may`, `tu_choi`) appear when set, and status/update/inquiry calls omit `expected_outcome` (matching `SC-T23`–`SC-T29`).
- **Verify:**
  - `ai-services/.venv/bin/python ai-services/eval_harness/validate_scenarios.py $(ls ai-services/eval_harness/scenarios/SC-T*.json) --btc-samples` -> `36/36 passed`
  - `PYTHONPATH=ai-services:. ai-services/.venv/bin/python -m eval_harness.preflight --offline-check --scenarios ai-services/eval_harness/scenarios --btc-root /home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS` -> exits `0`

## Step 2: Turn-Level Consultation & Guardrail Alignment (`SC-T01`–`SC-T22`)
- **Action:**
  - Ensure `_buy(turn) == False` on every non-order turn (including inquiry turns, size-exchange turns, return turns, and pickup-scheduling turns) and `_buy(turn) == True` on the final turn of every `order.create` call.
  - Ensure every `explicit_product_queries(turn)` extracted on a final purchase turn resolves to a single unique base SKU via `_mentions(query, catalog_items)`:
    - Use `"máy hút sữa điện đôi Spectra"` and lowercase `"ví momo"` in `SC-T05 call_1`.
    - Use uppercase `"AirPure Y"` in `SC-T12 call_1`.
    - Reference `"1 chiếc máy lọc không khí đang trao đổi"` on the final turn of `SC-T21 call_3` (since `"AirPure Pro"` matches both `SKU-AP-PRO` and `SKU-AP-FLT-P`).
    - Reference `"1 chiếc nồi chiên không dầu đó"` on the final turn of `SC-T22 call_1`.
  - Ensure exact catalog tokens in inquiry turns (`"Philips 6.2L"`, `"Lock&Lock 4L"`, `"Spectra S1"`, `"Panasonic F-409"`, `"Senko TS16"`, `"Samsung AX40"`, `"ghế ngồi ô tô Isofix Chicco"`, `"xe đẩy gấp gọn BabyGo Lite"`).
  - Ensure every `order.create` call explicitly requests price + stock on an earlier turn (`PresentedOffer` -> `AcceptedOffer`) and never introduces a new shipping address on the final purchase confirmation turn.
  - Ensure multi-item basket calls (`SC-T10 call_1` and `SC-T18 call_2`) ask for the combined 2-item basket quote on Turn $k-1$ and confirm `"cả 2 sản phẩm"` (`_spoken_quantities == {2}`) on Turn $k$.
  - Focus `SC-T17 call_2` on `SKU-SN-RUN1-41-DEN` (`1.290.000đ` after `RUN-10` expiry) to avoid the `"(3 đôi)"` -> `3đ` regex false positive in `checks.py`.
  - Remove customer self-repetition of `room_area_m2` in returning calls (`SC-T09 call_3`, `SC-T13 call_3`, `SC-T21 call_3`).
- **Verify:**
  - Run consultation/basket/memory mechanics verification script across all 22 scenarios -> `0` errors.

## Step 3: Dataset Acceptance & Regression Test Suite
- **Action:**
  - Run `m1_acceptance.py` dataset check and `pytest` regression suite.
- **Verify:**
  - `PYTHONPATH=ai-services:. ai-services/.venv/bin/python -m eval_harness.m1_acceptance --btc-root /home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS dataset ai-services/eval_harness/scenarios` -> `"dataset_ready": true`
  - `PYTHONPATH=ai-services:. ai-services/.venv/bin/pytest ai-services/eval_harness/test_scenario_contract.py ai-services/eval_harness/test_preflight.py ai-services/eval_harness/test_m1_acceptance.py ai-services/eval_harness/test_fact_usage.py ai-services/test/test_k0_harness_replay.py -q` -> `97 passed`
