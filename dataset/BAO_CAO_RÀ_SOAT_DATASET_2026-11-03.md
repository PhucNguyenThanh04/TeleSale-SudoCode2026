# Báo cáo rà soát dataset ASR và khả năng sử dụng cho eval AI/memory

Ngày rà soát: 03/11/2026.

## 1. Kết luận

Hai bộ dữ liệu có thể dùng cho benchmark ASR và làm nguồn thiết kế scenario đánh giá agent. Tuy nhiên, các nhãn `entities` hiện tại chưa tương đương bộ đáp án memory trong sample BTC. Không nên chuyển trực tiếp `entities` thành `facts_established` rồi chạy lấy điểm memory.

Cần giữ nguyên dataset gốc, tạo bộ chuyển đổi riêng, bổ sung ngữ cảnh theo sản phẩm, fixture nghiệp vụ, tiêu chí chấm và các phiên khách quay lại.

Báo cáo này kiểm tra nội dung và nhãn dữ liệu; không kết luận chất lượng trích xuất memory thực tế của agent. Muốn kiểm chứng phần đó phải chạy hệ thống, đối chiếu trace và memory writes.

## 2. Phạm vi và nguồn đối chiếu

### Dữ liệu được đọc

- GT synth cho T01, T03–T12 trong `team22-edge-synth/ground_truth.json` của archive audio synth.
- GT clone cho T02, T13–T22 trong `team22-edge-clone/ground_truth.json` của archive audio clone.
- Manifest, segment annotation và WAV header của hai bộ; kiểm tra tính toàn vẹn ZIP và đối chiếu bản giải nén.
- Kịch bản nguồn: [team_synthetic.json](../speech/dialogues/team_synthetic.json) và [team_clone.template.json](../speech/dialogues/team_clone.template.json).

### Nguồn đối chiếu trong workspace

- Bảy mẫu trong `test_set/public_sample/` của gói BTC.
- Schema scenario BTC trong `schemas/scenario_format.md`.
- Điều chỉnh đề và giải đáp mentor trong `DIEU-CHINH-DE.md` và `GIAI-DAP-MENTOR.md`.
- Evaluator tham chiếu BTC trong `eval/reference_eval.py`.
- [Registry slot memory của AI service](../ai-services/app/constants.py), [schema proposal memory](../ai-services/app/schemas/langmem.py).
- [Validator dữ liệu speech](../speech/validate.py) và [pipeline replay](../speech/replay.py).

Các đường dẫn sang bộ BTC là đường dẫn cục bộ, giả định thư mục BTC nằm cạnh repository.

### Giới hạn kiểm tra

- Đã đọc đủ 22 hội thoại, gồm lời khách, lời nhân viên, entity từng lượt và entity toàn hội thoại.
- Đã chạy kiểm tra offline; không chạy ASR, gọi LLM, benchmark hoặc live eval.
- Chưa nghe kiểm tra chất lượng phát âm và mức nhiễu của từng audio.
- Không sửa dataset, source code hoặc dữ liệu BTC trong lần rà soát.

## 3. Thống kê và kiểm tra kỹ thuật

| Nội dung | Kết quả |
|---|---|
| Số hội thoại/audio | 22, mỗi bộ 11 |
| Tổng thời lượng WAV | 1.173,131 giây, khoảng 19 phút 33 giây |
| Tổng lượt thoại | 217 |
| Lượt khách | 108 |
| Split được khai báo | 2 dev, 20 holdout |
| Hội thoại có nhãn noisy | 7 |
| Định dạng audio | WAV mono, 16 kHz, PCM 16 bit |
| ZIP và bản giải nén | Không phát hiện lỗi ZIP; nội dung file giải nén khớp ZIP |
| Segment annotation | Số segment khớp số lượt; thời điểm bắt đầu/kết thúc hợp lệ trong thời lượng WAV |
| Hash ground truth | Khớp manifest theo quy tắc chuẩn hóa CRLF → LF của dự án |
| Hash kịch bản nguồn | Khớp source hash trong manifest |
| Validator trên hai kịch bản nguồn | 22 hội thoại, 0 lỗi, 3 cảnh báo |
| Entity tổng so với gộp entity theo lượt | Cả 22 hội thoại khớp quy tắc lượt sau ghi đè khóa trùng |

