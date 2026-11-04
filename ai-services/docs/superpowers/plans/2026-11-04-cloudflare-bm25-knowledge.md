# Cloudflare BGE-M3 + BM25 Knowledge — Implementation Plan

> **For agentic workers:** Dùng `superpowers:executing-plans`, thực hiện tuần tự trong checkout hiện tại. Không sub-agent, worktree, git add hoặc commit. Plan đã được duyệt và triển khai code/test offline. Không chạy API, nạp lại dữ liệu hoặc thay dịch vụ đang chạy; xem báo cáo kết quả cùng thư mục.

**Goal:** Chuyển knowledge từ BGE-M3 local CUDA sang Cloudflare dense + BM25 CPU, giữ hợp đồng evidence, nghiệp vụ BTC và khả năng triển khai qua Docker Compose.

**Architecture:** Cloudflare tạo dense; ứng dụng tính BM25 document/query trên CPU theo artifact bất biến của release. Qdrant lưu named vectors `dense`/`sparse`, dùng IDF một lần và RRF; PostgreSQL tiếp tục giữ nguồn, manifest và active pointer có thẩm quyền. Ingestion và serving dùng chung cấu hình/adapter.

**Tech Stack:** Python 3.12, Pydantic, httpx sẵn có, tokenizer CPU, qdrant-client, PostgreSQL, pytest và HTTP mock/Qdrant trong bộ nhớ.

**Spec:** [MCP Knowledge/RAG, cập nhật 04/11/2026](../specs/2026-11-03-mcp-knowledge-rag-design.md).

## Tóm tắt thực hiện

1. Đổi cấu hình/fingerprint sang Cloudflare và BM25, giữ secrets ngoài manifest.
2. Viết HTTP adapter có deadline, retry hữu hạn và phân loại lỗi quota.
3. Tạo BM25 artifact theo release và tích hợp sparse IDF/RRF vào Qdrant.
4. Cập nhật publisher, activation, loader và verifier; tách readiness khỏi đánh giá chất lượng.
5. Tích hợp search, log và thông báo khách khi provider lỗi.
6. Chuyển Docker sang CPU, cập nhật README và chạy kiểm thử offline phù hợp.

## Global Constraints

- Đường dẫn tính từ gốc repository. Chỉ sửa phần cần cho kiến trúc mới; giữ cấu trúc MCP hiện có, không refactor module không liên quan.
- Không chạy eval, Recall@k, LLM judge, benchmark, live model, smoke API, Docker build/up hoặc ingest/activate dữ liệu thật trong phạm vi code/test. Không đọc đáp án QA để tạo vocabulary, aliases hoặc luật search.
- Không cài/tải dependency, tokenizer hoặc model khi chưa được phép. Viết dependency/build recipe được phép; bước tải asset cần được chỉ rõ và duyệt trước thực thi.
- Test dùng cấu hình giả, mock HTTP, repo giả và Qdrant `:memory:`; không lấy credentials/DSN từ `.env` thật. SQL integration chỉ chạy khi có DB test được chỉ định rõ.
- Không xóa collection, reset DB, dọn Docker data, chuyển phân vùng hoặc push image.
- Không thay chunking, metadata registry, quyền, ngày hiệu lực, required links, quy tắc trả lời có điều kiện hoặc quy trình handoff BTC đã duyệt.
- Không thêm provider fallback hoặc BM25-only khi Cloudflare lỗi. Quota lỗi trả `unavailable`, `evidence=[]`; log phải ghi `quota_exhausted` khi có căn cứ từ provider.
- Không ghi secrets trong runtime JSON/manifest/payload/log; không sao chép nội dung bổ sung từ khách vào payload Qdrant hoặc log. Artifact lexical là dữ liệu nội bộ, không xuất cho agent.
- Giữ `relevance_verified=false` khi chưa đánh giá; tách tính toàn vẹn/readiness khỏi cờ này ở tất cả nơi kiểm tra, không tự đổi thành true.
- Mỗi task chạy test tập trung. Chỉ chạy full suite offline một lần cuối nếu cần theo AGENTS.md; không lặp kiểm tra đã đạt nếu không có thay đổi liên quan.

