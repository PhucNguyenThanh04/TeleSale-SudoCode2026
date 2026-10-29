# Kế hoạch RAG và pipeline audio có thể debug

Ngày: 2026-10-29. Trạng thái: đang triển khai. Lát cắt RAG đầu tiên đã được nối vào `policy.search` dưới cờ `POLICY_RAG_ENABLED`; D0, R2–R5 đầy đủ và pipeline audio chưa hoàn tất. Baseline: [rag-baseline-20261029.md](rag-baseline-20261029.md).

## 1. Kết quả cần bàn giao

1. RAG chính sách/FAQ chạy trong `mcp-catalog`, có nguồn dẫn, kiểm ngày hiệu lực và quyền truy cập; đo được so với tìm từ khóa hiện tại.
2. Một lượt audio vào → text → cùng harness đang có → câu trả lời đã kiểm → TTS → phát audio, giữ được memory qua các phiên.
3. Từ một `trace_id`, xem được từng component đã nhận gì, trả gì, mất bao lâu, vì sao chọn/chặn/fallback; chạy lại riêng một component bằng input đã lưu có kiểm soát.
4. Sau khi luồng theo lượt ổn định, mở rộng streaming và ngắt lời. Không đánh đồng bản audio theo lượt với voice realtime đạt TTFA của M2.

Thứ tự: **hợp đồng debug → RAG trên text → audio theo lượt → streaming/ngắt lời**. Debug là tiêu chí nghiệm thu của mỗi bước, không để đến cuối.

## 2. Những gì tái sử dụng

| Phần | Nền hiện tại | Việc cần thêm |
|---|---|---|
| Policy | `mcp_catalog/services/catalog.py::search_policy`, lọc public/ngày trong repository | Hybrid retrieval, rerank, evidence contract và fallback có kiểm soát |
| Nạp tri thức | `dataloader_offline/source.py`, `postgres.py`, `vector.py` | Snapshot được publish, kiểm đồng bộ, loại dữ liệu thu hồi, index chỉ có nội dung public |
| Harness | LangGraph `accept → retrieve_context → run_agent → verify → persist` | Evidence/citation xuyên các node, audio delivery state, trace context |
| Tracing | `harness/observability.py`, `harness/tracing.py`, `mcp_shared/observability.py` | Correlation xuyên backend/speech/AI/MCP; artifact refs; replay; redaction thống nhất |
| ASR | `speech/asr.py`, `audio.py`, `normalize.py`, `replay.py` | Adapter phục vụ lượt audio, model nạp một lần, job lifecycle, metadata tin cậy |
| TTS | `speech/tts.py` hiện chủ yếu sinh dataset | Adapter runtime bất đồng bộ, text đã xác minh, event phát âm thanh, cancellation |
| Backend/UI | Backend đã có chat/session/auth; UI chưa triển khai | API audio, player, timeline debug có xác thực, trạng thái từng bước |
| Eval | `eval/run_eval.py`, `score_pair.py`, trace audit và speech evaluation | Runner RAG, test tích hợp audio, lỗi giả lập, số đo xuyên suốt |

Đường dẫn phía AI dưới `ai-services/app/`; backend dưới `backend/app/`. Các đường dẫn module mới bên dưới là đề xuất.

Giới hạn cần xử lý ngay: log harness hiện không ghi correlation từ tham số `_turn`; `langfuse_capture_content` dùng `debug_mask()` chỉ lọc credential và có thể xuất request/payload chưa che PII. Không dùng bật cờ này làm lời giải cho yêu cầu debug.

## 3. Hợp đồng debug chung — bước D0

### 3.1. Correlation và event

Mỗi lượt có `trace_id`; mỗi component có `span_id` và `parent_span_id`. Giữ `session_id`, `turn_id/client_msg_id`, `attempt`, `component`, `operation`, `status`, `duration_ms`, `error_code`, `input_ref`, `output_ref`, `config_version` và `code_revision`.

