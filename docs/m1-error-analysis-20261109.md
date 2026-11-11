# Phân tích lỗi trước cải tiến: run 20261109T092333Z-d2c77902

Nguồn là `ai-services/eval_harness/results/20261109T092333Z-d2c77902/`, đặc biệt
`full.diagnostics_full.jsonl`, `.events.json`, `.stages.json`, `btc_score.json` và
`extraction_report.json`. Artifacts không được sửa trong quá trình phân tích.
Run dùng Qwen2.5-3B AWQ local, 7 scenario/39 lượt mỗi cấu hình, answer guardrails
tắt, execution degraded, extraction needs_review. Đây là **mốc trước sửa**, không
phải điểm của checkout hiện tại hoặc điểm của model API dự kiến.

| # | Vị trí trace full | Bằng chứng / lỗi | Phân loại và hướng xử lý |
|---|---|---|---|
| 1 | Dòng 1, SC01/call_1/1 | Catalog có kết quả, grounding từ chối `unsupported_product_spec`, 5 recovery đều unavailable | Grounding/recovery và draft model; giữ fallback an toàn nhưng cần tư vấn hữu ích khi có đủ bằng chứng |
| 2 | Dòng 2, SC01/call_1/2 | Đã quote AirPure Y và Samsung AX40 nhưng chỉ trả chưa kiểm tra được | Thực thi tool chưa chuyển thành câu trả lời; không thể coi tool thành công là task thành công |
| 3 | Dòng 6, SC01/call_2/2 | `model_invocation` failed, `unknown_error` | Lỗi execution; chưa đủ request ID/exception để ghép chắc chắn với HTTP 400 của vLLM |
| 4 | Dòng 7, SC01/call_2/3 | Model failed; recovery hỏi chọn mẫu khi khách yêu cầu lên đơn | Phải tách lỗi execution khỏi lỗi thiếu selection; không tự cấp selection để nâng TSR |
| 5 | Dòng 8, SC02/call_1/1 | Khách hỏi giá AirPure X, agent nói sẽ tra nhưng không gọi tool | Model/tool execution; không thêm regex theo riêng tên AirPure để che lỗi |
| 6 | Dòng 12, SC02/call_2/2 | Hỏi quà tặng nhưng agent chỉ hứa kiểm tra, không pricing call | Follow-up thiếu hành động và bằng chứng hiện tại |
| 7 | Dòng 14, SC03/call_1/1 | Tìm sneaker với category áo khoác, nhận kết quả rỗng | Arguments đúng kiểu nhưng sai nghĩa; strict schema không tự sửa lựa chọn category |
| 8 | Dòng 18, SC03/call_2/2 | Query chỉ còn “Mất phí gì không”, mất câu hỏi đổi size phía trước | Lỗi harness đã tái hiện/fix offline: giữ ngữ cảnh câu hỏi để tránh truy hồi phí ship chung |
| 9 | Dòng 19, SC03/call_2/3 | Nói sẽ giúp đổi giày nhưng không có `order.update` | Nghiệp vụ chưa hoàn thành; không được chấm pass chỉ theo lời hứa |
| 10 | Dòng 20, SC04/call_1/1 | Catalog giá 1.690.000đ, agent nói 169.000đ | Sai số tiền; answer checks bị tắt. Test bổ sung còn tìm ra lỗi checker dùng tiền giảm làm bằng chứng giá bán, đã tách hai loại tiền |
| 11 | Dòng 21, SC04/call_1/2 | Nói mọi size giảm 50.000đ, không pricing call; catalog có phụ thu size 43 | Nhầm phụ thu/giảm giá; phải kiểm bằng đúng quote và đúng loại claim |
| 12 | Dòng 24, SC04/call_2/2 | Phủ nhận KM dù ground truth còn KM | HR được scorer ghi nhận; không dùng giá đúng để kết luận cả câu về KM đúng |
| 13 | Dòng 25, SC04/call_2/3 | Vừa nhắc SKU ở các lượt trước, khách chốt size/màu nhưng lại hỏi mẫu nào | Replay tái hiện thiếu metadata catalog. Đã sửa lookup từ advice có nguồn và rederive selection trước stock; chưa có điểm live sau sửa |
| 14 | Dòng 26–30, SC05 | Cả chuỗi không có business tool call | Không có bằng chứng kiểm KM hết hạn hay tạo đơn; model lớn có thể giúp nhưng chưa được đo |
| 15 | Dòng 31 và 36, SC06 | Nói giá Xiaomi Pro, nhưng quote ở đầu là SKU khác; cuối cùng hỏi xác nhận offer | Câu hỏi xác nhận cuối không tự là bug: offer được nói trước đó chưa đủ nguồn cho đúng SKU. Không bỏ consent gate để khớp kịch bản tĩnh |

## Các hạn chế của điểm tổng hợp

- TSR full và baseline đều 1/7 (14,3%); không có order.create/order.update trong
  hai trace. Memory có giúp dùng lại vài fact nhưng chưa chứng minh tăng task success.
- HR full tổng 12,5%, riêng giá/KM 14,3%, không đại diện toàn bộ claim sai:
  SC04 call_1 thiếu ground truth để scorer đối chiếu giá sai và giảm giá bịa.
- RQR 0% không chứng minh đã giảm 40% khi baseline cũng 0. Extractor còn gán câu
  hỏi chọn sản phẩm thành blocker do có chữ “trao đổi”; đã sửa regression offline.
- Có 2 lỗi model phase ở full và 1 ở baseline. Log server có 3 HTTP 400 và 10 lỗi
  JSON tool-call trong khoảng eval, nhưng không đủ correlation để gán từng lỗi
  server cho từng turn/model hoặc LangMem request.
- 39 lượt không đủ quy mô latency BTC. Run này đo voice transcript và TTFT proxy;
  không gán nó thành phép đo chat M1 nonstreaming của runner mới.

## Bằng chứng cần có ở vòng sau

Giữ test/model cố định; bật guardrails; dùng chế độ text và database eval tách
riêng. Đối chiếu lại các ca ở trên, lưu score/trace có hash và quan sát cả ca hồi
quy. Không đổi ground truth theo lời agent, không nới consent gate, không coi test
offline đã pass là bằng chứng các lỗi model/serving trong bảng đã hết.