## Review Focus

1. HTTP 429 chưa chứng minh hết quota: test quota có mã rõ, rate limit có Retry-After và lỗi chưa rõ riêng biệt ở task 2/5.
2. Tokenizer khác nhau do Unicode/mã/SKU hoặc đảo thứ tự corpus: test NFC, giữ dấu, mã ghép và vocabulary ổn định ở task 3.
3. Ready giả hoặc buộc eval để startup: test ready với chất lượng chưa đánh giá, nhưng từ chối index/artifact lỗi ở task 4/5.
4. Nạp dở/chạy lại/thu hồi trong lúc nạp: test không đổi active, không tái dùng artifact sai và không vượt revocation ở task 4.
5. Compose lấy nhầm `.env` hoặc vẫn kéo CUDA: kiểm tra cấu hình/env_file, image recipe và test không cần GPU ở task 6.

## Ranh giới file và giao diện

- `mcp_knowledge/schemas.py`, `config.py` và `app/configs.py`: runtime công khai, credentials và fingerprint.
- `mcp_knowledge/services/cloudflare.py` (mới): duy nhất HTTP adapter + lỗi provider an toàn.
- `mcp_knowledge/services/embedding.py`: giữ facade `PolicyEncoder`, kiểm tra token/độ dài, queue và dense normalization; bỏ `FlagBackend`.
- `mcp_knowledge/services/bm25.py` (mới): tokenizer, vocabulary, thống kê corpus, encode query/document CPU; không truy cập DB/API.
- `mcp_knowledge/repos/qdrant.py`: sparse IDF, query fusion và xác minh vector/payload/artifact.
- `knowledge/services/publish.py`, `releases.py`, `dataloader_offline/knowledge.py`, `verification.py`: build/activation/preflight/đối chiếu release.
- `mcp_knowledge/services/knowledge.py`, `dependencies.py`, `server.py`: orchestration search, readiness, breaker và log.
- Agent giữ tool và schema evidence cũ; chỉ bổ sung phản hồi lỗi kỹ thuật tại ranh giới trả lời nếu thiếu.

### Task 1: Cấu hình Cloudflare/BM25 và fingerprint

**Files:** Modify `ai-services/app/configs.py`, `ai-services/app/mcp_servers/mcp_knowledge/{schemas.py,config.py}`, `config/policy-runtime.json`, `ai-services/test/test_policy_contracts.py`, `ai-services/test/test_configs.py`.

**Interfaces:** Giữ `PolicyRuntimeConfig.fingerprint() -> str`; thêm cấu hình provider/model/API contract/tokenizer/BM25. Settings có `cloudflare_account_id: str | None`, `cloudflare_api_token: SecretStr | None`. Credentials không thuộc `PolicyRuntimeConfig`.

- [x] Viết test fingerprint đổi khi provider/model/tokenizer/normalization/BM25 tokenizer/k1/b đổi; credentials không xuất hiện trong config dump và manifest. Giữ kiểm tra giới hạn evidence/candidate.
- [x] Test đọc hai biến Cloudflare theo precedence process environment > `.env`, dùng file giả; thiếu biến chỉ làm lỗi khởi tạo knowledge, không làm ba MCP khác thất bại.
- [x] Thay CUDA/model commit/dtype local bằng `provider=cloudflare`, `model_name=@cf/baai/bge-m3`, adapter version, tokenizer revision/path (dự kiến `5617a9f61b028005a4858fdac845db406aefb181`, chỉ là tokenizer kiểm độ dài, không phải cam kết revision phía Cloudflare), `dimension=1024`, `normalization=l2`, prefix rỗng. Tokenizer phải là asset đã có và có hash/revision, không tự tải.
- [x] Đề xuất giới hạn ban đầu: max input 4096 token **chỉ dùng nếu hợp đồng provider xác nhận hỗ trợ**, HTTP concurrency 1, batch ingestion 1, queue 4, deadline 60s, dependency timeout 10s, breaker 3 lỗi/cooldown 30s; giữ candidate 30/30, hard limit 20. Các số này là cấu hình vận hành, không phải kết quả đo.
- [x] Giữ `relevance_verified=false`; bỏ learned-sparse threshold cũ. Tạm không gán ngưỡng BM25 như chứng nhận đủ bằng chứng; kiểm tra tiêu chí có/không evidence hiện tại bằng test tổng hợp. Không tuyên bố cải thiện chất lượng hoặc tự đặt relevance thành true.
- [x] Chạy hai file test trên bằng runner offline ở cuối plan, xác nhận lỗi trước sửa và đạt sau sửa. Chưa tạo bất kỳ release thật nào.

