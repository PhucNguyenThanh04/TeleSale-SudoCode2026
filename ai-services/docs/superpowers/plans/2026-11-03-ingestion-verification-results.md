# Kết quả rà soát ingestion BTC

Thực hiện theo [plan đã duyệt](2026-11-03-ingestion-verification.md), ngày 04/11/2026 (Asia/Ho_Chi_Minh). Không chạy eval, benchmark, model thật hoặc sửa dữ liệu đang vận hành trong đợt rà soát này.

**Kết luận:** dữ liệu nguồn PostgreSQL đầy đủ và đúng nội dung/cột nghiệp vụ; Qdrant khớp snapshot đã nạp và có trường ngày hết hiệu lực. Registry được sửa ba phiên bản tài liệu có căn cứ rõ ràng trong tiêu đề BTC, nên release cũ hiện **không còn khớp registry mới ở 31 chunk**. Verifier trả `failed`/exit 1 đúng với sai lệch này. Chưa nạp lại, chỉnh snapshot/payload thật hoặc đổi active để làm kết quả pass.

## 1. Bằng chứng và đích đã kiểm tra

Lệnh chạy từ gốc repo:

```bash
ai-services/.venv/bin/python -m dataloader_offline --verify-ingestion \
  --release-id policy-43342651696f55fd1e9baa4e2065e091 \
  --runtime-config config/policy-runtime.json
```

- PostgreSQL nguồn và reviewer đều là DB `telesale`, cùng định danh cluster/thời điểm khởi động server. Các role khác nhau được chấp nhận.
- Qdrant: `http://127.0.0.1:6333`.
- Collection: `policy_43342651696f55fd1e9baa4e2065e091`.
- Release: `prepared`; `relevance_verified=false`, `serving_ready=false`.
- Đối chiếu dữ liệu thật bằng transaction PostgreSQL chỉ đọc và các API đọc Qdrant. Không dùng model để xác minh.
- JSON bằng chứng local: `.superpowers/sdd/2026-11-03-ingestion-verification/live-verification.json` (git-ignored, không chứa raw CRM hoặc mật khẩu).

## 2. Phân loại nguồn BTC

| Nguồn | Đích hoặc vai trò | Đánh giá |
|---|---|---|
| `catalog/products.json` | Sản phẩm/biến thể trong `btc_source`; giữ JSON đầy đủ | pass |
| `catalog/products.csv` | Bản chiếu để đối chiếu, không nạp trùng | pass: SKU, tên, ngành, hãng, giá, tồn, số biến thể và attributes khớp JSON |
| `catalog/promotions.json` | Toàn bộ 13 chương trình, kể cả chưa/đã hết hiệu lực, trong PostgreSQL; tool nghiệp vụ chọn theo ngày | pass |
| `catalog/inventory_timeline.json` | 12 sự kiện theo SKU/ngày | pass |
| `catalog/crm_seed.json` | 50 khách, 2 đơn, 3 phiên; giữ hai khách dùng chung số điện thoại | pass |
| `policy/*.md` | 14 tài liệu, 99 ID gốc; 93 snapshot/point an toàn và 6 ID bị loại | pass về nội dung/ID; version metadata cần release mới |
| `rag/qa_labeled.json` | Bộ câu hỏi/đáp án đánh giá, không phải corpus trả lời khách | đúng phạm vi; không chạy |
| `asr/ground_truth.json` | Ground truth ASR, không đưa vào tri thức khách | đúng phạm vi; không chạy |
| `test_set/public_sample/*`, `simulator/*` | Kịch bản/persona kiểm thử | đúng phạm vi; không chạy eval |
| `schemas/*` | Hợp đồng tích hợp/trace/brief | giữ làm tài liệu phát triển |
| `eval/*`, trace/report mẫu | Script/tài nguyên chấm, không ingestion vào RAG | không chạy/chỉnh sửa |
| `README.md`, `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md` | Yêu cầu và hướng dẫn đề thi | dùng để rà soát thiết kế, không tự nhập corpus khách |
| `policy.zip` | Bản đóng gói chính sách | pass: 14/14 file khớp byte với thư mục giải nén |
| `eval.zip` | Bản đóng gói script/tài nguyên chấm | 7/8 file khớp; `eval/reference_eval.py` khác bản giải nén. Không tham gia ingestion; chưa xác định bản chuẩn để chấm |

