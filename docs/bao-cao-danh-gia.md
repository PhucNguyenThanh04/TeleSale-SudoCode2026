# Báo cáo đánh giá TeleSale SudoCode 2026

Ngày tổng hợp: **27/11/2026**. Checkout: `a4a816732987f69b805f76d47b12491bce73e8fb` cộng các sửa đổi chưa commit có sẵn về guardrail/review. Kiến trúc được trình bày trong [tài liệu đi kèm](tai-lieu-kien-truc.md).

**Kết luận từ bằng chứng hiện có:** bộ nhớ giảm hỏi lại và tăng mang theo ngữ cảnh trên bộ 7 scenario lịch sử; Full sau P2 vẫn chỉ đạt TSR 57,1%. Các sửa chữa mới có kiểm thử và replay offline, chưa có paired evaluation chứng minh KPI của checkout hiện tại. Chỉ số HR lưu trong score có giới hạn trích xuất và không bao phủ lỗi báo đã thực hiện thao tác.

## 1. Dữ liệu, nguồn và phương pháp

### Các bộ bằng chứng được sử dụng

| Bộ | Quy mô / cách dùng | Nguồn |
|---|---|---|
| Full/baseline trước cải tiến | 7 scenario, 13 cuộc gọi, 39 lượt mỗi cấu hình; 3 hard cases | [`before`](../eval_results/before/), đặc biệt [`btc7.score.json`](../eval_results/before/btc7.score.json) |
| P0, P1, P2 | Cùng quy mô 7/13/39; score lịch sử và trace tương ứng | [`after_p0`](../eval_results/after_p0/), [`after_p1`](../eval_results/after_p1/), [`after_p2`](../eval_results/after_p2/) |
| Ablation | Full, no-memory và ba cấu hình tắt thành phần | [`summary.json`](../eval_results/ablation/summary.json) cùng các `*.score.json`/trace |
| RAG end-to-end | 60 câu, trace và retrieval score; generator `gemma4:31b`, temperature 0,2; bộ này khác dialogue benchmark | [`report.json`](../results-rag/e2e-score-02/report.json), [`trace.jsonl`](../results-rag/e2e-02/trace.jsonl) |
| Kiểm tra code hiện tại | 85 test offline tập trung và hai frozen-row replay, chạy trong lượt viết báo cáo | Lệnh và kết quả ở mục 7 |
| Bộ scenario cuối | Manifest ghi 48 scenario, 118 cuộc gọi, 323 lượt, 38 hard cases | [`_manifest.json`](../eval/scenario_final/_manifest.json); chưa có cặp Full/baseline tương ứng được xác minh trong báo cáo này |

Các bảng hội thoại dưới đây lấy số trực tiếp từ JSON đã lưu; không chạy model, seed/reset DB hoặc sửa trace/nhãn. `REPORT.md` được dùng để tìm lịch sử P0–P3, sau đó đối chiếu score/events/raw text. Model, phần cứng và toàn bộ flags của dialogue runs không được chứng minh đầy đủ bởi các sidecar này; không gán model RAG sang dialogue runs.

Sidecar dialogue ghi `status=completed`, `execution_health=healthy`, streaming text, cùng knowledge release `policy-79dd0a921214cb762c5e4514232d9522`. SHA-256 của tám trace có report tại các thư mục before/P0/P1/P2/ablation khớp trường `turn_diagnostics.trace_sha256`. Các mốc before/P0/P1 ghi `decision_diagnostics.complete=false`; P2 và các ablation bổ sung không có gate này. Hash khớp chứng minh liên kết artifact, không chứng minh nhãn hay extractor đúng.

### Baseline không bộ nhớ được hiểu thế nào?

Runner dùng cùng runtime và đặt `memory.include_prior=False`: không đưa profile/episode liên phiên vào context; vẫn giữ lịch sử và tool evidence trong phiên, vẫn commit lượt. Baseline vẫn có CRM/catalog/order và các lớp bảo vệ. Vì vậy phép so sánh đo đóng góp của **bộ nhớ liên phiên**, không phải so với một chatbot không tools hoặc không lưu gì.

