# Sửa hai ca chọn offer mơ hồ — 16/11/2026

Hai test trong `test_presented_offers.py` đã được tái hiện fail và sửa mà không thay kỳ vọng:

- `test_named_choice_recovers_one_of_multiple_presented_offers`
- `test_cross_session_named_choice_uses_bounded_committed_offer_candidates`

Nguyên nhân: focus từ câu hỏi giá Aster bị dùng như lựa chọn của khách, lọc mất offer Brio trước khi xử lý “lấy mẫu đó”. Khi qua phiên mới, recommendation cũ cũng có thể khôi phục focus đó.

Sửa trong `mcp_shared/consultation.py`: khi có nhiều offer thực sự được nói trong cùng lượt và chưa có lựa chọn của khách, bỏ focus/recommendation ngầm và giữ offer chưa xác định. Quyết định dựa trên nguồn của lời agent, không dựa vào thứ tự catalog hay điểm eval. Snapshot cũ còn lưu offer_candidates cùng nguồn cũng được kiểm lại khi khôi phục, không sửa dữ liệu lưu trực tiếp. Khách nêu rõ tên sản phẩm vẫn chọn được offer tương ứng; một offer duy nhất hoặc lựa chọn rõ đã xác minh vẫn giữ consent hợp lệ.

`test_offer_ambiguity.py` thêm 9 ca: cùng phiên/khác phiên, có/không recommendation cũ, không gọi order.create khi mơ hồ dù model đề xuất SKU, hỏi lại mẫu nào rồi tạo đúng Brio sau lựa chọn rõ; giữ trường hợp một offer hoặc đã chọn rõ Aster; xử lý snapshot cũ.

Kiểm cuối: **174 passed**, 1 warning deprecation thư viện, 6,65 giây. Gồm hai test gốc, 9 ca mới, presented offers, consultation memory/flow/followup/response, purchase continuation, returning recovery và toàn bộ test sửa sáu ca lượt 2. `git diff --check` qua.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/test/test_offer_ambiguity.py ai-services/test/test_presented_offers.py \
  ai-services/test/test_consultation_memory.py ai-services/test/test_consultation_flow.py \
  ai-services/test/test_consultation_followup.py ai-services/test/test_consultation_response.py \
  ai-services/test/test_purchase_continuation.py ai-services/test/test_returning_purchase_recovery.py \
  ai-services/test/test_m1_round2.py ai-services/test/test_m1_round2_runtime.py --tb=short
```

Chỉ kiểm offline qua wrapper chặn network/credentials/.env. Không chạy eval model thật, ASR hoặc DB; không đổi scorer, scenario, trace hay ground truth. Chưa có số TSR/p95 mới; người dùng sẽ chạy paired eval sau thay đổi này.