Ba cảnh báo từ validator:

1. T06, lượt 2: không nhận diện được nhãn `SKU-SN-TRK` từ cách viết “trekking hai pro”.
2. T06, lượt 3: không nhận diện được nhãn `SKU-SN-TRK` từ cách viết “hai pro”.
3. T02: thời lượng ước tính sát ngưỡng dưới 45 giây. Đây là cảnh báo ước tính, không phải kết luận WAV bị lỗi.

Không được suy ra rằng 0 lỗi validator đồng nghĩa bộ dữ liệu đã đủ để chấm memory. Validator này kiểm định dạng, nhãn và nghiệp vụ của kịch bản nguồn.

## 4. Metadata và chất lượng cần làm rõ

| Vấn đề | Nhận xét và hướng xử lý |
|---|---|
| Engine thực tế | Manifest của cả hai bộ ghi `engine=edge`. Không mô tả lần phát hành này là ElevenLabs hoặc VieNeu chỉ dựa trên mô tả kịch bản nguồn. |
| Tên bộ clone | Bộ `team22-edge-clone` có `team_preview=true`; tên template không chứng minh audio đã clone giọng thành viên. |
| Vùng giọng | Các khóa Bắc/Nam đang ánh xạ về cùng hai voice ID HoaiMy/NamMinh. Nhãn vùng chưa đủ chứng minh có khác biệt giọng vùng miền trong audio. |
| Checksum khác khi hash raw bytes | File dùng CRLF; phải dùng quy tắc chuẩn hóa LF của dự án. Không cần sửa checksum vì khác xuống dòng Windows/Linux. |
| Nhãn holdout | Có 20 hội thoại được khai báo holdout; nhãn này không tự chứng minh dữ liệu chưa được dùng để điều chỉnh hệ thống. |
| Chất lượng audio | Cần nghe kiểm tra phát âm, khớp transcript và mức nhiễu trước khi dùng làm kết quả chính thức. |

Nên bổ sung mô tả phát hành hoặc provenance riêng; không chỉnh âm thầm artifact gốc đã có hash.

## 5. Khác biệt với schema memory của BTC

| Nội dung | Hai file hiện tại | Sample BTC |
|---|---|---|
| Nhãn thực thể trong lời thoại | Có `entities` từng lượt và toàn hội thoại | Không phải cấu trúc chính để chấm memory |
| Thông tin thiết lập trong phiên | Chưa có `facts_established` | Có |
| Thông tin bắt buộc dùng ở phiên sau | Chưa có `must_carry_over` | Có ở ca đa phiên |
| Thông tin không được hỏi lại | Chưa có `must_not_ask` | Có ở ca đa phiên |
| Liên kết khách hàng và phiên | Chưa có cấu trúc liên kết đầy đủ | Có khách hàng và các `call_n` |
| Điều kiện hoàn thành nghiệp vụ | Chưa có `success_if` | Có |
| Kỳ vọng trạng thái bộ nhớ | Chưa có `memory_expectation` | Schema BTC hỗ trợ; không phải mọi sample đều khai báo |

Cả 22 hội thoại chưa có `facts_established`, `must_carry_over`, `must_not_ask`, `memory_expectation`, `customer_id`, `calls`, `channel` và `channel_identity` ở cấp hội thoại.

`entities` toàn hội thoại được gộp bằng cách lượt sau ghi đè cùng khóa ở lượt trước. Quy tắc này có thể làm mất lịch sử lựa chọn, quan hệ SKU–giá và trạng thái biến thể. Đây là hạn chế khi tái sử dụng cho memory, không phải tự thân là lỗi định dạng ASR.