Nguồn: [`make_baseline_runtime`/`run_configuration`](../ai-services/eval_harness/benchmark_runner.py), [`MemoryStore`](../ai-services/app/agent/memory/store.py), [`memory.read`](../ai-services/app/mcp_servers/mcp_memory/services/memory.py).

### Định nghĩa chỉ số và giới hạn

| Chỉ số | Cách đọc trong bộ score | Hướng tốt / giới hạn |
|---|---|---|
| RQR | `redundant / total_questions × 100`; phụ thuộc slot/question do extractor xuất | Giảm; có thể bỏ sót câu hỏi lặp hoặc một câu ánh xạ nhiều slot |
| CCR | `used / required × 100` trên các fact carry-over yêu cầu | Tăng; cần evidence dùng fact đúng, không chỉ có fact trong DB |
| TSR | Scenario đạt các tiêu chí task của scorer / tổng scenario | Tăng; không đồng nhất với số đơn tạo; criterion/args matcher có thể chưa phủ đủ receipt và ngữ nghĩa |
| Hard TSR | TSR trên 3 scenario khó trong bộ nhỏ | Tăng; một scenario tương đương khoảng 33,3 điểm % |
| HR tổng | Claim sai / claim có ground truth được scorer đối chiếu | Giảm; không phải tỷ lệ mọi phát ngôn sai |
| HR giá/KM | Claim giá/KM sai / claim giá/KM được đối chiếu | Giảm; lỗi extractor ảnh hưởng cả tử và mẫu số |
| Guardrail violations | Tổng các loại PII, over-escalation, claims-human, forbidden-pattern của scorer | 0 là tốt trong phạm vi đó; không bao phủ mọi lỗi authorization/receipt |
| Calls-to-Close | Trung bình số cuộc gọi đến chốt trong các ca chốt được | Giảm; phải đọc cùng `n_closed`, tránh bỏ ca thất bại khỏi phân tích |
| TTFT / Total | Trong sidecar lịch sử: đến guarded answer delta đầu / cuối; đơn vị ms | Giảm; không gồm ASR/TTS, HTTP transport, prepare và đợi memory worker |
| Call Brief latency | Thời gian brief ở phiên quay lại | Giảm; chỉ 6 mẫu trong mỗi run Full |
| Fallback | Đếm `events[].recovery.status == "fallback"` | Giảm nếu vẫn giữ đúng/an toàn; trường `fallback_observed` của các artifact này đều false nên không dùng để đếm |

Nguồn hợp đồng đo: [`conversation_measurement`](../ai-services/eval_harness/benchmark_runner.py), [`scorer.py`](../ai-services/eval_harness/scorer.py), [`extractor.py`](../ai-services/eval_harness/extractor.py). Scorer tham chiếu BTC là thẩm quyền của điểm chính thức từng run; adapter/check bổ sung phải được công bố riêng.

## 2. Full so với baseline không bộ nhớ

Baseline ở bảng là trace từ `before`, được tái sử dụng trong score P2; chưa phải baseline mới sinh lại tại thời điểm P2.

| Chỉ số | Baseline không bộ nhớ | Full trước cải tiến | Full sau P2 |
|---|---:|---:|---:|
| RQR ↓ | 31,6% (6/19) | 0,0% (0/16) | 0,0% (0/16) |
| CCR ↑ | 4,8% (1/21) | 57,1% (12/21) | 52,4% (11/21) |
| TSR ↑ | 57,1% (4/7) | 57,1% (4/7) | 57,1% (4/7) |
| Hard TSR ↑ | 100,0% (3/3) | 66,7% (2/3) | 33,3% (1/3) |
| HR tổng ↓ | 0,0% (0/15) | 11,1% (2/18) | 0,0% (0/16) |
| HR giá/KM ↓ | 0,0% (0/13) | 13,3% (2/15) | 0,0% (0/14) |
| Guardrail violations ↓ | 0 | 0 | 0 |
| Calls-to-Close ↓ | 1,75 (4 ca chốt) | 1,75 (4 ca chốt) | 1,67 (3 ca chốt) |
| TTFT p50 / p95 ↓ | 1683 / 3835 | 1723 / 4026 | 1479 / 3799 |
| Total p50 / p95 ↓ | 2400 / 5556 | 2184 / 4833 | 1918 / 3982 |
| Call Brief p50 / p95 ↓ | Không có | 115 / 186 | 110 / 232 |

