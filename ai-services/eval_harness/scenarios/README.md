# Bộ scenario của team

T01–T22 đã trỏ vào 22 khách phân biệt có sẵn trong CRM BTC gốc; không trùng
khách của T23–T29 và không dùng số điện thoại chung C034/C035. T23–T29 giữ
nguyên dữ liệu và scenario_id SC01–SC07.

Không sửa hoặc bổ sung CRM/catalog BTC. `_crm_seed.json` là fixture team cũ,
được giữ nguyên để tham khảo, không dùng cho bộ test này và không import vào DB.
Canonical loader bỏ qua file có tên bắt đầu bằng `_`; không dùng validator
legacy `--all` vì nó coi cả file metadata này là scenario.

## Mapping khách

| Ca | Customer BTC | Tên | Kênh |
| --- | --- | --- | --- |
| T01 | C037 | Toàn | hotline, zalo_oa |
| T02 | C002 | Tuấn | hotline |
| T03 | C039 | Cường | hotline, zalo_oa |
| T04 | C003 | Lan | hotline, zalo_oa |
| T05 | C005 | Hương | hotline |
| T06 | C043 | Tiến | hotline, zalo_oa |
| T07 | C009 | Ngọc | hotline, zalo_oa |
| T08 | C045 | Lâm | hotline, zalo_oa |
| T09 | C006 | Nam | hotline |
| T10 | C011 | Mai | hotline, zalo_oa |
| T11 | C032 | Tâm | hotline |
| T12 | C031 | Oanh | hotline |
| T13 | C047 | Đạt | hotline, zalo_oa |
| T14 | C013 | Trang | hotline, zalo_oa |
| T15 | C015 | Vy | hotline |
| T16 | C049 | Trung | hotline, zalo_oa |
| T17 | C008 | Long | hotline |
| T18 | C010 | Đức | hotline |
| T19 | C004 | Minh | chat_fanpage, hotline |
| T20 | C019 | Linh | hotline |
| T21 | C021 | Yến | hotline, zalo_oa |
| T22 | C014 | Huy | hotline |

## Các điều chỉnh nghiệp vụ

- T10 dùng đúng tên xe đẩy Joie Pact/SKU-MB-STR1 trong catalog BTC, giữ giá và
  tổng giỏ 8.480.000đ. T14 dùng đúng loại quạt đứng Senko TS16. Call so sánh
  T14 không có một `price_vnd` chung vì đang báo giá hai SKU; bỏ nhãn HR giá
  mơ hồ này, giữ kiểm tra giá đơn Panasonic 2.450.000đ trong `args_match`.
  Giá tư vấn từng SKU phải đối chiếu quote riêng. Thay đổi phạm vi nhãn này
  không chứng minh HR của agent được cải thiện; kết quả run cũ giữ nguyên.
- T11 dùng đơn shipping OD301177 của Tâm/C032, đổi sản phẩm được hỏi từ nồi
  chiên sang Spectra S1; ngày đặt 03/10/2026, tracking GHN7781234 theo seed.
- T12 dùng Oanh/C031, có đơn delivered OD188213 / AirPure X 2024 từ 17/02/2026
  để đủ quyền trade-in. Sửa lời thoại “năm ngoái” thành “tháng 2 năm nay”.
- T02/T20 thêm phiên mua Windbreak ở call_1 rồi đổi ở call_2, theo dõi ở
  call_3. Không dùng OD487215/OD752946 giả định; matcher lấy mã đơn thật được
  order.create trả về theo cơ chế alias của scorer BTC tháng 11.
- T22 dùng ba phiên: mua Xiaomi 4.5L → trả hàng và hỏi form hoàn tiền → tra
  đơn cũ. Gộp phần hoàn tiền vào phiên trả, giữ tiêu chí trả lời về form;
  bỏ speech_dialogue_ref cũ sau thay cấu trúc. Không dùng OD768213 giả định.
- T20 miễn phí vận chuyển lần đổi đầu, vẫn có chênh lệch 40.000đ khi L be
  chuyển sang XL navy. Đã bổ sung lời xác nhận đồng ý phần chênh lệch.
- T15 không còn giả định RO10 đã được tư vấn ở phiên 1: khách nêu rõ mẫu này
  ở phiên 2; bỏ nhãn carry-over sản phẩm không được thiết lập chắc chắn.
- T19 dùng Facebook fb.minh.658 của C004 thay cho Zalo giả định. Các ca Zalo
  còn lại dùng đúng zalo_id trong CRM BTC.

Toàn thư mục hiện có 29 ca / 67 phiên / 170 lượt (`SC-T01`–`SC-T22` đã chuẩn hóa `persona` ID theo `BTC-Data-Vong1-TEAMS/simulator/personas.json`, bổ sung `days_later`, và căn chỉnh `customer_turns` theo state machine tư vấn `consultation.py` / `commerce_evidence.py` / `basket.py`). Lời khách báo nhận hàng ở
các phiên hậu mãi là lời khai của khách; không tự sửa trạng thái giao hàng trong
DB/tool. Các nhãn chấm điểm không được cung cấp cho agent làm đáp án.

## Kiểm chứng offline

Đã kiểm contract, định danh từng kênh, SKU/variant, owner của đơn lịch sử,
đơn tạo từ phiên trước, giá/tồn kho và phí/chênh lệch đổi trả bằng mock BTC
tháng 11 trong snapshot tạm chỉ ghép patch chính thức. Không ghép CRM team.
Có 45 lượt kiểm expected tool bằng mock, không phải kết quả hội thoại model.

Kiểm contract và nhãn độ phủ từ root repo (chỉ đọc file):

```bash
PYTHONPATH=ai-services:. ai-services/.venv/bin/python -m eval_harness.preflight \
  --offline-check --scenarios ai-services/eval_harness/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS
PYTHONPATH=ai-services:. ai-services/.venv/bin/python -m eval_harness.m1_acceptance \
  dataset ai-services/eval_harness/scenarios --btc-root ../BTC-Data-Vong1-TEAMS
```

Chạy eval thật cần gói BTC đầy đủ chứa scorer đã cập nhật để so khớp mã đơn động;
runner tạo snapshot trực tiếp từ `--btc-root` bằng prepare_btc_release, không
cần thư mục patch riêng. Kiểm offline không chứng minh
model đạt TSR/CCR/RQR. Chưa gọi model, import/reset DB hoặc chạy eval live.