### Task 2: Cloudflare adapter và dense encoder bất đồng bộ

**Files:** Create `ai-services/app/mcp_servers/mcp_knowledge/services/cloudflare.py`; modify `services/embedding.py`, `services/dependencies.py`; create `ai-services/test/test_policy_cloudflare.py`; update `ai-services/test/test_policy_embedding.py`.

**Interfaces:** `CloudflareEmbeddingClient.embed(texts: list[str], *, deadline: float) -> list[list[float]]`; `PolicyProviderError` chứa reason/status/provider_code an toàn. `PolicyEncoder.encode(text: str, *, deadline: float) -> list[float]` chỉ tạo dense; facade mới không tạo sparse. `start()` chỉ kiểm tra config/tokenizer/client, không warmup/gọi mạng. HTTP client được inject để test bằng `httpx.MockTransport`.

- [x] Đối chiếu tài liệu REST embeddings hiện hành để cố định route/body/output fixture trong test; ưu tiên route synchronous `/accounts/{account_id}/ai/run/@cf/baai/bge-m3` với `text`. Nếu schema chính thức mâu thuẫn ví dụ, không đoán hoặc gọi API ngầm; xác minh bằng tài liệu/schema chính thức, ghi rõ phần cần smoke được phép trước phát hành. Không sử dụng schema rerank/query-contexts thay embeddings.
- [x] Viết test thành công ánh xạ đủ đầu vào, đúng thứ tự; thiếu/thừa vector, chiều sai, NaN/Inf/zero bị từ chối. Normalization L2 ở ứng dụng; fixture synthetic nhỏ không khẳng định chiều thật provider đã được kiểm tra.
- [x] Thêm lỗi `quota_exhausted`, `rate_limited`, `auth`, `config`, `network`, `invalid_response`, `provider_error`; dùng HTTP status + mã/message được allowlist, không giữ raw body hoặc exception chứa request Authorization.
- [x] Test quota/auth/input sai không retry; transient network/5xx retry tối đa một lần trong deadline; rate limit tôn trọng Retry-After nếu còn thời gian. HTTP 429 không rõ mã không được ghi là quota đã hết.
- [x] Chỉ một lớp sở hữu retry/breaker Cloudflare trong `PolicyDependencies`; adapter HTTP không có retry riêng. Giữ cách xử lý PostgreSQL/Qdrant, không nhân retry thành bốn request.
- [x] Test queue đầy, query quá dài, deadline đã hết không gửi HTTP; cancellation/timeout không rò semaphore và không cho tác vụ đang chạy vượt giới hạn. Không gọi HTTP trong `start()` hay healthcheck.
- [x] Tái sử dụng cơ chế PII có sẵn cho text gửi provider; kiểm tra không gửi email/số điện thoại khách, nhưng vẫn giữ mã SKU/ngày/số liệu cần thiết. Không thay global masking tool/scorer fields.
- [x] Chạy `test_policy_cloudflare.py` và `test_policy_embedding.py` offline. Loại các test khẳng định ba warmup/GPU vốn không còn thuộc kiến trúc; thay bằng assertions hành vi mới.

### Task 3: BM25 artifact và Qdrant RRF