`reference_date` được kiểm theo bộ BTC `2026-10-15`. `currency=VND`, hướng dẫn timeline và ghi chú seed là thông tin ngữ cảnh/hướng dẫn, không phải record khách hàng riêng. Việc thực thi nghiệp vụ timeline/giá nằm ở tool hiện có. Không dùng ngày máy chủ để thay ngày nghiệp vụ.

README BTC ghi 14 khuyến mãi nhưng JSON thực tế có 13; không tạo chương trình thứ 14 để khớp mô tả.

## 3. Đối chiếu dữ liệu PostgreSQL thực tế

| Bảng | Nguồn / DB | Missing / extra / changed | Kết quả |
|---|---:|---:|---|
| products | 40 / 40 | 0 / 0 / 0 | pass |
| variants | 96 / 96 | 0 / 0 / 0 | pass |
| promotions | 13 / 13 | 0 / 0 / 0 | pass |
| inventory_events | 12 / 12 | 0 / 0 / 0 | pass |
| customers | 50 / 50 | 0 / 0 / 0 | pass |
| crm_orders | 2 / 2 | 0 / 0 / 0 | pass |
| crm_sessions | 3 / 3 | 0 / 0 / 0 | pass |
| policy_documents | 14 / 14 | 0 / 0 / 0 | pass |
| policy_chunks | 99 / 99 | 0 / 0 / 0 | pass |

Đã so sánh các cột nghiệp vụ/khóa/quan hệ, JSON chuẩn hóa và source hash, không chỉ số dòng. `policy_documents` là biểu diễn metadata nguồn legacy theo writer hiện có; metadata/rules phục vụ đầy đủ nằm ở snapshot từng chunk.

## 4. Metadata thời gian và phiên bản của 14 tài liệu

| File | Version registry sau rà soát | Ngày/basis và căn cứ |
|---|---|---|
| `changelog.md` | not_stated | `on`; không có khoảng chung cho toàn nhật ký, từng mục ghi mốc thay đổi |
| `chinh-sach-bao-hanh.md` | **2026-10** | Tiêu đề dòng 1 ghi rõ phiên bản. Không gán ngày hết hiệu lực chung; `BH-01.rules` và `CL-04` chia quyền lợi theo ngày đơn 31/07–01/08/2026 |
| `chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md` | 2026-06 | Tiêu đề/lời dẫn dòng 1–3 và `CL-01`: `order_date`, ngày cuối 30/09/2026 |
| `chinh-sach-doi-tra.md` | 2026-10 | Tiêu đề và `CL-01`: đơn từ 01/10/2026; `order_date` |
| `chinh-sach-van-chuyen-thanh-toan.md` | **2026-10** | Tiêu đề dòng 1 ghi rõ phiên bản; không suy ra toàn tài liệu bắt đầu 01/10. `VC-03` liên kết `CL-03` cho thay đổi COD |
| `dieu-khoan-khuyen-mai.md` | 2026-10 (nhãn registry) | Tiêu đề ghi hiệu lực từ 01/10/2026; `on`. Ngày/số tiền của từng chương trình ưu tiên promotions JSON theo lời dẫn |
| `faq.md` | **2026-10** | Tiêu đề dòng 1 ghi rõ phiên bản; không quy định ngày hết hạn chung |
| `ghi-chu-nhap-hang-NOI-BO.md` | not_stated | Nguồn restricted; chỉ bản an toàn của NB-01/02/03 phục vụ; ngày ETA không phải ngày hết hiệu lực toàn file |
| `noi-quy-nhan-vien.md` | not_stated | Loại khỏi corpus khách; không bịa ngày hiệu lực |
| `playbook-telesale.md` | not_stated | Tiêu đề ghi tháng tài liệu, không tự suy ra mốc hiệu lực; hướng dẫn nghiệp vụ an toàn được giữ |
| `quy-trinh-cod-hoan-hang.md` | not_stated | Tiêu đề ghi 2026-10, không khẳng định một khoảng ngày chung |
| `spec-gia-dung.md` | not_stated | “cập nhật 10/2026” là mốc cập nhật; không tự biến thành ngày bắt đầu/hết hiệu lực |
| `spec-thoi-trang-me-be.md` | not_stated | Tương tự; `SP-SN-01.effective_until=null` |
| `thong-bao-lich-nghi.md` | not_stated | Lịch/giờ trong nội dung không phải ngày hết hiệu lực chung của tài liệu |