Nguồn: [`before/btc7.score.json`](../eval_results/before/btc7.score.json), [`after_p2/btc7.score.json`](../eval_results/after_p2/btc7.score.json).

So với baseline lưu sẵn, Full P2 giảm RQR 31,6 điểm %, tức 100% tương đối, và tăng CCR 47,6 điểm %. Các con số cho thấy ngữ cảnh liên phiên giúp tránh hỏi lại trong tập này. **TSR không tăng**; Hard TSR còn thấp hơn. Không thể kết luận bộ nhớ làm tăng tỷ lệ chốt đơn chỉ từ RQR/CCR.

Total p95 thấp hơn baseline khoảng 28,3%, nhưng đây là chênh lệch quan sát giữa run, chưa là ước lượng nhân quả. Mỗi cấu hình chỉ 39 lượt; chính scorer cảnh báo cần ≥100 lượt để p95 có ý nghĩa. `memory_checks=[]` trong score không phải bằng chứng mọi kiểm tra bộ nhớ đều đạt.

## 3. Kết quả trước/sau cải tiến P0–P2

| Mốc | RQR | CCR | TSR | Hard TSR | HR giá/KM | TTFT p50/p95 | Total p50/p95 | Brief p50/p95 | Fallback |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Trước | 0,0% | 57,1% | 57,1% | 66,7% | 13,3% (2/15) | 1723/4026 | 2184/4833 | 115/186 | 8 |
| P0 | 0,0% | 52,4% | 57,1% | 66,7% | 11,1% (2/18) | 1774/4043 | 2230/4735 | 114/176 | 9 |
| P1 | 0,0% | 52,4% | 42,9% | 66,7% | 0,0% (0/10) | 2013/4522 | 2332/5055 | 120/207 | 11 |
| P2 | 0,0% | 52,4% | 57,1% | 33,3% | 0,0% (0/14) | 1479/3799 | 1918/3982 | 110/232 | 6 |

Latency tính bằng ms. Guardrail violations của scorer đều 0. Số fallback được tính lại từ recovery status trong các events sidecar.

Lịch sử thay đổi được mô tả ở [`REPORT.md`](../REPORT.md), và cơ chế tương ứng còn thấy trong code:

| Nhóm cải tiến | Nội dung | Đánh đổi / bằng chứng |
|---|---|---|
| P0 — memory hardening | Facts từ receipt xác định; chống revision trùng; TTL; allowlist tool result; giữ runner tiếp tục khi enrichment lỗi | CCR từ 12/21 xuống 11/21, fallback tăng 8→9; chưa chứng minh memory tốt hơn bằng điểm này. Báo cáo lịch sử ghi worker Docker chưa rebuild đồng bộ |
| P1 — recovery/fallback | Bổ sung quote/stock còn thiếu, fallback gắn ngữ cảnh | HR giá/KM được chấm về 0 nhưng TSR xuống 3/7, fallback lên 11; ít claim hơn không tự nghĩa là tư vấn đúng hơn |
| P2 — latency | Fast authorization cho trường hợp hẹp; read I/O độc lập được song song; giữ tuần tự writes | Total p95 giảm, TSR hồi về 4/7; Hard TSR còn 1/3; không có nhiều seed/repetition để tách nhiễu |

Từ trước tới P2: TTFT p50 giảm khoảng 14,2%, p95 giảm 5,6%; Total p50 giảm 12,2%, p95 giảm 17,6%; fallback giảm 25% (8→6). Call Brief p95 lại tăng 186→232 ms, khoảng 24,7%. Đây là các **chênh lệch lịch sử quan sát được**.

Hai claim gây HR ở mốc trước có vấn đề ánh xạ extractor, phân tích ở mục 6. Vì vậy mức giảm 13,3%→0% là mức giảm **điểm HR lưu sẵn**, chưa chứng minh hai hallucination thật đã bị loại. Câu “đã lên đơn” không có receipt ở P2 vẫn sai dù HR giá/KM bằng 0.

