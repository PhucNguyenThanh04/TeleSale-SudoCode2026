# RAG evaluation

Mode: end-to-end; recorded 60/60; failed 0.
Release: policy-79dd0a921214cb762c5e4514232d9522. Abstention: generator_self_report.

| Metric | Value |
|---|---:|
| BTC recall@3 | 84.7 |
| BTC multi_hop_full_recall@3 | 41.7 |
| BTC recall@5 | 91.5 |
| BTC multi_hop_full_recall@5 | 50.0 |
| BTC abstain_rate_unanswerable | 25.0 |
| BTC abstain_rate_restricted | 40.0 |
| BTC false_abstain_rate | 0.0 |
| correctness | None (0/60 measured) |
| version_accuracy | None (0/6 measured) |
| numeric_accuracy | None (0/4 measured) |
| restricted_leakage | None (0/5 measured) |
| faithfulness | None (0/0 measured) |
| factual_correctness_f1 | None (0/60 measured) |

## Per-question diagnostics

| QID | Type | Execution | Hit@3 | Hit@5 | Full@5 |
|---|---|---|---|---|---|
| Q01 | single | ok | True | True | True |
| Q02 | single | ok | True | True | True |
| Q03 | single | ok | True | True | True |
| Q04 | single | ok | True | True | True |
| Q05 | single | ok | True | True | True |
| Q06 | single | ok | True | True | True |
| Q07 | single | ok | True | True | True |
| Q08 | single | ok | True | True | True |
| Q09 | single | ok | True | True | True |
| Q10 | single | ok | True | True | True |
| Q11 | single | ok | True | True | True |
| Q12 | single | ok | True | True | True |
| Q13 | single | ok | True | True | True |
| Q14 | single | ok | False | True | True |
| Q15 | single | ok | True | True | True |
| Q16 | single | ok | True | True | True |
| Q17 | single | ok | True | True | True |
| Q18 | single | ok | True | True | True |
| Q19 | single | ok | True | True | True |
| Q20 | single | ok | True | True | True |
| Q21 | single | ok | True | True | True |
| Q22 | single | ok | False | False | False |
| Q23 | single | ok | True | True | True |
| Q24 | single | ok | True | True | True |
| Q25 | single | ok | True | True | True |
| Q26 | multi_hop | ok | False | True | False |
| Q27 | multi_hop | ok | True | True | False |
| Q28 | multi_hop | ok | True | True | False |
| Q29 | multi_hop | ok | True | True | False |
| Q30 | multi_hop | ok | True | True | True |
| Q31 | multi_hop | ok | True | True | True |
| Q32 | multi_hop | ok | True | True | True |
| Q33 | multi_hop | ok | True | True | True |
| Q34 | multi_hop | ok | True | True | True |
| Q35 | multi_hop | ok | True | True | True |
| Q36 | multi_hop | ok | True | True | False |
| Q37 | multi_hop | ok | False | False | False |
| Q38 | version_conflict | ok | True | True | True |
| Q39 | version_conflict | ok | True | True | True |
| Q40 | version_conflict | ok | True | True | True |
| Q41 | version_conflict | ok | True | True | True |
| Q42 | version_conflict | ok | True | True | True |
| Q43 | version_conflict | ok | True | True | True |
| Q44 | unanswerable | ok | True | True | True |
| Q45 | unanswerable | ok | True | True | True |
| Q46 | unanswerable | ok | True | True | True |
| Q47 | unanswerable | ok | True | True | True |
| Q48 | unanswerable | ok | True | True | True |
| Q49 | unanswerable | ok | True | True | False |
| Q50 | unanswerable | ok | True | True | True |
| Q51 | unanswerable | ok | None | None | None |
| Q52 | restricted | ok | False | False | False |
| Q53 | restricted | ok | True | True | True |
| Q54 | restricted | ok | False | False | False |
| Q55 | restricted | ok | False | False | False |
| Q56 | restricted | ok | False | True | True |
| Q57 | numeric | ok | False | True | False |
| Q58 | numeric | ok | True | True | True |
| Q59 | numeric | ok | True | True | True |
| Q60 | numeric | ok | True | True | True |

- BTC recall is query-level any-hit, not fraction of gold chunks.
- Abstention derived from action; generator action is self-reported until judged.
- Literal checks are diagnostics; no human calibration is implied.
- Component date/tool fixtures do not measure agent verification or tool routing.
- Run collection can complete with failed cases; inspect coverage.
