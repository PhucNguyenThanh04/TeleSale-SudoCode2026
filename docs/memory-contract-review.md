# Rà soát hợp đồng memory C–D (đề xuất, chưa triển khai)

Ngày rà soát: 2026-10-18. Nguồn: gói BTC Vòng 1 tại `../BTC-Data-Vong1-TEAMS/` (tính từ thư mục cha repo), `app/constants.py`, `app/agent/memory/fact_candidates.py`, `app/agent/guardrails/checks.py`, `app/agent/harness/context.py`, `docs/memory-policy.md` và ba report `eval/runs/memory-fallback-diag-{1,2,3}.json`. Ba report dùng cùng `gemma4:31b`; đây là nhánh một lượt với tool giả lập chỉ đọc, không phải eval memory đa phiên. Điểm blocker được chuẩn hóa là phép **chấm lại** report, không phải cải thiện hệ thống.

## C. Hợp đồng BTC và code hiện tại

### Nguồn chuẩn và ý nghĩa slot

| Khái niệm | BTC công bố | Code/policy hiện tại | Kết luận |
|---|---|---|---|
| Size/màu | Public sample `SAMPLE-03` dùng `size=39`, `color="den"` cho biến thể/đơn; `must_carry_over` có `size`, `color`. `call_brief.schema.json` mô tả `profile_facts` mở, ví dụ `size`. Trace schema để `questions[].slot`, `facts_used[]` là string, không liệt kê slot. | Registry có cả `size`/`color` và `preferred_size`/`preferred_color`; policy phân biệt lựa chọn giao dịch và sở thích tự nêu. | BTC minh họa `size`/`color`, không định nghĩa hoặc bác bỏ cặp `preferred_*`. Reference evaluator so tên slot chính xác; nó không tự coi `preferred_size` bằng `size`. |
| Người ra quyết định/trở ngại | Sample `SAMPLE-01`, `SAMPLE-06` có `blocker="can hoi chong"`/`"can hoi vo"`; `SAMPLE-02` có `"so sanh gia"`. Call Brief nhận `open_blockers: string[]`, ví dụ chờ hỏi chồng/so sánh giá. | `blocker: str`; Call Brief lấy `profile.blocker` thành mảng một chuỗi. | BTC không có slot `decision_maker` riêng hay enum blocker được công bố. Quan hệ người cần hỏi hiện nằm trong text blocker. |
| Phản đối | `SAMPLE-02` có `objection="dat_qua"`; `must_carry_over` chứa `objection`. | `objection: str`; `fact_evidence` chỉ công nhận giá trị `dat_qua` qua nhánh đặc biệt cho cụm đắt/giá cao. | `dat_qua` là giá trị đã quan sát và được code hỗ trợ, **không phải enum đầy đủ do BTC công bố**. |
| Thanh toán | `tools.schema.json` quy định tham số `order.create.payment` là `COD|bank|momo|zalopay`; sample có `COD`. | Memory `payment: str` và extractor không ép enum. | Tập bốn giá trị là hợp đồng **tool đặt đơn**. Chưa có enum riêng được công bố cho memory slot. |

`call_brief.schema.json` yêu cầu `profile_facts: object` với `additionalProperties: true`, `open_blockers: string[]`, `must_not_ask: string[]`, và không ép enum cho các fact này. Mô tả `profile_facts` nói “kèm nguồn”, nhưng `context.py` hiện truyền `key -> value` không kèm nguồn: đây là chênh lệch mô tả/schema mềm, chưa sửa. `reference_eval.py` tính RQR từ `must_not_ask` và CCR từ `must_carry_over` bằng tên slot; nó không định nghĩa tập giá trị cho memory fact. Ngoài enum payment của tool, các giá trị quan sát trong public sample là: `objection={dat_qua}`, `blocker={can hoi chong, can hoi vo, so sanh gia}`, `color={den}`. Không thể gọi các tập sample này là đầy đủ.

