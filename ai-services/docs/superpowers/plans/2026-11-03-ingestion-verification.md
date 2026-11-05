# Rà soát và kiểm thử ingestion BTC — Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` để thực hiện từng task trong checkout hiện tại. Không sub-agent, worktree, git add hoặc commit. Các checkbox đã được thực hiện/đối chiếu; SQL integration không có DB test được ghi `not_verified` trong báo cáo.

**Goal:** Kiểm chứng dữ liệu BTC được phân loại đúng, nạp đủ nội dung được phép sử dụng vào đúng nơi và phát hiện được sai lệch về nội dung, metadata, ngày hiệu lực, snapshot và vector index.

**Architecture:** Kiểm tra chuỗi file BTC → parser/metadata → `btc_source` → snapshot `knowledge.policy_sources` → payload/vector Qdrant → kiểm tra khả năng áp dụng chính sách. PostgreSQL giữ dữ liệu có thẩm quyền; Qdrant giữ index và bản sao kiểm tra an toàn. Tái sử dụng loader, parser, publisher và test hiện có; bổ sung một lệnh xác minh chỉ đọc để kết quả kiểm tra toàn luồng có thể tái lập.

**Tech Stack:** Python, pytest, asyncpg, Pydantic, SQLAlchemy, Qdrant `:memory:`, fake encoder/repository. Dữ liệu đang vận hành chỉ được đọc khi đối chiếu cuối.

**Spec:** [MCP Knowledge/RAG design](../specs/2026-11-03-mcp-knowledge-rag-design.md). Phạm vi kiểm thử tuân theo yêu cầu người dùng: kiểm chức năng để sửa lỗi, không chạy eval chất lượng RAG.

## Global Constraints

- Đường dẫn trong plan tính từ gốc repo, trừ lệnh ghi rõ chạy tại `ai-services/`.
- Người dùng đã duyệt và cho triển khai inline. Đã hoàn thành phạm vi code/test/đối chiếu chỉ đọc; xem báo cáo kết quả.
- Không gọi LLM, encode bằng model thật, tải/cài thêm dependency, chạy Recall@k, calibration, benchmark hoặc bộ QA BTC có đáp án.
- Không nạp lại corpus thật, sửa payload thật, migrate/reset DB, xóa collection/volume hoặc kích hoạt release trong quá trình kiểm thử. Lần đối chiếu dữ liệu đang vận hành là chỉ đọc; mọi sửa dữ liệu thật cần được mô tả và duyệt riêng.
- Test lỗi và thử chạy lặp sử dụng dữ liệu tổng hợp, fake encoder và Qdrant trong bộ nhớ. SQL integration chỉ dùng DB test đã được chỉ định rõ qua cấu hình hiện có; không lấy DSN đang vận hành làm DB test thay thế.
- Sửa đúng lỗi tái hiện được; không đổi kiến trúc thư mục, tạo dashboard/framework đánh giá hoặc thay toàn bộ parser.
- Không in DSN có mật khẩu, secret, nội dung CRM hoặc hội thoại khách. Báo cáo dùng số lượng, mã mục, tên trường và loại sai lệch.
- Metadata thiếu ngày không được tự lấp bằng ngày hiện tại hoặc ngày suy ra từ tên file. `effective_until` bao gồm ngày cuối; xét theo `date_basis`.
- Ingestion đúng không đồng nghĩa relevance đã xác minh hoặc hệ thống đã sẵn sàng phục vụ. Không tự đổi `relevance_verified` hay active pointer.

## Review Focus

