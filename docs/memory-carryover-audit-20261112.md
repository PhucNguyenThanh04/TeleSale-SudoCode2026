# Audit memory carry-over — smoke 17ffa366

Frozen Full score: 9/31 CCR, 0/13 RQR. This is an evidence audit, not rescoring.
`Read key` means the first-turn diagnostic lists that key; it does not prove the value/provenance or durable write. `Prior write` means a public memory_writes receipt, not proof that the background projection retained it.
No raw customer identifiers are included. All labels below are from the frozen scenario snapshot.

| Scenario/call | Label | Prior write | Read key | BTC counted | Investigation |
|---|---|---|---|---|---|
| SC02/call_2 | product_advised | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC02/call_2 | price_quoted_vnd | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC02/call_2 | competitor_price_vnd | yes | yes | no | Not repeated; policy forbids unsupported competitor comparisons. Do not force a numeric mention to improve CCR. |
| SC02/call_2 | objection | yes | yes | no | Read key present; value/source/use needs separate evidence. |
| SC-T05/call_2 | product_advised | yes | yes | no | Successful handoff brief carries product_advised; top-level-only tool extraction misses nested usage. |
| SC-T06/call_2 | size | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T06/call_2 | color | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T06/call_3 | size | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T06/call_3 | color | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T09/call_2 | room_area_m2 | yes | yes | no | Read key present; value/source/use needs separate evidence. |
| SC-T09/call_2 | product_advised | yes | yes | no | Read key present; value/source/use needs separate evidence. |
| SC-T09/call_3 | room_area_m2 | yes | yes | no | Read key present; value/source/use needs separate evidence. |
| SC-T09/call_3 | product_advised | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T10/call_2 | order_id | no | no | no | Upstream order was not created; no order ID exists to remember. Not a memory write failure. |
| SC-T10/call_2 | product_advised | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T13/call_2 | room_area_m2 | yes | yes | no | Catalog uses min_room_area_m2/max_price_vnd. Check scope, prior source and current repetition before credit. |
| SC-T13/call_3 | budget_vnd | yes | yes | no | Catalog uses min_room_area_m2/max_price_vnd. Check scope, prior source and current repetition before credit. |
| SC-T13/call_3 | room_area_m2 | yes | yes | no | Catalog uses min_room_area_m2/max_price_vnd. Check scope, prior source and current repetition before credit. |
| SC-T13/call_3 | has_children | yes | no | no | Earlier write receipt exists but read key missing. Projection/read/context boundary needs reproduction; durable cause not saved. |
| SC-T17/call_2 | size | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T17/call_2 | color | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T17/call_3 | product_advised | yes | yes | no | Read key present; value/source/use needs separate evidence. |
| SC-T17/call_3 | size | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T17/call_3 | color | yes | yes | no | Exact variants are read/ordered. Need catalog-bound attribute extraction; a new size/current repetition must not be credited as old recall. |
| SC-T18/call_2 | product_advised | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T19/call_2 | order_id | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T19/call_2 | product_advised | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T22/call_2 | order_id | yes | yes | yes | Counted; no repair inferred from this label alone. |
| SC-T22/call_2 | product_advised | yes | yes | no | Agent names the prior product; catalog alias/source evidence must be checked before counting. |
| SC-T22/call_3 | payment | yes | yes | no | Status-only contact; old payment need not be spoken. No demonstrated failure to retain/use a needed payment. |
| SC-T22/call_3 | order_id | yes | yes | yes | Counted; no repair inferred from this label alone. |

Accounted for 31 labels; 9 counted by the saved BTC rule. No score or trace was rewritten.

Further proof must come from production-path replay with controlled repository/projection and inference only. Missing causal information in this frozen run remains unknown; no live DB inspection is required to repair reproducible boundary defects.
