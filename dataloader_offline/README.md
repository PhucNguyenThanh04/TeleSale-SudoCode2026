# BTC offline data loader

Chạy từ thư mục gốc repo. Loader nạp catalog/CRM và bản chính sách an toàn vào
PostgreSQL `btc_source`; tùy chọn `--prepare-policy` nối tiếp sang workflow dựng
hybrid index của MCP Knowledge. Không sửa file BTC và không tự kích hoạt release.

## Kiểm tra và nạp PostgreSQL

```bash
ai-services/.venv/bin/python -m dataloader_offline --dry-run
ai-services/.venv/bin/python -m dataloader_offline
ai-services/.venv/bin/python -m dataloader_offline --verify-postgres
```

`--dry-run` đọc/kiểm tra nguồn, không kết nối DB/Qdrant, đọc runtime config hoặc
chạy model, kể cả khi truyền `--prepare-policy`. Nguồn mặc định là thư mục anh em
`../BTC-Data-Vong1-TEAMS`; đổi bằng `BTC_DATA_DIR` hoặc `--data-dir`.
`DATABASE_URL` lấy từ môi trường hoặc `backend/.env`.

Có thể dùng venv riêng với `dataloader_offline/requirements-postgres.txt`
(asyncpg và Pydantic 2) cho luồng chỉ nạp PostgreSQL. Luồng dựng index cần môi trường
AI đã cài các dependency trong `ai-services/requirements.txt` và cấu hình
theo [runbook](../ai-services/docs/mcp-knowledge-runbook.md).

Lệnh nạp mặc định ghi PostgreSQL trong một transaction, dùng upsert; không tự
xóa bản ghi cũ. `--only-postgres` giữ tương thích và không kết hợp với
`--prepare-policy`. Sau khi nạp, loader nói rõ index chưa được dựng.

## Dựng index qua cùng lệnh nạp

Luồng index dùng Cloudflare Workers AI BGE-M3 dense và BM25 CPU. Cần Internet,
credentials Cloudflare, tokenizer nhỏ đi kèm mã nguồn, Qdrant, migrations và
actor reviewer đã được cấp quyền. Không cần GPU, Torch hoặc cache model weights.

Trong `ai-services/.env` cấu hình `CLOUDFLARE_ACCOUNT_ID` và
`CLOUDFLARE_API_TOKEN` (quyền Workers AI), không đưa credentials vào runtime JSON.
File [config/policy-runtime.json](../config/policy-runtime.json) dùng provider và
BM25 mới; `relevance_verified=false` thể hiện chưa đo chất lượng, không ngăn
release đạt `ready` khi kiểm tra tính toàn vẹn thành công.

Môi trường local đã có actor `btc-loader` và DSN reviewer có thể chạy từ root:

```bash
ai-services/.venv/bin/python -m dataloader_offline \
  --data-dir ../BTC-Data-Vong1-TEAMS \
  --prepare-policy --actor btc-loader --runtime-config config/policy-runtime.json
```

Lệnh này **gọi API Cloudflare, tiêu quota và ghi PostgreSQL/Qdrant**; không phải
unit test hoặc dry-run. Máy khác phải provision actor có `knowledge_review`
rồi thay `btc-loader` bằng actor đó. Không có actor tự cấp quyền mặc định.
Trước lần nạp đầu cần migrations 0001/0002/0003 của AI và đúng dependency;
chỉ tạo runtime JSON không thay thế các điều kiện này.

Đặt `KNOWLEDGE_DATABASE_URL` bằng DSN reviewer qua môi trường hoặc
`ai-services/.env`, và `QDRANT_URL` trong môi trường. Quyền `knowledge_review`
phải được provision trước; loader không tự cấp quyền hay dùng DSN admin thay thế.
Các bảng nguồn `btc_source` phải nằm trong DB mà workflow Knowledge sử dụng.

Luồng chạy: kiểm tra nguồn → kiểm tra runtime config/quyền/active ID → nạp
PostgreSQL → encode/upsert/verify index → trả `release_id` và trạng thái.
Nếu bước dựng index lỗi, lệnh thất bại nhưng transaction nguồn đã commit;
active release không thay đổi. Có thể sửa nguyên nhân rồi chạy lại.

- Lần đầu bỏ `--expected-active`; lần sau truyền ID active hiện tại.
- `--revision-id ID` đưa supplement đã duyệt vào bản dựng.
- `--metadata PATH` dùng cùng registry đã review cho parser nguồn và publisher.
- Không tự tải model, chạy eval/calibration hoặc đánh dấu relevance đã xác minh.
- `relevance_verified=false` giữ nguyên chất lượng chưa đánh giá; release có thể `ready` về integrity nhưng chưa active cho đến bước kích hoạt riêng.

Kích hoạt là bước ghi riêng, chỉ sau khi kiểm tra release: đặt biến `POLICY_RELEASE_ID`
bằng ID mới nhận từ output prepare; dùng đúng actor/config đã dùng khi dựng:

```bash
cd ai-services
.venv/bin/python -m app.knowledge.cli policy-activate --actor btc-loader --release-id "$POLICY_RELEASE_ID" --runtime-config ../config/policy-runtime.json
```

Lần kích hoạt sau truyền thêm `--expected-active CURRENT_RELEASE`. Workflow kiểm
quyền, manifest, snapshot, index, cấu hình và CAS trước khi đổi active pointer.

## Dữ liệu được nạp