Các ca task fail cũng thay đổi: trước là SC01/SC03/SC05; P2 là SC01/SC05/SC06. SC03 có `order.update` thật ở P2, nhưng SC06 mất `order.create`. Nâng một ca không đủ nếu một ca khác hồi quy.

### Những sửa đổi mới hơn P2

Code hiện tại có receipt checks, bảo toàn vai trò main/gift, explicit identity transport, continuation hữu hạn, context freshness, dependency closure và cache verdict trong một lần verifier. Các ledger [`agent-reliability`](superpowers/plans/2026-11-26-agent-reliability-progress.md) và [`trace-recovery`](superpowers/plans/2026-11-26-trace-recovery-progress.md) lưu lịch sử RED/GREEN cùng giới hạn.

Những thay đổi này **chưa có số TSR/CCR/HR/latency mới** được xác minh ở checkout hiện tại. Đặc biệt `GuardedStream.feed()` hiện chưa phát draft; `finish()` phát câu đã kiểm toàn bộ, nên TTFT lịch sử 1479/3799 ms không đại diện cho hành vi buffering mới. Không suy ra độ giảm latency từ việc bớt gọi semantic reviewer trong test.

## 4. Ablation và mức tin cậy

| Cấu hình | RQR | CCR | TSR | Hard TSR | HR giá/KM | TTFT p50/p95 | Total p50/p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `full` | 0,0% | 52,4% | 57,1% | 33,3% | 0,0% | 1479/3799 | 1918/3982 |
| `no_memory` | 31,6% | 4,8% | 57,1% | 100,0% | 0,0% | 1683/3835 | 2400/5556 |
| `no_authorizer` | 6,2% | 52,4% | 71,4% | 66,7% | 7,1% | 1721/3777 | 2121/4677 |
| `no_verify` | 12,5% | 52,4% | 71,4% | 66,7% | 15,0% | 1406/3078 | 1694/3383 |
| `no_progressive_streaming` | 5,3% | 52,4% | 71,4% | 66,7% | 9,1% | 2140/5374 | 2140/5374 |

Nguồn: [`ablation/summary.json`](../eval_results/ablation/summary.json), các score cùng thư mục và [`run_ablation.py`](../eval/run_ablation.py). Tất cả có guardrail violations bằng 0 theo scorer.

Đã kiểm tra byte: `ablation/full.jsonl` trùng trace P2; `ablation/no_memory.jsonl` trùng baseline trước. Hai hàng này là tái sử dụng kết quả, không phải hai lần chạy độc lập mới.

Khi tắt verify hoặc authorizer, TSR lưu sẵn tăng từ 4/7 lên 5/7, nhưng HR giá/KM cũng tăng. Điều này cho thấy cần xem đồng thời completion và phát ngôn có nguồn; không có cơ sở bỏ kiểm quyền ghi để tối ưu TSR. Guardrail counter bằng 0 không chứng nhận authorization an toàn.

Run tắt progressive streaming chậm hơn và đồng thời thay đổi nội dung/TSR/HR. Do không có repeated runs cùng model/seed/hardware đầy đủ, không thể quy toàn bộ chênh lệch cho cơ chế streaming. Hơn nữa implementation streaming hiện tại đã đổi; bảng này chỉ mô tả các artifact lịch sử.

## 5. Đánh giá riêng kho chính sách/RAG

| Chỉ số đã lưu | Kết quả | Phạm vi |
|---|---:|---|
| Câu thu thập / execution failed | 60/60; 0 lỗi thực thi | Không đồng nghĩa 60 câu trả lời đúng |
| Recall@3 / Recall@5 | 84,7% / 91,5% | BTC query-level any-hit; mẫu số 59, không phải tỷ lệ tất cả gold chunks |
| Multi-hop full recall@3 / @5 | 41,7% / 50,0% | Chỉ 12 câu multi-hop; lấy trọn bằng chứng còn hạn chế |
| MRR@5 | 0,7517 | 59 câu đủ điều kiện |
| Retrieval p50 / p95 | 328,0 / 544,4 ms | 60 câu của pipeline RAG này |
| Generation p50 / p95 | 797,0 / 1602,9 ms | Cấu hình generator của run RAG |
| Abstain unanswerable / restricted | 25,0% / 40,0% | Từ `generator_self_report`, chưa được chấm độc lập |
| False abstain | 0,0% | Cùng giới hạn self-report |
| Answer correctness / version accuracy / numeric accuracy / restricted leakage | Chưa có số đo | Các trường `value=null`, `measured=0`; `judge=null`, file judgments rỗng |

