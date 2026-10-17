# Bộ đo memory v1

`memory_facts_v1.jsonl` gồm 50 lượt tổng hợp được gắn nhãn thủ công, không chứa dữ liệu khách thật. Các câu trải qua hàng gia dụng, giày, balo và vali, gồm ba `input_mode`, fact có cấu trúc, fact mở, câu hỏi, giả định, thông tin người thứ ba và dữ liệu cần loại. `preferred_size`/`preferred_color` là sở thích; `size`/`color` là lựa chọn giao dịch, theo `docs/memory-policy.md`. Khóa bộ nhãn này sau baseline; ca lỗi mới thêm vào bộ khác để tránh sửa nhãn theo output của model.

Chạy từ gốc repo:

```bash
ai-services/.venv/bin/python -m eval.memory_facts_baseline --out eval/memory_fallback_baseline.json
ai-services/.venv/bin/python -m pytest -q eval/test_memory_facts_baseline.py
```

Runner dùng model/agent cấu hình trong `ai-services/.env`, gọi nhánh `run_agent` với `fact_extraction_mode=fallback` và tool nghiệp vụ mock chỉ đọc. Mỗi ca là một lượt độc lập; không gọi PostgreSQL, MCP HTTP hoặc ghi hồ sơ khách. Kết quả gồm nhãn, fact được nhận, số lần extractor chạy và thời gian từng ca. Scorer tính TP/FP/FN theo **đúng key, kiểu và giá trị**; paraphrase của slot dạng text hoặc dùng `size` thay `preferred_size` được tính là sai. Đây là baseline cho khả năng trích fact, không phải thước đo latency end-to-end hay public-sample đa phiên.

Report còn ghi `key_only_slots` (chỉ đúng key) và `normalized_blocker_slots` bên cạnh `typed_slots` nghiêm ngặt. Phép chuẩn hóa chỉ dành cho chấm blocker: bỏ dấu/chấm câu/khoảng trắng thừa và quy về `hỏi vợ`/`hỏi chồng` khi cùng chỉ người cần hỏi; các key khác vẫn so khớp chính xác. Mỗi row có `diagnostics.before_fact_evidence` (nguồn agent/extractor, đề xuất đã che PII, kết quả kiểm và lý do) cùng `diagnostics.after_fact_evidence` (fact thực sự được nhận). Đây là log đo, không thay đổi quy tắc ghi nhớ. File report chỉ nên chứa ca tổng hợp; runner từ chối câu đầu vào còn PII thô.

Fact mở có nhãn nhưng runtime hiện chưa có tầng lưu này, nên baseline ghi `predicted=0`. Khi so với phiên bản `always`, chạy lại cả hai cấu hình cùng model/API/tham số và báo riêng precision/recall của slot và fact mở. Không dùng 50 câu này làm điều kiện rẽ nhánh trong runtime.
