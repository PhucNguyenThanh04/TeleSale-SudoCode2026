# Submission runtime — short plan

User yêu cầu đọc gói BTC và cùng sửa để người chấm chạy được. Nguồn: README, DIEU-CHINH-DE, GIAI-DAP-MENTOR và schema/latency trong gói BTC. Chọn phạm vi M1 trước theo hệ thống hiện có; đang hỏi profile API/local cho bản nộp. Không tạo goal mới, agent/worktree, dependency mới hoặc chạy live model/reset DB.

- [x] Khớp BTC runner: --scenarios bất kỳ, full/baseline, trace thật, M1 text default; giữ guard reset explicit và parity.
- [x] Sửa cold checkout thiếu tokenizer: setup command tải đúng revision/hash, mặc định chỉ kiểm, test mock HTTP/atomic publish. Không đưa 17MB asset vào Git.
- [x] Viết docs/submission-runbook.md: môi trường Python, config/secrets, BTC import/migrations/store/roles/index, các process và lệnh chấm, ASR/KGL/evidence cần nộp; root README trỏ đúng tài liệu có thật.
- [x] Focused offline tests + help/dry-run/checksum/docs audit. Báo rõ những bước clean-machine/live chưa kiểm chứng; không tuyên bố đã đủ điểm/chạy sạch máy mới khi chưa làm.

Review focus: no secrets in command/output; không reset DB demo; worker cùng model/profile/DB; knowledge index chưa ready không được giả fallback; không đọc nhãn scenario vào agent; source-date/schema BTC Nov giữ nguyên.

## Evidence / remaining rehearsal

- BTC root entrypoint existed; retained required flags and explicit eval-reset guards. RED changed expected lifecycle to text and failed on old voice behavior. Changed only BTC single-trace CLI default/fallback to text; explicit --delivery-mode voice retained. Text stub now correctly acknowledges committed memory instead of relying on voice receipt no-op. Focused runner/parity/tokenizer tests: 18 passed, /tmp/submission-focused.log. Added separate CLI argument test for default and explicit voice; output /tmp/submission-cli-default.log.
- Cold checkout blocker: 17MB BGE tokenizer excluded by Git. New scripts/prepare_knowledge_tokenizer.py verifies existing bytes by default and downloads only with --download, pinned revision+SHA; atomically publishes, refuses existing wrong bytes and cleans mismatch temporary file. Three tests RED missing module then GREEN with mocked HTTP; no download/model call performed. Actual local checksum matches config.
- Root README links to absent runbooks/contracts replaced with existing docs. New submission-runbook covers fresh env/secrets, import, all migrations through backend0006/AI0004, store setup/roles, separate reviewer/worker logins, prepare/activate/verify index, host API/gateway/workers, BTC flags/snapshot scorer, ASR and evidence bundle. Passwords/keys never printed by our commands. Destructive/costly commands documented as explicit operator steps, not executed.
- Verified CLI --help; loader --dry-run returned 40 products/96 variants/13 promos/50 customers/99 chunks. Refused to infer 14 promos merely from organizer prose when actual source has 13. Knowledge still uses Cloudflare, so local LLM does not establish all-local.
- User asked collaborative submission readiness, not permission to reset current DB/run model. Asked asynchronously which LLM profile to submit; no answer yet. Kept both profile paths, no model config changed. No full suite, dependency install, Docker build/up, DB migration/provision/index activation, live ASR/eval or deployment performed.
- Written requirements/command path fixed and offline checks complete for this batch. Clean-machine rehearsal, locked dependencies/model profile, dataset/artifact handoff, live healthy eval/KPI, ASR evidence and two comparable KGL rounds remain unproven. Do not describe the submission as fully accepted or bootstrap as tested on a clean machine. Further work needs chosen model and explicitly designated isolated environment/credentials, not reuse of production/demo data.