Nguồn: [`results-rag/e2e-score-02/report.json`](../results-rag/e2e-score-02/report.json). Không dùng Recall@5 để thay cho chất lượng trả lời, cũng không dùng self-report abstain để suy tỷ lệ từ chối thực tế. Evidence replay lịch sử ghi 8 câu từ chối tường minh và 6 bất đồng action/text; đó là diagnostics literal, chưa phải nhãn người: [`offline-evidence.json`](superpowers/plans/2026-11-26-agent-reliability-offline-evidence.json).

## 6. Phân tích các trường hợp hệ thống làm sai

Các ca dưới đây được đọc trực tiếp từ trace hiện có, do trợ lý AI phân tích, chưa phải đánh giá người độc lập. Mỗi vị trí ghi **dòng JSONL, scenario/call/turn**. `B` = [`before Full`](../eval_results/before/btc7_full.jsonl); `N` = [`baseline`](../eval_results/before/btc7_baseline_no_memory.jsonl); `P2` = [`after P2 Full`](../eval_results/after_p2/btc7.full.jsonl). Events cùng prefix cung cấp rejection/recovery; tool list của dòng không bao gồm toàn bộ lịch sử phiên, nên không suy “không gọi tool ở dòng này” thành “không có bằng chứng từ trước” trừ trường hợp receipt thao tác mới.

### 14 ca lỗi hội thoại và thực thi

