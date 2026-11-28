# Bộ kịch bản đánh giá harness của nhóm

Bản gộp có 48 kịch bản, 118 phiên và 323 lượt khách. Dữ liệu dùng catalog, CRM và chính sách BTC. Bộ này chưa có kết quả chạy model với các ID mới.

- TEAM-01 đến TEAM-22: 22 ca phát triển từ bộ gốc của nhóm.
- TEAM-23 đến TEAM-42: 20 ca đánh giá bổ sung, trước đây mang ID HO-01 đến HO-20.
- TEAM-43 đến TEAM-48: sáu ca an toàn tổng hợp mới; ca 28 và 12 bổ sung danh tính mơ hồ và địa chỉ cũ. Các số CCCD/STK trong TEAM-43 là dữ liệu thử nghiệm.
- Loại khỏi bản gộp bảy ca SC01 đến SC07 (file SC-T23 đến SC-T29). Không xóa bộ nguồn hoặc dữ liệu BTC.

`_source_map.json` ghi ID cũ, đường dẫn nguồn và checksum. Runtime bỏ qua metadata bắt đầu bằng dấu gạch dưới. Bản sửa M2 đã chuẩn hóa persona, bổ sung kỳ vọng ngữ nghĩa và cấu trúc đơn, siết mã đơn tra cứu và sửa nhãn carry-over. Hash trong bảng đối chiếu là của nguồn gốc, không phải hash của bản sửa. Báo cáo/trace lịch sử dùng ID cũ; không được coi là kết quả trên bản gộp mới.

Tiêu chí rà soát chi tiết của 20 ca bổ sung nằm ở `../held_out/review.json`, tra theo original_id trong bảng đối chiếu. Nhãn do assistant soạn, chưa có đánh giá độc lập của con người. Bộ cuối đã dùng để phát triển các phép kiểm tra bổ sung; không quảng bá đây là bộ test độc lập. Hai bộ nguồn và các kết quả lịch sử vẫn giữ nguyên.

Kiểm tra offline từ gốc repo:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.preflight --offline-check --scenarios eval/scenario_final --btc-root ../BTC-Data-Vong1-TEAMS
```

Khi chạy chấm, truyền `--scenarios eval/scenario_final`; trong Compose đặt `SCENARIOS_DIR=./eval/scenario_final`.

## Kiểm tra bổ sung của nhóm

`success_if` vẫn dùng các trường BTC hỗ trợ. `supplemental_checks` kiểm số đơn thành công và chính xác từng đơn vị hàng, không chấp nhận chia đơn hoặc thêm hàng. `semantic_requirements` ghi các yêu cầu cần judge/người rà soát; thiếu đánh giá được báo `needs_review`.

Paired runner tự xuất `supplemental_evaluation.json` và hash tham chiếu trong `run.json` khi chạy bộ này. File `btc_score.json` tiếp tục là nguyên kết quả BTC. Supplemental failure hoặc needs_review không được tự diễn giải thành nghiệm thu M2 thành công dù TSR BTC cao.

Kiểm trace đã lưu bằng lệnh offline:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.semantic_eval \
  --scenarios eval/scenario_final --trace /path/to/full.jsonl \
  --btc-root ../BTC-Data-Vong1-TEAMS --out /path/to/new-semantic-report.json
```

Kiểm định dữ liệu và các lỗ hổng chấm điểm đã sửa:

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/eval_harness/test_final_dataset.py ai-services/eval_harness/test_semantic_eval.py
```

Simulator đã có engine/runner 3 seed và kiểm thử stub; xem `docs/evaluation/m2-simulator.md` từ gốc repo. Judge dùng rubric BTC và tiêu chí riêng trong từng call, có mẫu người chấm và phép tính đồng thuận; xem `docs/evaluation/m2-judge.md`. Chưa chạy model trên bộ cuối, chưa có nhãn người độc lập; chưa nghiệm thu M2 chỉ từ preflight. Bảng đối chiếu yêu cầu nằm ở `docs/evaluation/m2-readiness.md`.

`_manifest.json` ghi checksum của dữ liệu cuối và các nguồn BTC được dùng. Thay dữ liệu hoặc nguồn phải được rà soát trước khi chốt manifest mới; không cập nhật checksum chỉ để bỏ qua lỗi kiểm tra. Địa chỉ lịch sử trong ca 12 lấy đúng phiên BTC tháng 2; yêu cầu xác nhận lại sau hơn sáu tháng được đánh giá ngữ nghĩa, không coi quyền trade-in là hết hạn theo địa chỉ.

Loader kiểm hash khi thư mục có manifest, kể cả khi chạy từ snapshot BTC. `judge_criteria` chọn các tiêu chí áp dụng từ đúng 12 tiêu chí BTC; bộ cuối bao phủ cả 12, không ép tiêu chí đổi trả/PII/chốt đơn vào mọi phiên. Các source_sections đã được kiểm có thật trong policy. ASR ở TEAM-46 là transcript nhiễu tổng hợp, không phải bằng chứng WER/CER đo từ audio.