**Bẫy tài liệu hết hiệu lực: pass.** Cả 93 payload có key `effective_until`; đúng 5 `DT-OLD-*` có giá trị `2026-09-30`. Đơn xác minh ngày 30/09 chọn bản cũ; ngày 01/10 chọn bản mới, dù ngày gọi là 03/11 trong fixture. Ngày khách khai chỉ cho kết quả conditional; thiếu ngày đơn không dùng ngày gọi thay thế.

Ví dụ point thật `DT-OLD-01`: `b2abbc08-6c8b-5e6b-a709-83aead3a95c4`. Metadata nằm trong `result.payload` khi đọc point bằng REST. Query giới hạn `with_payload` có thể chỉ trả vài trường; không dùng kết quả query chọn lọc để kết luận trường không tồn tại trong point.

## 5. Các lỗi code đã sửa và bằng chứng chức năng

| Phát hiện | Sửa | Bằng chứng |
|---|---|---|
| Mất section đã khai báo metadata nhưng không có required link có thể bị bỏ qua | Parser từ chối section khai báo nhưng không còn trong nguồn | Test thất bại trước sửa, đạt sau sửa |
| Version của BH/VC/FAQ ghi not_stated dù tiêu đề có phiên bản | Sửa đúng 3 entry registry thành 2026-10 | Test đối chiếu tiêu đề BTC |
| Khoảng ngày bắt đầu sau ngày kết thúc vẫn được chấp nhận | Validate interval cho `SourceChunk` và `PolicyRule` | Hai test RED→GREEN |
| CRM order/session trùng ID giữa hai khách có thể overwrite | Chặn duplicate nested IDs trước import | Hai test RED→GREEN; số điện thoại chung vẫn được phép |
| Build/serve chỉ đọc QDRANT_URL từ process, bỏ qua `.env` | Resolver chung process → Settings `.env` → default cho build/activate/server/verify | Test precedence |
| Preflight chưa kiểm cache/CUDA/dependency/schema/quyền/đích | Kiểm không khởi tạo model; xác minh reviewer và nguồn cùng DB | Test fake từng nhánh lỗi; không ghi nguồn nếu preflight fail |
| Nguồn có thể thay đổi giữa parse/import/build | Fingerprint đầu vào và kiểm lại policy snapshot trước hoàn tất; lỗi báo đúng giai đoạn/source commit | Test thay nguồn bằng fixture, active không đổi |
| ID/hash vẫn đúng nhưng payload mất ngày hoặc sửa text/metadata | Strict verifier so 20 trường với snapshot | Test cố tình xóa/sửa ngày, basis, source, content, links/rules |
| Schema hybrid đúng nhưng một point thiếu dense/sparse vẫn được nhận | Strict verifier đọc từng vector, kiểm đủ hai nhánh, dimension, finite, norm và sparse values | Test xóa riêng từng nhánh RED→GREEN; không encode lại dữ liệu thật |
| Dùng lại release ready trả kết quả cũ mà không kiểm index/thu hồi/nguồn | Verify ngoài transaction SQL, kiểm lại trạng thái/quyền/CAS/approval/revocation/nguồn; không encode lại | Ba test RED→GREEN: payload, revocation, source drift |
| Chỉ có bảng đếm chưa đủ xác nhận toàn luồng | Thêm `--verify-ingestion` chỉ đọc, report sai lệch theo ID/field và exit code | Test nguồn JSON/cột sai, missing/extra, snapshot/date sai, nhầm đích/release, lỗi kết nối |