| Ca | Vị trí và yêu cầu | Hành vi quan sát được / tác động | Nguyên nhân có bằng chứng và hướng xử lý |
|---|---|---|---|
| F01 | N dòng 5, SC01/call_2/1: nhắc máy đã hỏi trước | Hỏi lại mẫu nào; không phục hồi tư vấn AirPure Y | Baseline tắt liên phiên; lỗi trải nghiệm so với kỳ vọng carry-over. Full cùng dòng nhớ phòng 25m²/bé nhỏ/AirPure Y. Đây là lợi ích quan sát được của memory, không phải bug cài đặt baseline |
| F02 | N dòng 25, SC04/call_2/3: “lấy size 41 màu đen, lên đơn” sau trao đổi Facebook | Hỏi lại tên/mã giày, không tạo đơn | Mất tham chiếu giữa kênh/phiên; Full tạo đúng variant ở dòng 25. Khôi phục advice có nguồn nhưng vẫn phải kiểm identity và variant, không nối khách bằng SĐT tự khai |
| F03 | B dòng 2, SC01/call_1/2: nhà có bé, ngân sách khoảng 5 triệu | Hai đoạn đề xuất AirPure Y và giá 5,2 triệu bị lặp trong cùng câu trả lời | Events có draft bị `price_without_quote` rồi repair thành công; output giữ cả prefix và câu sửa. Nguyên nhân phù hợp với phát draft trước review. Code hiện tại buffer toàn câu; test publication kiểm nhánh này, chưa có run mới chứng minh hết lặp |
| F04 | B dòng 6, SC01/call_2/2: hỏi giá có như trước không | Chỉ fallback chung “chưa xác minh đủ”, không trả giá hay chỉ rõ phần thiếu | Events: hai lần `price_without_quote`, recovery fallback. Dòng trước đã refresh các sản phẩm nhưng checker/model không chuyển evidence thành câu hữu ích. Cần ràng buộc đúng sản phẩm và sửa câu từ quote; không nới kiểm giá |
| F05 | B dòng 7, SC01/call_2/3: đồng ý lên đơn, giao địa chỉ cũ | Đọc lại offer 5,2 triệu và xin xác nhận lần nữa; chỉ quote/stock, không `order.create` | Completion thiếu hành động; scorer fail SC01. Phải kiểm địa chỉ/consent còn thiếu thật hay hỏi thừa. Continuation hiện tại có thể yêu cầu model hoàn tất nhưng vẫn qua authorization; không tự tạo đơn để khớp scenario |
| F06 | B dòng 19, SC03/call_2/3: đồng ý làm thủ tục đổi size | Nói đã tiếp nhận, phiếu sẽ gửi và shipper thu hồi; chỉ có `order.preview_update(status=preview)` | Preview bị diễn đạt như đã ghi, còn hứa logistics chưa có receipt. Cần `order.update` thật và diễn đạt đúng status. P2 dòng 19 có update `review_pending`; chỉ xác nhận chờ duyệt. Replay checker hiện tại từ chối câu B với `order_update_unverified` |
| F07 | B dòng 21, SC04/call_1/2: hỏi “có giảm không” | Fallback không báo KM, không hỏi đúng thông tin thiếu | Events: `promotion_quote_missing` cả draft/repair; không có pricing call tại dòng. Cần resolve variant rồi lấy quote thích hợp hoặc giải thích phần chưa biết; không biến catalog price thành ưu đãi |
| F08 | B dòng 29, SC05/call_2/2: phản đối giảm 500k cũ hết hạn | Lời xin lỗi nối với fallback chung, không giải thích ngày hết hạn/offer hiện tại | Events: `promotion_detail_unverified`, repair cũng bị chặn. Cần phân biệt giá lịch sử, chương trình hết hạn và quyền lợi mới; không tự bù giá ngoài tool |
| F09 | B dòng 30, SC05/call_2/3: “thôi cũng được, lên đơn” | Xin lỗi rồi fallback, không có business tool mới hay receipt tạo đơn | Events: `price_without_quote` và fallback; task fail. Cần continuation có tools sau khi xác định consent với offer mới; recovery viết lại không đủ để hoàn thành giao dịch |
| F10 | B dòng 35, SC06/call_2/2: hỏi ship COD ở Q7 HCM | Phát “có hỗ trợ ship COD” rồi nối fallback không xác minh | Events: `promotion_quote_missing` hai lần dù có pricing call trong lượt. Chưa có bằng chứng để quy lỗi cho model hay checker riêng lẻ; cần tách COD/ship và kiểm quote theo địa điểm. Buffer tránh ghép thông điệp mâu thuẫn |
| F11 | P2 dòng 2, SC01/call_1/2: ngân sách/bé nhỏ | Đầu câu đề xuất máy AirPure Y, cuối câu hỏi thêm về “Màng lọc thay thế AirPure X/Y” | Fallback chuyển trọng tâm sang quà sau read `catalog.get_details`; events có `price_without_quote` rồi fallback. Code mới chỉ cho fallback chọn sản phẩm được khách hiện tại gọi rõ và loại gift-only; chưa có generation sau sửa |
| F12 | P2 dòng 6, SC01/call_2/2: hỏi giá máy cũ | Gọi `pricing.get_quote` cho màng lọc và trả lời về màng lọc, thay vì máy đã tư vấn | Gift role bị kéo thành mục tiêu của read/reply; không chỉ là fallback chọn từ sai. Cần bảo toàn main/gift trong evidence, memory admission và prompt; đọc giá/kho quà không chứng minh khách chọn quà |
| F13 | P2 dòng 30, SC05/call_2/3: đồng ý lên đơn | Câu xin lỗi bị lặp, rồi yêu cầu xác nhận payment; không có `order.create` | Events đánh dấu repair `succeeded`, nhưng task vẫn chưa xong. Review “câu có nguồn” không đo completion. Khi mặc định COD hợp lệ và đủ dữ kiện cần continuation; thiếu điều kiện thật vẫn phải hỏi |
| F14 | P2 dòng 36, SC06/call_2/3: “ok lên đơn cho anh” | Khẳng định đơn đã lên thành công, giá 5,49 triệu, COD và quà; `tool_calls=[]` | Không có receipt tạo đơn trong lượt yêu cầu này. Scorer fail SC06, nhưng HR giá/KM vẫn 0. Checker hiện tại từ chối với `order_creation_unverified`; trước khi ghi thật vẫn phải kiểm verified actor, không khôi phục phone fallback thiếu xác thực của run cũ |