- Trạng thái kết thúc: `ok`, `error`, `timeout`, `cancelled`, `skipped`, `degraded`. Retry là attempt riêng, không đè lỗi lần trước.
- `on` là ngày nghiệp vụ từ request. Timestamp vận hành dùng thời gian thực; duration dùng đồng hồ đơn điệu. Không dùng timestamp log để tính chính sách/giá/ngày giao.
- Correlation sinh/kiểm tại backend, truyền qua HTTP và cơ chế metadata/context được SDK MCP hỗ trợ. Xác minh khả năng SDK trước khi chốt cách truyền; không tự thêm trường trace bắt buộc vào tham số tool BTC.
- Span định danh/SQL chỉ ghi ref, operation name và số lượng; không ghi DSN, token, SQL có giá trị PII hay đường dẫn file chứa tên khách.
- Hash nội dung không thay thế kiểm soát truy cập. ID/ref cần opaque; không lấy hash số điện thoại làm định danh công khai.

### 3.2. Lưu dữ liệu để điều tra

- Luôn có log JSON có cấu trúc cục bộ với metadata đã lọc; Langfuse là exporter tùy chọn, không phải điều kiện để debug được.
- Payload mặc định là bản đã che và giới hạn kích thước. Audio/raw transcript/prompt snapshot cần thiết chỉ lưu ở kho artifact nội bộ có quyền đọc, retention cấu hình và audit truy cập; trace giữ ref.
- Debug với dữ liệu synthetic được phép giữ chi tiết hơn, nhưng vẫn không ghi credential. Dữ liệu khách thực không tự được phép lưu/xuất chỉ vì bật debug.
- Nội dung public truy hồi được có thể lưu theo `chunk_id + source_hash + corpus_version`. Thông tin private và danh tính không vào index RAG.
- Endpoint debug kiểm operator và quyền phiên. Không cung cấp API đọc file tùy ý qua `input_ref` hoặc URL người dùng nhập.
- Lỗi exporter không làm hỏng hội thoại; tuy nhiên lượt có mất trace phải báo `observability_degraded`, không báo debug coverage hoàn chỉnh.

### 3.3. Replay và giao diện

Xem trace theo cây span và waterfall; nhấp mỗi bước để xem input/output đã che, artifact được phép đọc, config, lý do, diff và thời gian. Có bộ lọc theo session/lượt/component/error.

Replay mặc định dùng artifact/snapshot và mock kết quả của tool ghi. Replay RAG chỉ truy hồi; replay TTS chỉ sinh lại audio từ câu trả lời đã kiểm. Không chạy lại `order.create`, `order.update`, callback, handoff hoặc memory write trên DB đang phục vụ khách. Chế độ tích hợp dùng DB thử nghiệm cô lập, operation key và seed riêng.

Replay model có thể khác output cũ: giữ seed nếu nhà cung cấp hỗ trợ, phiên bản/config và phân biệt replay output ghi sẵn với chạy inference mới; không hứa bit-for-bit với LLM.

Nghiệm thu D0: một lượt mock đi qua backend → AI → ba MCP có trace liên kết, lỗi/timeout có span kết thúc, payload không lộ PII/secret, replay không gây side effect thật.

## 4. Giai đoạn A — xây RAG trước

### R1. Chốt corpus, quyền, phiên bản và baseline

- Giữ PostgreSQL là nguồn chuẩn; Qdrant là index dẫn tới nguồn. Chưa mở rộng RAG sang giá/tồn kho/CRM.
- Giữ chunk ID BTC để đối chiếu QA. Giữ cấu trúc bảng, tiêu đề và liên hệ tài liệu; không cắt mất điều kiện/ngoại lệ. Nếu cần chia nhỏ, ánh xạ về chunk BTC gốc.
- Manifest chứa phiên bản corpus, source hash, model/revision embedding, kích thước vector, cấu hình chuẩn hóa/chunking và ngày hiệu lực/quyền.
- Chỉ nội dung public vào index public; không index nguyên văn tài liệu nội bộ hoặc placeholder nội bộ như bằng chứng trả lời khách. Giữ dữ liệu nguồn BTC nguyên bản.
- Chạy baseline `policy.search` hiện tại trên QA để biết lỗi lexical: bỏ sót, chọn bản cũ, trả sai chính sách, từ chối sai. Tách dev và held-out; ghi rõ các mẫu công khai đã dùng để phát triển.

