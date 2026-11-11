# Memory Evidence Audit Implementation Plan

**Goal:** Kiểm chứng completeness/use của memory và RQR từ run mới trước Knowledge Gap UI.
**Architecture:** Read-only audit artifact đã hash-bound; dùng scorer/extractor hiện có, không thêm runtime metrics.
**Tech Stack:** Python/JSON/pytest và báo cáo Markdown.
**Spec:** docs/superpowers/specs/2026-11-11-memory-evidence-audit-design.md.

## Constraints / review focus
- Current checkout, không agents/worktrees/auto-commit; giữ các thay đổi cũ.
- Không model live/reset DB, không sửa dataset/scorer/result gốc.
- Không lấy key presence hay complete worker làm fact accuracy; không dùng current quote làm prior recall.
- Không sửa extractor chỉ để tăng CCR; kiểm source/scope/customer repetition và câu hỏi uncertain.
- Không bỏ phần bộ team vì thiếu file; hỏi vị trí, tiếp tục phần độc lập.

## Tasks
- [x] 1. Verify saved pair bằng load_pair; tạo bảng đủ 21 fact requirements kèm trace coordinates/write values/context keys/official use/unknown.
- [x] 2. Review facts_used và toàn bộ câu hỏi quay lại, test nhóm fact usage/extraction liên quan; sửa riêng khi có RED chứng minh.
- [x] 3. Đối chiếu tiêu chí BTC, ghi kết luận đạt/chưa chứng minh/chưa đạt, không gán lỗi nguồn thành lỗi storage.
- [ ] 4. Tìm và review bộ khoảng 22 kịch bản; chuẩn bị bước eval đúng source/date/identity và điều kiện chạy. Chưa có file phải giữ pending.
- [ ] 5. Audit report/spec/plan/test evidence, git diff --check; complete chỉ khi đầy đủ phạm vi.

## Ledger
- User giao goal sau khi đồng ý bảng audit + review extraction + kiểm bộ team. Thiết kế giữ scope đó; không tiếp tục làm frontend gap.
- Đã hỏi vị trí bộ team bằng async input sau khi chỉ tìm thấy 7 public samples trong workspace. Còn làm được audit sample offline.

- Task 1: load_pair và verify_report_turn_diagnostics thành công trên 39 full +39 baseline rows. Tạo docs/memory-evidence-audit-20261111.json + .md, đủ 21 requirements; assert official used=4. 11 prior-write keys đều thấy trong first-return stages, 7 chưa có official use, 10 không có prior fact write/context key. Không khẳng định 11 values/source chính xác vì snapshot không xuất vào artifact.
- Task 2 RED→GREEN: test quote acceptance mong price_quoted_vnd/confirm thất bại vì blocker/open. Sửa extractor nhận acceptance/xác nhận báo giá rõ ràng; giữ personal-blocker behavior. Thêm original BTC scorer test: confirm đầu không redundant, confirm thứ hai redundant. Focused trace-extraction/fact-usage/extraction-report: 75 passed, /tmp/memory-audit-extraction-tests.log. Scorer-alignment/reextract: 18 passed, /tmp/memory-audit-replay-tests.log.
- Offline replay nguyên pair qua reextract_trace trong /tmp/memory-extraction-review-20261111-d8c7ccfc: source_preserved=true, source_integrity_issues=[], 3 question rows sửa nhãn; mọi metric delta=0. facts_used không tái tạo vì thiếu prior value/source snapshot. Không gọi model hoặc DB. Review status vẫn needs_review, không giả duyệt toàn bộ extraction.
- Task 3: báo cáo phân biệt lỗi nguồn (03 không có đơn, 04 không có quote đúng, 05 chưa có verified offer) với memory mất fact; full RQR0/4 vs baseline4/10 đạt relative >=40% trên sample, CCR4/21 chưa chứng minh use tốt. Đọc lại source facts_used/runner confirms provenance/scope/customer repetition/call-start snapshot vẫn có tests; không sửa để tăng điểm.
- Task 4 partial: tìm thấy ZIP/source team22 speech cũ (11+11 dialogues). Đọc ground_truth/source trực tiếp: không có calls/must_carry_over, chưa phải dataset memory đa phiên. Report index 19 không thay cho bộ bổ sung mới. Vị trí bộ mới đã hỏi và chưa nhận trả lời. Chưa chạy live hoặc sinh 22 scenario thay thế.
- Tự review diff extractor/test/report; git diff --check sạch. Scope source/debugging/plan skills giữ các ưu tiên AGENTS: không agent/worktree/commit và không chờ duyệt lại việc đã được user giao.
- Goal còn active: audit sample/extraction xong; review đúng bộ mới và kế hoạch kiểm chứng còn pending vì thiếu vị trí/source. Đây là lần đầu chờ thông tin này, không đánh dấu blocked/complete.
- Continuation audit: kiểm độc lập JSON report với source bytes, exact set 21 scenario/call/fact requirements, từng coordinate write/value/op và official-use theo BTC. Tất cả khớp; hash run gốc còn nguyên. Đã xác nhận lại output hai focused groups (75/18 passed), không chạy lại các test đã xanh. Không có process cần chờ.
- Tái kiểm workspace chưa có bộ team đa phiên mới; chỉ thấy 7 sample và hai ZIP speech cũ. Chưa nhận vị trí bộ team từ người dùng. Phần sample/report đã tự audit xong; Task 4 và completion toàn phạm vi còn chờ dữ liệu. Đây là goal turn thứ hai gặp điều kiện thiếu nguồn, chưa đủ ngưỡng blocked.
- Blocked audit (goal turn thứ ba cùng điều kiện): revalidate workspace vẫn chỉ có sample BTC và ZIP speech cũ; chưa có đường dẫn/bộ đa phiên mới, không có process live để chờ. Task 1–3 và audit phần độc lập xong; Task 4 không thể review đúng dataset khi thiếu nguồn. Không tự tạo dữ liệu thay thế hoặc chạy eval khác. Chuyển goal blocked, chờ người dùng cung cấp vị trí bộ team.
