# Kiểm chứng memory — run 20261111T031614Z-d8c7ccfc

## Kết luận có điều kiện

- Lưu/enrichment và tiếp nối phiên chạy được trong sample: 39/39 enrichment completed; brief và episode trước có ở 18/18 lượt quay lại. Hai lượt memory_read_status=unknown là SAMPLE-04 call_1 turn 1–2 khi identity chưa biết, không phải evidence memory read thất bại.
- 21 fact requirements: 11 có prior accepted write và key ở context đầu phiên sau; cả 11 xuất hiện lại ở mức key. Không quan sát được trường hợp có prior write nhưng key vắng. Điều này không chứng minh accuracy/source/value/TTL/isolation của toàn bộ memory.
- 4/21 được scorer ghi nhận dùng; 7 có key nhưng chưa được ghi nhận dùng; 10 không có prior fact write hoặc key trong context fact đầu phiên sau. Không ép lưu fact chỉ vì facts_established có nhãn.
- RQR full 0/4, baseline 4/10=40%; đạt mức giảm tương đối >=40% trên sample này. Chưa nghiệm thu tổng quát: mẫu nhỏ, extraction needs_review và 12/18 lượt quay lại lỗi model.
- CCR chính thức vẫn 19%; không đổi scorer, nhãn hoặc trace gốc để tăng điểm. Sample 7 ca không thay cho ít nhất 20 ca đa phiên/5 ca khó. Chưa chạy bộ team hay live inference trong audit này.

## Bảng 21 fact requirements

Coordinate viết dạng call_1:T1. Cột context chỉ là key trong stages đầu call_2, không phải full value/source snapshot. Cột use dựa đúng facts_used và argument-key rule của BTC. Không có write ≠ không có thông tin trong history/episode/CRM.

| Scenario | Fact | Prior writes quan sát được | Context đầu call_2 | Official use |
| --- | --- | --- | --- | --- |
| SAMPLE-01 | product_advised | call_1:T1 `"SKU-AP-X"` | product:SKU-AP-X | Chưa ghi nhận |
| SAMPLE-01 | price_quoted_vnd | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-01 | room_area_m2 | call_1:T1 `25` | prior_fact_keys | Chưa ghi nhận |
| SAMPLE-01 | blocker | call_1:T4 `"cần hỏi chồng"` | prior_fact_keys | Chưa ghi nhận |
| SAMPLE-02 | product_advised | call_1:T1 `"SKU-AP-X"` | product:SKU-AP-X | T2 |
| SAMPLE-02 | price_quoted_vnd | call_1:T1 `4890000` | product:SKU-AP-X | Chưa ghi nhận |
| SAMPLE-02 | competitor_price_vnd | call_1:T2 `4590000` | prior_fact_keys | Chưa ghi nhận |
| SAMPLE-02 | objection | call_1:T2 `"dat_qua"` | prior_fact_keys | Chưa ghi nhận |
| SAMPLE-03 | order_id | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-03 | variant_sku | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-03 | size | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-03 | color | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-04 | product_advised | call_1:T1 `"SKU-SN-RUN2"` | product:SKU-SN-RUN2 | T1 |
| SAMPLE-04 | price_quoted_vnd | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-04 | promo_code | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-05 | product_advised | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-05 | price_quoted_vnd | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-05 | promo_code | Không có fact write | Không thấy key | Chưa ghi nhận |
| SAMPLE-06 | product_advised | call_1:T1 `"SKU-XM-4P"`; call_1:T1 `"SKU-XM-4L"` | product:SKU-XM-4P, product:SKU-XM-4L | T2, T3 |
| SAMPLE-06 | price_quoted_vnd | call_1:T1 `2990000`; call_1:T1 `5490000` | product:SKU-XM-4P, product:SKU-XM-4L | T3 |
| SAMPLE-06 | room_area_m2 | call_1:T2 `35` | prior_fact_keys | Chưa ghi nhận |

## Phân tích theo nguyên nhân