Trong evaluator BTC, RQR sử dụng `must_not_ask`, còn CCR sử dụng `must_carry_over` và dữ liệu trace. Thiếu các khai báo này thì không có phép đo memory tương đương sample BTC, dù hội thoại vẫn chạy được qua agent.

## 6. Rà soát từng hội thoại

“Thiếu” trong bảng sau nghĩa là thiếu khi xây đáp án memory, không đồng nghĩa nhãn ASR bắt buộc phải chứa mọi chi tiết.

| Ca | Ngữ cảnh dùng được | Thông tin cần bổ sung hoặc làm rõ |
|---|---|---|
| T01 | Xiaomi 4 Pro, COD, giá và khuyến mãi được báo | Quận 7 nằm trong lời khách nhưng chưa thành nhãn ngữ cảnh. Giá/tồn kho cần chứng cứ tool. Chưa có phiên trước dù khách hỏi “còn hàng chưa”. |
| T02 | Windbreak, size cũ M, size mới L, navy, mã đơn | Tương đối đầy đủ cho một lần đổi size. Khách tự đọc lại mã đơn nên chưa đo được việc nhớ đơn từ phiên mua trước như SAMPLE-03. |
| T03 | So sánh hai máy lọc nước; cuối cùng chọn Kangaroo, COD | Entity tổng không giữ đầy đủ danh sách đã so sánh. Nguồn nước máy và Từ Sơn/Bắc Ninh chưa được biểu diễn riêng. |
| T04 | Philips 6,2 lít, COD, giá báo | Thiếu Gò Vấp trong nhãn. Cần tiêu chí không tiết lộ hoặc hứa ưu đãi tương lai; câu khách hỏi sale không phải xác nhận ưu đãi đang có hiệu lực. |
| T05 | Spectra S1, thanh toán MoMo | Cần giữ Medela là phương án đã so sánh, Nam Định là nơi giao. Không coi quà khách thấy trên fanpage là quà còn hiệu lực. |
| T06 | HikePro, lựa chọn trắng → xám | Thiếu size 41, chiều dài chân 25,5 cm và Hà Đông trong nhãn memory. Hết hàng phải gắn với size 41 trắng, không áp cho toàn bộ HikePro. |
| T07 | Warmly, đen, COD, điện thoại | Thiếu size L, Tân Bình và yêu cầu gửi xác nhận qua Zalo trong nhãn. |
| T08 | Ngân sách 2,5 triệu, Xiaomi Tower → Panasonic, COD | Phân biệt sản phẩm hỏi ban đầu với sản phẩm được tư vấn sau. Thiếu yêu cầu có remote, chạy êm và địa điểm Quận 3 trong nhãn. |
| T09 | AirPure Pro, phòng 35 m², có con nhỏ | Thiếu yêu cầu gọi lại và lịch hẹn trong entities. A đề xuất 10:00 ngày 21/10 rồi khách đồng ý; eval phải kiểm tra lịch thực tế agent tạo, không nạp lịch từ lời A mẫu làm chứng cứ runtime. |
| T10 | Có con, ngân sách 9 triệu, COD | Entity tổng chỉ giữ xe đẩy và giá 3,49 triệu, trong khi khách mua cả ghế ô tô và xe đẩy, tổng 8,48 triệu. Thiếu tuổi bé 10 tháng và Cầu Giấy trong nhãn. |
| T11 | Nồi chiên, mã đơn, giá/COD được nhân viên nhắc | Cần fixture CRM cho đơn cũ. Trạng thái giao, tracking và ngày đến phải đối chiếu dữ liệu nghiệp vụ, không lấy lời A mẫu làm kết quả của agent đang test. |
| T12 | AirPure Pro → AirPure Y, chuyển khoản | Thiếu ngữ cảnh sở hữu AirPure X bản 2024 và điều kiện trade-in trong entities. Giữ lịch sử so sánh, Thái Nguyên; xác minh điều kiện trade-in bằng CRM/tool. |
| T13 | Phòng 25 m², ngân sách 3 triệu, có bé | Nhóm fact khách tương đối tốt. Thiếu nhu cầu phòng ngủ và Huế trong nhãn. Không tự gán “để suy nghĩ” thành blocker hỏi chồng/vợ. |
| T14 | Panasonic, có bé, COD | Giữ Senko là phương án đã so sánh. Thiếu phòng ngủ và Bình Thạnh trong nhãn; không chỉ giữ sản phẩm cuối rồi mất diễn biến tư vấn. |
| T15 | Sunhouse UF → Kangaroo RO10 | Thiếu nguồn nước giếng khoan và Đà Lạt, dù đây là nguyên nhân đổi phương án. Không suy ngân sách khách từ giá máy. |
| T16 | Lock&Lock 4 lít, COD | Biên Hòa/Đồng Nai chưa có nhãn. Giá, bảo hành, giao hàng thuộc ngữ cảnh tư vấn/nghiệp vụ, không phải mặc định là sở thích lâu dài. |
| T17 | RunLite 1, đen, thêm hộp tất | Thiếu size 41, chiều dài chân 25 cm, size thường đi 40 và giỏ hai món. Entity tổng có SKU giày nhưng giá 149.000đ là giá tất; không dùng cặp đó làm báo giá giày. |
| T18 | Bình Pigeon và máy hâm Fatz | Entity tổng mất bình sữa và giá của bình. Cần giỏ hai món, tổng 779.000đ. Điều kiện đổi trả bình còn seal phải gắn đúng sản phẩm. |
| T19 | Máy tiệt trùng, chuyển khoản | Thiếu Hải Phòng trong nhãn. Phân biệt bảo hành 12 tháng với đổi mới 30 ngày có điều kiện lỗi NSX được xác nhận. Hỏi mua bảo hành mở rộng chưa có nghĩa mua được gói đó. |
| T20 | Windbreak L → XL, be → navy, mã đơn | Entity tổng mất màu cũ be. Giữ riêng biến thể cũ/mới, XL be hết hàng và chênh lệch 40.000đ; phí đổi size 0đ là khoản khác. |
| T21 | Phòng 40 m², giá đối thủ 5,9 triệu, blocker so sánh giá | Thiếu objection riêng; giá đối thủ thuộc Samsung. AirPure Pro chỉ là phương án hỏi thêm, chưa phải sản phẩm chốt mua. |
| T22 | Nồi chiên Xiaomi, mã đơn, COD | Thiếu ngày nhận 24/10 và chưa sử dụng trong nhãn. COD thuộc đơn cũ, chuyển khoản hoàn tiền là nghiệp vụ khác. Không lưu tài khoản ngân hàng vào memory từ lời khách đề nghị cung cấp. |

