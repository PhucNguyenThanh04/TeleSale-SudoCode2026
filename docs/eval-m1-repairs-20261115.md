# Kết quả sửa eval M1 — 15/11/2026

Phạm vi: hoàn thiện đường đánh giá theo đề BTC C.4, bảng A.6, điều chỉnh latency/ASR và quy trình chấm chéo. Không thay scorer BTC, scenario, ground truth hoặc hành vi agent. Không gọi model, ASR, TTS, embedding API hay reset DB.

## Những phần đã sửa

| Phần | Kết quả |
|---|---|
| BTC snapshot | Dùng trực tiếp gói `--btc-root`, không phụ thuộc patch đã xóa; giữ hash và tương thích snapshot cũ. |
| Extractor | Phân biệt lời mời, câu chọn mẫu, xác nhận lựa chọn và consent mua; bổ sung slot cho yêu cầu số lượng/lý do trả hàng/đặc tính; trích thời hạn bảo hành/đổi trả rõ ràng; sửa số viết bằng chữ có hàng trăm+hàng chục; phân biệt câu thiếu thông tin và claim thực tế. |
| Mặc định chạy | Paired runner mặc định `text`, giữ explicit `--delivery-mode voice`. |
| Bảng A.6 | Thêm chênh lệch Full−Baseline bằng điểm phần trăm và mức giảm RQR tương đối do BTC tính. Giá trị thiếu vẫn là chưa đo; baseline bằng 0 không thành giảm 100%. |
| Nghiệm thu | Lưu `m1_conversation_acceptance.json`, in lại các check fail/missing bằng công cụ nghiệm thu hiện có; không đồng nhất `validated` với đạt M1. |
| ASR | Nhận báo cáo BTC/team qua các cặp `--asr-...-dataset/run`; kiểm input/audio/score hash, chấm kiểm lại offline bằng BTC và kiểm exact entity tiền/SĐT. Báo riêng hai nhóm, không lấy trung bình WER. |
| Độ phủ ASR | Không nhận mẫu BTC ít hơn 12 hội thoại làm bằng chứng đủ tập; nhóm team cần ≥20 file. Thiếu audio, local metadata hoặc chuẩn hóa vẫn chưa đủ. |
| Chấm trace offline | CLI `eval.score_pair` nhận `--btc-root`, dùng nguyên scorer chỉ định; `reextract_trace` giữ nguyên lời agent/tool/memory/latency và tạo output mới. |

Hướng dẫn một lệnh và cách đính kèm ASR: [eval_harness/README](../ai-services/eval_harness/README.md#lệnh-nghiệm-thu-hội-thoại-m1). README root cũng đã dẫn vào lệnh này.

## Kiểm chứng

**320 kiểm thử tập trung qua**, chạy qua `eval_harness/offline_tests.py` với socket/network bị chặn, bỏ credentials và `.env`. Gồm extractor semantics/integrity, ASR evidence, bảng báo cáo, paired runner/CLI, acceptance, scorer, replay, text lifecycle và luồng knowledge sử dụng runner. Không chạy full suite.

Nhóm file trong lệnh kiểm:

```text
ai-services/test/test_knowledge_repo.py
ai-services/eval_harness/test_question_semantics.py
ai-services/eval_harness/test_claim_semantics.py
ai-services/eval_harness/test_extraction_quality.py
ai-services/eval_harness/test_extraction_report.py
ai-services/eval_harness/test_report_metrics.py
ai-services/eval_harness/test_asr_evidence.py
ai-services/eval_harness/test_run_official.py
ai-services/eval_harness/test_m1_acceptance.py
ai-services/eval_harness/test_reextract_trace.py
ai-services/eval_harness/test_official_pipeline.py
ai-services/eval_harness/test_text_lifecycle.py
ai-services/eval_harness/test_entrypoint_parity.py
ai-services/eval_harness/test_eval_harness.py
ai-services/eval_harness/test_trace_extraction.py
ai-services/eval_harness/test_btc_release.py
ai-services/eval_harness/test_knowledge_triplet.py
eval/test_run_eval.py
eval/test_score_pair.py
```

`test_knowledge_repo.py` cũng cung cấp helper in-memory cho test triplet, cần nằm trong đường collection khi chạy wrapper offline. Các test ASR dùng fixture, không phải điểm nhận dạng audio thật.

## Replay trên trace thực tế đã lưu

Nguồn: `knowledge-triplet-final/20261113T194849Z-e1e46a43/k0/20261113T194849Z-e62e734b`, 29 scenario/170 lượt mỗi mode. Dùng đúng scorer trong BTC snapshot của nguồn.

Output: `ai-services/eval_harness/results/measurement-audit/20261115-m1-extraction-v2/`. `replay_manifest.json` ghi `source_preserved=true`, `source_integrity_issues=[]`. Không tạo run live giả hoặc sửa trace cũ.

| Nội dung full | Trước | Sau replay |
|---|---:|---:|
| Câu hỏi emitted còn uncertainty | 28 | 0 |
| Claim chưa phân giải | 67 | 51 |
| Claim emitted | 141 | 145 |
| RQR | 3,7% | 3,7% |
| CCR | 63,3% | 63,3% |
| TSR | 79,3% | 79,3% |
| HR theo scorer BTC | 0% | 0% |

Số đo chính thức không đổi. Delta trích xuất không được báo là agent cải thiện; không bỏ claim khó để nâng điểm. Candidate có điều kiện, thiếu mapping hoặc còn mơ hồ vẫn giữ trong sidecar và `extraction_status=needs_review`.

## Giới hạn còn lại

- Chưa có người chấm độc lập review 20 lượt; các nhãn test là self-reviewed. Không tự nhận đã đạt yêu cầu review của BTC.
- Trace lịch sử vẫn vượt TTFT p95 (4.068 ms so với 3.000 ms), và report mới ghi rõ chưa đạt hội thoại M1. Chưa đo lại model với code hiện tại.
- Chưa có report ASR thật đủ tập để đính kèm; chức năng nhận/kiểm ASR đã được kiểm bằng fixture. Khi bàn giao cần cả report, GT, hypotheses, metadata và audio nguồn còn truy cập được.
- Chưa chạy live model/MCP/DB hoặc bootstrap trên máy sạch. Các thiếu sót dataset, hai vòng cải tiến và demo nêu trong báo cáo đối chiếu không thuộc lần sửa eval này.