Debug ingestion: số tài liệu/chunk trước-sau, chunk bị loại và lý do, hash, version, embedding failures. Debug baseline: query đã che, ngày áp dụng, candidates và điểm.

### R2. Index có phiên bản và retrieval kết hợp

Luồng nạp: nguồn → kiểm định → public/version metadata → PostgreSQL snapshot → embedding local → Qdrant staging → kiểm đủ ID/hash → publish snapshot nhất quán.

- Giữ bản index trước để quay lui; loại chunk bị xóa/thu hồi; từ chối query với metadata/index không tương thích. Một lượt dùng cùng `corpus_version`, không trộn hai lần publish.
- Tái sử dụng model embedding đang cấu hình để làm mốc đầu tiên. Chọn model thay thế chỉ sau khi đo chất lượng và tài nguyên; không khóa tên model mới trong kế hoạch.
- Thêm lớp lexical rõ ràng trong PostgreSQL, embedding cho query và truy hồi dense từ Qdrant; ghép kết quả bằng phương pháp fusion được cấu hình. Ghi riêng điểm từng nhánh; không coi similarity là xác suất đúng.
- Áp bộ lọc quyền/ngày trước khi nội dung vào reranker/model; dùng cùng điều kiện cho lexical và dense. Tải lại và kiểm hash/quyền/hiệu lực từ PostgreSQL sau retrieval.
- Giữ điều kiện sản phẩm, thời gian và ngữ cảnh của khách khi chuẩn hóa query. Không tự bỏ điều kiện để tăng số kết quả.
- Giới hạn thời gian, số candidates và token evidence; lựa chọn top-k/fusion trên dev rồi khóa cấu hình khi đo.

Nghiệm thu R2: index reload tái lập được, không rò nội bộ, không trộn version, một query có candidate lists và lý do loại đủ để debug; test PostgreSQL + Qdrant thật trên dữ liệu cô lập.

### R3. Rerank, bằng chứng và hành vi khi thiếu nguồn

Luồng runtime:

`policy.search → chuẩn hóa query → quyền/ngày → lexical + dense → fusion/dedup → rerank → revalidate PostgreSQL → evidence`

- Giữ tool MCP hiện tại `policy.search(query, on, order_date?)`. `order_id` là tham số ở lớp harness: harness tra `order.status` và xác minh quyền rồi mới chuyển ngày đơn đã xác minh xuống MCP; model không tự quyết `order_date`.
- Nếu câu hỏi cần ngày đơn mà chưa có nguồn xác minh, hỏi thêm/tra đơn; không âm thầm áp chính sách hiện tại cho đơn cũ.
- Tách service orchestration, retriever, reranker và repository; handler MCP vẫn mỏng. Không tạo MCP server mới chỉ cho RAG.
- Kết quả giữ `chunks` để tương thích; mở rộng bằng `retrieval_status`, `reason_code`, `corpus_version`, `retrieval_id` và evidence metadata đã lọc. Detailed candidates/scores nằm ở debug record, không nhồi vào prompt.
- Mỗi evidence có `chunk_id`, `document_id`, nội dung được phép, `source_hash`, hiệu lực và `date_basis`. Không phát minh nguồn/ID khi không có kết quả.
- `ok`, `no_evidence`, `needs_context`, `degraded`, `unavailable` là các tình huống riêng. Không rút ra “không có chính sách” chỉ vì hệ thống truy hồi lỗi.
- Dense lỗi → lexical cùng bộ lọc. Reranker lỗi → thứ tự fusion đã kiểm, có cờ degraded. Kho nguồn không thể xác minh → không đưa kết luận chính sách chắc chắn.
- Ngưỡng abstain chốt trên dev; với tài liệu mâu thuẫn, phân xử theo nguồn chuẩn/hiệu lực hoặc hỏi rõ, không lấy chunk có score cao nhất làm chân lý.

