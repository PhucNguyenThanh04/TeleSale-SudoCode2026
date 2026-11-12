# Review offline bộ scenario mới — 11/11/2026

**Cập nhật sau chỉnh phạm vi:** T01–T22 đã dùng 22 khách có sẵn trong BTC,
định danh kênh thật và đơn đúng chủ. T02/T20/T22 tạo đơn bằng phiên mua trong
chính scenario; T11/T12 dùng hai đơn seed BTC có sẵn. Không ghép CRM team;
nguồn BTC và T23–T29 giữ nguyên. Xem [mapping và thay đổi cụ thể](../ai-services/eval_harness/scenarios/README.md).
Phần dưới là review lịch sử trước khi sửa, không phải danh sách blocker hiện
hành. Các đề xuất bổ sung fixture trong review này đã bị loại bỏ.

Nguồn: `ai-services/eval_harness/scenarios/` ở thời điểm review. Không chỉnh file
scenario, CRM/catalog BTC, harness hoặc DB; không gọi model/eval live. Contract
đối chiếu là gói BTC gốc ghép patch `BTC-cap-nhat-11-2026` bằng prepare_btc_release
trong temporary directory, không đổi nguồn BTC.

## Kết luận

Chưa chạy eval toàn bộ. Quy mô đã đủ cho một lượt lớn, nhưng có blocker contract
và thiếu fixture đầu vào khiến phép đo memory/TSR không đáng tin với seed hiện tại.

- 29 JSON, ID không trùng: 22 ca team T01–T22, 7 ca dựa sample BTC ở T23–T29.
- 65 cuộc gọi, 225 lượt; 28 ca đa phiên, 14 ca có nhiều kênh, 15 ca khó theo nhãn.
- 8 file bị load_scenarios từ chối; validator dừng ở lỗi đầu nên toàn thư mục
  không thể chạy. 21 file còn lại chỉ qua contract cơ bản, không có nghĩa qua
  kiểm chứng nghiệp vụ, identity hoặc đã chạy model.
- Các call_date/days_later và SKU/variant trong success args được kiểm; chưa
  thấy SKU/variant không tồn tại. Đối chiếu giá/stock ở các success có SKU bằng
  mock BTC Nov; trade-in T12 phụ thuộc fixture sở hữu máy cũ còn thiếu.

## P0 — Các lỗi phải giải quyết trước chạy

| Vấn đề | Ca cụ thể | Bằng chứng / hướng xử lý |
| --- | --- | --- |
| expected_outcome ngoài contract | T01/T03/T06/T09/T13/T17/T22, đều call_3 | tra_cuu_don, tu_van_doi_hang, tu_van_gia_ton, tu_van_san_pham, tra_cuu_hoan_hang không được hỗ trợ. Contract hiện có hen_goi_lai/chot_don/chuyen_may/tu_choi. Nếu chỉ là mô tả mục tiêu, dùng customer_goal/notes và bỏ expected_outcome không phù hợp, giữ success_if; không gán chot_don cho lượt chỉ tư vấn. |
| Tool thật chưa đồng bộ với validator | T18 call_1: policy.search | Production có policy.search ở MCP Knowledge nhưng tools.schema BTC không liệt kê; load_scenarios báo expected_tool_unsupported. Đây là lệch hợp đồng harness, không kết luận policy.search là tool sai. Cần xử lý extension hợp lệ hoặc tiêu chí quan sát phù hợp, không sửa scorer BTC hay bỏ assertion để lấy green. |
| Khách mới không có trong CRM nguồn | T01–T22, cả 22 phone có 0 hit trong crm_seed BTC | Scenario metadata/notes không tự tạo customer. Không có owner thì long-term facts/order creation không thể hoạt động như người đã xác minh. Cần fixture CRM riêng cho bộ team, nạp tường minh vào DB eval và giữ fingerprint giống nhau giữa full/baseline. Không sửa CRM BTC để chấm hidden. |
| Mapping đa kênh chưa có | T01/T03/T04/T06/T07/T08/T10/T13/T14/T16/T19/T21 dùng team-harness-v1-tXX | Tất cả ID này có 0 hit Zalo trong CRM nguồn; T13 lặp lại ở call_3. Dùng cùng customer_phone ở metadata không chứng minh Zalo ID thuộc khách đó. Fixture phải nối phone/Zalo cho cùng owner; không bỏ identity guard hay tự tin dữ liệu khách khai. |
| Đơn được giả định tồn tại chưa có fixture | T02 OD487215, T11 OD731508, T20 OD752946, T22 OD768213 | Không thấy trong orders của CRM BTC, không được tạo từ call trước, không có seed order declaration được runner áp dụng. Notes nói có đơn không tạo ra đơn. Cần seed order đúng chủ, SKU/variant, payment, date/status để kiểm đổi/trả/tra cứu. seed_history hiện chỉ bổ sung lịch sử phiên CRM, không phải cơ chế tạo order. |
| Matcher PII xung đột redaction | T01/T03/T17/T22 call_3 | success_if.args_match.customer_phone là literal phone. inspect_eval_inputs báo pii_args_match; trace mask thành [SỐ ĐÃ ẨN] nên không so khớp số gốc đáng tin. Dùng business order_id/receipt đã xác minh và assertion owner-binding riêng; không tắt masking hoặc bỏ kiểm ownership trong runtime. |

