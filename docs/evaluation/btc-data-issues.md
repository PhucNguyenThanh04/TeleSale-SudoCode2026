# Các bất nhất nguồn BTC cần xác nhận

Nguồn: gói BTC cục bộ, mock/scorer cập nhật tháng 11. Không sửa các file BTC hoặc điểm lịch sử. Khi báo cáo, ghi rõ khác biệt giữa tài liệu, nhãn và tool; không tự coi một nguồn mâu thuẫn là bằng chứng chất lượng model.

| Vị trí | Quan sát offline | Cách xử lý trong bộ team |
|---|---|---|
| `pricing.quote_order` | Moaz Bebe 1.890.000đ có MOM-FREESHIP trong order_promos nhưng freeship=false; get_quote trả true. | Không dùng trường này làm nhãn duy nhất để chấm freeship. Giữ căn cứ VC-02 và điều kiện promotion; cần BTC xác nhận. |
| MOM-FREESHIP theo giỏ | Bình Pigeon + Fatz tổng 779.000đ không nhận freeship trong mock, dù policy quy định ngưỡng đơn 500.000đ. | TEAM-18 không gán một freeship vô điều kiện theo mock. Rà ngữ nghĩa theo chính sách và ghi bất nhất. |
| RAG Q57 | Đáp án ghi 10.435.000đ; quote_order tháng 11 tính Pro 7.690.000đ + X 2.445.000đ = 10.135.000đ. | Giữ nguyên bộ RAG BTC, công bố ca bất nhất thay vì thay reference để tăng điểm. |
| RAG Q29 | AX40 + AirPure X tháng 10 có giá sau KM 8.935.000đ; câu hỏi giả định tổng vượt 10 triệu. | Phân biệt giả định trong câu hỏi và tổng thực tế; cần BTC xác nhận expected answer. |
| Catalog SKU-WF-RO10 | attributes.stages=0, tên và SP-WF-01 ghi 10 lõi. | Không tạo nhãn zero-stage từ catalog. Ghi nguồn technical spec và mâu thuẫn khi chấm. |
| schedule.callback | Chủ nhật 18:30 bị dời đến thứ Ba 18:30; 11/11 lúc 22:00 bị dời 08:00 cùng ngày dù lịch sale mở 07:00–23:00. | Chưa dùng kết quả mock làm chuẩn ngữ nghĩa cho hai ranh giới này. Đối chiếu LN-01/LN-02 khi bổ sung ca. |
| Hồ sơ nguồn | README ghi 14 promotion nhưng JSON có 13; không có eval/validate_scenarios.py được README nhắc tới. | Báo số đếm thực tế và dùng kiểm tra offline của nhóm; không tuyên bố đã chạy validator BTC bị thiếu. |
| Judge prompt template | Có JSON mẫu chứa dấu ngoặc nhọn chưa escape; gọi str.format() trực tiếp báo KeyError criterion_id. | Giữ nguyên rubric, chỉ thay đúng ba placeholder scenario_json/transcript/criteria. Có test chạy prompt thực với stub. |

Scorer BTC còn cho phép check_call đạt khi order.status không có đơn, handoff tool báo lỗi, hoặc nhiều đơn cộng tổng đúng. `semantic_eval` của nhóm kiểm riêng kết quả tool, mã đơn, schema handoff và số đơn/giỏ; điểm chính thức vẫn giữ nguyên.