- Có cấu trúc: 40 sản phẩm, 96 biến thể, 13 khuyến mãi, 12 sự kiện tồn kho,
  50 khách hàng, 2 đơn và 3 phiên seed. Giữ JSON đầy đủ của từng bản ghi.
  `products.csv` không nạp riêng; cùng tập SKU với JSON.
- Chính sách: dùng chung parser/metadata với publisher, giữ lời dẫn, bảng,
  ngoại lệ và hướng dẫn playbook. Bảng nguồn đối chiếu 14 tài liệu/99 mã mục;
  93 mục lưu nội dung an toàn, 6 mục bị loại chỉ giữ placeholder restricted.
  `NB-02` giữ ngày dự kiến; `NB-01`/`NB-03` chỉ giữ giới hạn tiết lộ;
  `KM-06` bỏ giá sàn. Hash nguồn giữ theo raw section body để review supplement.
- Metadata ngày `on` của parser được ánh xạ thành `call_date` trong bảng nguồn
  để tương thích reference/reviewer hiện có; snapshot MCP giữ schema đầy đủ.
- Parser từ chối thiếu tài liệu bắt buộc trong registry, metadata không hợp lệ,
  ID trùng hoặc liên kết thiếu. Không âm thầm dựng corpus thiếu cả một file.
- QA có đáp án, bộ test, ASR ground truth, simulator, schema, script eval và
  tài liệu hướng dẫn đề thi không được tự đưa vào kho trả lời khách.

`btc_source.policy_chunks` phục vụ đối chiếu/review; MCP Knowledge đọc snapshot
`knowledge.policy_sources` và Qdrant của release đã kích hoạt. Chỉ có 99 dòng
trong bảng nguồn không chứng minh MCP đã sẵn sàng tra cứu.

## Xác minh toàn luồng chỉ đọc

Từ gốc repo, dùng đúng release cần kiểm tra:

```bash
ai-services/.venv/bin/python -m dataloader_offline --verify-ingestion \
  --release-id "$POLICY_RELEASE_ID" \
  --runtime-config config/policy-runtime.json
```

Lệnh đối chiếu JSON, các cột nghiệp vụ/quan hệ, ID và hash của 9 bảng nguồn;
snapshot/manifest và artifact BM25; payload đầy đủ (gồm lexical fingerprint);
từng vector dense/BM25 và schema IDF của Qdrant.
Đích Qdrant lấy theo thứ tự môi trường process → `ai-services/.env` → localhost.
DSN nguồn và reviewer phải tới cùng DB/cluster; role có thể khác nhau.

Kết quả là JSON, exit `0` khi mọi kiểm tra đạt, `1` khi sai lệch/lỗi kết nối,
`2` khi tham số CLI không hợp lệ. Report không in giá trị CRM hoặc secret.
`missing`, `extra`, `changed` cho biết mã bản ghi và đường dẫn trường sai.
Lệnh không import dữ liệu, chạy model, sửa payload, tạo collection hoặc đổi active.

- `effective_until` bị thiếu key là lỗi; có key với `null` chỉ hợp lệ khi khớp snapshot.
- `date_basis=order_date` xét theo ngày đơn, không dùng ngày hiện tại để loại bản cũ.
- `ingestion_status=passed` không đồng nghĩa `serving_ready=true`; một release
  `ready` chưa active vẫn chưa được phục vụ; relevance chưa đánh giá được báo riêng.
- Source/metadata thay đổi sau khi build sẽ được báo lệch; không sửa snapshot cũ
  để làm kết quả pass. Phát hành bản mới qua workflow được duyệt.

Ghi nhận lịch sử trước chuyển provider: đợt rà soát 04/11/2026 trên release local cũ trả exit `1`: bản phát hành cũ có
31 chunk BH/FAQ/VC còn `source.version=not_stated`, trong khi registry đã sửa
đúng thành `2026-10` theo tiêu đề BTC. Nội dung, 9 bảng nguồn, 93 vector/payload
so với snapshot cũ và ngày hết hiệu lực đều khớp. Xem [báo cáo](../ai-services/docs/superpowers/plans/2026-11-03-ingestion-verification-results.md).

Luồng nạp có preflight credentials/tokenizer CPU/schema/quyền/đích trước khi ghi.
Khi lỗi, thông báo có `stage` và `source_commit_confirmed`; lỗi build sau commit
nguồn không được hiểu là đã nạp index thành công. Loader không tự prune seed đã
bị xóa khỏi file; verifier báo những record đó trong `extra` để xử lý có kiểm soát.


## Chuyển từ index local cũ

Release local dense/learned sparse không tương thích với Cloudflare dense/BM25,
kể cả cùng tên BGE-M3. Dựng collection mới, kiểm bằng `--verify-ingestion`, rồi
kích hoạt với `--expected-active` đúng ID đang phục vụ. Không xóa collection cũ
hoặc sửa manifest để giả tương thích. Runtime mới chỉ rollback tới release
Cloudflare/BM25 tương thích; quay về local cũ cần cả runtime cũ.

Nếu Cloudflare xác nhận hết quota, dừng build với lỗi `quota_exhausted`; release
dở không active. Sửa nguyên nhân rồi chạy lại cùng config/base ID; release hoàn
chỉnh được verify lại mà không encode. Chưa hỗ trợ resume từng chunk của build dở.
Hết quota không phải thiếu dữ liệu nguồn; không tự chuyển gói trả phí hoặc dùng
BM25-only. Verify ingestion chỉ đọc, không gọi API hoặc tạo điểm eval.