**Kiểm public sample về sở thích chưa chốt:** bảy file `SAMPLE-*.json` không có trường `memory_writes`; không có nhãn `preferred_size`/`preferred_color`. `SAMPLE-03` ghi `size=39`, `color="den"` trong `facts_established` sau cuộc có mua hàng. Vì vậy public sample không cho biết một sở thích chưa chốt được ghi vào memory với key nào, và không đủ căn cứ để khẳng định BTC phân biệt hai cặp key.

**Đề xuất sửa lại, chưa triển khai và cần duyệt riêng:** một key BTC `size` và một key `color`; thuộc tính đi kèm `kind=preference|selection` biểu thị mức chốt, không tạo slot mới. Câu hỏi tồn kho đơn thuần không thành fact. Khi khách chọn/đổi biến thể, cập nhật `kind=selection` và giữ provenance; sở thích chưa chốt dùng `kind=preference`. Rủi ro trace: `reference_eval.py` chỉ so tên slot, nên `facts_used=["size"]` có thể được tính CCR dù agent chỉ dùng sở thích chưa chốt thay vì size đã mua; `must_not_ask=["size"]` có thể khiến agent bỏ qua câu xác nhận biến thể cần thiết. Trace hiện không có trường `kind` chuẩn, nên phải báo nghĩa `kind` ngoài `facts_used`/`questions[].slot` và đối chiếu lời thoại, tool args khi chấm; chưa được lén đổi tên slot hoặc coi điểm reference là bằng chứng dùng đúng mức chốt.

### Prompt/schema extractor hiện tại

Extractor được yêu cầu JSON `{fact_candidates:[{key,value,source}]}` với key trong danh sách, nhưng không có `evidence_quote`. Parser chỉ lọc cấu trúc JSON sơ bộ và PII/độ dài; `SlotSpec.value_type` hiện chỉ mang tính mô tả, chưa được parser/`fact_evidence` dùng để ép kiểu. `fact_evidence` nhận scalar `str|int|float|bool` chung rồi dùng các nhánh kiểm chứng riêng. Không có thuộc tính enum/allowed values trong `SlotSpec`.

| Customer slot | `SlotSpec.value_type` | Ràng buộc giá trị của extractor hiện tại | Kiểm chứng hiện tại đáng chú ý |
|---|---|---|---|
| `room_area_m2` | `int` | Không ép kiểu theo slot | Bằng chứng số nguyên dương + đơn vị diện tích. |
| `budget_vnd` | `int` | Không ép kiểu theo slot | Chỉ nhận int nằm trong số tiền parser nhận là ngân sách. |
| `has_children` | `bool` | Không ép bool theo slot | Nhánh bool kiểm cụm có/không có con; scalar khác vẫn đi qua nhánh chung. |
| `preferred_size`, `size` | `str|int` | Không enum | Cùng kiểm mẫu `size <value>`. |
| `preferred_color`, `color` | `str` | Văn bản tự do; không tập màu | Cùng kiểm mẫu `màu <value>` sau bỏ dấu. |
| `payment` | `str` | Văn bản tự do; không ép bốn giá trị tool | Kiểm `thanh toán/trả/ship <value>`; chưa chuẩn hóa `bằng`, case của value. |
| `competitor_price_vnd` | `int` | Không ép kiểu theo slot | Số tiền phải nằm gần cụm đối thủ trong lời khách. |
| `objection` | `str` | Văn bản tự do | Nhánh bằng chứng chỉ nhận `dat_qua` cho cụm đắt/giá cao. |
| `blocker` | `str` | Văn bản tự do | Nhánh chung nhận giá trị nếu là đoạn con của lời khách, không xét loại trở ngại. |

Các slot chỉ từ tool (`product_advised`, `price_quoted_vnd`, `promo_code`, `promo_expiry`, `order_id`, `in_stock`, `variant_sku`) không nằm trong prompt extractor khách; chúng cũng không có enum memory. `promo_expiry` có kiểu `str` mô tả, chưa ép định dạng ngày bằng `SlotSpec`.