**Files:** Create `ai-services/app/mcp_servers/mcp_knowledge/services/bm25.py`, `ai-services/test/test_policy_bm25.py`; modify `ai-services/app/mcp_servers/mcp_knowledge/repos/qdrant.py`, `ai-services/test/test_policy_storage.py`.

**Interfaces:** `build_bm25_artifact(texts: list[str], config) -> dict`; `BM25Encoder(artifact)` có `encode_document(text) -> tuple[list[int], list[float]]`, `encode_query(text) -> tuple[list[int], list[float]]`. Artifact gồm tokenizer version, vocabulary, số document, avgdl, k1/b và hash. Giữ `HybridVector` làm DTO ghép dense/sparse ở caller; `HybridPolicyIndex.query()` giữ chữ ký hiện có.

- [x] Test NFC/NFD của `bảo hành` cùng token, giữ dấu khác với `bao hanh`, casefold; mã `DT-OLD-03`, SKU và số liệu có hành vi cố định. Dùng pattern Unicode chữ/số, giữ nhóm nối bằng `-`, `.`, `/`; không stemming/stopwords/segmentation model.
- [x] Vocabulary đánh số theo danh sách term sắp xếp ổn định, corpus được chuẩn hóa thứ tự theo chunk ID; đảo input không đổi artifact/hash. Query OOV trả sparse rỗng, không sửa vocabulary; corpus rỗng/avgdl không hợp lệ bị từ chối.
- [x] Dùng `k1=1.2`, `b=0.75`; kiểm công thức document trong spec bằng fixture có tf/dl/avgdl biết trước; query term phân biệt trọng số 1. Không nhân IDF ở CPU.
- [x] Collection mới một shard; `sparse.modifier=IDF`, dense COSINE. Kiểm version/schema hỗ trợ trước upsert. `verify()` kiểm modifier/shard, artifact hash, vector document mong đợi, ID/payload/hash; không chấp nhận sparse chỉ vì có cùng số phần tử.
- [x] Test Qdrant trong bộ nhớ với corpus tổng hợp: IDF chỉ áp dụng một lần, hai prefetch cùng release/quyền/fingerprint, RRF và mapping IDs ổn định; OOV bỏ prefetch sparse nhưng dense vẫn hoạt động. Lỗi artifact phải fail closed.
- [x] Chạy `test_policy_bm25.py` và `test_policy_storage.py`. Không search bộ QA BTC để chọn tokenizer/threshold, không truy cập Qdrant thật.

### Task 4: Build/activate/verify release thống nhất

**Files:** Modify `ai-services/app/knowledge/services/{publish.py,releases.py}`, `ai-services/app/mcp_servers/mcp_knowledge/services/knowledge.py`, `dataloader_offline/{knowledge.py,verification.py}`; update `ai-services/test/{test_policy_publish.py,test_policy_cli.py,test_dataloader_postgres.py,test_ingestion_verification.py,test_policy_search.py}`.

**Interfaces:** Giữ CLI và `build_policy_release(...)`, `activate_release(...)`, `verify_ingestion(...)`. Manifest schema mới có `pipeline=cloudflare_dense_bm25`, dense fingerprint, artifact BM25/hash, snapshot/config hashes, checks integrity và quality riêng. Artifact ở manifest PostgreSQL, không thêm bảng/migration nếu JSON hiện tại đã đáp ứng; chỉ hash lexical nằm trong payload Qdrant.