1. Có đủ số dòng nhưng sai/mất nội dung hoặc metadata: so sánh ID, JSON, hash và trường bắt buộc; không chỉ đếm.
2. Mất `effective_until` khác với có trường nhưng giá trị `null`: kiểm tra riêng hai tình huống.
3. Tài liệu cũ hết hiệu lực cho đơn mới nhưng vẫn dùng cho đơn cũ: kiểm ngày biên và ngày đơn chưa xác minh.
4. Nạp dang dở hoặc chạy lại: không báo thành công toàn luồng, không đổi active, không nhân bản dữ liệu.
5. Đọc nhầm DB/Qdrant/release hoặc nguồn thay đổi giữa các giai đoạn: xuất đích đã kiểm tra, xác minh snapshot và phát hiện dữ liệu trộn phiên bản.

## Mốc đối chiếu của bộ BTC hiện tại

Các con số này thuộc bộ BTC `reference_date=2026-10-15`; không dùng làm số mặc định cho mọi corpus tương lai.

| Nhóm | Kỳ vọng | Đích/ý nghĩa |
|---|---:|---|
| Sản phẩm / biến thể | 40 / 96 | `btc_source.products`, `variants`; JSON đầy đủ |
| Khuyến mãi / sự kiện tồn kho | 13 / 12 | `promotions`, `inventory_events` |
| Khách / đơn / phiên seed | 50 / 2 / 3 | `customers`, `crm_orders`, `crm_sessions` |
| Tài liệu / mục chính sách gốc | 14 / 99 | Đối chiếu tất cả mã mục, kể cả mục bị loại |
| Mục phục vụ an toàn | 93 | Snapshot PostgreSQL và point Qdrant tương ứng |
| Mục không phục vụ | 6 | `NQ-01…05`, `NB-04`; không có raw text trong index |
| Chính sách đổi trả cũ | 5 | `DT-OLD-01…05`, `effective_until=2026-09-30`, `date_basis=order_date` |
| Chính sách đổi trả mới | 7 | `DT-01…07`, `effective_from=2026-10-01` |

Release đã đối chiếu trước khi lập plan: `policy-43342651696f55fd1e9baa4e2065e091`, collection `policy_43342651696f55fd1e9baa4e2065e091`, trạng thái `prepared`. Đây là mốc kiểm tra, không phải kết quả thực hiện plan.

`products.csv` không cần nạp trùng với JSON; phải kiểm tập SKU và sự tương ứng của các cột có chung ý nghĩa. QA có đáp án, ASR ground truth, simulator, schemas, test/eval và tài liệu hướng dẫn đề thi được ghi rõ vai trò; không tự đưa vào corpus trả lời khách. Chênh lệch README BTC ghi 14 khuyến mãi so với JSON có 13 phải được báo là khác biệt của nguồn, không tự tạo thêm chương trình.

## Task 1: Đối chiếu nguồn, ranh giới chunk và nội dung an toàn

**Files:** `dataloader_offline/source.py`, `ai-services/app/knowledge/policy/{source.py,metadata.json}`, `ai-services/test/{test_dataloader_offline.py,test_policy_sources.py}`. Chỉ sửa implementation khi có test chứng minh lỗi.

**Interfaces:** Tái sử dụng `read_release(root, metadata_path=None)`, `read_policy(directory, metadata_path=None)`, `parse_policy_sources(directory, metadata)` và `default_metadata()`.