### Đối chiếu log ba lần

Diagnostic ghi `decision=no_fact_evidence` và `fact_evidence=null` cho T11, M07, T16, T17, T20 trong cả ba lần. **`fact_evidence` chỉ trả nguồn hoặc `None`, không trả mã lý do nội bộ**; `no_fact_evidence` là mã do runner chẩn đoán gán. Quy tắc cụ thể dưới đây được suy ra từ giá trị đề xuất và nhánh code, không phải reason code đã được validator phát ra.

| Ca | Đề xuất trong log | Quy tắc khiến không có bằng chứng |
|---|---|---|
| T11 | `objection="Mức giá này đắt quá"` từ extractor | Nhánh `objection` đòi `value == "dat_qua"`; cụm nguồn có “đắt quá” nhưng value không chuẩn. |
| M07 | `objection="đắt quá"` từ extractor | Cùng quy tắc `value == "dat_qua"`. |
| T16 | `budget_vnd=2000000` từ agent và extractor | `customer_budget_amounts` không nhận cấu trúc có tên sản phẩm chen giữa “ngân sách” và “2 triệu”; tập số tiền trả về rỗng. |
| T17 | `payment="MoMo"` từ extractor (lần 1 thêm agent) | Mẫu kiểm chờ phương thức ngay sau `thanh toán/trả/ship`; câu có “bằng MoMo”, đồng thời value giữ hoa/thường khác văn bản đã fold. |
| T20 | `preferred_color="xanh dương"` từ agent và extractor | Mẫu kiểm chờ `màu xanh dương` liền nhau; câu là “Màu tôi muốn là xanh dương”. |

T24 và N06 là FP tái hiện **3/3**. T24: extractor đề xuất `payment="momo"`, `fact_evidence="customer"`, decision `accepted` dù lời khách là câu hỏi “... được không”. N06: extractor đề xuất `has_children=true`, cùng kết quả `accepted`, dù mệnh đề bắt đầu bằng “Nếu”. Không có đề xuất sai từ agent trong hai ca này ở ba report. Log sau kiểm chứa đúng các fact sai trên.

## D. Đề xuất triển khai sau khi duyệt

1. **Đề xuất có quote và miền giá trị theo tầng.** Extractor trả `{key,value,evidence_quote}`. Đầu tiên kiểm quote nằm trong một đoạn lời khách sau chuẩn hóa Unicode, khoảng trắng và dấu câu nhẹ; không xóa từ phủ định, điều kiện hay đổi thứ tự từ. Sau đó kiểm phép chuyển cụm nguồn → value. `SlotSpec` hiện chưa có metadata miền/parser, nên đây là thiết kế tương lai, chưa đổi registry ở lượt này. Tầng đóng có nguồn xác nhận thì ép kiểu/miền chặt: `payment` dùng bốn giá trị của tool sau quy tắc chuẩn hóa chữ hoa/thường, `has_children` là bool, số tiền/diện tích là số hợp lệ có đơn vị và ngữ cảnh, ngày là ngày hợp lệ khi slot tương ứng cần. Quote đúng nhưng value ngoài miền đóng phải bị từ chối với `value_out_of_domain`, không ghi văn bản tự do. Tầng mở/chưa được BTC công bố đầy đủ như `objection`, `blocker` dùng các giá trị chuẩn **đã thấy trong sample cộng `khac`**; khi không khớp giá trị đã biết, giữ `value="khac"` và `evidence_quote` nguyên văn thay vì từ chối, đồng thời đếm/log riêng số `khac` theo key. Không coi tập sample là enum đầy đủ. Màu/size không được ép vào danh sách cố định của sample; chúng cần kiểm lời khách và biến thể catalog khi có ngữ cảnh. Parser quote + tiền/cụm thanh toán/màu có thể giải T11, M07, T16, T17, T20. Test hai chiều: các ca đó phải nhận giá trị đúng; giá shop báo không thành budget (N01), hỏi phương thức không thành payment (T24), hỏi tồn kho size không thành lựa chọn. Rủi ro bỏ sót: cách nói mới/ASR lỗi không khớp từ điển; rủi ro lọt sai: quote có thật nhưng value bị ánh xạ sai hoặc quá nhiều `khac` làm memory kém hữu ích. Đo strict key+value, key-only, từng reason code, số `khac` và số quote/value không khớp trên bộ 50; held-out chỉ chạy một lần sau khi quy tắc chốt.

