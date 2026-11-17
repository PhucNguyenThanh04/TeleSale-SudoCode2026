# M1 lượt 2 — sửa sáu ca nghiệp vụ

Hoàn tất sửa các nguyên nhân xác định từ SC-T06, SC-T09, SC-T18, SC-T19, SC-T20 và SC04. Kiểm bằng inference giả lập, graph thật, MCP catalog/order thật với repository trong RAM và memory commit/read trong RAM. Không có eval model thật hoặc số TSR/latency mới.

## Thay đổi và bằng chứng

| Ca | Nguyên nhân đã xác định | Sửa và kiểm chứng |
|---|---|---|
| SC-T06 | Stock-only không kích hoạt chuẩn bị tư vấn; đường policy chỉ chuẩn bị quote khi hỏi giá. Có thể dùng tồn SKU gốc cho câu khẳng định biến thể; “có sẵn trong kho” còn lọt kiểm stock. | Chuẩn bị read tồn đúng biến thể cho yêu cầu trực tiếp hoặc scope đã có nguồn duy nhất, kể cả chưa muốn mua. Đường policy cũng chuẩn bị tồn độc lập. Verifier nhận cách nói “có sẵn trong kho”, kiểm đúng SKU và polarity. Không tạo phiếu đổi từ câu chỉ hỏi tồn. |
| SC-T09 | Chỉ lấy quote khi khách đã hỏi cả giá và tồn; câu giá được dùng thay câu trả lời tồn. | Chuẩn bị inventory khi khách yêu cầu, dùng cả kết quả hết hàng; câu trả lời phải có phần stock. Test runtime/MCP trên AirPure Pro ngày 19/10 xác nhận có `inventory.check` đúng SKU và không phát sinh đơn. |
| SC-T18 | Quote tổng giỏ có trong tool nhưng draft chỉ nói một món vẫn có thể được coi là đủ; recovery của một sản phẩm đi trước tổng giỏ. | Chuẩn bị stock từng SKU trong giỏ được yêu cầu; yêu cầu câu trả lời có tổng giỏ được quote xác nhận. Ưu tiên trả tổng khi khách hỏi tổng/giỏ, không để giỏ cũ lấn câu hỏi stock của sản phẩm khác. Runtime trả đủ Pigeon + Fatz, tổng 779.000đ trước consent, rồi tạo đúng hai dòng COD sau consent. |
| SC-T19 | `derive_presented_offers` kiểm câu giá + bảo hành chỉ với catalog/quote/stock, bỏ nguồn policy mà verifier đã dùng. Offer bị mất dù câu đã được giao hợp lệ. | Khi dựng offer, thêm policy observation đã có tại thời điểm câu nói, cùng chủ/phiên/ngày. Runtime ba lượt có policy ở giữa tạo được đúng một đơn Moaz Bebe 1.890.000đ, chuyển khoản. Test âm: policy thiếu/sai chủ/đến sau/khác ngày hoặc thời hạn không có nguồn đều không cấp consent. |
| SC-T20 | Model chọn `exchange_product` cho đổi biến thể cùng sản phẩm; receipt thành công chưa có recovery riêng, còn có thể bị hậu xử lý thay bằng tư vấn giá. | Chuẩn hóa sang `exchange_size` chỉ khi đơn đã được xác minh thuộc khách và catalog xác nhận SKU cũ/mới cùng sản phẩm. Nếu CRM thiếu SKU cũ, đọc `order.status` qua boundary ownership. Dùng receipt đúng order/action/variant/status để xác nhận yêu cầu đang chờ thu hồi; không thực hiện lại write. Test RAM/MCP xác nhận một update, không create/fallback. |
| SC04 | Chưa chọn biến thể khiến shortlist không lấy được quote mẫu để trình bày giá. Khi parent và variant cùng có quote, recovery có thể coi là mơ hồ; giá mới không gắn size/màu nên consent tiếp tục lặp. | Cho phép quote mẫu để trả lời giá trước khi có lựa chọn; lúc mua vẫn kiểm quote/tồn của biến thể thật. Recovery ưu tiên quote biến thể và nêu size/màu. Runtime chốt RunLite size 41 đen ở 1.521.000đ; size 43 bị chặn ở giá mới 1.740.000đ và chỉ tạo sau lần khách xác nhận mới. |

Câu xác nhận đổi hàng dựa trên receipt không đọc lại số tiền dưới dạng đơn giá. Không thêm ngoại lệ cho claim giá thiếu quote, không suy phí/chênh lệch thành giá sản phẩm.