- [x] Đọc inventory file BTC và lập bảng nguồn → đích → được dùng/không dùng → lý do trong báo cáo cuối. Đối chiếu mọi file thuộc catalog/policy, không dựa vào số lượng đã hardcode trong loader.
- [x] Bổ sung `test_every_original_section_is_served_or_explicitly_excluded`: tập 99 ID gốc bằng hợp của tập 93 ID an toàn và đúng 6 ID bị loại; hai tập không giao nhau. Loader giữ 99 ID để đối chiếu, publisher không tạo point cho ID bị loại.
- [x] Bổ sung `test_chunk_keeps_document_prelude_title_table_and_notes`: dùng fixture Markdown nhỏ có hai mục, bảng nhiều dòng và ghi chú; assert từng phần nằm đúng chunk, heading tiếp theo không lọt sang chunk trước. `[BH-01]` được lưu ở ID, chữ tiêu đề vẫn có trong `content`.
- [x] Mở rộng test lỗi: thiếu file bắt buộc, mất một section có metadata/liên kết, ID trùng, mục rỗng, metadata không nhận diện, liên kết thiếu. Khi mất section không có registry độc lập để chứng minh, ghi rõ giới hạn; không tuyên bố kiểm toàn bộ section chỉ vì đã kiểm đủ file.
- [x] Test `NB-02` giữ ngày dự kiến nhưng không giữ số lượng/nhà cung cấp; `NB-01`/`NB-03` chỉ có giới hạn tiết lộ; `KM-06` không có giá sàn; playbook an toàn không bị xóa trắng. Test hash body nguồn, hash toàn file và hash nội dung an toàn đúng vai trò.
- [x] Với test mới: chạy để thấy thất bại đúng nguyên nhân, sửa tối thiểu rồi chạy lại nhóm bị ảnh hưởng. Không sửa metadata chỉ để đạt một con số kỳ vọng.

**Run từ `ai-services/`:** `.venv/bin/python -m pytest test/test_dataloader_offline.py test/test_policy_sources.py -q`.

## Task 2: Kiểm metadata thời gian và bẫy tài liệu hết hiệu lực

**Files:** `ai-services/app/knowledge/{policy/metadata.json,policy/rules.py,schemas.py}`, `ai-services/test/{test_policy_sources.py,test_policy_rules.py}`.

**Interfaces:** `SourceChunk`, `PolicyRule`, `apply_policy_rules(chunks, request, context)` giữ schema và semantics hiện có. Không thêm trường `expires_at` trùng nghĩa với `effective_until`.

- [x] Lập bảng metadata của 14 tài liệu và các ngoại lệ cấp mục, dẫn tới dòng/đoạn BTC chứng minh ngày, phiên bản, phạm vi và quan hệ thay thế. Phân biệt ngày cập nhật tài liệu, thời hạn quyền lợi và ngày áp dụng chính sách; không dùng thay thế lẫn nhau.
- [x] `test_all_old_return_sections_keep_expiry_and_prelude`: cả 5 `DT-OLD-*` có ngày cuối `2026-09-30`, basis `order_date` và lời dẫn giữ lại cho đơn cũ; cả 7 mục mới bắt đầu `2026-10-01`.
- [x] `test_return_policy_boundary_uses_verified_order_date`: ngày nghiệp vụ `2026-11-03`; đơn xác minh `2026-09-30` chọn bản cũ, đơn `2026-10-01` chọn bản mới. Ngày biên được tính inclusive.
- [x] `test_unknown_and_reported_order_dates_never_confirm_entitlement`: không có ngày đơn không lấy `on` thay thế; ngày khách khai chỉ tạo kết quả `conditional`; ngày giả mạo ở request bị từ chối.
- [x] `test_warranty_rule_boundary_is_not_global_document_expiry`: kiểm ngoại lệ Karofi/Kangaroo đến `2026-07-31` và từ `2026-08-01` trong `rules`; không gắn ngày hết hạn này lên toàn bộ `BH-01`.
- [x] `test_unspecified_expiry_is_present_null_not_invented`: `SP-SN-01` có key ngày với giá trị `None`; metadata không được suy ra hiệu lực vô hạn. Ngày không hợp lệ hoặc khoảng bắt đầu lớn hơn ngày cuối phải được phát hiện ở bước validation phù hợp.

**Run:** `.venv/bin/python -m pytest test/test_policy_sources.py test/test_policy_rules.py -q`.

## Task 3: Kiểm ghi PostgreSQL, preflight và tính đầy đủ của dữ liệu có cấu trúc

**Files:** `dataloader_offline/{__main__.py,knowledge.py,source.py,postgres.py}`, `ai-services/test/test_dataloader_offline.py`. Thêm `ai-services/test/test_dataloader_postgres.py` cho SQL integration opt-in nếu cần.