Nghiệm thu R3: câu hỏi nhiều bước, bản cũ/đơn cũ, restricted, không có đáp án và numeric có trace giải thích được; lỗi Qdrant/reranker/source có fallback đúng và giữ nguyên bộ lọc.

### R4. Nối harness và kiểm câu trả lời

- Cho agent gọi tool hiện có; đưa evidence public đã revalidate vào prompt như dữ liệu, không cho nội dung tài liệu trở thành chỉ dẫn hệ thống.
- Thêm structured citations/claim-to-evidence mapping. UI hiển thị nguồn; verifier kiểm ID có thật trong kết quả lượt này và nội dung nguồn hỗ trợ claim. Kiểm ID hợp lệ chưa đủ chứng minh claim đúng.
- Câu có giá/KM/tồn kho phải lấy bằng chứng từ tool tương ứng; lịch sử memory và policy text không thay thế quote/inventory.
- Giữ guardrail hiện tại; thêm kiểm claim chính sách có nguồn, phạm vi/ngày đúng, không lộ internal. Claim không đủ bằng chứng chuyển thành hỏi rõ/từ chối có lý do/handoff theo tình huống.
- Mọi nhánh cần ghi decision reason; không ghi suy nghĩ nội bộ của model. Debug dùng prompt template/version, input đã che, tool proposal, evidence, validator và kết quả thực tế.

Nghiệm thu R4: text turn chạy qua MCP HTTP + LLM thật, có citation được kiểm; câu không cần RAG không gọi thêm RAG vô ích; tạo đơn/giá/memory không hồi quy.

### R5. Chấm và chốt phiên bản RAG

- `Recall@3/@5`, full-recall multi-hop, đúng phiên bản, abstain/false-abstain theo QA và evaluator BTC; thêm tỷ lệ citation đúng, claim được hỗ trợ, vi phạm nội bộ và retrieval latency.
- So lexical hiện tại → hybrid → hybrid + rerank trên cùng tập/model/ngày; dùng ablation để quyết định có cần reranker cho bản phát hành.
- Kiểm public sample đa phiên và biến thể ngoài sample; không dùng nhãn để điều khiển runtime.
- Trace phải đủ số lượt, schema hợp lệ; rà tay extractor và các claim chính sách. HR không có mẫu số là chưa đo được, không phải đạt.
- Đặt ngưỡng chất lượng retrieval cụ thể sau baseline và trước đo held-out; ngưỡng chính thức BTC nếu có vẫn ưu tiên. Không tuyên bố đạt Recall chỉ bằng unit test.

Đầu ra A: một phiên bản RAG có manifest, báo cáo so baseline, trace mẫu, hướng dẫn tái lập và lỗi còn lại. Chỉ sau đây mới nối audio vào pipeline đang ổn định.

## 5. Giai đoạn B — audio đầu vào đến đầu ra

### V1. Audio theo lượt, dùng cùng text harness

```text
Micro / file của người dùng
  → Backend xác thực, mở trace và phiên
  → Nhận audio, kiểm định dạng/kích thước, lưu audio_ref
  → Decode / resample / kiểm chất lượng
  → VAD xác định đoạn nói
  → ASR local
  → Chuẩn hóa text và số, kiểm tín hiệu không chắc chắn
  → Che PII / chuyển dữ liệu giao hàng vào kho được kiểm soát
  → Text turn: session_id + client_msg_id + identity tin cậy + on
  → CRM / memory / Call Brief
  → LangGraph + LLM ↔ MCP catalog/RAG, order, memory
  → Kiểm câu trả lời và ghi memory có bằng chứng
  → Chuẩn hóa lời đọc từ câu trả lời đã duyệt
  → TTS runtime
  → Backend chuyển audio + player nhận/phát
  → Ghi trạng thái đã phát / bị ngắt / lỗi phát
```