## 7. Quy tắc chuyển nhãn sang đáp án memory

| Nhãn hiện tại | Cách xử lý |
|---|---|
| `sku` | Phân biệt sản phẩm khách hỏi, được tư vấn, thay thế và chốt mua. Không mặc định mọi SKU là `product_advised`. |
| `price_vnd` | Chỉ thành `price_quoted_vnd` khi đã xác định đúng SKU, biến thể và lần báo giá. |
| `size_old`, `size_new`, `color` | Giữ riêng trạng thái cũ và lựa chọn mới. Bổ sung `variant_sku` sau khi xác minh bằng catalog/tool. |
| `in_stock`, `promo_expiry` | Gắn đúng sản phẩm/biến thể, ngày và nguồn chứng cứ. Phiên sau phải kiểm tra lại tính hiện hành. |
| `phone` | Dùng qua luồng liên kết/xác minh định danh. Số đọc trong lời thoại chưa tự động là danh tính đáng tin cậy. |
| `blocker` | Cần lời khách làm bằng chứng. “Để suy nghĩ” khác “cần hỏi chồng/vợ”. |
| `payment` | Phân biệt phương thức của đơn cũ, ý định thanh toán đơn mới và phương thức hoàn tiền. |
| Các điều kiện chính sách | Giữ điều kiện áp dụng, sản phẩm và phiên bản/ngày hiệu lực; không rút thành một con số áp dụng toàn bộ hội thoại. |