**Interfaces:** Giữ `import_release(database_url, release)`, `release_counts(release)`, `validate_policy_prepare(...)`, `import_data(args, release)`; không đổi quyền của role phục vụ.

- [x] Test mọi field JSON của cả 7 nhóm có cấu trúc được giữ trong `data`; kiểm PK, quan hệ cha/con và dữ liệu đơn/phiên lồng nhau, không chỉ số lượng INSERT. Hai khách dùng chung số điện thoại vẫn được giữ.
- [x] Test nạp hai lần vào fake writer có trạng thái: ID không trùng, nội dung cập nhật đúng. Test nguồn bỏ một record: xác định chính sách upsert hiện tại giữ record cũ; verifier phải báo record thừa thay vì coi là đồng bộ hoàn toàn. Không thêm auto-delete.
- [x] Test lỗi giữa transaction ghi nguồn không được báo import thành công. Fake chỉ chứng minh cách sử dụng transaction; rollback SQL thực chỉ được xác nhận khi có DB test riêng.
- [x] Test thiếu config/cache/dependency/CUDA, thiếu bảng/quyền, sai active ID, Qdrant không kết nối và DSN reviewer trỏ nhầm DB. Kiểm tra trước khi ghi những điều kiện có thể kiểm bằng cấu hình, schema, kết nối và cache, không khởi tạo model để làm preflight.
- [x] Đối chiếu cách đọc `QDRANT_URL`/đường dẫn config giữa môi trường process, `.env`, CLI và Compose; ghi rõ precedence, bảo đảm lệnh build và lệnh verify kiểm đúng đích. Đối chiếu danh tính DB bằng truy vấn; không yêu cầu hai DSN có cùng tên role.
- [x] `--dry-run` không được resolve DSN, mở kết nối hoặc encode. Lệnh chỉ nạp PostgreSQL phải nói rõ chưa build index; lỗi prepare sau khi nguồn commit phải báo đúng giai đoạn, exit khác 0 và không ngụ ý toàn luồng đã thành công.
- [x] SQL integration dùng `KNOWLEDGE_TEST_DSN` và `KNOWLEDGE_EXPECTED_TEST_DATABASE` theo cơ chế hiện có; kiểm danh tính trước mọi ghi, không reset schema/data thật. Không có DB test thì đánh dấu `not_verified`, không dùng fake để tuyên bố SQL đã được xác minh.

**Run:** `.venv/bin/python -m pytest test/test_dataloader_offline.py -q`; chỉ chạy file SQL integration khi DB test đã được chỉ định và cho phép.

## Task 4: Kiểm snapshot, payload Qdrant và phát hành dang dở

**Files:** `ai-services/app/mcp_servers/mcp_knowledge/repos/qdrant.py`, `ai-services/app/knowledge/services/publish.py`, `ai-services/test/{test_policy_storage.py,test_policy_publish.py,test_knowledge_erasure.py}`.

**Interfaces đề xuất:** Mở rộng `HybridPolicyIndex.verify(release, config, *, chunks=None)` để khi có `chunks`, đối chiếu payload với snapshot đầy đủ. `build_policy_release(...)` truyền snapshot đang build; `refresh_payloads(...)` kiểm index cơ bản trước sửa và kiểm payload đầy đủ sau sửa, để vẫn sửa được payload cũ thiếu field. Cập nhật fake index bị ảnh hưởng trong test.