F01–F02 mô tả failure của baseline theo yêu cầu đánh giá; F03–F14 là 12 lượt Full làm sai hoặc không hoàn thành. Các lỗi cùng gốc vẫn được giữ thành từng ca vì xảy ra ở các yêu cầu/điểm lifecycle khác nhau. Không suy từ một ca đã bị checker từ chối rằng người dùng đã nhận được câu sửa tốt.

### Hai sai lệch phép đo cần đọc cùng bảng HR

| Ca đo | Vị trí | Bằng chứng và ảnh hưởng |
|---|---|---|
| M01 — giá cuối bị gán thành giá niêm yết | B dòng 24, SC04/call_2/2 | Agent nói giá cuối 1.521.000đ, giảm 169.000đ so với niêm yết 1.690.000đ. `claims` lại chứa `list_price_vnd=1521000` và `list_price_vnd=1690000` cùng câu. Score tính claim đầu sai. Đây là lỗi gán trường có bằng chứng trực tiếp, không thể dùng làm ví dụ agent thực sự báo niêm yết 1.521.000đ |
| M02 — phủ định hết hạn bị tách khỏi mã KM | B dòng 28, SC05/call_2/1 | Agent nói AP-SEP “hiện đã hết hạn”, giá mới 4.890.000đ. Extractor gán `promo_AP-SEP_active=true` từ phần câu đứng trước dấu phẩy; score tính sai so với truth false. Cần giữ phủ định/ngữ cảnh câu, không sửa điểm/trace lịch sử để che vấn đề |

Ở M01, agent còn hỏi size/màu; việc đó có thể cần thiết cho variant, không mặc định là hỏi thừa. Ở M02, quà mới trong quote không có nghĩa AP-SEP vẫn còn hiệu lực. Không nhập hai loại khuyến mãi vào một nhãn generic để kết luận phát ngôn sai.

Hai ca này giải thích vì sao score trước ghi HR giá/KM 2/15 trong khi đọc câu trả lời cho thấy cần review extractor. **Không tính lại một “HR đúng”** từ hai ca, vì cần rà toàn bộ claims, mẫu số và các claim bị bỏ sót trước.

### Tổng hợp nguyên nhân

Các ca cho thấy bốn điểm yếu chính: mất tham chiếu liên phiên, gift làm nhiễu sản phẩm chính, recovery chỉ sửa lời mà chưa hoàn tất thao tác, và phát ngôn hoàn thành không gắn receipt. Lỗi phát draft/sửa ghép cũng làm câu trả lời lặp hoặc tự mâu thuẫn. Phép đo còn yếu ở ánh xạ claim và phạm vi ground truth.

Ưu tiên kiểm lại các ca F06/F14 vì tác động nghiệp vụ trực tiếp, rồi F11/F12 vì có thể lan vào memory; sau đó mới tối ưu fallback/latency. Đây là ưu tiên rút ra từ bằng chứng, không phải công bố các ca đã được giải quyết live.

## 7. Xác minh offline thực hiện khi viết báo cáo

Áp dụng trên checkout đã nêu, giữ nguyên các thay đổi người dùng có sẵn:

```bash
PYTHONPATH=ai-services:ai-services/test:. ai-services/.venv/bin/python -m pytest -q \
  ai-services/test/test_general_order_and_guardrail_fixes.py \
  ai-services/test/test_guardrail_precision.py \
  ai-services/test/test_verifier_review_reuse.py
```

Kết quả: **85 passed in 2.11s**. Các test dùng fixtures/mock, kiểm payment normalization, commerce evidence, budget versus giá bán, phạm vi claim, buffer câu trả lời và reuse/invalidation của semantic verdict. Đây là selection tập trung, không phải toàn bộ suite hoặc đánh giá model thật.

Replay chỉ đọc hai dòng đã lưu, truyền nguyên `agent_text`, `tool_calls`, `user_text` vào các checker hiện tại:

| Dòng replay | `check_grounding` | `check_answer` |
|---|---|---|
| B dòng 19 | `order_update_unverified` | `order_update_unverified` |
| P2 dòng 36 | `order_creation_unverified` | `order_creation_unverified` |

Replay xác nhận lớp kiểm hiện tại bắt được hai phát ngôn thao tác sai. Nó không gọi LLM, không thực thi order và không dựng lại toàn bộ memory/session context; vì vậy không tạo ra TSR/HR/latency mới. Những kết quả test lịch sử trong các ledger được giữ là bằng chứng lịch sử, không cộng dồn thành một tổng test mới.