Test writer có trạng thái chứng minh contract transaction, upsert, giữ JSON và không tự prune bằng dữ liệu tổng hợp. Không suy rộng thành bằng chứng rollback PostgreSQL thật.

## 6. Kết quả snapshot/index hiện có

| Tiêu chí | Kết quả |
|---|---|
| Định danh DB nguồn/reviewer | pass |
| 9 bảng nguồn so với file BTC | pass |
| Snapshot hash so với manifest đã phát hành | pass |
| 93 point, payload đầy đủ, ID/hash/fingerprint/schema/vector so với snapshot cũ | pass |
| Trường hết hiệu lực và 5 mốc ngày bản cũ | pass |
| Nguồn bị thu hồi trong release này | Không có |
| Metadata registry mới so với manifest cũ | **fail: metadata_hash_mismatch** |
| Snapshot cũ so với parser/registry đã sửa | **fail: 31 chunk chỉ lệch source.version** |
| Relevance/serving | Chưa xác minh; release prepared, không đổi active |

31 chunk cần nhận version đúng gồm: `BH-01…05` (5), `FAQ-01…19` (19), `VC-01…07` (7). Nội dung và vector hiện có không bị mất; đây là registry được sửa sau lần build, không phải thiếu 31 point.

**Xử lý dữ liệu được đề xuất, chưa thực hiện:** duyệt một lần phát hành mới theo registry đã sửa, dùng workflow prepare/verify; giữ collection cũ để truy vết. Không chỉnh thẳng snapshot/manifest bất biến hoặc xóa collection để che sai lệch. Kích hoạt vẫn là bước riêng và không được bỏ gate relevance.

## 7. Kiểm thử, tự review và giới hạn

- Full regression unit/mock chạy **một lần** bằng settings tổng hợp, API key/token giả, không có DSN/runtime config đang vận hành: **541 passed, 14 skipped**; một cảnh báo deprecation trustcall/LangGraph hiện có.
- Trong tự review sau full suite, phát hiện nhánh tái sử dụng release ready ở mục 5. Đã sửa với ba ca RED→GREEN; chạy lại đúng nhóm publisher/storage/loader: **59 passed**. Không chạy lại toàn suite thành công.
- Các nhóm source/date, writer replay, verifier read-only và CLI đã có kiểm tra riêng. `--dry-run` vẫn đọc được bộ BTC và không mở dịch vụ.
- Tự review bởi tác giả theo yêu cầu không dùng sub-agent; không có reviewer độc lập. Các quyết định phạm vi: giữ SQL integration opt-in; strict verify thêm cấu trúc vector vì schema không bảo đảm mỗi point có đủ hai nhánh; không sửa dữ liệu thật để biến kết quả fail thành pass.
- **not_verified:** SQL rollback/fault injection và role integration trên DB test riêng, do không có `KNOWLEDGE_TEST_DSN`/`KNOWLEDGE_EXPECTED_TEST_DATABASE` được chỉ định. 14 test skipped không được tính là pass.
- **not_verified/out of scope:** Recall, chất lượng câu trả lời, latency, calibration, khả năng phục vụ production. Không chạy bộ QA/eval BTC hoặc encode bằng model thật trong đợt này.
- Runtime không có registry độc lập chứa đủ 99 section ID gốc. Parser bắt thiếu file/section đã khai báo/required link; test corpus cụ thể đối chiếu 99 ID và lần audit đối chiếu policy.zip. Không khẳng định phát hiện được mọi section chưa khai báo bị xóa khỏi một corpus tương lai mà không có manifest nguồn riêng.
- Bản giải nén `eval/reference_eval.py` khác archive là khác biệt nguồn ngoài ingestion; chưa xác định bản chuẩn để chấm và không tự chỉnh sửa.

**Trạng thái plan:** hoàn thành code, test chức năng và đánh giá chỉ đọc. Kết quả dữ liệu thật vẫn có sai lệch version metadata cần được duyệt phát hành bản mới; không tuyên bố ingestion đang vận hành đã đạt toàn bộ kiểm tra mới.