- [x] Test build từ parser/safe chunks + aliases được duyệt: tạo snapshot hoàn chỉnh rồi artifact BM25; từng chunk nhận dense từ task 2 và sparse từ task 3, ghép thành `HybridVector` trước upsert. Không gửi restricted thô/PII hoặc QA answers ra API.
- [x] Lưu model/provider/adapter/tokenizer/normalization và lexical artifact trong manifest có hash; không giả model commit/dtype Cloudflare. Runtime fingerprint + lexical hash chứng minh cùng pipeline; vocabulary không xuất ở MCP/eval tool hoặc payload phục vụ khách.
- [x] Tăng manifest schema để từ chối release local cũ rõ ràng. Đổi provider/lexical tạo release/collection mới, giữ active cũ nguyên vẹn; rollback chỉ nhận release tương thích runtime. Không triển khai lại encoder CUDA làm fallback.
- [x] Đổi preflight `_validate_local_runtime` thành kiểm tra provider config/credentials/tokenizer CPU đã có; giữ kiểm DB identity/schema/grants, source fingerprint, CAS/revocation và Qdrant. Không cần Torch/CUDA/cache weights; preflight không gọi model.
- [x] Integrity pass cho phép release `ready` dù `checks.relevance_verified=false`; activation và search kiểm index/artifact/snapshot/quyền/compatibility, không đòi eval. Verifier báo riêng `ingestion_status`, `serving_ready`, `relevance_verified`; ready không đồng nghĩa đã kiểm provider sống hoặc đạt điểm BTC.
- [x] Test quota giữa build không đánh dấu ready/đổi active; chạy lại release hoàn chỉnh phải verify mà không gọi embed. Có thể rebuild release dở theo batch, không hứa resume từng chunk; chỉ tái dùng dữ liệu khi toàn bộ hash/fingerprint được kiểm tra.
- [x] Test source/metadata/approval thay đổi và revocation/erasure trong lúc build vẫn chặn activation. Vocabulary có thể chứa từ từ supplement: giữ trong phạm vi dữ liệu nội bộ và áp dụng quy trình thu hồi/xóa hiện có, không tạo bản sao token khách còn phục vụ sau erasure.
- [x] Giữ đầy đủ payload inspection, `effective_until` kể cả null, title/lời dẫn/bảng và các trường hợp đơn lịch sử. Verifier so sánh artifact và sparse mới mà không encode lại hoặc gọi API.
- [x] Chạy các test được sửa trong task; cập nhật fixture dùng chung tại `test_policy_embedding.py` và caller theo dense-only interface, không xóa assertions nghiệp vụ hiện có để làm test qua.

### Task 5: Search, log quota và phản hồi giao diện

**Files:** Modify `ai-services/app/mcp_servers/mcp_knowledge/{server.py,services/knowledge.py}`; modify `ai-services/app/agent/harness/agent_nodes.py` nếu cần để bảo đảm thông báo; update `ai-services/test/{test_policy_search.py,test_policy_integration.py,test_policy_agent_evidence.py,test_mcp_knowledge.py}`.

**Interfaces:** `PolicySearchService.search(request, context) -> PolicySearchResult` và `policy.search` giữ nguyên schema. Search ghim release trước khi lấy artifact, dense và lexical query; không dùng artifact release trước còn trong bộ nhớ cho release sau. Consumer chỉ nhận lỗi chung `knowledge_unavailable`/`knowledge_timeout`, không provider detail.

- [x] Test release A/B đổi vocabulary khác nhau không trộn query vectors. Readiness xác minh artifact/index/DB mà không gọi API; cờ relevance false không cản phục vụ index hợp lệ, artifact/hash sai vẫn bị từ chối.
- [x] Nối dense encoder, BM25 query và index; không thực hiện search BM25-only khi HTTP lỗi. Giữ source verification, required links, ngày đã xác minh/ngày khách khai, top_k/hard limit và recheck revocation hiện có.
- [x] Dùng caplog xác nhận quota có `reason=quota_exhausted`, provider/model, HTTP status, provider code an toàn, request/release ID; không token/query PII/raw response. Với breaker mở do quota, giữ nguyên nguyên nhân quota cho request bị chặn, thay vì chỉ log tên exception chung.
- [x] Test quota trả `unavailable` + evidence rỗng, không retry, không gọi Qdrant lexical; rate limit khác quota. Timeout và overloaded giữ trạng thái tương ứng; Knowledge Gap Loop vẫn nhận `mcp_unavailable`, không tạo gap thiếu tri thức.
- [x] Giao diện/agent trả “Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.” khi không trả lời được do lỗi này; không lộ quota/credentials, không tạo handoff/callback mới. Bảo vệ tại ranh giới phản hồi hiện có bằng test agent stub, không thêm lượt LLM hoặc sửa frontend chỉ để map lỗi.
- [x] Với câu nhiều ý, phần độc lập đã có bằng chứng hợp lệ vẫn tuân mục 8.1 của spec; không ghi đè toàn bộ câu trả lời/tool nghiệp vụ khác vì một tool lỗi. Thêm test mixed tools để giữ phần có căn cứ và báo phần policy chưa tra được.
- [x] Chạy bốn file test của task offline; giữ test MCP → agent → guardrail → Knowledge Gap Loop, không đổi eval adapter/scorer nếu schema vẫn tương thích.

