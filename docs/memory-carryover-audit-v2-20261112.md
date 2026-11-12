# Memory audit — latest smoke v2 90613d42

This audit uses the frozen latest run, not smoke v1. Saved Full CCR is 13/31, RQR 2/14. No scores or traces are rewritten.
Key presence in stage diagnostics is weaker than proof of a correct value/source. Public write receipts are not proof of durable projection. Redacted room scope labels are diagnostic privacy, not evidence of a broken runtime scope.

| Scenario/call | Required fact | Prior write receipt | Read key | Counted | Evidence / next action |
|---|---|---|---|---|---|
| SC02/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC02/call_2 | price_quoted_vnd | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC02/call_2 | competitor_price_vnd | yes | yes | no | Known but not numerically repeated; policy prohibits unsupported competitor comparisons. Do not force repetition for CCR. |
| SC02/call_2 | objection | yes | yes | no | Price objection is available; response refers to considering price but strict paraphrase matching does not credit it. Inspect actual follow-up relevance. |
| SC-T05/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T06/call_2 | size | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T06/call_2 | color | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T06/call_3 | size | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T06/call_3 | color | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T09/call_2 | room_area_m2 | yes | yes | no | Prior room is in read view. Check min_room_area_m2 and scoped speech: filter aliases currently undercount use. |
| SC-T09/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T09/call_3 | room_area_m2 | yes | yes | no | Prior room is in read view. Check min_room_area_m2 and scoped speech: filter aliases currently undercount use. |
| SC-T09/call_3 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T10/call_2 | order_id | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T10/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T13/call_2 | room_area_m2 | yes | yes | no | Prior room is in read view. Check min_room_area_m2 and scoped speech: filter aliases currently undercount use. |
| SC-T13/call_3 | budget_vnd | yes | yes | no | Customer repeats 5.5m now: do not count the repeated value as proof of memory recall. |
| SC-T13/call_3 | room_area_m2 | yes | yes | no | Prior room is in read view. Check min_room_area_m2 and scoped speech: filter aliases currently undercount use. |
| SC-T13/call_3 | has_children | yes | yes | no | Read key present. Child-safe recommendation is compatible, but not causal proof of using this fact; do not add a decorative mention. |
| SC-T17/call_2 | size | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T17/call_2 | color | yes | yes | no | Inspect exact catalog-backed variant use. Current repetition or changed size is not old recall; no SKU-suffix guessing. |
| SC-T17/call_3 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T17/call_3 | size | yes | yes | no | Status-only contact after failed order creation: no order to track; do not force old size/color into response. |
| SC-T17/call_3 | color | yes | yes | no | Status-only contact after failed order creation: no order to track; do not force old size/color into response. |
| SC-T18/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T19/call_2 | order_id | no | no | no | T19 prior order was never created; missing ID is upstream execution, not forgotten memory. Do not ask for a known-nonexistent ID. |
| SC-T19/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T22/call_2 | order_id | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T22/call_2 | product_advised | yes | yes | yes | Counted; no memory defect inferred from this label alone. |
| SC-T22/call_3 | payment | yes | yes | no | Status-only call need not repeat payment. Missing usage does not prove missing memory. |
| SC-T22/call_3 | order_id | yes | yes | yes | Counted; no memory defect inferred from this label alone. |

## RQR examples

Both saved redundant questions are in T19 call_2. Its call_1 has no successful order.create, so the scenario’s expected generated order_id was never established. The runtime should communicate that no order was found without repeatedly demanding an ID; fabricating an order or weakening purchase consent is out of scope.

## Repair scope

1. Preserve deterministic fact availability and valid provenance through completion, masking and later sessions; test deletions, ownership, updated values and per-product/per-room isolation.
2. Honor current context and existing session answers rather than repeatedly asking for information already present or unavailable by a confirmed lookup.
3. Report catalog-filter/variant/handoff attribution separately as measurement correction, without pretending it improves memory.
4. Keep missing causal evidence unknown and validate repaired paths offline; no new live metrics claimed.
