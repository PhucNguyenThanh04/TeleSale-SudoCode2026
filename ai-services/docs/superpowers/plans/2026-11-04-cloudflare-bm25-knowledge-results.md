# Kết quả chuyển Knowledge sang Cloudflare + BM25

Ngày: 04/11/2026. Phạm vi: code và test chức năng offline theo
[plan đã duyệt](2026-11-04-cloudflare-bm25-knowledge.md).

## Thay đổi

- Settings nhận Account ID/API token; runtime JSON giữ provider/model/tokenizer hash,
  BM25 và giới hạn vận hành. Token và đường dẫn tokenizer theo host không đi vào
  manifest/config hash, tránh khác hash giữa host và container.
- HTTP adapter synchronous BGE-M3 text input; kiểm batch/vector, L2 normalize ở
  encoder, hàng đợi và HTTP concurrency hữu hạn. Startup không warmup hay gọi API.
- Quota được phân loại bằng mã Cloudflare 3036 hoặc thông báo xác nhận, khác rate
  limit và capacity 3040. Một lớp retry/breaker, tối đa một retry transient;
  quota không retry, breaker giữ reason để log request sau vẫn có nguyên nhân.
- BM25 NFC/casefold giữ dấu và mã ghép; vocabulary/avgdl cố định theo release,
  k1=1.2/b=.75. Qdrant sparse IDF áp dụng một lần, RRF cùng filter của hai nhánh;
  OOV bỏ prefetch lexical, lỗi provider không chạy BM25-only.
- Publisher tạo manifest schema 3/pipeline cloudflare_dense_bm25, artifact BM25 và
  collection mới, upsert từng document. Verify lại release hoàn chỉnh không encode.
  Quota giữa build không đổi active. Không hứa resume từng chunk của build dở.
- Readiness/build/activation/verifier phân biệt integrity và chất lượng chưa đo;
  relevance_verified giữ false. Startup kiểm đầy đủ snapshot/artifact/vector.
- Khách nhận thông báo chung khi lỗi; log có quota_exhausted/status/code/request/
  release, không có token hoặc raw PII. Phần có căn cứ từ tool khác được giữ.
- Dockerfile Python CPU; bỏ weights/Torch/FlagEmbedding/CUDA/GPU reservation.
  Tokenizer 17.1 MB được tái sử dụng từ cache đã có, không download trong lượt này.
  Compose truyền hai biến Cloudflare, Qdrant ghim v1.19.1 (client 1.19.x).
  README/loader guide/runbook đã đồng bộ đường chạy và điều kiện chuẩn bị release.

## Kiểm chứng

Các test mới được chạy lỗi trước khi thêm implementation tương ứng: cấu hình,
HTTP adapter, encoder async, BM25, IDF config, readiness mới, thông báo lỗi và
pin Compose. Các test hồi quy bổ sung dùng dữ liệu tổng hợp/mocks.

Full suite offline từ ai-services:

```bash
.venv/bin/python ../.superpowers/sdd/2026-11-04-cloudflare-bm25-knowledge/run_offline_tests.py test eval_harness/test_eval_harness.py
```

Kết quả: **569 passed, 14 skipped, 1 warning**, 10.72 giây.
14 test tích hợp bị bỏ qua vì không có môi trường/DSN test; không được tính đạt.
Warning hiện có từ trustcall import LangGraph Send đã deprecated.
Sau lượt full suite, chỉ bổ sung pin Qdrant và tài liệu; test Compose tập trung
được chạy lại: **2 passed**. Không chạy lại full suite.

Runner dùng file settings giả, xóa biến credentials/DSN từ process, tắt tracing
và chặn socket network thật. Không gọi API embedding/LLM, eval hoặc benchmark.
Tên eval_harness/test_eval_harness.py ở lệnh trên là unit test scorer/extractor,
không phải chạy bộ eval BTC.

## Chưa xác minh và bước vận hành tiếp theo

- Chưa smoke Cloudflare thật: chưa xác nhận quyền token, output/schema/chiều thực tế,
  giới hạn provider hoặc quota tài khoản. Không dùng token lộ trong chat để kiểm tra.
- Chưa build/pull/start Docker, cài dependency hoặc kiểm chứng trên máy sạch.
  Pin Qdrant không tự nâng/hạ server đang chạy; kiểm tương thích dữ liệu hiện có
  trước khi thay version, không xóa storage để chuyển đổi.
- Chưa nạp lại BTC, tạo collection/release thật, đổi active pointer hoặc migrate DB.
  Release local cũ cần build mới; runtime mới không phục vụ learned sparse cũ.
- Chưa kiểm SQL grants trên DB test; chưa đo chất lượng retrieval/answer hay latency.
- Chưa git add/commit/push; giữ thay đổi có sẵn của checkout.

Các bước thật (smoke, prepare, verify, activate, Compose) được mô tả trong
[runbook](../../mcp-knowledge-runbook.md). Cần người vận hành duyệt đúng thao tác
trước khi thực hiện; kết quả offline không thay thế kết quả vận hành đó.
