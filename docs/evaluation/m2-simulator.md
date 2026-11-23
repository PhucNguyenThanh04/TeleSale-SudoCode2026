# Customer simulator M2

Simulator là phép đánh giá thích ứng riêng. Bộ chấm chéo BTC tiếp tục chạy lời khách cố định; không lấy trace simulator thay cho cặp trace chính thức vì lời khách giữa Full và baseline có thể khác nhau.

## Luồng thực thi

`customer_simulator.py` điều khiển patience, xác nhận lặp, giá lệch, yêu cầu thông tin mới, ý định chưa mua, lạc đề, giới hạn 12 lượt và kết thúc. LLM đọc prompt persona BTC để phân loại phản hồi thực tế và câu hỏi trong dàn ý đã được trả lời. Mọi lời khách gửi cho agent được lấy từ dàn ý, fact khai báo hoặc các câu phản ứng cố định; LLM không được tự sinh dữ kiện khách. Các quan sát LLM vẫn cần kiểm chứng qua review và đối chiếu trace.

`simulator_runner.py` chạy ba seed, mỗi seed cả Full và baseline trên cùng nguồn BTC, knowledge release, model và tham số agent. Mỗi cấu hình kiểm DB, warm-up và reset runtime qua các hàm hiện hành. Customer dùng cùng model ở temperature 0.3; agent giữ temperature đã cấu hình. Runner từ chối đổi seed nguồn, database identity hoặc code/dataset trong thí nghiệm.

Lượt mô phỏng dùng `run_scenario_call` và streaming runtime như runner text. Nhãn success_if, must_not_ask, ground truth và tiêu chí judge chỉ ở phía simulator; request tới agent chỉ mang lời khách, ngày và định danh kênh. Lời khách từ fixture có thể cố tình chứa PII tổng hợp; runtime phải che trước khi gửi agent ra model và lưu log. Payload của LLM quan sát cũng được che PII.

Patience chỉ phạt slot thuộc must_not_ask hoặc đã hỏi/trả lời trong phiên. Fact cũ không nằm trong must_not_ask có thể được hỏi lại khi TTL/xóa dữ liệu cho phép. Các call kết thúc sớm có thể chưa thiết lập đủ fact theo dàn ý; log/trace phải được rà trước khi khẳng định các kỳ vọng carry-over còn hợp lệ.

## Chạy

Lệnh sau gọi model nhiều lần và reset DB eval ở từng cấu hình. Chỉ chạy khi đã được phép sử dụng tài nguyên/provider và có DB eval riêng. Không dùng DB demo đang phục vụ.

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.simulator_runner \
  --scenarios eval/scenario_final --btc-root ../BTC-Data-Vong1-TEAMS \
  --expected-database telesale_eval_m1 --seeds 7,17,27 \
  --out ai-services/eval_harness/results/simulator-m2-01 --allow-model-calls
```

Đầu ra có snapshot nguồn và dataset, run.json, cùng trace.jsonl, simulator.jsonl, btc_style_score.json và supplemental.json cho mỗi seed/config. Manifest run ghi hash các artifact. Trace cuối lưu cả memory đã hoàn tất; file tạm khi chạy lỗi không được coi là kết quả hoàn chỉnh.

TSR theo từng seed là kết quả assertions BTC; mean/stddev dùng ba seed (độ lệch chuẩn quần thể) và báo thêm khoảng max–min. Chỉ báo complete nếu mọi call của mọi scenario đều có log, và chỉ báo repeatability_pass khi khoảng TSR không quá 10 điểm phần trăm. Repeatability không chứng minh chất lượng; supplemental có needs_review thì chưa có nghiệm thu ngữ nghĩa.

## Kiểm chứng offline

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/eval_harness/test_customer_simulator.py \
  ai-services/eval_harness/test_simulator_lifecycle.py
```

Các kiểm thử dùng observer/runtime giả lập và cấm kết nối mạng. Chúng xác nhận luật điều khiển, cách ly nhãn, điều kiện chạy live, reset sáu cấu hình qua stub và trace sau persistence. Chưa chứng minh model thực tuân thủ vai khách hoặc đạt TSR trên bộ cuối.