### Task 6: Docker CPU, hướng dẫn và xác minh cuối

**Files:** Modify `ai-services/Dockerfile.knowledge`, `ai-services/requirements-knowledge.txt`, `docker-compose.yml`, `ai-services/.env.example`, `README.md`, `ai-services/README.md`, `dataloader_offline/README.md`, `ai-services/app/knowledge/README.md`, `ai-services/test/test_mcp_compose.py`.

- [x] Đổi knowledge base thành Python 3.12 slim; bỏ Torch/torchvision/FlagEmbedding/CUDA và mount cache weights/GPU reservation. Giữ httpx hiện có; khai báo tokenizer CPU trực tiếp, pin revision/hash asset; không kéo transformers/Torch chỉ để đếm token.
- [x] Dùng asset `ai-services/app/mcp_servers/mcp_knowledge/assets/bge-m3-tokenizer.json` (trong image `/service/app/mcp_servers/mcp_knowledge/assets/bge-m3-tokenizer.json`), kiểm hash khi nạp; viết quy trình chuẩn bị asset rõ ràng. Build recipe có thể lấy asset nhỏ đã pin khi build được cho phép; runtime không tải asset. Không chạy Docker build trong đợt test này.
- [x] Truyền đúng hai biến credentials bằng explicit `environment` của `mcp-knowledge`: `CLOUDFLARE_API_TOKEN: ${CLOUDFLARE_API_TOKEN:?Set Cloudflare token}` và tương tự cho account ID. README dùng `docker compose --env-file .env --env-file ai-services/.env up --build -d` từ root; file thứ hai có precedence cao hơn, xác minh không override ngoài ý muốn các biến DB/port. Không thêm service `env_file` chứa toàn bộ secrets. Host loader tiếp tục đọc `ai-services/.env` qua Settings; không sửa file secrets thật trong task.
- [x] Giữ các biến DB và cấu hình của ba MCP còn lại; test Compose với env giả kiểm hai biến đến đúng service, runtime mount fail-fast, không GPU/weights, đủ bốn server. Không chạy `docker compose config` với env thật vì có thể in token.
- [x] README ghi đúng lệnh cấu hình, prepare/verify/activate/start và expected states; nêu rõ những lệnh nào cần API quota, Internet hoặc quyền ghi. Không dùng `/path/to/...` như lệnh chạy sẵn; dùng runtime config thực tế, actor lấy từ cấu hình quyền đã cấp và release ID từ output.
- [x] Hướng dẫn chuyển đổi giữ index cũ; prepared/ready/active là các trạng thái khác nhau. Smoke API, nạp thật và kích hoạt là bước vận hành riêng sau duyệt, không đánh dấu đã hoàn thành khi chỉ unit test.
- [x] Chạy test Compose offline; sau các test tập trung đạt, chạy full suite offline tối đa một lần theo AGENTS.md, loại live integration bằng cấu hình test hiện có. Không chạy command eval dù nằm cạnh unit tests.
- [x] Rà diff cuối: chỉ scope cần thiết, không secrets, không sửa QA BTC, không cờ quality giả; báo chính xác test pass/skip và bước vận hành chưa chạy. Dừng để người dùng review code trước mọi thao tác thật.

## Cách chạy kiểm thử offline

Từ `ai-services/`, tái dùng runner cô lập đã có tại `.superpowers/sdd/2026-11-03-ingestion-verification/run_offline_tests.py`. Khi triển khai, mở rộng danh sách biến cần loại bỏ để bao gồm Cloudflare, bật chặn HTTP ngoài mock và tắt tracing/prompt từ xa; chỉ dùng fake credentials. Không in `.env` để debug.