Khi thiết kế nhãn memory riêng, nên ghi nguồn lượt thoại, người nói, phạm vi sản phẩm và thời điểm. Đây là metadata phục vụ kiểm tra; không tự thêm trường lạ vào hợp đồng JSON BTC nếu loader chưa hỗ trợ.

Giá, tồn kho, khuyến mãi và đơn hàng cần chứng cứ nghiệp vụ theo quy tắc admission của dự án. Lời A trong audio là lời tham khảo của dataset, không phải tool evidence của lần chạy eval mới.

## 8. Mức độ bao phủ các sample BTC

| Sample BTC | Nội dung gần nhất trong dataset | Phần còn thiếu |
|---|---|---|
| SAMPLE-01: nhu cầu, blocker, khách quay lại | T13 có phòng, ngân sách, có bé | Phiên quay lại và khai báo carry-over/không hỏi lại. |
| SAMPLE-02: nhớ giá và phản đối giá | T21 có giá đối thủ và so sánh giá | Objection đầy đủ, phiên sau và kiểm tra giữ/cập nhật báo giá. |
| SAMPLE-03: mua rồi đổi size | T02, T20 có lần đổi size | Phiên mua trước liên kết đúng khách/đơn; không phụ thuộc việc khách tự đọc lại toàn bộ thông tin. |
| SAMPLE-04: Facebook → hotline | Một số ca nhắc fanpage/Zalo | Cặp phiên thực tế khác kênh và mapping định danh. |
| SAMPLE-05: nhớ giá cũ, cập nhật KM hết hạn | Có câu hỏi về khuyến mãi | Cặp phiên trước/sau hạn và tiêu chí không giữ nhầm giá cũ. |
| SAMPLE-06: ASR/teencode, hàng về giữa hai phiên | T01 có nghiệp vụ sau khi hàng về | Phiên trước, bản ASR/teencode và chuỗi carry-over tương ứng. |
| SAMPLE-07: chính sách cũ/mới | Có nhiều câu đổi trả | Ca viện dẫn chính sách cũ 14 ngày/phí 20.000đ rồi kiểm tra agent sửa lại. |

Lưu ý về nguồn mẫu: SAMPLE-01 của BTC có lời khách “ngân sách tầm 5 triệu” nhưng `facts_established.budget_vnd=5700000`. Đây là điểm không nhất quán cần lưu ý khi thiết kế nhãn mới; không tự sửa file BTC gốc.

## 9. Tách benchmark ASR và eval agent

Theo giải đáp BTC, ASR được benchmark riêng bằng WER/CER/Entity Accuracy; RQR/CCR/TSR/HR được chấm trên text. ASR local là yêu cầu M1; audio BTC được đánh giá cùng ít nhất 20 file của team.

Hai phần có thể dùng chung nội dung kịch bản nhưng có đầu vào và đáp án khác nhau:

```text
Audio ── ASR local ── transcript dự đoán ── đối chiếu GT ── điểm ASR
                          │
                          └── transcript khách cố định
                                  ├── agent full
                                  └── agent baseline không nhớ phiên trước
                                            │
                                            └── trace ── điểm agent/memory
```