- Bản đầu dùng nhấn-nói/nhả-nút hoặc file từng lượt để có đầu-cuối rõ; không đợi streaming mới kiểm được audio end-to-end.
- VAD không phải diarization. Micro riêng của khách không cần phân người nói. File ghi cả agent/khách cần diarization/segmentation đúng; boundary nhãn của benchmark chỉ là oracle trong eval, không được coi là chức năng runtime.
- ASR chạy worker local, model nạp một lần; tách công việc CPU/GPU khỏi event loop FastAPI. Identity và ngày lấy từ session, không từ phỏng đoán ASR.
- Không có tiếng nói/ASR rỗng/nhiễu → nhắc khách nói lại hoặc nhập text; không bịa transcript, không dùng ground truth bù chữ, không gửi lượt rỗng vào harness.
- Giá/SĐT/ngày nghe không chắc → xác nhận có mục tiêu; điểm ASR là tín hiệu chẩn đoán, không coi là xác suất hiệu chuẩn. Không xác nhận lại tất cả slot đã chắc chắn.
- API audio trả turn/job ref và tiến độ có xác thực. Hợp đồng chính xác chốt ở task V1; giữ route text cũ và tránh cho frontend trực tiếp gọi MCP/speech worker.

### V2. TTS runtime và playback

- Tái sử dụng phần engine/chuẩn hóa phù hợp từ `speech`, nhưng không gọi nguyên pipeline sinh dataset ở mỗi lượt. Adapter runtime cần timeout, cancellation và cache có kiểm soát.
- Chọn một engine đã có adapter để đo đầu tiên; chốt local/API theo chất lượng, latency, tài nguyên và phạm vi dữ liệu được phép gửi. Không mặc định một dịch vụ TTS hiện có đáp ứng realtime.
- TTS chỉ nhận `verified_answer` cùng hash/revision. Chuyển số tiền, ngày, SKU sang lời đọc nhưng giữ nguyên nghĩa và con số; citation ID hiện trên UI, không bắt TTS đọc chuỗi ID.
- Nếu chuẩn hóa lời đọc làm thay đổi dữ kiện, chặn trước TTS. Các unit test kiểm nhiều cách diễn đạt/sản phẩm, không chỉ câu sample.
- Phân biệt `generated`, `verified`, `persisted`, `audio_ready`, `playback_started`, `played`, `interrupted`. “Model sinh câu” không đồng nghĩa “khách đã nghe”.
- Fact khách và tool thành công ghi theo sự thật đã xảy ra. Lời hứa/thông tin đã truyền đạt giữ delivery status; lần sau không khẳng định khách đã nghe toàn bộ đoạn bị ngắt.
- TTS/player lỗi → vẫn hiển thị text đã kiểm, retry riêng audio; không chạy lại harness hay tạo lại đơn. Client reconnect dùng turn/message ref để nhận lại kết quả.

Nghiệm thu V1–V2: một khách nói, nhận audio trả lời, gọi lại phiên mới và được tiếp nối đúng; tất cả span và artifact liên kết. Kiểm cả HTTP, ASR, MCP, PostgreSQL, LLM, TTS và playback thật; tách kết quả mock với đo thật.

### V3. Streaming và ngắt lời — sau bản theo lượt

