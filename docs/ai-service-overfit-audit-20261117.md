# Rà soát hardcode và khả năng tổng quát của ai-services

Ngày: 17/11/2026. Phạm vi: mã nguồn `ai-services`, tập trung các quyết định có thể phụ thuộc vào dữ liệu/kịch bản publish. Giữ nguyên các thay đổi đã tồn tại trong checkout trước đợt rà soát này.

## Phạm vi kiểm tra

- Quét tĩnh toàn bộ Python nguồn: 164 module trong `app`, 5 script Python, 94 module hỗ trợ đánh giá trong `eval_harness`, 7 module trong `rag_eval` (không tính các file test).
- Kiểm tra các literal về scenario, sản phẩm, thương hiệu, ngày, mã khuyến mãi; tham chiếu fixture/nhãn/expected answer; và điều kiện rẽ nhánh qua AST. Đọc luồng quyết định từ graph/harness tới công cụ catalog, pricing, order, consultation, variant resolution, guardrails, memory và policy retrieval.
- Đối chiếu các hằng số nghiệp vụ với dữ liệu promotion và hợp đồng được mô tả trong README. Các file scenario/test/QA là đầu vào đánh giá; không chuyển chúng thành dữ liệu phục vụ tư vấn.
- Không thấy nhánh ra quyết định nghiệp vụ theo ID `SC-T...`, customer fixture cụ thể hoặc expected answer trong runtime. Tham chiếu từ `system_start` tới helper fingerprint của eval dùng để kiểm tra dữ liệu khởi động, không đưa nhãn đánh giá vào câu trả lời.

Quét tĩnh hỗ trợ tìm điểm phụ thuộc dữ liệu; không phải bằng chứng rằng mọi cách diễn đạt ngôn ngữ tự nhiên đều được xử lý đúng.

## Các điểm đã sửa

| Điểm phụ thuộc trước đây | Cách xử lý hiện tại | Kiểm chứng |
| --- | --- | --- |
| `AIR-2ND-50` được dùng trực tiếp để xác định promotion đã sử dụng trong ngày | Truyền tập mã thực tế từ đơn cùng ngày; mỗi promotion đọc mã của chính nó | Đổi mã promotion, báo giá → tạo đơn → báo giá lại; giá và tạo đơn nhất quán |
| Chọn hàng giảm giá thứ hai bằng category máy lọc không khí và chỉ lấy promotion đầu tiên | Dùng `applies_to`, loại promotion, thời hạn và điều kiện; xét từng promotion, lọc variant hợp lệ trước khi chọn đơn vị rẻ nhất | Danh mục đèn mới, nhiều promotion, min_qty, vùng, quyền sở hữu, once_per_customer và size bị loại |
| Freeship giỏ hàng phụ thuộc mã `NAM-SHIP0` | Xác định từ promotion có type `freeship` đã được áp dụng | Mã freeship mới trên giỏ dưới ngưỡng miễn phí mặc định |
| Chỉ promotion quyền sở hữu đầu tiên được phân bổ một lần; discount stackable được liệt kê nhưng chưa trừ vào giá | Phân bổ theo từng mã và cộng discount được phép cộng dồn vào giá cuối | Hai promotion sở hữu khác nhau, discount cộng dồn |
| Danh sách size/màu đóng trong nhận diện claim; size `38` có thể khớp cả `38.5`, màu `xanh` có thể khớp `xanh dương` | Chọn giá trị từ metadata catalog; dùng chung matcher giữa chọn variant và gắn claim, ưu tiên giá trị dài nhất tại cùng vị trí | `3XL`, `38.5`, `one size`, màu nhiều từ; không nhầm từ “có”/“mẫu” thành lựa chọn variant |
| Mã không có tiền tố `SKU-` bị từ chối dù đã có catalog xác minh | Cho phép mã được xác minh bằng metadata; mô tả tool yêu cầu lấy nguyên mã từ catalog | SKU `LAMP:2028-A`; tên tự đề xuất chưa có bằng chứng vẫn bị chặn |
| Query chứa model số không có trong catalog bị bỏ phần số, trả về model khác | Giữ ràng buộc model khi tìm kiếm | `Nova 900` không trả `Nova 800` |
| Chuẩn bị giỏ chỉ nhận đúng hai sản phẩm, mỗi món một; không chuẩn bị giỏ nhiều đơn vị cùng mẫu | Nhận nhiều sản phẩm có số lượng rõ ràng; nhiều đơn vị cùng mẫu dùng quote_order; chọn variant qua metadata | Giỏ 2/3/4 sản phẩm, 2/3 đơn vị cùng mẫu, nhiều đơn vị của variant đã chọn |
| Parser số lượng và bộ lọc evidence khác nhau; bỏ “2 máy”, chỉ đọc chữ số cuối của số bằng chữ ghép | Dùng chung parser số lượng của basket, tái sử dụng parser số nguyên tiếng Việt sẵn có | “2 máy”, “ba chiếc”, “năm bộ”, “mười một chiếc”, “hai mươi ba máy”, “một trăm linh năm bộ” |
| Mô tả category của tool trông như danh sách category được phép cố định | Mô tả category theo catalog, các đường dẫn chỉ là ví dụ | Kiểm tra hợp đồng tool và test catalog với category mới |