## 8. Mức đáp ứng và bằng chứng còn thiếu

| Hạng mục | Bằng chứng hiện có | Kết luận trong phạm vi báo cáo |
|---|---|---|
| Giảm RQR ≥40% tương đối | P2 0% so với baseline 31,6%; score ghi đạt | Đạt trên bộ 7 ca lịch sử, phụ thuộc extractor |
| TSR ≥70% | Full P2 4/7 = 57,1% | Chưa đạt; cấu hình tắt bảo vệ không thay cho kết quả Full |
| HR giá/KM <5% | P2 score 0/14 | Đạt theo score lưu sẵn; cần review trích xuất và bao phủ claim |
| Guardrail violations bằng 0 | Bộ đếm scorer bằng 0 | Đạt phạm vi bộ đếm; F06/F14 cho thấy chưa bao phủ mọi lỗi |
| Latency đạt mục tiêu triển khai | 39 lượt/6 brief, không gồm transport/audio; code streaming đã đổi | Chưa đủ chứng nhận latency hiện tại |
| Paired Full/baseline bộ 48 ca | Có manifest và runner; chưa có cặp trace được xác minh tại đây | Chưa có số đo tương ứng |
| Cải tiến code mới sau P2 | 85 test hiện tại, hai replay; ledger offline trước | Có bằng chứng hành vi hẹp; chưa có KPI live mới |
| Hai vòng knowledge release có kiểm soát | Workflow có trong code; P0–P2 giữ cùng policy release | Các bảng P0–P2 đo thay đổi harness, không phải hai vòng knowledge release |
| WER/CER, TTFA/voice end-to-end, chi phí/cuộc, TCA, nhãn người/judge | Có công cụ và một số tài liệu lịch sử; chưa xác minh bộ đo phù hợp cùng phiên bản | Không điền giá trị suy đoán |

Để có so sánh chốt cho bản hiện tại cần cùng model/tham số, prompt version, catalog/source fingerprint, ngày/seed, worker image, hardware và knowledge release; mỗi cấu hình dùng DB eval cô lập, giữ trace/report/extraction/hash. Xác minh deployment agent và worker cùng code, chạy lại các ca sai, đủ lượt cho latency và review claim/receipt độc lập trước khi kết luận cải tiến.

Runner live có reset runtime và gọi provider; báo cáo này chỉ ghi quy trình, không thực hiện các thao tác đó. Hướng dẫn vận hành nằm trong [README](../README.md); [`score_pair.py`](../eval/score_pair.py), [`trace_audit.py`](../eval/trace_audit.py), [`extraction_review.py`](../ai-services/eval_harness/extraction_review.py) cung cấp các bước ràng buộc bằng chứng.

## 9. Định vị artifact chính

| Artifact | Run ID / SHA-256 trace |
|---|---|
| Before Full | `8f6a6f6b-1984-4e02-b691-dca3704a5cb6`; `88d5b5554d9e352a0b3d5bc1e873b9d2ecde3e550e1301f817b7df622849fb0e` |
| Baseline không bộ nhớ | `ae75983d-448c-4107-856b-288c5f045905`; `555c9621ffb38d659656b8b95370105fe82719b4772eb1bc75085f62125f8d07` |
| P0 Full | `4ff6d04c-78cd-4d00-ab57-090c29b6b88e`; `b1d5300ba9580c08768e2c7012d869315b7af04e609ecce9a81e15b16a902aa0` |
| P1 Full | `aba290c6-ca1b-47dc-81d1-01b360160e66`; `0b3c45f603ece54251039184f006d1e82cb62c0edf40f085944fe68ec2dd3398` |
| P2 Full | `34caec4b-80dc-4fe5-a842-1417f2d27735`; `ee8669a1dc8a7cc20a376a858c6e52f97289b8e103ef16adcb0ffabfa756f72b` |

Đường dẫn và số dòng ở mục 6 cho phép mở lại từng ca mà không cần chạy model. Các artifact lịch sử không được sửa trong quá trình tổng hợp hai báo cáo.