- Thêm transport realtime phù hợp sau khi đo bản đầu; không buộc dùng WebRTC/tổng đài nếu demo WebSocket theo lượt đủ mục tiêu trước mắt.
- VAD end-of-speech chốt utterance; partial transcript chỉ để hiển thị. Chỉ final utterance mới được phép kích hoạt nghiệp vụ.
- Phát TTS theo câu/đoạn chỉ sau khi đoạn đó đã được verifier duyệt. Không phát draft LLM rồi mới phát hiện giá sai. Claim liên quan nhau cần kiểm như một nhóm trước khi phát.
- Ngắt lời: dừng player/TTS, hủy công việc model/retrieval chưa cần thiết, bỏ chunk thuộc generation cũ. Dùng `utterance_id/generation_id/sequence_no`, backpressure và hàng đợi giới hạn.
- Tool ghi đã commit không được coi là rollback khi khách ngắt. Chờ/đối soát kết quả, lưu chính xác, giải thích ở lượt sau; mọi retry giữ idempotency.
- Nếu nghe và phát đồng thời, xử lý echo để tiếng TTS không tự trở thành yêu cầu khách. Theo dõi queue wait, model warmup và tranh chấp GPU giữa ASR/TTS.
- Kiểm cancellation, race, reconnect và ≥2 phiên đồng thời trước tuyên bố M2 realtime.

## 6. Mỗi component phải debug được gì?

Mọi hàng dưới đây đều có input/output refs, thời gian, trạng thái, config/version và error code theo D0.

| Component/span | Chi tiết tối thiểu cần xem | Kiểm/replay độc lập |
|---|---|---|
| Capture/ingress | Utterance ID, codec, sample rate, số byte, checksum, client sequence | File synthetic ngắn/dài/sai codec; reconnect |
| Decode/resample | Sample rate trước/sau, duration, clipping/đoạn rỗng | Cùng audio_ref, so waveform/hash |
| VAD | Các mốc start/end, padding, đoạn bị bỏ và lý do | Nghe clip cạnh boundary, im lặng/nhiễu |
| ASR | Model/device thực dùng, raw segments có quyền, decode options, duration | Chạy riêng clip; giữ raw trước cleanup |
| Normalize | Text trước/sau đã che, rule ID, số/entity thay đổi | So diff, cặp diễn đạt/đối chứng |
| PII/identity | Loại dữ liệu bị che, identity status, lý do xác minh; không lộ giá trị | Mẫu synthetic và số chung; kiểm quyền |
| Memory/context | Fact được chọn/loại, TTL/source/supersede, token budget, brief refresh | Snapshot context, cùng on, không ghi DB thật |
| Query/filter | Query đã che, điều kiện ngày/quyền/SKU, context còn thiếu | Query khác cách diễn đạt; giữ điều kiện |
| Lexical/dense | Candidate ID, score riêng, version, thời gian từng nhánh | Tắt một nhánh; lỗi Qdrant |
| Fusion/rerank | Thứ tự trước/sau, model, item bị loại, reason | Cùng tập ứng viên snapshot |
| Source revalidation | Hash/version/ngày/quyền cuối, chunk bị thu hồi | Index cũ, nguồn bị xóa, chính sách cũ |
| LLM | Template/version, context refs, tool proposal, tokens, time, finish reason | Mock response hoặc inference mới có nhãn |
| Harness precondition | Tool dự định gọi, tham số đã lọc, quyết định allow/block | Thiếu stock/quote/owner; timeout |
| MCP/service/repo | RPC → validation → service → DB span, operation key, transaction outcome | Mock BTC; integration DB cô lập |
| Answer verifier | Claim, evidence IDs, rule, pass/block/fallback | Citation giả, sai số, sai policy date |
| Memory write | Fact accepted/rejected, source, supersede, write receipt | DB thử; retry không ghi lặp |
| Spoken-text formatter | Verified text/hash → spoken text; mapping số/ngày/SKU | Sai số bị chặn; đọc tự nhiên |
| TTS | Engine/voice thực, input hash, chunk sequence, time to first audio | Tổng hợp lại từ verified_answer |
| Playback | Client nhận/giải mã/phát/xong/ngắt, buffer underrun | Audio cùng ref; không gọi lại business |
| Ingestion/publish | IDs/hash, loại internal, index build/publish/rollback | Reimport idempotent, missing/stale chunks |
| Eval/export | Độ phủ lượt/span, schema, config/model/seed hash, lỗi exporter | So artifact với trace; mất trace phải hiện rõ |

