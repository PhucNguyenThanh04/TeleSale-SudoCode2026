# Judge và người chấm M2

Judge dùng nguyên 12 tiêu chí PASS/FAIL BTC, chọn các tiêu chí áp dụng từ `judge_criteria` của mỗi phiên và bổ sung `semantic_requirements` của nhóm dưới ID `team:*`. Prompt có policy được dẫn nguồn, catalog, promotion, tồn kho theo thời gian và transcript các phiên trước. Nội dung gửi model được che PII; nhận xét chỉ được trích câu có thật trong lời agent đã che. Thiếu hành vi bắt buộc phải FAIL, có thể để evidence rỗng và giải thích. Đây là đánh giá ngữ nghĩa bổ sung; scorer BTC giữ nguyên.

Kết quả gắn checksum trace, scenario, scorer, schema, rubric, policy/catalog, code kiểm tra và prompt từng phiên. Thiếu/đúp tiêu chí, thiếu phiên, quote không tồn tại hoặc nguồn thay đổi đều bị từ chối. Snapshot BTC bao gồm rubric JSON.

Chạy từ gốc repo với trace hoàn tất. Lệnh `run` gọi model theo cấu hình trong môi trường, temperature 0, seed 17. Cần được phép dùng tài nguyên/provider trước khi chạy. Đặt đường dẫn output mới; không ghi đè bằng chứng.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.llm_judge run \
  --scenarios eval/scenario_final --trace /path/to/full.jsonl \
  --btc-root ../BTC-Data-Vong1-TEAMS --out /path/to/judge.json --allow-model-calls
```

Sinh tối thiểu 20 cặp (call, criterion) ngẫu nhiên có seed. Mẫu không điền verdict LLM để giảm ảnh hưởng lên người chấm. Người review mở đúng trace/scenario/nguồn gắn trong judge.json, điền tên ở reviewer, PASS/FAIL và căn cứ ở evidence của từng sample. Không thay danh sách mẫu, không dùng assistant điền thay người; nhãn giả trong unit test không phải bằng chứng nộp.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.llm_judge sample \
  --judge /path/to/judge.json --count 20 --seed 17 --out /path/to/human-review.json
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.llm_judge agreement \
  --judge /path/to/judge.json --human /path/to/human-review.json --out /path/to/agreement.json
```

Agreement báo số mẫu, % đồng thuận và Cohen kappa. Gate nhóm yêu cầu đủ 20, có người chấm và kappa ≥0.6. Nếu mọi verdict đều cùng một lớp khiến kappa không xác định, không tự coi 100% đồng thuận là hiệu chuẩn đạt; cần thu thêm mẫu đủ biến thiên và phân tích sai khác. Thay judge sau khi chấm người làm mất binding, phải review lại đúng kết quả mới.

Áp judge và nhãn người vào báo cáo bổ sung bằng lệnh offline:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.semantic_eval \
  --scenarios eval/scenario_final --trace /path/to/full.jsonl \
  --btc-root ../BTC-Data-Vong1-TEAMS --judge-report /path/to/judge.json \
  --human-review /path/to/human-review.json --out /path/to/semantic-reviewed.json
```

Không có nhãn người thì vẫn xuất kết quả judge, nhưng `complete=false`, `needs_human_calibration`. Hiệu chuẩn đạt cũng không xóa một FAIL thực tế của agent/tool. Không có trace và model thật trong quá trình sửa này; các kiểm thử đều dùng stub, cấm mạng. Việc che PII làm hạn chế kiểm chứng địa chỉ/định danh nguyên bản; đối chiếu log nội bộ theo quyền truy cập khi cần, không công bố PII trong bằng chứng nộp.