- SAMPLE-01: room/blocker/product AP-X có write và key; không có fact giá cũ được lưu. Phiên sau tạo đơn AP-Y giá 5,2 triệu không chứng minh nhớ lời báo giá AP-Y trước đó. Source dialogue và nhãn dự định không đồng nhất.
- SAMPLE-02: bốn fact cần mang theo đều có write và key. Cả ba lượt quay lại model lỗi; chỉ product được đánh dấu dùng. Ưu tiên khả năng dùng context, không kết luận store làm rơi fact.
- SAMPLE-03: phiên đầu không tìm được sản phẩm và không tạo order. Không được sinh order_id/variant/size/color của đơn chưa có để đáp ứng nhãn. Failure nguồn nghiệp vụ xảy ra trước bước memory carryover.
- SAMPLE-04: product có nguồn; lời báo giá 129–169 triệu sai không trở thành verified price fact, không có quote tool thành công ở call_1. Không lưu giá sai là hành vi đúng; đơn call_2 dùng tra cứu hiện tại. Hai lượt Fanpage đầu chưa biết identity.
- SAMPLE-05: không có pricing tool/correct offer ở call_1, chỉ câu trả lời phủ nhận giảm giá và lời hẹn gọi lại. Episode có không đảm bảo fact giá/KM cũ tồn tại; không lấy nhãn dự định làm sự thật.
- SAMPLE-06: cả Pro/Lite và giá riêng có writes và scoped keys. Diện tích 35 có nguồn, nhưng không được ghi nhận dùng ở call_2. Việc có hai sản phẩm không thể tự hiểu thành đã chọn Pro. Grounding giá phải đúng SKU; extractor HR có dấu hiệu gán 2,99 triệu của Lite sang Pro, chưa sửa trong scope memory/questions.

## Review extraction và ranh giới bằng chứng

- `facts_used` đòi source phiên trước, đúng scope/value, loại customer vừa nhắc lại và không dùng failed tool. Runner dùng snapshot đầu call, giữ catalog aliases qua các lượt. Giữ các ranh giới này; không thêm credit chỉ vì key có mặt hoặc đơn được tạo.
- Trace public không chứa full snapshot value/source/session của profile/scoped_facts; không thể tính lại causal recall hay xác minh từng value đọc ra từ artifact. Không tự tái dựng snapshot từ đáp án label. Bảng JSON đi kèm giữ phần unknown rõ ràng.
- Bug tái hiện: “Mình đồng ý báo giá này để em lên đơn không ạ?” thành blocker/open. Sửa thành price_quoted_vnd/confirm, thêm test giữ câu hỏi về chồng/vợ là blocker và dùng nguyên scorer chứng minh lần xác nhận đầu hợp lệ, lần thứ hai là thừa.
- Replay reextract_trace vào thư mục /tmp mới kiểm hash toàn bộ nguồn và scorer, source_preserved=true; không thay lời agent/tool/facts_used. Tất cả metric delta bằng 0, score chính thức giữ nguyên. Extraction vẫn needs_review, không tự duyệt toàn bộ vì đã sửa một bug.
- Có 3 dòng câu hỏi đổi nhãn; chi tiết old/new và fingerprint lưu trong [JSON audit](memory-evidence-audit-20261111.json).

## Bộ team và bước tiếp theo

Đã tìm thấy hai ZIP `dataset/team22-edge-*` ngày 03/11 và hai source trong `speech/dialogues/`: tổng 22 dialogue, mỗi bundle 11. Đọc ground_truth/source trực tiếp xác nhận cả 22 không có `calls` hoặc `must_carry_over`; đây là dữ liệu speech/ASR một cuộc gọi, chưa phải 22 scenario đa phiên mới để đo CCR/RQR. `dataset_index.json` khai 19 ca nhưng không chứng minh bộ team mới đã có; chỉ có 7 scenario JSON rời trong eval_harness/scenarios. Đã hỏi người dùng vị trí bộ bổ sung mới và đang chờ; không tự coi bộ ASR cũ là bộ mới, không tạo dataset thay thế.

Khi nhận file: kiểm format/ngày/kênh/identity, >=20 ca đa phiên và >=5 ca khó; kiểm nhãn carryover đúng lời thực sự có thể được xác lập, tách nhớ fact khỏi lựa chọn/consent/receipt; kiểm success_if theo quote/stock/promo ngày cuộc gọi. Chốt dữ liệu trước chạy, cùng model/code/seed/full-baseline. Xác định rõ DB eval tách biệt trước live run/reset.

## Verification

- `load_pair` xác minh scenario/trace/score/manifests và scorer snapshot; `verify_report_turn_diagnostics` xác minh stages/events.
- Audit script kiểm đủ 21 rows, tổng official-used =4 khớp score. Hash nguồn được lưu trong JSON audit.
- Focused extraction/fact usage/report tests: 75 passed; scorer alignment/reextract tests: 18 passed. Không gọi model hoặc đụng database triển khai.