- [x] Viết `test_verify_rejects_missing_expiry_even_when_hash_fields_match`: xóa key `effective_until` của một point nhưng giữ ID/hash → verify có snapshot phải fail. Key tồn tại với `null` được chấp nhận nếu snapshot cũng `null`.
- [x] Test sửa riêng ngày cuối thành `2099-12-31`, đổi `date_basis`, làm mất `source`, sửa `content`, thiếu `rules`/`required_links`, chèn ID lạ hoặc point thừa/thiếu: tất cả sai lệch được phát hiện theo trường tương ứng.
- [x] So sánh đầy đủ 20 key payload hiện có với snapshot/config. Nội dung/source của supplement phải `null`, không copy aliases/source references có nguồn từ khách; nội dung BTC phải đúng bản an toàn.
- [x] Test dense dimension, sparse schema, fingerprint, release ID và hash. Mất metadata không được qua chỉ vì hash nằm trong payload vẫn đúng.
- [x] Test refresh giữ nguyên vector, point ID, số point, release và active pointer. Snapshot hash sai phải bị chặn trước khi ghi; lỗi giữa refresh phải báo thất bại, không báo đã đồng bộ đủ.
- [x] Dùng fake encoder gây lỗi trước/giữa encode, lỗi upsert/verify và nguồn thay đổi giữa các giai đoạn. Release không được chuyển `ready` khi nguồn/snapshot/index không nhất quán; nguồn PostgreSQL đã commit phải được báo riêng.
- [x] Test build lặp cùng nguồn/config/base không tạo point/release trùng; không giả định chạy lại `prepared` sẽ không encode nếu code chưa hỗ trợ điều đó. `relevance_verified=false` giữ `prepared`, không đổi active.

**Run:** `.venv/bin/python -m pytest test/test_policy_storage.py test/test_policy_publish.py test/test_knowledge_erasure.py -q`, với cấu hình test độc lập `.env` đang vận hành.

## Task 5: Lệnh xác minh ingestion chỉ đọc, có kết quả tái lập

**Files:** Tạo `dataloader_offline/verification.py`; sửa `dataloader_offline/__main__.py`; thêm `ai-services/test/test_ingestion_verification.py`.

**Interface đề xuất:**

```python
async def verify_ingestion(database_url, source_dir, *, knowledge_database_url,
                           qdrant_url, release_id, runtime_config_path,
                           metadata_path=None) -> dict:
    ...
```

- [x] Thêm mode `--verify-ingestion --release-id ID --runtime-config PATH`, dùng cùng `--data-dir`/`--metadata` với loader. Không kết hợp với `--prepare-policy`, `--verify-postgres`, `--only-postgres` hoặc `--dry-run`. `--actor`, `--expected-active`, `--revision-id` vẫn chỉ dành build.
- [x] Xác minh source → `btc_source` bằng tập ID, JSON chuẩn hóa và hash; báo riêng missing/extra/changed. Đối chiếu 99 ID nguồn, 93 snapshot và point theo manifest của release được chỉ định, không tự chọn một collection theo tên gần giống.
- [x] Kiểm snapshot hash/manifest hash, metadata/ngày, payload và schema index qua verifier Task 4. Không encode, tải model hoặc sửa bất kỳ field nào để làm kết quả pass.
- [x] Mọi SELECT trong transaction chỉ đọc; Qdrant chỉ gọi API đọc. Test monkeypatch các phương thức write/encode để lập tức fail nếu verifier gọi nhầm.
- [x] Report gồm đích DB/Qdrant đã đọc, release/collection, expected/actual counts, ID sai lệch và tên trường sai. Không xuất raw CRM, secret hoặc toàn bộ nội dung khách.
- [x] Phân biệt `ingestion_status=passed`, `release_status=prepared`, `relevance_verified=false`, `serving_ready=false`. Lỗi kiểm tra hoặc không kết nối: status failed và exit khác 0; không dùng bảng đếm rỗng như kết quả kiểm thành công.
- [x] Test dùng fake repo, fake encoder bị cấm gọi và Qdrant `:memory:`: dữ liệu đúng; đúng count nhưng sai JSON; thiếu/thừa ID; thiếu key ngày; sai ngày; sai snapshot; nhầm release/đích; lỗi kết nối. Test CLI mode không âm thầm gọi luồng import.

