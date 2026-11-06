# Bộ đo memory v1 — baseline lịch sử

Runner live `eval.memory_facts_baseline` đã ngừng hỗ trợ: nó gọi custom
`fact_candidates` và `fact_extraction_mode=fallback`, đã bị loại khỏi production
khi memory chuyển sang LangMem. Xem [cleanup audit](../ai-services/docs/cleanup-audit-2026-10-31.md).
CLI và API evaluate/diagnostics legacy trả lỗi rõ trước khi đọc settings, dựng
model hoặc ghi output. Không khôi phục validator cũ để tạo điểm cho runtime mới.

`memory_facts_v1.jsonl` vẫn giữ nguyên 50 ca synthetic và nhãn lịch sử.
Các helper `load_cases`, `score`, `score_keys`, `score_normalized_blocker` vẫn
hoạt động offline để đọc/chấm lại predicted slots đã có; chúng không chứng minh
chất lượng memory LangMem hiện tại. Các report cũ giữ nguyên giá trị lịch sử.

Scorer strict so đúng key, kiểu và giá trị; wrong value tính cả FP và FN.
Key-only chỉ so key. Chuẩn hóa blocker chỉ dùng cho chấm, không thay đổi runtime.
Không sửa nhãn corpus theo output model.

Kiểm tra offline từ root repository:

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py eval/test_memory_facts_baseline.py -q
```

Đánh giá runtime hiện tại dùng paired harness trong
[eval_harness/README.md](../ai-services/eval_harness/README.md).
Chạy live cần ủy quyền riêng; bộ 50 ca lịch sử không tự động được chuyển thành
một benchmark LangMem mới và không thay thế bộ paired eval.
