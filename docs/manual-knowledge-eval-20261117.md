# Eval hai cấu hình, duyệt gap và chạy file Full K1 riêng

Luồng hiện tại theo yêu cầu đã làm rõ:

1. Chạy eval bình thường: No memory và Full, chấm BTC, detect gap từ Full K0.
2. Eval kết thúc. Người dùng duyệt/sửa/từ chối đề xuất và phát hành K1 ở frontend.
3. Chạy `run_knowledge_eval.py --base-run RUN`: chỉ một lượt Full K1 rồi báo cáo ba cột.

Không dùng `--manual-review` hoặc lệnh resume. Thiết kế pause/resume trước đó
đã được thay bằng giao diện hai file này. Coordinator cũ được tái sử dụng nội bộ
cho kiểm tra provenance, chạy Full và chấm điểm; không chạy lại cặp A/B.

Hướng dẫn: [Knowledge evaluation](../ai-services/eval_harness/KNOWLEDGE_TRIPLET.md#luồng-duyệt-trên-frontend).

## Đối chiếu yêu cầu

| Yêu cầu | Bằng chứng |
|---|---|
| Eval thường chạy hai cấu hình và detect rồi kết thúc | run_official.main gọi detect_after_pair sau metrics; test CLI kiểm gọi đúng một pair và một hook; lỗi hook không sửa kết quả cặp |
| Chạy file khác chỉ Full K1 | run_knowledge_eval.py → evaluate_published; bài test hai file xác nhận baseline, Full K0, Full K1 đúng ba lượt, không có baseline thứ tư |
| Chưa publish không gọi model, không chờ duyệt | evaluate_published báo lỗi trước coordinator; test thiếu proposals/chưa publish và disabled detection không mở DB |
| Dùng frontend/hạ tầng đang chạy | system_start eval chỉ gọi paired runner, không gọi Docker, tạo boot/schema hoặc bật/tắt server; frontend đang chạy được giữ nguyên |
| Không làm BTC chạy ba lượt hoặc chờ người duyệt | run_eval.py và eval/run_eval.py không đổi; regression BTC single-trace CLI đạt |
| Chỉ đề xuất từ Full K0; không tự approve/publish | knowledge_manual và scoped worker vẫn giữ các gate đã kiểm offline; hook detect không gọi LLM/embedding |
| Chỉ knowledge đã duyệt thuộc đúng cặp | Collector kiểm event/gap/revision/decision/source/test/manifest; revision sửa trong cùng gap được nhận, bản ngoài scope/bị từ chối/stale test bị chặn |
| Giữ nguyên cặp K0 | Metadata review được đặt ở RUN.knowledge bên cạnh RUN, giữ hash/scenarios/scorer/seed/model/source; C dùng memory sạch qua canonical runner |
| Duyệt frontend, giữ revision nền | Chrome test experiment kiểm scope, approve/prepare/activate riêng biệt, item hybrid dạng tham chiếu, giữ K0 và bỏ revision ngoài scope |
| Báo cáo đúng mức bằng chứng | So sánh ba cột BTC và review provenance; C là cross-release, không tự công bố accuracy từ test tự sinh hoặc resolved |

## Kiểm thử

Focused AI/harness/BTC CLI batch:

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/test/test_knowledge_repo.py ai-services/test/test_system_start.py \
  ai-services/eval_harness/test_knowledge_followup.py \
  ai-services/eval_harness/test_knowledge_triplet.py \
  ai-services/eval_harness/test_run_official.py eval/test_run_eval.py --tb=short
```

95 passed trước khi bổ sung case detect failure; sau đó hai case normal CLI
đạt 2 passed, tổng 96 bài khác nhau đạt, gồm kiểm lỗi phân tích không làm hỏng
metrics cặp đã hoàn tất. Wrapper chặn network,
không nạp credentials/.env. Không chạy full suite.

Chrome/gateway: chạy riêng test experiment trong backend/test/test_knowledge_browser.py:
1 passed. Các gate worker/approve/collector và memory reset đã được kiểm trong
lượt triển khai trước; fixture reset chỉ bổ sung prepare/playback no-op, giữ
assertion reset hai lần và không sửa code reset thật.

## Giới hạn

Chưa chạy model, ASR, embedding, bootstrap hoặc reset DB thật; chưa có metrics
M1 mới. Test điều phối dùng runner doubles, worker/review service dùng RAM;
HTTP/browser chạy local với upstream giả. Actor là reviewer cấu hình tại gateway,
không phải danh tính cá nhân nếu dùng chung actor. Giữ hạ tầng đang chạy giữa hai
lệnh và không chạy fresh startup hoặc eval/chat khác trên cùng DB. Cập nhật reset
memory và đường eval không Docker: [existing-stack eval](existing-stack-eval-20261117.md).