Không thêm nhánh theo ID scenario hay tên sản phẩm của test mới. Bước chuẩn bị giỏ chỉ đọc dữ liệu; tạo đơn vẫn phải qua các gate về lựa chọn, offer đã nói với khách, consent, giá, tồn kho và danh tính.

## Hằng số được giữ có chủ đích

- Phí/giới hạn COD, phí đổi hàng, lịch nghỉ, lịch callback, thời gian vận chuyển và ngưỡng freeship mặc định: quy tắc nghiệp vụ của nguồn hiện tại, không phải đáp án cho một case hội thoại.
- Metadata policy về hiệu lực, phiên bản, liên kết điều khoản và nội dung được phép công bố: dữ liệu có nguồn và provenance. Không bỏ kiểm tra hiệu lực hoặc công bố nội dung nội bộ để làm parser tổng quát hơn.
- Alias tiếng Việt, regex nhận diện ngôn ngữ, giới hạn số tool và số ứng viên tư vấn: cơ chế diễn giải/giới hạn tài nguyên. Trường hợp không đủ bằng chứng vẫn cần model hoặc hỏi lại; không suy ra quyền mua từ kết quả tìm kiếm.

## Kết quả kiểm chứng

**278 test liên quan đã qua**. Không chạy toàn bộ suite, benchmark hay live model evaluation.

```bash
PYTHONPATH=ai-services:ai-services/test ai-services/.venv/bin/python -m pytest -q \
  ai-services/test/test_commerce_generalization.py \
  ai-services/test/test_catalog_generalization.py \
  ai-services/test/test_november_pricing.py \
  ai-services/test/test_second_item_promotion.py \
  ai-services/test/test_mcp_business.py \
  ai-services/test/test_catalog_query.py \
  ai-services/test/test_catalog_ranked.py \
  ai-services/test/test_price_grounding.py \
  ai-services/test/test_promotion_grounding.py \
  ai-services/test/test_product_switch_grounding.py \
  ai-services/test/test_variant_contracts.py \
  ai-services/test/test_basket_harness.py \
  ai-services/test/test_basket_runtime.py \
  ai-services/test/test_tool_budget.py \
  ai-services/test/test_business_completion.py \
  ai-services/test/test_consultation_shortlist.py \
  ai-services/test/test_consultation_flow.py \
  ai-services/test/test_model_tool_contract.py --tb=short
```

Hai file test generalization gồm 33 trường hợp, sử dụng dữ liệu tự tạo, không tải catalog/QA/scenario publish. Các lỗi xác nhận được đã có phản ví dụ thất bại trước sửa. Trong đợt kiểm tra rộng, 8 test basket runtime đã lỗi với logic có sẵn trước đợt này (xác minh bằng khôi phục hàm cũ trong bộ nhớ, không sửa checkout); thay đổi parser số lượng và chuẩn bị quote_order đã làm cả 8 test qua.

Giới hạn: kết quả chứng minh hành vi deterministic và hồi quy offline trong các tình huống đã kiểm tra. Chưa kiểm chứng khả năng tổng quát của model thật, prompt đang quản lý từ xa hay mọi tổ hợp promotion/ngôn ngữ tự nhiên. Không tự động publish prompt hoặc deploy dịch vụ.