Ví dụ test tập trung (đường dẫn file mới chỉ có sau khi triển khai task):

```bash
.venv/bin/python ../.superpowers/sdd/2026-11-03-ingestion-verification/run_offline_tests.py test/test_policy_cloudflare.py test/test_policy_embedding.py
```

Full suite offline cuối, chỉ sau khi xác nhận collection không gọi live model/network:

```bash
.venv/bin/python ../.superpowers/sdd/2026-11-03-ingestion-verification/run_offline_tests.py test eval_harness/test_eval_harness.py
```

Nếu thiếu dependency hoặc DB test, ghi `not_verified` và nguyên nhân; không cài thêm, dùng DB thật hoặc chạy model để thay thế mà chưa được phép. Một test Qdrant in-memory không chứng minh Docker/server thật đã hoạt động; báo giới hạn này rõ ràng.

## Các regression test phải có tên và kết quả rõ ràng

| Task | Test tối thiểu | Assertion chính |
|---|---|---|
| 1 | `test_cloudflare_credentials_not_in_runtime_fingerprint` | Config không chứa token; đổi token không làm đổi fingerprint |
| 2 | `test_quota_exhausted_is_not_retried` | Một HTTP call; reason là `quota_exhausted` |
| 2 | `test_unknown_429_is_not_reported_as_quota` | Không log/kết luận hết quota từ status đơn lẻ |
| 2 | `test_encoder_start_has_no_network_calls` | `start()` không tiêu quota |
| 3 | `test_bm25_unicode_ids_and_artifact_order_are_stable` | NFC/NFD và thứ tự corpus không thay mapping/hash |
| 3 | `test_bm25_document_weights_and_idf_applied_once` | Điểm reference khớp công thức, không nhân IDF hai lần |
| 4 | `test_integrity_ready_does_not_claim_relevance_verified` | Integrity đạt, relevance false, cho activate hợp lệ |
| 4 | `test_quota_during_build_preserves_active_release` | Không ready, active giữ nguyên |
| 4 | `test_cached_release_verification_does_not_embed` | Release hoàn chỉnh chạy lại không gọi API |
| 5 | `test_quota_logs_reason_but_returns_generic_unavailable` | caplog có reason; evidence rỗng, không Qdrant search |
| 5 | `test_mixed_tool_failure_preserves_supported_answer` | Giữ phần có căn cứ; policy lỗi nhận thông báo chung |
| 6 | `test_knowledge_compose_cpu_and_explicit_cloudflare_env` | Không GPU/weights; đúng hai biến Cloudflare tại service |

Đây là test chức năng với fixture tổng hợp và mock, không phải bộ eval BTC.

## Tiêu chí hoàn thành phạm vi code/test

- Cùng config/release tạo được dense/BM25 qua mock API và truy hồi hybrid bằng Qdrant trong bộ nhớ.
- Log quota rõ, phản hồi khách chung, không fallback ngầm; không mất logic quyền/thời gian/liên kết/nguồn.
- Build/activation/verifier phân biệt integrity, readiness và quality chưa đánh giá; không còn bắt CUDA hoặc eval để phục vụ pipeline mới.
- Docker recipe CPU và README thống nhất; test chức năng đạt, không tuyên bố eval/API thật/deployment đã đạt khi chưa chạy.
- Không tự prepare/activate dữ liệu thật, sửa active pointer hoặc xóa index cũ. Plan này thay phần local CUDA của plan 03/11 cho các task chuyển kiến trúc; không mở lại các task nghiệp vụ đã hoàn thành.


## Kết quả triển khai

Hoàn tất phạm vi code và test offline ngày 04/11/2026. Xem
[báo cáo kết quả](2026-11-04-cloudflare-bm25-knowledge-results.md) để phân biệt
các kiểm tra đã đạt với API/Docker/ingestion thật chưa thực hiện.