Parser query cũng được sửa để giữ nguyên hãng trong tên literal như “Xiaomi Smart 4 Pro”, thay vì chỉ “Smart 4 Pro”. Đây là hồi quy phát hiện khi kiểm luồng khách quay lại: query bị rút ngắn tạo catalog rộng hơn và làm mất trọng tâm bộ nhớ. Không thêm cache catalog mới để xử lý vấn đề này.

## Kiểm chứng

- [test_m1_round2.py](../ai-services/test/test_m1_round2.py): 26 test về stock, variant/scope có nguồn, consent, policy evidence, giỏ, ownership, receipt lỗi và idempotency. Các lỗi sửa được tái hiện fail trước khi sửa.
- [test_m1_round2_runtime.py](../ai-services/test/test_m1_round2_runtime.py): 7 test chạy graph/MCP/commit thật trong RAM cho sáu nhóm, gồm giá biến thể tăng phải xác nhận lại.
- Batch 24 file liên quan: **410 passed, 2 failed**, 1 warning deprecation thư viện, 27,12 giây. Không full suite. Gồm cả deep/react, text/voice giả lập trong các regression có sẵn; không gọi ASR/TTS thật.
- Sau khi kiểm lại ngân sách tool, cả **7 test runtime qua với giới hạn 8 tool/lượt** (4,61 giây), không cần nâng lên 12 để vượt các ca này. Test stock kiểm cả lời trả lời còn/hết hàng theo kết quả MCP.
- Toàn bộ ca mới qua trong batch trên. Những regression khách quay lại bị tác động trong quá trình sửa đã được sửa và qua lại; không thay expectation để che hồi quy.
- Wrapper `eval_harness/offline_tests.py` chặn network, loại credentials/`.env`. Không chạy bootstrap/reset/migrate DB, không sửa scorer, scenario, ground truth hoặc trace lịch sử.
- Đã kiểm lại hash toàn bộ artifact review/replay lượt 1 và snapshot run nguồn: dữ liệu BTC và trace lịch sử giữ nguyên. `git diff --check` qua.

Hai test còn fail là các test có sẵn:

1. `test_presented_offers.py::test_named_choice_recovers_one_of_multiple_presented_offers`
2. `test_presented_offers.py::test_cross_session_named_choice_uses_bounded_committed_offer_candidates`

Cả hai đòi “lấy mẫu đó” không tự chọn sau khi agent nói nhiều offer; hiện code giữ focus Aster từ ngữ cảnh trước. Đã gọi lại hai test với hàm `derive_presented_offers` nguyên bản từ `git show HEAD` trong bộ nhớ: **cả hai vẫn fail**. Chúng không có policy/stock statement nên thay đổi policy evidence/stock lần này không làm đổi kết quả đó. Không sửa các test hoặc mở thêm việc thay semantics focus đa offer ngoài sáu ca đã thống nhất. Không gọi toàn bộ test suite là xanh.

Cập nhật sau lượt 2: hai ca trên đã được sửa trong lượt riêng theo yêu cầu người dùng; xem [bằng chứng sửa offer mơ hồ](offer-ambiguity-fix-20261116.md). Số 410/2 ở trên là kết quả lịch sử của lượt 2.

Lệnh batch đã chạy:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/test/test_m1_round2.py ai-services/test/test_m1_round2_runtime.py \
  ai-services/test/test_catalog_query.py ai-services/test/test_presented_offers.py \
  ai-services/test/test_consultation_flow.py ai-services/test/test_consultation_response.py \
  ai-services/test/test_consultation_followup.py ai-services/test/test_consultation_shortlist.py \
  ai-services/test/test_consultation_priorities.py ai-services/test/test_consultation_memory.py \
  ai-services/test/test_purchase_continuation.py ai-services/test/test_returning_purchase_recovery.py \
  ai-services/test/test_commerce_evidence.py ai-services/test/test_transaction_reply.py \
  ai-services/test/test_transaction_continuation.py ai-services/test/test_basket_harness.py \
  ai-services/test/test_basket_runtime.py ai-services/test/test_price_grounding.py \
  ai-services/test/test_model_tool_contract.py ai-services/test/test_november_pricing.py \
  ai-services/test/test_policy_rules.py ai-services/test/test_mcp_gateway.py \
  ai-services/test/test_chat_latency.py ai-services/test/test_execution_diagnostics.py --tb=short
```

## Giới hạn nghiệm thu

Đây là sửa runtime và kiểm hồi quy offline. Các câu trả lời/model tool call trong test là giả lập; không suy từ chúng rằng model thật sẽ gọi đúng mọi tool hoặc TSR đã tăng. Điểm lịch sử 79,3% và TTFT p95 4.068 ms không được thay bằng kết quả test. Cần một paired run thật được cho phép sau đó để đo chất lượng và latency của code mới. ASR thuộc người phụ trách khác.