Debug không yêu cầu đọc chain-of-thought. Cần quan sát quyết định, dữ liệu, quy tắc và side effect thực tế.

## 7. Latency và tiêu chí hoàn thành

- Tách queue wait, ASR, normalization, context/brief, retrieval từng nhánh, LLM/tool, verifier, persistence, TTS và playback. Không cộng duration các span chạy song song như tổng end-to-end; dùng critical path và timestamp boundary.
- M1 text theo BTC: Call Brief ≤5s, TTFT p95 ≤3s, total p95 ≤8s; ≥100 lượt, bỏ 3 warm-up. Với API chưa streaming, TTFT = total theo hướng dẫn BTC.
- ASR offline báo thời gian/phút audio riêng. Voice TTFA từ VAD end-of-speech đến audio đầu tiên thực phát; ghi thêm backend audio-ready và client playback-start riêng, không đồng nhất hai mốc. M2 mục tiêu p95 ≤2,5s, chưa cam kết khi chưa đo.
- Báo cold start riêng; benchmark full/baseline cùng hardware/model/config, cùng transcript và seed DB sạch. RAG ablation độc lập với memory baseline.
- Kiểm ít nhất: im lặng, noise, ASR sai số, query không đáp án, policy cũ, restricted, Qdrant timeout, model timeout, MCP lỗi, memory write lỗi, TTS lỗi, mất mạng, retry và ngắt lời lúc đơn đang commit.
- Kết quả cuối phải có báo cáo tách unit/mock, public sample, dữ liệu ngoài sample và hệ thống thật. Không lấy một trace/demo thành công làm bằng chứng tổng quát.

## 8. Chia việc thành các thay đổi có thể review

| Mốc | Phạm vi chính | Điều kiện chuyển bước |
|---|---|---|
| D0 | Trace contract, redaction, artifact refs, propagation, replay an toàn | Một lượt thấy được xuyên các service, không lộ dữ liệu |
| R1 | Corpus manifest và lexical baseline | Biết baseline, ngày/quyền/source rõ |
| R2 | Ingestion versioned + lexical/dense + fusion | Truy hồi có provenance, index nhất quán |
| R3 | Rerank + evidence contract + lỗi/fallback | Thiếu nguồn/lỗi/phiên bản xử lý đúng |
| R4 | Nối harness/verifier/citations | Câu trả lời text có bằng chứng; business không hồi quy |
| R5 | Eval RAG, public multisession, ablation | Báo cáo tái lập và cấu hình phát hành |
| V1 | Audio ingress + local ASR adapter + text turn | Audio vào đi qua cùng harness, trace đủ |
| V2 | Verified text → runtime TTS → player | Audio hai chiều theo lượt, retry không lặp nghiệp vụ |
| V3 | Streaming, ngắt lời, concurrency | Lỗi/race/cancellation và latency được kiểm thật |

Các task RAG tập trung ở `dataloader_offline/`, `ai-services/app/rag/`, catalog `services/` + `repos/`, harness `context/policy/state`, guardrails và `eval/`. Các task audio tập trung vào adapter runtime tái sử dụng `speech/`, backend API/schema/service, UI mới và hợp đồng playback. Không chuyển nghiệp vụ catalog/order sang backend.

Đầu việc triển khai đầu tiên được đề xuất: D0 và R1, sau đó một lát cắt R2–R4 nhỏ cho policy text có trace đầy đủ. Chưa triển khai voice realtime hoặc chọn thêm framework trước khi lát cắt này được kiểm.