2. **Bộ lọc ngữ cảnh theo mệnh đề cho mọi customer slot.** Xác định nguồn phát ngôn và lực phát ngôn của chính mệnh đề chứa quote: khách khẳng định/chọn/sửa so với hỏi, giả định “nếu”, phủ định, trích lời người thứ ba hoặc lời agent. Chỉ nhận khẳng định của khách hoặc phủ định có giá trị rõ ràng (ví dụ `has_children=false`); với câu trộn, không bác toàn bộ lượt. Lời agent/tool không được làm bằng chứng customer fact. Cách này nhắm T24, N06; N02 cũng là đối chứng người thứ ba. Test hai chiều bắt buộc: **không ghi** “thanh toán momo được không?”, “nếu tôi có con nhỏ thì sao?”; **phải ghi** “tôi thanh toán momo nhé”, “nhà có con nhỏ, hỏi giúp”, “ngân sách 5 triệu, được không?”. T09/T05/T06 và N07 là đối chứng thêm; N07 nêu giá đối thủ rồi hỏi giá shop vẫn giữ phần khẳng định. Rủi ro bỏ sót: câu hỏi tu từ hoặc câu sửa ngắn; rủi ro lọt sai: phạm vi “nếu”/phủ định cắt sai khi nhiều mệnh đề. Đo precision/recall nghiêm ngặt trước–sau trên cùng bộ 50, **đếm số fact đúng đã được nhận trước lọc nhưng bị mất sau lọc** theo key/ca, FP theo ngữ cảnh và tỷ lệ mệnh đề không phân giải được; không dùng dấu hỏi cuối câu để loại cả lượt. Số fact đúng bị mất hiện **chưa có** vì bộ lọc chưa triển khai.

3. **Giữ nghĩa của `blocker` khi chưa có fact mở.** Chỉ nhận blocker khi khách nói rõ điều kiện đang ngăn hoặc trì hoãn quyết định mua hiện tại (cần hỏi người quyết định, chưa quyết, đang so giá...), không dùng key này để chứa sở thích sản phẩm hay điều kiện giao hàng. Sở thích/điều kiện ngoài registry để ở trạng thái chưa ghi có lý do chẩn đoán, chờ thiết kế fact mở riêng; không thêm slot hoặc nhét sang blocker. Cách này nhắm O04, M03, M06; O09 cần kiểm riêng vì “cân nhắc mua hay thuê” có thể là thái độ nhưng nhãn hiện không coi blocker. Test hai chiều: O04/M03/M06 không ghi blocker, T10/T18 và blocker so giá của BTC vẫn được giữ; M03 vẫn giữ size đúng nếu đã chọn key. Rủi ro bỏ sót: trở ngại thật diễn đạt như sở thích; rủi ro lọt sai: câu có “không thích” nhưng được model gọi là điều kiện mua. Đo precision/recall riêng blocker, FP ở nhóm open fact và ảnh hưởng đến `open_blockers` trong Call Brief.

Mọi đề xuất phải chạy lại chấm nghiêm ngặt ban đầu; chấm blocker chuẩn hóa chỉ là phép phân tích độ nhạy của bộ chấm, không chứng minh hệ thống tốt hơn. Bộ 50 đã được xem để phân tích lỗi nên chỉ là tập phát triển; held-out do người khác gắn nhãn, khóa hash và chỉ chạy một lần sau khi quy tắc đã chốt.