Nếu người làm dataset đã có fixture CRM/orders nằm ngoài thư mục hoặc đã import
trên DB riêng, cần cung cấp file, lệnh nạp và hash để kiểm chứng. Kết luận thiếu
fixture ở trên dựa vào seed/source/runner đang có trong checkout; không khẳng
định đã truy vấn DB triển khai. Đã tìm cả các file ignored liên quan dưới dataset
và speech/data; chưa thấy fixture CRM/seed tương ứng.

## P1 — Chất lượng nhãn và sức phân biệt

1. T12 yêu cầu AirPure Y 4.800.000đ ngày 27/10. Với customer chưa có lịch sử,
   mock trả 5.200.000đ, TRADE-IN-AP ineligible requires_owned_sku. Chạy mock với
   một owner seed có SKU-AP-X-2024 delivered thì đúng 4.800.000đ. Giữ ý định test
   trade-in và seed điều kiện sở hữu hợp lệ; không tự đổi giá để chạy qua.
2. T01 call_3 vẫn must_carry_over/blocker sau khi vợ đã đồng ý ở call_2 và đơn
   đã chốt. Cần phân biệt blocker đã giải quyết với blocker đang có hiệu lực;
   không yêu cầu hệ thống nhắc/ràng buộc lại blocker cũ. Ưu tiên trạng thái đơn,
   sản phẩm, quà tặng/điều kiện đã chấp nhận đúng nguồn.
3. Nhiều call_2 order.status chỉ yêu cầu tên tool, không kiểm đúng đơn hoặc
   kết quả thành công. Cần đọc thêm diagnostic/result assertion cho owner/order;
   call đúng tên nhưng order_not_found không phải tác vụ thành công thực tế.
   Giữ scorer BTC nguyên bản, báo phần kiểm bổ sung riêng nếu contract chưa hỗ trợ.
4. T13 buộc catalog.search.max_price_vnd=5500000: kiểm đúng một cách truyền filter,
   chưa đủ chứng minh kết quả tư vấn tuân ngân sách hoặc memory cũ bị supersede.
   memory_expectation.superseded là heuristic/review của scorer, không phải một
   full state assertion tự động. Kèm kiểm state/value/source thực tế trước khi
   tuyên bố budget update đúng.
5. Call_3 nhiều ca khách tự nhắc lại model/size/diện tích. Extractor facts_used
   loại dữ kiện khách vừa cung cấp khỏi credit recall; đừng coi CCR thấp ở các
   lượt này tự động là quên. Cần vài lượt quay lại không nhắc lại value để đo nhớ.
6. Bộ mới không phải holdout nguyên vẹn nếu đã xem và dùng để chỉnh code. T23–T29
   dựa sample BTC, không tính là 7 ca team mới độc lập. Tên file T23 nhưng ID SC01
   hợp contract nhưng cần index/binding audio theo scenario_id, không suy từ tên.
7. Lịch giao/nhận ở call_3 là lời khách, không tự cập nhật order lifecycle trong
   tool. Nếu chấm trạng thái delivered/pickup/refund, phải có fixture/event nguồn
   tương ứng; không suy tool đã cập nhật chỉ vì thời gian trôi qua.

## Các điểm tốt đã kiểm

- Đủ số ca đa phiên và số lượt để vượt ngưỡng dataset/latency về quy mô trên giấy.
- Câu hỏi có budget update, multi-product, alias ASR, promotion expiry và call_3
  hậu mãi; success_if có cả cấm write khi khách chỉ hỏi, giúp bắt tạo đơn thừa.
- Stock của trekking 41 trắng (19/10), Windbreak XL be (28/10), Tower Fan (22/10)
  đều thật sự hết trong mock, phù hợp ý định các ca khó liên quan.
- Mọi giá đối chiếu được ở success có SKU khớp mock theo ngày trừ T12 do thiếu
  owned-SKU condition. Nhận xét này chưa kiểm chứng toàn bộ free-form speech hay
  tất cả điều kiện ngầm trong dữ liệu.

## Kiểm tra đã thực hiện

- Per-file load_scenarios với effective BTC Nov: 8 failures kể trên; aggregate
  load fail outcome_unsupported. Không bỏ qua lỗi để tạo run validated giả.
- inspect_eval_inputs: 7 unsupported_outcome +1 unknown_expected_tool +4
  pii_args_match. Không có trace mới nên không kết luận runtime identity/quality.
- CRM source đối chiếu phone/channel/order; đọc code initialize_identity,
  SeedHistoryGateway và runner để xác nhận metadata không auto seed CRM/order.
- Mock Nov thuần Python với catalog gốc, chỉ state trong process, không DB/LLM;
  kiểm giá/tồn kho và trade-in conditional; các source không bị sửa.

Thứ tự xử lý đề xuất: contract + fixture/identity/orders + matcher PII → kiểm
lại offline → smoke vài ca đại diện → mới chạy full 29 ca trên DB eval riêng.
Đây là review, chưa có chỉnh sửa scenario hoặc triển khai fixture mới.