**Run:** `.venv/bin/python -m pytest test/test_ingestion_verification.py test/test_dataloader_offline.py -q`.

## Task 6: Đối chiếu dữ liệu thật chỉ đọc và báo cáo đánh giá

**Files:** `dataloader_offline/README.md`, `ai-services/docs/mcp-knowledge-runbook.md`; tạo báo cáo `ai-services/docs/superpowers/plans/2026-11-03-ingestion-verification-results.md` khi thực hiện xong.

- [x] Chạy lệnh verify-only Task 5 trên release được chỉ định, xuất danh tính instance và point ID để người dùng có thể mở đúng point kiểm tra. Phân biệt payload của point, kết quả query chọn lọc field và giao diện xem schema.
- [x] Kiểm đủ 93 point có key `effective_until`; đúng 5 `DT-OLD-*` có ngày cuối `2026-09-30`; các mốc riêng trong `BH-01.rules` được giữ. Không yêu cầu mọi chunk đều có ngày hết hạn khác `null`.
- [x] Đối chiếu 7 nhóm JSON nguồn, 14 tài liệu/99 mục, 93 snapshot và payload; mọi sai lệch được ghi bằng ID/field, không chỉ tổng số.
- [x] Chạy full regression unit/mock tối đa một lần cuối khi có thay đổi code. Dùng file settings test tổng hợp có API key/token giả và không chứa DSN/runtime config đang vận hành, tránh test vô tình tải model hoặc dùng DB thật. Lỗi cấu hình test thì chỉ sửa và chạy lại nhóm thất bại.
- [x] Báo cáo mỗi tiêu chí `pass` / `fail` / `not_verified`, kèm lệnh và bằng chứng. Tách kết quả dữ liệu đang có khỏi bảo đảm hành vi khi lỗi được kiểm bằng fake; ghi riêng SQL integration chưa chạy nếu không có DB test.
- [x] Với lỗi thực: ghi nguyên nhân, test tái hiện, sửa code tối thiểu và đề xuất sửa dữ liệu cần thiết. Không tự nạp lại/xóa/đổi active. Nếu kết quả đúng nhưng người dùng vẫn không thấy field, đối chiếu URL/collection/point thay vì suy đoán lỗi UI.
- [x] Cập nhật README với lệnh verify-only chạy được và cách hiểu `null`, ngày đơn, prepared/ready; các placeholder phải được ghi rõ. Không công bố điểm chất lượng RAG hay khả năng phục vụ đã được chứng nhận từ kiểm tra ingestion.

## Điều kiện hoàn tất

1. Mỗi file/nhóm BTC có phân loại và đích rõ ràng; không lẫn nguồn kiểm thử vào corpus khách hàng.
2. Nội dung được phép sử dụng, bảng, lời dẫn và metadata có bằng chứng đối chiếu, không chỉ khớp số lượng.
3. Bẫy bản cũ/bản mới, ngày biên, ngày khách khai và ngoại lệ bảo hành có test chức năng.
4. Verifier phát hiện được cả key bị thiếu và giá trị sai dù ID/hash cũ vẫn còn.
5. Lỗi từng giai đoạn và chạy lặp được kiểm ở môi trường cô lập; không sửa active hay báo thành công giả.
6. Có lệnh kiểm chỉ đọc tái lập trên đúng instance/release, báo cáo pass/fail/not_verified và giới hạn còn lại.

**Không phải điều kiện hoàn tất:** chạy eval BTC, đánh giá Recall/latency, encode lại corpus, bật relevance hoặc kích hoạt release. Những việc đó nằm ngoài plan này.

**Kết quả thực hiện:** [2026-11-03-ingestion-verification-results.md](2026-11-03-ingestion-verification-results.md). Regression offline: 541 passed, 14 skipped; sau tự review, nhóm publisher/storage/loader: 59 passed. Dữ liệu thật cần release mới để đồng bộ version metadata của 31 chunk; chưa sửa dữ liệu thật.