- Nếu dùng lời C từ ground truth: đang đánh giá agent trên lời khách chuẩn, không đo lỗi ASR.
- Nếu dùng lời C do ASR sinh: cố định cùng transcript cho cả full và baseline.
- Chỉ gửi lời khách vào agent. Không gửi lời đáp A, entity ground truth hoặc đáp án chấm vào runtime.
- Giữ lời A ở bản gốc để tham khảo thiết kế tiêu chí và kiểm tra mạch thoại.
- Rà lại các câu khách phụ thuộc lời A: câu tiếp theo có thể không phù hợp nếu agent thực tế trả lời khác.
- Có thể dùng pipeline `speech/replay.py` để cắt lượt khách theo annotation và xuất replay. Annotation A/C không phải kết quả diarization được dự đoán.

22 audio đáp ứng số lượng tối thiểu 20 file team ở phần ASR về mặt số đếm; chất lượng vẫn cần kiểm tra. Riêng bộ này chưa đủ mốc tổng corpus 40 audio/1 giờ. Hai mươi hội thoại mang nhãn holdout cũng không tương đương 20 scenario đa phiên.

## 10. Đầu việc bàn giao

1. Giữ nguyên ZIP, WAV, GT, segment và manifest; ghi rõ engine thực tế và trạng thái preview trong tài liệu phát hành.
2. Nghe kiểm tra transcript/giọng/nhiễu, ưu tiên cách đọc tên HikePro ở T06. Nếu sửa nhãn hoặc audio, tạo phiên bản mới và cập nhật provenance/hash nhất quán.
3. Xây mapping khách hàng–hội thoại–phiên, gồm `dialogue_id`, `conversation_key`, `session_key`, `session_index`, `identity_ref`, `call_date`. Chỉ nối các phiên khi có thiết kế kịch bản xác nhận.
4. Chuyển các lượt khách sang schema scenario BTC. Bổ sung persona, kênh, ngày, `success_if` và ground truth nghiệp vụ.
5. Xây nhãn memory theo từng lượt và phạm vi sản phẩm; ưu tiên T06, T07, T09, T10, T12, T17, T18, T20, T21.
6. Chuẩn bị fixture CRM/order cho T11, T12, T20, T22; rà lại fixture đơn liên quan T02. Không nạp sẵn memory được kỳ vọng agent phải tự học từ phiên chạy trước.
7. Bổ sung phiên quay lại, đa kênh, thay đổi lựa chọn, KM hết hạn và tồn kho thay đổi; khai báo `facts_established`, `must_carry_over`, `must_not_ask` phù hợp từng ca.
8. Dùng harness hiện có, bổ sung adapter khi cần; chưa có căn cứ cần xây lại toàn bộ eval hay sửa logic RAG chỉ để nhận dataset này.
9. Khi được cho phép chạy ASR/eval: đóng băng đầu vào, chạy hai cấu hình cùng transcript và lưu trace cùng provenance. Không chỉnh holdout theo lỗi rồi tiếp tục gọi nó là dữ liệu chưa từng dùng để điều chỉnh.

### Điều kiện nghiệm thu bộ scenario chuyển đổi

- Mọi fact kỳ vọng đều có nguồn hoặc fixture kiểm chứng được; không suy diễn thông tin khách chưa nói.
- Không nhầm SKU–giá, giỏ nhiều món, biến thể cũ/mới, phí đổi và tiền chênh lệch.
- Các phiên cùng khách liên kết đúng, ngày nghiệp vụ được giữ nguyên và điều kiện memory được khai báo trước.
- Fixture hỗ trợ được các đơn/lịch sử mua mà kịch bản giả định tồn tại.
- Không lọt đáp án GT hoặc lời A mẫu vào đầu vào agent.
- Các câu khách nối tiếp vẫn hợp lý khi chạy với agent thật.
- Scenario qua bước kiểm tra offline của harness trước khi chạy model; báo điểm ASR và agent riêng.

## 11. Trạng thái bàn giao

Đã hoàn thành rà soát offline và ghi nhận các điểm cần xử lý. Chưa chuyển đổi scenario, sửa nhãn, tạo fixture hoặc chạy model. Tài liệu này nằm trong `dataset/`, thư mục đang được Git ignore theo cấu hình hiện tại; chưa được commit/push.
