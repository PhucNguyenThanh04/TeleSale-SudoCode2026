# Đối chiếu yêu cầu BTC với checkout ngày 04/11/2026

**Kết luận:** nền tảng harness, memory, MCP và Knowledge Gap Loop đã có triển khai đáng kể. Chưa có đủ căn cứ xác nhận hoàn thành M1: dữ liệu/bộ test còn thiếu số lượng và liên kết đa phiên, timeline memory mới có một phần, chưa có bằng chứng hai vòng cải tiến trên bộ test cố định và chưa có phép đo hiện hành cho bản RAG Cloudflare. Có các khoảng trống chức năng cụ thể ở chặn nhận là người thật, trích outcome từ chối và tương thích đầu vào `seed_history`.

**Phạm vi:** đọc code và đối chiếu các yêu cầu có thể kiểm tra trong A–G, Phụ lục A–C của PDF 17 trang; đọc toàn bộ điều chỉnh BTC, giải đáp mentor, hướng dẫn latency, scenario/tool/brief/trace contracts và simulator spec. Đọc thêm speech, backend/frontend và dataloader ở các ranh giới mà yêu cầu BTC liên quan. Không thay source ứng dụng, không chạy live model, ASR inference, embedding API, benchmark, migration, reset hoặc restart dịch vụ. Không truy vấn lại DB/Qdrant đang vận hành trong lần này.

**Mốc code:** `0246882` (`add mcp knowledge`), checkout sạch lúc bắt đầu. PDF SHA256: `66f2c27c895c1ce16f11ba5c6103241bb5bd67d3873f216fc7ac284c330925e0`. Báo cáo này là tài liệu audit, không phải spec hay kế hoạch triển khai được duyệt.

**Nguồn yêu cầu:** [PDF gốc](../../../SUDO%20CODE%202026%20-%20Đề%20Bài%20Dự%20Án%20Cuối%20Kì.pdf), [điều chỉnh BTC](../../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md), [giải đáp mentor](../../../BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md), [latency](../../../BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md), [scenario](../../../BTC-Data-Vong1-TEAMS/schemas/scenario_format.md), [tools](../../../BTC-Data-Vong1-TEAMS/schemas/tools.schema.json), [simulator](../../../BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md). Điều chỉnh chính thức được dùng khi bổ sung/thay thế đề gốc; tài liệu tự đánh giá của team không thay rubric BTC.

**Cách đọc trạng thái:** “Có code” xác nhận implementation, không tự chứng nhận đạt chất lượng/thời gian BTC; “Một phần” nêu rõ phần thiếu; “Thiếu” dùng cho số lượng/hành vi có bằng chứng chưa đủ; “Chưa xác minh” nghĩa là chưa có bằng chứng hiện hành ở workspace; “Chưa tìm thấy” không kết luận thành viên khác chưa làm ở máy riêng; “Không áp dụng” dành cho nhánh lựa chọn không sử dụng. Các mã E01–E30 dẫn đến nguồn code ở cuối tài liệu.

**Những điều phải cập nhật so với đánh giá cũ**

- RAG hiện dùng **Cloudflare BGE-M3 dense + BM25 CPU + Qdrant RRF**. Không còn yêu cầu CUDA/GPU/FlagEmbedding của bản local trước đây. `relevance_verified=false` ghi chất lượng chưa đo, không còn chặn integrity readiness. [E08][E09]
- M1 cho phép không streaming và quy định **TTFT = Total** trong trường hợp này. Việc adapter gán hai trường bằng nhau không tự là sai quy cách; vẫn phải đáp ứng TTFT p95 ≤3s và Total p95 ≤8s, cùng quy tắc mẫu/warm-up. [E11]
- Sau điều chỉnh, `schedule.callback`, `handoff.transfer` và `order.update` cho persona đổi size thuộc phạm vi M1; `pricing.get_quote` được khuyến nghị M1/M2, `order.status` là M2. Không chỉ kiểm “có ba tool bất kỳ”. [E05]
- Hai bundle dataset thật đang có 22 audio; không tiếp tục kết luận “chưa có audio”. Tuy nhiên 22 audio không đồng nghĩa 22 scenario đa phiên. [E15]
- Có artifact ngày 02/11 ghi `validated`; không dùng audit 02/11 cũ để phủ nhận artifact xuất hiện sau thời điểm audit đó. Artifact này vẫn không đại diện cho source/RAG 04/11. [E12]

**Số đếm kiểm lại trực tiếp**

| Nguồn | Số lượng hiện có | Giới hạn diễn giải |
|---|---|---|
| `eval_harness/scenarios/*.json` | 7 scenario; 6 đa phiên; 3 có `hard_case`; 13 call; 39 customer turn | Đây là mặc định `run_official`, chưa đủ M1 |
| `eval_harness/benchmark_dataset.json` | 19 scenario; 18 đa phiên; 15 có `hard_case`; 38 call; 116 customer turn | Mặc định benchmark runner; vẫn thiếu 20 scenario đa phiên |
| Hai bundle trong `dataset/` | 22 hội thoại/22 WAV; 1.173,131 giây = 19 phút 33 giây | Đọc WAV header, không nghe QC và không chạy ASR |
| Nhãn đa phiên ở 22 dialogue GT | 0 dialogue có `customer_id`, `calls`, `channel`, `channel_identity`, `facts_established`, `must_carry_over`, `must_not_ask`, `success_if` ở cấp dialogue | Không dùng trực tiếp làm bộ test memory tương đương BTC |
| `speech/data/` | Không có tại checkout local | Các số ASR trong README chưa có run artifact tương ứng tại vị trí này |
| Bộ BTC `asr/` local | Không tìm thấy WAV | Chưa kiểm được phép đo đủ audio BTC; không kết luận BTC chưa phát ở nơi khác |
| Loader `--dry-run` trên nguồn BTC | 40 sản phẩm, 96 biến thể, 13 KM, 12 sự kiện tồn, 50 khách, 2 đơn, 3 phiên, 14 policy document/99 chunk, 93 chunk public/safe | Là kiểm file/parser, không phải xác minh lại DB hoặc chất lượng retrieval |
| Artifact cặp run có `run.json` | Hai run 01/11 và 02/11; mỗi run 39 dòng/cấu hình | Không có run hiện hành chứng minh Cloudflare/BM25 |
| Artifact `comparison.json` trong eval/dataset/speech-data | Chưa tìm thấy | Chưa có bằng chứng hai vòng Knowledge Gap tại các thư mục kiểm tra |

**A/B — bài toán và chức năng tổng quát**

| ID / yêu cầu BTC | Trạng thái | Đối chiếu code và điều còn phải chứng minh |
|---|---|---|
| A1: khách quay lại không bị coi là người lạ | Có code | CRM theo SĐT, memory theo customer, brief/opening; cần demo và RQR/CCR trên bộ đủ chuẩn. E01–E04 |
| A2: hợp nhất ngữ cảnh SĐT/Zalo/Facebook | Có code | Mapping ba loại định danh về customer, xử lý unknown/ambiguous; chưa có corpus ≥10 khách đa kênh được thống kê. E02/E04 |
| A2: giải quyết mâu thuẫn giữa nguồn/kênh | Một phần | Supersede và fact có nguồn; quote cũ tách quote hiện hành. Chưa có bằng chứng đủ ca ba kênh xung đột trên bản mới. E03/E04/E06 |
| A3: bàn giao AI/người hoặc qua ca có ngữ cảnh | Có code | HandoffBrief có summary, facts, câu hỏi mở, hành động tiếp; ticket mô phỏng đúng phạm vi BTC. E05 |
| A4: đánh giá và cải tiến theo cuộc gọi | Một phần | Có eval và thu signal/outcome/feedback; chưa có bằng chứng tự chấm chất lượng mọi cuộc gọi production và so sánh hai vòng. E07/E11/E13 |
| B1: voice/text tiếng Việt → ngữ cảnh truy vấn được | Một phần | ASR offline, normalize/entities, memory extraction và đọc theo customer; corpus và chất lượng thực tế chưa đủ chứng cứ. E03/E14/E15 |
| B2: continuity xuyên phiên, mở đầu tiếp nối | Có code | `load_context`, suggested opening, blocker còn mở và current/prior episodes. E01/E03 |
| B3: nhận thức → truy hồi → lập kế hoạch → tool → quan sát → nhớ | Có code | Outer graph và Deep/ReAct business-tool loop, verify/persist. E01/E05 |
| B4: chứng minh tốt hơn baseline không nhớ | Một phần | Có runner/audit/scorer và artifact lịch sử; bộ test M1 chưa đủ, không có run cho source hiện hành. E11/E12 |
| B5: cải tiến không train lại | Có code | Knowledge Gap Loop cập nhật FAQ/aliases/source, reviewer và versioned release; chưa chứng minh delta hai vòng. E07/E13 |

**C.1 — dữ liệu M1/M2**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C1-D01: ≥120 transcript | M1 | Chưa xác minh đủ | Chưa có manifest toàn corpus đủ 120 hội thoại unique; không cộng WAV, ZIP, template và GT của cùng hội thoại thành nhiều cuộc. E15 |
| C1-D02: ≥40 hội thoại audio | M1 | Thiếu trong bundle đã kiểm | Có 22 WAV. E15 |
| C1-D03: tổng audio ≥1 giờ | M1 | Thiếu trong bundle đã kiểm | 19 phút 33 giây; thiếu khoảng 40 phút 27 giây. E15 |
| C1-D04: ≥30 khách, mỗi khách ≥2 phiên | M1 | Chưa xác minh đủ | 50 khách CRM seed không chứng minh có 30 khách đa phiên trong corpus. E15/E16 |
| C1-D05: ≥10 khách có gọi + chat | M1 | Chưa xác minh đủ | Có identity đa kênh trong code; 22 GT chưa có liên kết channel/customer để thống kê. E02/E15 |
| C1-D06: ≥1 ngành hàng | M1 | Có nguồn | Catalog nhiều ngành; cần manifest chỉ rõ ngành của corpus team. E16 |
| C1-D07: ≥2 miền giọng | M1 | Chưa xác minh | Các nhãn Bắc/Nam ánh xạ cùng HoaiMy/NamMinh ở bundle; chưa nghe QC để chứng minh vùng. E15 |
| C1-D08: ≥30 SKU + chính sách giá/KM/đổi trả/ship | M1 | Có nguồn và loader | 40 sản phẩm, 96 biến thể, 14 tài liệu; dry-run đạt. E16 |
| C1-D09: ≥3 persona M1 | M1 | Có ca mẫu, chưa đủ corpus | Sample/scenario có hỏi người nhà, so giá, đổi size; cần thống kê persona trên corpus bàn giao. E11/E15 |
| C1-D10: ≥250 transcript | M2 | Chưa xác minh đủ | Chưa có manifest đạt. E15 |
| C1-D11: ≥100 audio, ≥3 giờ | M2 | Thiếu trong bundle đã kiểm | 22 file/19,55 phút. E15 |
| C1-D12: ≥60 khách đa phiên, có khách ≥3 phiên | M2 | Chưa xác minh đủ | Chưa có mapping corpus đạt; có code hỗ trợ nhiều phiên. E02/E15 |
| C1-D13: ≥30 khách đa kênh | M2 | Chưa xác minh đủ | Chưa có manifest khách/kênh. E15 |
| C1-D14: 3 ngành, 3 miền | M2 | Một phần | Catalog nhiều ngành; chưa có bằng chứng 3 miền audio. E15/E16 |
| C1-D15: ≥20% audio nhiễu | M2 | Có nhãn ở bundle | 7/22 gắn noisy; nhãn/synth pipeline không thay QC thực tế. Đây không phải kết luận đạt toàn M2 dataset. E15 |
| C1-D16: ≥100 SKU | M2 | Cần làm rõ cách đếm | Nguồn chung có 40 mã sản phẩm/96 biến thể; không tự thêm SKU trái catalog BTC. Công bố riêng hai số và thống nhất cách đếm. E16 |
| C1-D17: thêm persona hỏi nhiều không mua / lần 3 mất kiên nhẫn | M2 | Có ca trong bundle benchmark | Không có simulator đã chạy/độ phủ corpus và run mới. E11/E12 |
| C1-D18: được dùng LLM+TTS sinh toàn bộ dữ liệu | Chung | Phù hợp | Hai bundle ghi engine Edge; không mô tả bộ “clone” preview là clone giọng thật. E15 |
| C1-D19: cấm ghi âm khách thật chưa ẩn danh/đồng ý | Chung | Chưa thấy vi phạm trong hai bundle | Các bundle được sinh; không suy rộng kết luận cho mọi dữ liệu ngoài workspace. E15 |

**C.1 — xử lý tiếng Việt và memory**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C1-P01: ASR tiếng Việt model có sẵn chạy local | M1 | Có code | `speech/asr.py` dùng faster-whisper/PhoWhisper, cache/model local; không chạy inference lần audit. E14 |
| C1-P02: báo WER/CER ≥20 file | M1 | Có scorer, chưa xác minh kết quả đủ | Có CLI/evaluate/reference scorer; README có kết quả lịch sử nhưng không có `speech/data` tương ứng ở đây. E14/E15 |
| C1-P03: chuẩn hóa tiền dạng nói/viết tắt | M1 | Có code/test | ITN/TN, lexicon/entities; 71 speech tests tập trung đạt, không phải điểm ASR thật. E14 |
| C1-P04: chuẩn hóa SĐT | M1 | Có code/test | Number/phone entities; chưa có exact-match report thật hiện hành. E14 |
| C1-P05: chuẩn hóa ngày/lịch hẹn | M1 | Có code, cần E2E | Speech date entities và callback contract; agent suy thời điểm theo `on`, cần test hội thoại ngày tương đối/ngày nghỉ. E05/E14 |
| C1-P06: teencode/viết tắt/không dấu | M1 | Một phần | API nhận `chat_teencode`, catalog fold dấu, speech lexicon; không có preprocessor teencode tập trung ở accept (chỉ mask PII), chất lượng phụ thuộc model và chưa đo đủ. E01/E05/E14 |
| C1-P07: code-switch Việt–Anh | M1 | Có code/test | Lexicon normalize ship/size/COD và tên sản phẩm; chất lượng audio cần report. E14 |
| C1-P08: trích intent | M1 | Một phần | Episode `customer_goal`/topic là biểu diễn ý định; không có taxonomy intent riêng. Cần chứng minh output đáp ứng nghiệp vụ, không bắt buộc tự thêm classifier. E03 |
| C1-P09: sản phẩm/size/màu | M1 | Có code | Scoped product facts + variant resolution, không trộn size giữa SKU. E03/E05 |
| C1-P10: mức giá đã báo | M1 | Có code | Giá lấy từ tool và lời đã báo, provenance; không lấy budget/giá đối thủ làm quote shop. E03/E06 |
| C1-P11: thời điểm hẹn gọi lại | M1 | Một phần | Tool lưu callback_at; profile chủ yếu `callback_scheduled` boolean, cần chứng minh thời điểm được mang sang brief khi cần. E03/E05 |
| C1-P12: người ra quyết định | M1 | Có code | Blocker/evidenced text và decision-maker resolution nhận hỏi chồng/vợ/người nhà. E03 |
| C1-P13: kết quả chốt/hẹn/từ chối | M1 | Một phần | Chốt/handoff/callback từ tool có xác minh; nhánh worker không nâng candidate `tu_choi` thành canonical outcome (chi tiết F06). E03/E05 |
| C1-P14: PII khi log/gửi model ngoài | M1 | Có cơ chế, chưa bảo đảm mọi cấu hình | Accept/context/extractor/embedding có masking, trace theo path. Debug Langfuse capture-content xuất raw request nếu bật ngoài production; cần kiểm cấu hình triển khai. E17 |
| C1-P15: diarization hai người nói | M2 | Chưa tìm thấy predictor | Annotation A/C/replay không phải diarization dự đoán. E14 |
| C1-P16: sửa lỗi ASR bằng từ điển | M2 | Có code | Lexicon/hotwords/normalize; cần report tác động trên tập chưa chỉnh luật theo đáp án. E14 |
| C1-P17: xử lý audio nhiễu | M2 | Có thành phần | Audio transforms, VAD và lọc hallucination ASR; chưa chứng minh chất lượng thật. E14/E15 |
| C1-P18: ASR streaming | M2 | Chưa có trong đường đang đọc | Speech serving khai báo `stt_streaming=false`; nhận diện theo segment offline. E18 |
| C1-P19: objection + cách xử lý | M2 | Một phần | Objection/blocker có slot; lời tư vấn/next_step có episode, chưa có extraction đánh giá đủ cặp objection–handling. E03 |
| C1-P20: sentiment | M2 | Một phần | Handoff schema có optional sentiment; chưa có pipeline đo chất lượng trích sentiment. E05 |
| C1-P21: cam kết đã hứa | M2 | Một phần | Actions/quoted_prices và narrative; chưa có cấu trúc/đánh giá bao phủ mọi loại promise. E03 |
| C1-P22: tokenization để nghiệp vụ vẫn dùng PII | M2 | Một phần | Trusted identity và masking tách model khỏi dữ liệu nghiệp vụ; chưa có token vault/tokenization đầy đủ. E02/E17 |
| C1-P23: xóa toàn bộ dữ liệu khách | M2 | Một phần | Erasure request/executor, suppression và knowledge tombstone; các store traces/backups/exports còn scope/pending. E19 |
| C1-M01: working memory | M1 | Có code | Turns theo session lưu từng lượt, history có giới hạn. E01/E04 |
| C1-M02: episodic memory | M1 | Có code | Canonical episode theo session, topics/blockers/actions/quotes, worker bền vững. E03/E04 |
| C1-M03: profile memory | M1 | Có code | Facts theo customer/scope/slot, phiên bản completed mới được đọc. E03/E04 |
| C1-M04: quyết định ghi/không ghi | M1 | Có code/test | Typed proposal + identity/evidence admission, reject PII/unsupported fact. E03 |
| C1-M05: khách đổi ý, vô hiệu giá trị cũ | M1 | Có code/test | Revision/supersede/select latest; scoped size/color. Cần đo chất lượng extractor thực. E03/E04 |
| C1-M06: semantic KB/RAG | M2 | Có code mới | Cloudflare dense/BM25/RRF, authoritative PostgreSQL snapshot. Chưa có retrieval report mới. E08/E09 |
| C1-M07: TTL/decay theo thời gian | M2 | Một phần | Promo validity, freshness refresh, cảnh báo địa chỉ >180 ngày; không có decay tổng quát cho mọi ý định/fact. Expired fact vẫn được đưa vào context kèm cảnh báo ở brief. E01/E04 |
| C1-M08: truy vết nguồn ký ức | M2 | Có code | Session/turn/source_kind/source_tool/evidence_quote/revision. E03/E04 |
| C1-M09: chống memory poisoning | M2 | Có code/test, cần quality eval | Unknown/ambiguous không nạp profile ứng viên; evidence admission/negation/conflict gates. Không chứng nhận chống mọi đầu độc ngữ nghĩa. E02/E03 |

**C.2 — harness, công cụ và hiệu năng**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C2-01: nhận diện khách qua SĐT | M1 | Có code | CRM lookup, session identity binding. E02 |
| C2-02: brief nêu khách là ai/số lần gọi | M1 | Có code | `n_previous_sessions`, customer fields, prior IDs. E01/E05 |
| C2-03: brief có sản phẩm/giá/KM đã báo | M1 | Có code | Products advised, quoted_on, promo_still_active và nguồn tool. E01/E03 |
| C2-04: brief có blocker tồn đọng | M1 | Có code | Open episode items, loại blocker đã giải quyết. E01/E03 |
| C2-05: brief có next action | M1 | Có code | `suggested_next_action`, warnings/open questions. E01 |
| C2-06: mở đầu xác nhận tiếp nối | M1 | Có code/test | Suggested opening và prompt bám ngữ cảnh; vẫn cần chất lượng model thật. E01/E05 |
| C2-07: không hỏi mở slot đã biết | M1 | Có chỉ dẫn/test, chưa chứng minh đủ | Prompt/must_not_ask; không có deterministic gate chặn mọi câu hỏi thừa. Cần RQR trên bộ đủ chuẩn. E01/E11 |
| C2-08: chỉ xác nhận khi cần | M1 | Một phần | Prompt và scorer phân biệt confirm/open; chưa có guard lặp xác nhận trong output runtime. E05/E11 |
| C2-09: ≥3 tool có schema | M1 | Có code | CRM, catalog, inventory, order, callback, handoff và memory; schemas/handlers tách. E02/E05 |
| C2-10: giá/KM lấy từ công cụ | M1 | Có code/test | Quote, current-day preconditions, verify/recover; guardrails optional có thể tắt một số answer checks, grounding vẫn chạy. E05/E06 |
| C2-11: giải thích đưa/cắt gì trong prompt | M1 | Có code/tài liệu | Customer facts/sales history/session history/episodes tách; history_turns và max_episodes giới hạn. E01 |
| C2-12: khi nào gọi tool/khi nào không | M1 | Có code | Business descriptions, middleware/allowlist, preconditions/cache. Budget mặc định 3 cần kiểm ca catalog+inventory+quote+create. E05/E06 |
| C2-13: lỗi tool/timeout | M1 | Một phần | Tool errors/fallback, knowledge deadline/retry/breaker; pin release/CRM có thể lỗi trước graph, không đến fallback lời thoại. E02/E06/E08 |
| C2-14: ASR trả rác | M1 | Có thành phần, cần trọn luồng | ASR clean/filter, replay ghi not_ready nếu rỗng; API text không có confidence/VAD metadata để tự đánh giá mọi transcript rác. E14/E18 |
| C2-15: LLM sai định dạng | M1 | Có code/test | Parse JSON answer khi có, invalid/exception fallback và tool schema validation. E06 |
| C2-16: khi nào chuyển người và bàn giao gì | M1 | Có code/test | Explicit request, erasure route, agent theo scope; brief dựng từ state, ticket queued mới báo thành công. E05/E06 |
| C2-17: chat text + xử lý file offline | M1 | Có thành phần | Text API, speech CLI/replay request mapping; chưa có walkthrough bản triển khai hiện hành. E14/E18/E20 |
| C2-18: Call Brief ≤5s | M1 | Chưa xác minh hiện hành | Có latency field; run cũ ít mẫu; timer nội bộ không gồm bước pin release trước `_run`. E01/E02/E12 |
| C2-19: TTFT p95 ≤3s | M1 | Chưa xác minh đạt | Non-streaming được phép TTFT=Total. Run cũ 39 turn không đủ ≥100; chưa có run code mới. E11/E12 |
| C2-20: Total p95 ≤8s | M1 | Chưa xác minh đạt | Config policy deadline 60s không bảo đảm target 8s; cần phép đo thực. E08/E11 |
| C2-21: demo một phiên đồng thời | M1 | Chưa xác minh deployment | Code hỗ trợ text session; không chạy demo trong audit. E20 |
| C2-22: phát hiện KM hết/hết hàng khi quay lại | M2 | Có code/test | Context refresh quote/inventory và warnings; tối đa ba candidate SKU tự refresh, phần còn lại có cảnh báo. E01 |
| C2-23: xử lý khách gọi số lạ | M2 | Một phần | Unknown/ambiguous và verify endpoint có; không có voiceprint, không tự tin nhận diện từ một lời khai chưa xác minh. E02/E20 |
| C2-24: barge-in | M2 | Một phần | Frontend có dừng phát/ghi âm thủ công; chưa thấy tự phát hiện tiếng nói khách để ngắt audio. E18 |
| C2-25: nén context khi vượt token window | M2 | Một phần | Bounded history/episode summary, chưa có cơ chế tính token rồi nén động. E01/E03 |
| C2-26: voice gần realtime, TTFA p95 ≤2,5s | M2 | Chưa xác minh | TTS streaming có; STT batch, agent trả text xong mới TTS. Âm thanh “đang kiểm tra” không chứng minh latency câu trả lời nghiệp vụ. E18 |
| C2-27: Call Brief ≤3s | M2 | Chưa xác minh hiện hành | Cần run đủ mẫu trên stack mới. E01/E12 |
| C2-28: ≥2 phiên đồng thời | M2 | Chưa xác minh | AI lock theo session; speech inference lock serialize từng đoạn. Không có bằng chứng tải hai phiên. E02/E18 |

**C.3 — MCP hoặc A2A**

| ID / yêu cầu BTC | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|
| C3-01: chọn MCP/A2A, giải thích lý do | Có lựa chọn MCP | Nghiệp vụ nằm ở service/repo, agent gọi gateway; cần diễn giải lựa chọn trong hồ sơ nộp. E05/E21 |
| C3-02: ≥2 MCP ở M1 | Có code | Catalog/order/memory/knowledge, bốn process. E21 |
| C3-03: bắt buộc mcp-memory | Có code | Read/write độc lập, durable commit/worker. E04 |
| C3-04: thêm mcp-order ở M2 | Có code | Service/schema/role riêng. E05/E21 |
| C3-05: mcp-knowledge RAG ở M2 | Có code | Dedicated server, signed context, search/readiness. E08/E09 |
| C3-06: phân quyền theo tool/quyền ghi | Một phần đã có cơ chế | MCP auth, role/grants, signed policy context, reviewer quyền riêng, allowlist/preconditions. Shared MCP token không phải policy scope phân biệt mọi principal; grants thực chưa kiểm lại. E05/E08/E21 |
| C3-07: các agent thực sự chia sẻ trạng thái/chuyển giao nếu dùng A2A | Không áp dụng nhánh A2A | Deep/ReAct là implementation lựa chọn cho cùng harness; không tự tính là A2A. Không cần thêm multi-agent để đạt nhánh MCP. E01/E05 |

**C.4 — đánh giá và các công thức Phụ lục A**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C4-01: một lệnh đánh giá, in/xuất chỉ số | M1 | Có code | `run_official` tạo trace/audit/score/manifest và gọi scorer BTC. Có dependencies môi trường/release. E11 |
| C4-02: ≥20 scenario đa phiên | M1 | Thiếu | Directory 6; bundle 18. Không gọi 22 WAV độc lập là 22 scenario đa phiên. E11/E15 |
| C4-03: mỗi scenario 2–3 cuộc cùng khách | M1 | Một phần | Directory 6/7, bundle 18/19 đa phiên; cần bộ team đủ chuẩn. E11 |
| C4-04: ≥5 scenario khó | M1 | Directory thiếu | Directory 3; bundle 15 có nhãn hard. Cần dùng đúng snapshot công bố, không trộn mẫu số. E11 |
| C4-05: RQR = hỏi thừa/tổng câu hỏi | M1 | Có scorer, extractor thiếu độ phủ | Câu hỏi chung không ra slot hiện bị bỏ hoàn toàn; ảnh hưởng mẫu số. F02. E11 |
| C4-06: miễn xác nhận lần đầu; lần 2 tính thừa | M1, điều chỉnh | Có scorer | Internal và reference scorer xử lý confirmed slots; runtime chưa chủ động ngăn lặp. E11 |
| C4-07: giảm RQR tương đối ≥40% | M1 | Chưa xác minh hiện hành | Run 02/11 đạt trên 7 scenario; chưa chứng minh bộ đủ M1 và code mới. E12 |
| C4-08: CCR dùng đúng fact, mỗi fact một lần | M1 | Có adapter/scorer | `facts_used` cần observable speech/args và source phiên trước; paraphrase/scope vẫn có giới hạn rules. E11 |
| C4-09: không đọc vẹt ký ức để lấy CCR | M1 | Có định hướng, cần đánh giá lời thoại | Brief opening ngắn/blocker; regex chưa chứng minh được mục đích ngữ nghĩa của mọi fact. E01/E11 |
| C4-10: TSR nhị phân theo assertion | M1 | Có code | `success_if`, args_match, also_ordered/forbidden/max questions, authoritative BTC scorer. E11 |
| C4-11: TSR ≥70% | M1 | Chưa xác minh hiện hành | 02/11 ghi 6/7; không dùng thay run mới. E12 |
| C4-12: HR đếm claim, không đếm lượt | M1 | Có code, thiếu claim policy | Extractor lấy lời agent thay vì truth từ tool; không trích “đổi trả trong 30 ngày”. F03. E11 |
| C4-13: HR giá/KM ≤5% | M1 | Chưa xác minh hiện hành | 02/11 ghi 0/5 claim; mẫu nhỏ và source khác. E12 |
| C4-14: WER và CER, công bố normalize | M1 | Có scorer/documentation | Speech dùng normalization_rule + raw/canonical/written/spoken, rules hash; chưa có report đủ audio BTC + team tại đây. E14/E15 |
| C4-15: exact-match riêng tiền và SĐT | M1 | Có entity machinery, chưa đủ report | Entity scoring có; cần công bố mẫu số/kết quả tiền và điện thoại riêng, không chỉ tổng Entity Accuracy. E14 |
| C4-16: baseline cùng model/params/data, chỉ khác memory | M1 | Có runner | `include_prior=false`, namespace baseline, identity giữ; fingerprint source/seed và release pin. Cần kiểm nhất quán memory worker/model params trong phương pháp đo. E04/E11 |
| C4-17: bảng A.6 baseline/full/delta + lượt TB | M1 | Có artifact lịch sử | Không phải báo cáo trên bộ team đủ chuẩn/code mới. E12 |
| C4-18: ≥40 scenario | M2 | Chưa có đủ | Nhiều nhất bundle 19. E11 |
| C4-19: customer simulator kiên nhẫn giảm | M2 | Chưa tìm thấy implementation | Chỉ có static customer_turns và spec BTC; xem bảng bổ sung bên dưới. E11 |
| C4-20: Calls-to-Close | M2 | Có scorer | Có kết quả lịch sử; cần run hợp lệ hiện hành. E11/E12 |
| C4-21: Tool-Call Accuracy | M2 | Một phần | Có task assertion và tool diagnostics; chưa có metric accuracy tổng thể với nhãn/mẫu số rõ ràng. E11 |
| C4-22: RAG Recall@3 và @5 | M2 | Chưa có collector/report hiện hành | Runtime RAG không tự tạo trace retrieval chuẩn 60 QA; README nói collector cũ đã gỡ. E08/E11 |
| C4-23: p50/p95 | M2 | Có mã tính | Chưa đủ mẫu trên stack mới; warm-up của diagnostic khác báo cáo BTC nguyên bản. F05. E11 |
| C4-24: ước tính chi phí/cuộc | M2 / tiêu chí G7 | Chưa có báo cáo đầy đủ | Cost placeholder null; cần tính LLM chat + distiller + embedding + ASR/TTS theo pipeline dùng. E11/E14 |
| C4-25: LLM judge có rubric | M2 | Có rubric BTC, chưa thấy workflow team hoàn chỉnh | File rubric không đồng nghĩa đã chạy judge. E11 |
| C4-26: người chấm ≥20 mẫu, agreement/kappa | M2 | Chưa tìm thấy artifact | Không dùng unit test thay human calibration. E11 |

**C.5 — cải tiến theo thời gian**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C5-01: không fine-tune | Chung | Phù hợp code đang đọc | Các thay đổi ở dữ liệu/prompt/memory/retrieval/workflow, không thấy pipeline train. E03/E07/E08 |
| C5-02: thu ≥2 nguồn feedback | M1 | Có code | Operator feedback, evaluation_result, runtime signal và business outcome; chưa kiểm lượng event thực tế trong DB hiện tại. E07/E13/E20 |
| C5-03: ít nhất 1 cơ chế cải tiến | M1 | Có Knowledge Gap Loop | Event → analysis/gap → revision/test → review → release → verification. E07/E13 |
| C5-04: câu không trả lời được tự ghi thiếu sót | M1 | Có code | No_evidence/fallback/rejection events; lỗi kỹ thuật được phân loại riêng. E07 |
| C5-05: bổ sung tài liệu có nguồn | M1 | Có workflow | FAQ/aliases, source hashes, public sources, reviewer permission; không tự biến lời khách thành chính sách. E07 |
| C5-06: tự thêm test để không tái phạm | M1 | Một phần | Tạo regression draft/variations và approve test; check mặc định là lexical review, chưa chứng minh tự đưa ca vào frozen agent suite hoặc agent test tương đương. E07/E13 |
| C5-07: Exemplar Bank | Lựa chọn M1 | Chưa tìm thấy | Không bắt buộc thêm nếu Knowledge Gap Loop được chứng minh đạt. E07 |
| C5-08: vòng 0 → feedback → cải tiến → vòng 1 | M1 | Chưa có bằng chứng trọn vòng | Có comparator và workflow, chưa tìm thấy cặp báo cáo cải tiến có provenance tương thích. E13 |
| C5-09: giữ nguyên bộ test giữa hai vòng | M1 | Có kiểm soát trong comparator | FIXED source/data/seed/model/scorer và khác release; cần run thật. E13 |
| C5-10: trình bày delta bằng số | M1 | Có code, chưa có artifact | `compare_runs` xuất delta và improved/regressed scenarios. E13 |
| C5-11: biết thay đổi nào cần người duyệt | M1 | Có code | Reviewer permission, approve exact content/test hash, CAS activation. E07 |
| C5-12: ≥2 cơ chế cải tiến | M2 | Chưa đủ | Chỉ xác nhận Knowledge Gap Loop; memory extraction không tự tính là Reflection. E03/E07 |
| C5-13: Reflection có kiểm tra | M2 | Chưa tìm thấy | Episode summary lưu diễn biến không đồng nghĩa bài học chiến lược được kiểm chứng. E03 |
| C5-14: A/B xử lý phản đối | M2 | Chưa tìm thấy | Deep/ReAct/full/baseline là thí nghiệm kiến trúc/memory, không thay A/B kịch bản học từ outcome. E11 |
| C5-15: ≥3 vòng, phân tích cải tiến gây hại | M2 | Chưa có artifact | Comparator hỗ trợ liệt kê regressions, chưa có ba vòng. E13 |
| C5-16: không học “hứa đại để chốt” | M2 | Có cơ chế hạn chế | Source validation/dynamic-price restrictions/human approval; cần thử ca học sai và báo cáo tác động. E07 |
| C5-17: rollback khi chất lượng tụt | M2 | Một phần | Có rollback release thủ công/tombstone; chưa có quality gate tự động gắn chỉ số. E07/E08 |

**C.6 — sản phẩm và demo**

| ID / yêu cầu BTC | Mức | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|---|
| C6-01: web chat agent trực tiếp trả lời | M1 | Có code | Frontend → `/api/chat` → AI; có error/retry/identity. Chưa walkthrough live mới. E20 |
| C6-02: Call Brief hiện khi khách quay lại | M1 | Có code, UI một phần | API trả brief, frontend render summary/blockers/opening; chưa hiển thị đầy đủ mọi phần và có thể xóa brief ở lượt sau khi response null. E01/E20 |
| C6-03: dòng thời gian bộ nhớ khách | M1 | Một phần | `/api/calls` theo owner, danh sách call/message; chưa có timeline profile/episode/set/supersede theo customer xuyên nhân viên/kênh. E20 |
| C6-04: demo cuộc 1 tư vấn + giá/KM + hỏi người nhà | M1 | Có thành phần, chưa xác minh demo | Catalog/quote/blocker/callback có code; cần bằng chứng trên deployment mới. E01/E05 |
| C6-05: demo cuộc 2 nhận diện + tiếp nối + chốt | M1 | Có thành phần, chưa xác minh demo | Memory async và worker cần hoàn tất; mock test không thay demo live. E01/E03/E04 |
| C6-06: chạy script so baseline trực tiếp | M1 | Có runner, chưa đủ bộ nộp | Chạy eval có chi phí/reset nên không thực hiện trong audit. E11 |
| C6-07: copilot gợi ý nhân viên | M2 | Chưa tìm thấy luồng hoàn chỉnh | UI hiện agent gửi thẳng; feedback sau câu trả lời không phải approve/send copilot. E20 |
| C6-08: cảnh báo nhân viên sắp cam kết sai | M2 | Chưa tìm thấy | Guardrail agent không tương đương monitor lời nhân viên trước gửi. E06/E20 |
| C6-09: dashboard C.4 | M2 | Có code | Streamlit đọc run đã validate; không thay số liệu còn chưa đo. E11 |
| C6-10: demo cuộc 3 đổi size/hỏi vận đơn | M2 | Có tools, chưa xác minh demo | Order.status/update, ownership, nhớ order/variant. E05 |

**D/E/F/G — ràng buộc, hồ sơ nộp và tiêu chí chấm**

| ID / yêu cầu BTC | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|
| D01: model có sẵn, không cần train | Phù hợp | Ollama LLM, ASR local, Cloudflare embedding. E08/E14/E22 |
| D02: ASR local ở M1, LLM API được phép | Có code phù hợp | CLI ASR chạy local; frontend gọi Speech API trên máy đội là đường triển khai khác, cần công bố máy/model. E14/E18 |
| D03: dữ liệu thật phải có đồng ý/ẩn danh | Chưa thấy vi phạm ở bundle kiểm tra | Không dùng kết luận này bảo chứng dữ liệu ngoài workspace. E15 |
| D04: tiếng Việt tự nhiên và xưng hô | Có prompt, cần quality review | Prompt ngắn/dạ/anh/chị, CRM honorific; chưa có đánh giá ≥20 mẫu người. E01/E05 |
| D05: chạy theo README | Một phần | Root/AI/loader runbooks có; eval/frontend README còn thông tin ba MCP, policy unavailable; root có link tài liệu không tồn tại. E11/E20/E23 |
| D06: hỏi trực tiếp không được giả người thật | **Thiếu chặn runtime rõ ràng** | Synthetic probe “Dạ, em là người thật ạ.” đi qua cả check_grounding/check_answer; extractor chỉ ghi vi phạm để chấm sau. F01. E06/E11 |
| E01: công nghệ/lộ trình trong đề | Hướng dẫn, không phải gate | Không bắt buộc ChromaDB/LangGraph/Streamlit/Whisper cụ thể nếu cách khác đáp ứng yêu cầu; không lấy combo gợi ý làm đầu việc mới |
| F01: repo/README/setup/seed | Có code/tài liệu, còn sai lệch | Dataloader/migrations/provision/runbooks; chưa kiểm máy sạch, README chưa đồng nhất entrypoint. E16/E21/E23 |
| F02: dataset + cách sinh/phân bố/hạn chế/PII | Một phần | Có hai bundle/manifest và mô tả, chưa đủ M1/metadata đa phiên. E15 |
| F03: kiến trúc/harness/memory/tools/quyết định | Có tài liệu, cần đồng bộ | Architecture-review có phần local GPU/relevance gate cũ; runbook mới đúng Cloudflare. E23/E24 |
| F04: bảng chỉ số baseline | Có lịch sử, chưa bản hiện hành | 7 scenario/39 turns, source trước chuyển provider. E12 |
| F05: before/after cải tiến | Chưa tìm thấy đủ | Cần cặp run cùng frozen suite/model/code, khác release cải tiến. E13 |
| F06: phân tích ≥10 trường hợp sai | Chưa xác minh đủ gói nộp | Có nhiều audit kỹ thuật; chưa thấy báo cáo 10 lỗi hội thoại gắn scenario/trace/nguyên nhân/kết quả sửa cho bản nộp |
| F07: video 5–8 phút có demo hai cuộc | Chưa tìm thấy artifact trong các thư mục kiểm | Không kết luận team chưa có ngoài repo |
| F08: website đủ chức năng bắt buộc | Một phần | Chat/brief có; customer memory timeline chưa đủ. E20 |
| F09: slide ≤15 | Chưa tìm thấy artifact trong các thư mục kiểm | Cần kiểm gói nộp cuối, không thêm slide nếu ngoài phạm vi task |
| G01: dữ liệu & tiếng Việt 12% | Chưa thể chấm điểm | Đối chiếu C1; thiếu corpus/manifests và report ASR đầy đủ |
| G02: harness/continuity/guardrail 22% | Có nền tảng, còn gap chức năng | D06, fallback trước graph, outcome, demo/RQR/CCR hiện hành cần xử lý |
| G03: MCP/A2A 15% | Có nền tảng MCP | Bốn server; chưa chứng minh vận hành Cloudflare/SQL grants trên bản mới |
| G04: đánh giá 15% | Chưa đủ bằng chứng M1 | Bộ test chưa đủ, extractor còn thiếu độ phủ, source scorer BTC có hai bản khác nhau |
| G05: cải tiến 13% | Có code, chưa chứng minh hai vòng | Knowledge Gap Loop cần artifact before/after |
| G06: trải nghiệm/demo 13% | Một phần | Web có, timeline còn thiếu và chưa walkthrough live mới |
| G07: mở rộng/chi phí 5% | Một phần | Service boundaries, scoped store/queue; process-local runtime và chưa có cost/cuộc đầy đủ |
| G08: trình bày/phản biện 5% | Chưa xác minh | Cần báo đúng phạm vi test, số liệu lịch sử, hạn chế và tài liệu kiến trúc hiện hành |

Không quy đổi “có code” thành phần trăm hoàn thành hoặc tổng điểm. Trọng số chỉ giúp ưu tiên; không dùng để dự đoán điểm BTC khi chưa chạy nghiệm thu.

**Điểm thưởng G (chỉ xét sau M1)**

| Yêu cầu thưởng | Hiện trạng |
|---|---|
| Voice realtime mượt + barge-in | TTS streaming, STT batch, stop thủ công; chưa chứng minh |
| Voiceprint/số lạ; hai người chung SĐT | Có xử lý ambiguity/evidence, chưa có voiceprint |
| Toàn bộ local gồm LLM | Chưa chứng minh; đường mặc định có Ollama Cloud/Cloudflare |
| Tối ưu prompt tự động + ablation | Có Deep/ReAct/full/baseline; chưa thấy optimizer/ablation cải tiến tự động đủ bằng chứng |
| Playbook tự rút cách xử lý phản đối | Có policy playbook tĩnh; chưa có tầng học playbook có kiểm chứng |
| Cảnh báo cam kết nhân viên, dự đoán chốt/lịch tối ưu, drift | Chưa tìm thấy các chức năng này; không mở rộng scope để làm trong audit |
| MCP ngoài đời Calendar/Sheets/Notion | Chưa tìm thấy tích hợp; không phải M1 |

**12 điều chỉnh BTC — kiểm riêng để không bỏ sót**

| Điều chỉnh | Đối chiếu hiện tại |
|---|---|
| 1. Hiệu năng TTFT/Total/TTFA/brief/concurrency | Có field/timing; thiếu run hiện hành đủ mẫu; TTFT=Total được phép với non-streaming; diagnostic mới bỏ warm-up, authoritative score chưa bỏ |
| 2. Nguồn chung, test ẩn, trace chuẩn, bảng team và giải thích extractor | Loader nguồn chung và paired scorer có; thiếu frozen team suite đủ M1; extractor còn gap; không dùng QA/test answers làm RAG corpus |
| 3. Tên/tham số tools chuẩn | Các tên tool có; schema MCP và model wrapper cần giữ thống nhất, đặc biệt basket_skus ở order.create; cần kiểm parity ngoài vài ca mẫu |
| 4. Handoff ngoài phạm vi tính task success | Tool/brief/ticket và scorer có; không cần routing người thật |
| 5. Xác nhận lần 2 là thừa | Scorer có; runtime chỉ dẫn chưa đủ chặn mọi lặp; generic question extraction còn thiếu |
| 6. Precompute brief, freshness phải chạy lúc nhận diện | Summary precomputed + quote/inventory refresh có; cần tính đầy đủ thời gian và kiểm cross-channel khi session binding đã cache |
| 7. Recall@3/@5 trên QA chuẩn | Chưa có collector/report hiện hành; runtime RAG không thay eval |
| 8. ASR local, BTC audio + ≥20 file team, normalize chuẩn | Local ASR/scorer có, 22 team audio có; BTC WAV và report đủ tập chưa có local |
| 9. Policy có bản cũ/nội bộ/ngày nghỉ/spec/playbook/nhiễu | Parser/rules/safe transforms có, 93 safe chunk; quality 60 QA chưa đo. Cần xem current/old theo ngày đơn, không xóa cứng mọi bản cũ |
| 10. Tool theo thời gian và parity mock BTC | Inventory timeline, variants/delta, exclusivity/conditions/once/region/owned SKU có trong rules; end-to-end basket, runtime purchases/owned SKU và order update cần thêm bằng chứng |
| 11. 41 test ẩn/19 khó và kiểm tra bổ sung | Không yêu cầu có quyền xem hidden set. Team runner vẫn phải hỗ trợ schema; seed_history hiện không được đọc. Bảng tình huống bên dưới ghi coverage code |
| 12. Simulator + judge chuẩn hóa | Chưa có implementation/log 8 rules/3 seed và human agreement/kappa ≥20 mẫu |

**Các ca khó/chức năng BTC nêu trong điều chỉnh 11**

| Tình huống | Coverage hiện có / phần chưa xác nhận |
|---|---|
| Ba kênh báo giá khác nhau | Identity chung, quote history và giá hiện hành có; chưa có run mới chứng minh xử lý xung đột đủ |
| Hai người chung SĐT | CRM ambiguous, không nạp profile ứng viên; verified identity có nhưng order service vẫn resolve theo source_channel/source_identity; cần kiểm trọn luồng sau verify |
| Khách quay lại sau 8 tháng | Cảnh báo 180 ngày, discontinued/successor có; runner bỏ qua seed_history, TTL không tổng quát |
| KM loại trừ size | Quote rules có exclude_variant_size, variant selection có; chưa có trace hiện hành đủ ca |
| ASR lỗi/teencode | Runner ưu tiên customer_turns_asr, input_mode được truyền; preprocessing/quality cần chứng minh |
| CCCD/STK không lọt trace | Mask numeric 9–14 digit, safe field-path adapter và tests; không bảo chứng mọi dạng ngắt số/PII tự do, debug capture cần lưu ý |
| Ép giá/dò giá nhập | Quote boundaries, internal source transforms, guardrails; chưa có retrieval/answer quality report mới |
| Ba phiên đổi thông tin + hỏi đơn | Supersede/scoped facts/order.status/update có; chưa walkthrough mới |
| Hỏi AI hay người | **Guard runtime còn thiếu**, đã reproduce bằng synthetic draft |
| Yêu cầu xóa dữ liệu | Không báo xóa xong; handoff/xác minh và scoped erasure có; whole-record deletion chưa đầy đủ mọi store |
| 16 lượt, 4 sản phẩm | History bounded/scoped episode có; tool budget/default và không nén động cần kiểm trên scenario đủ dài |
| Tổng >10 triệu không COD | Per-order COD check có; giỏ nhiều order trong cùng lượt không có cart-total gate rõ; không suy per-order thành bảo đảm tổng giỏ |
| Không vượt ngân sách | Structured filters/quote/prompt có; filter list price không bằng final price, chưa có kiểm mọi giỏ nhiều món |
| Đổi sản phẩm hoàn chênh lệch | Service tính price_diff/refund/extra/fee; cần parity đầy đủ và diễn giải output đúng |
| Câu hỏi theo chính sách cũ | Rules dùng verified order date, conditional nếu khách khai; metadata/version được cập nhật; release cũ cần build lại |
| Callback ngày nghỉ/ITN tương đối | Callback dời giờ/ngày và trả moved_from; chưa có deterministic gate bắt lời agent luôn báo khách việc dời lịch |
| Không bình luận giá đối thủ | Giá đối thủ tách shop quote, guardrails có; chưa chứng minh mọi paraphrase/so sánh |
| Hết hàng lúc khách quyết | Order.create kiểm lại inventory, không chỉ tin lượt tư vấn; snapshot inventory mock không phải hệ thống reserve kho thật, phù hợp phạm vi mô phỏng |

**Phát hiện cụ thể cần đưa vào thảo luận tiếp**

| Mã / ưu tiên | Phát hiện | Bằng chứng và phạm vi kết luận |
|---|---|---|
| F01 / cao — D06 | Chưa chặn agent nhận là người thật | Probe offline: `check_grounding('Dạ, em là người thật ạ.', [])` trả None; `check_answer(..., [], '')` trả nguyên câu và reason None. Extractor có ghi `is_human=true` nhưng đó là chấm sau, không chặn gửi. Không khẳng định LLM thực tế đã nói câu này. E06/E11 |
| F02 / cao — RQR | Extractor bỏ câu hỏi không khớp slot regex | Probe “Chị cần em hỗ trợ gì thêm không ạ?” → `extract_questions=[]`. Scorer chỉ thấy questions được trích nên mất mẫu số câu hỏi; cần công bố giới hạn và kiểm nhãn người. E11 |
| F03 / cao — HR policy | Không trích đủ claim chính sách | Probe “Dạ, chị được đổi trả trong 30 ngày ạ.” → `extract_claims=[]`. Guardrail chặn được ví dụ thiếu evidence, nhưng một claim sai được gửi do nguyên nhân khác vẫn có thể không vào HR. E06/E11 |
| F04 / cao — schema test ẩn | `seed_history` không được runner xử lý | Đã đọc hai entrypoint và tìm trường: benchmark_runner và eval/run_eval không đọc/nạp seed_history. CRM seed sẵn có chỉ thay được ca đúng dữ liệu đó, không bảo đảm mọi seed_history trong input. E11/E25 |
| F05 / vừa — latency | Bỏ warm-up chưa đồng nhất | Diagnostic gọi `warm_up_turns=3`; publish_pair chuyển trace nguyên cho BTC, `reference_eval.latency` tổng hợp mọi dòng. Không tự sửa scorer BTC; cần phương pháp/report minh bạch. E11/E25 |
| F06 / vừa — C1 outcome | `tu_choi` có trong schema nhưng chưa có đường commit chuẩn tương ứng | `outcome_from_tool_calls` trả chốt/chuyển/hẹn hoặc khac; worker chỉ nâng candidate hen_goi_lai trong trường hợp có lời hẹn, không nâng tu_choi. Nhận xét từ code, chưa chạy model. E03 |
| F07 / vừa — combo | Schema model `order.create` thiếu `basket_skus` trong khi quote và MCP CreateInput có | Đã kiểm danh sách `_TOOL_FIELDS`: quote có, create không. `prepare_tool_call` yêu cầu basket ở quote/create khớp, có thể chặn tạo đơn dùng quote giỏ. Chưa kết luận mọi combo đều lỗi; cần ca offline cụ thể cho từng loại. E05/E06 |
| F08 / vừa — fallback | Pin release nằm ngoài graph/fallback | `run()` gọi knowledge_release trước `_run`; gateway pin lỗi raise. `KNOWLEDGE_ENABLED=false` không tắt dependency corpus BTC. Knowledge service search có thông báo lỗi không chứng minh pin failure cũng có. E02/E08 |
| F09 / vừa — vận hành/eval | Preflight DB mới kiểm ba MCP | `prepare_runtime_for_eval` kiểm catalog/order/memory, chưa kiểm knowledge dù knowledge có eval.database_identity. Không kết luận môi trường hiện đang trỏ nhầm; đây là lỗ hổng phát hiện cấu hình. E11/E08 |
| F10 / vừa — release | Runtime mới không dùng release local cũ | Code yêu cầu manifest schema 3/pipeline cloudflare_dense_bm25/BM25 artifact; bàn giao 04/11 nói chưa build/activate release mới. Audit ingestion cũ còn lệch metadata 31 chunk. Chưa truy vấn lại DB, không khẳng định trạng thái hiện tại vẫn y nguyên. E08/E09/E26 |
| F11 / vừa — PII | Debug trace có thể xuất raw request | `capture_content=true` dùng request.model_dump và debug_mask chỉ lọc credential; Settings cấm production nhưng cho môi trường khác. Không đọc/khẳng định cờ đang bật, không xuất dữ liệu khách. E17 |
| F12 / vừa — UI memory | Lịch sử cuộc gọi chưa là timeline memory | API calls lọc created_by; UI hiển thị messages, không đọc profile/episodes và lịch sử supersede theo customer. E20 |
| F13 / vừa — reproducibility | Hai bản reference_eval BTC local khác nhau | So byte file trong eval.zip với bản giải nén: khác. Đây là dữ liệu nguồn ngoài repo; cần xác định bản dùng khi nộp, ghim hash; không tự sửa BTC. E25/E26 |
| F14 / thấp — tài liệu | Architecture/eval/frontend docs chưa theo Cloudflare và bốn MCP | Root/knowledge runbook đã cập nhật, một số tài liệu cũ vẫn mô tả GPU/ba MCP/policy unavailable. Đọc code làm căn cứ hiện hành. E23/E24 |

Các mục F07/F09/F11 được ghi đúng phạm vi: lệch contract, thiếu preflight, cấu hình có thể gây rò. Không biến khả năng thành sự cố production đã xảy ra. Những giới hạn cache/idempotency trong process, thiếu TTL cache và đa worker có trong code; chưa có bằng chứng sự cố và không đề xuất refactor ngoài yêu cầu BTC trong đợt audit.

**Kiểm chứng đã thực hiện trong lần rà soát này**

- 25 file test AI/eval chọn theo hành vi continuity, scoped memory, admission/worker, recovery/handoff, variants/business/promotion, policy/cloudflare/BM25, knowledge review/release/erasure và trace/scorer/comparator: **193 passed, 1 warning**, 6,38 giây. Dùng runner offline có settings tổng hợp, xóa credentials/DSN trong process và chặn socket network thật. Warning trustcall/LangGraph Send đã deprecated.
- Speech `test_text.py`, `test_entities.py`, `test_evaluate.py`, `test_replay.py`: **71 passed**, 0,59 giây. Đây là test luật/scorer/replay với dữ liệu fixture; không chạy ASR/TTS hoặc model.
- `python -m dataloader_offline --dry-run`: đọc/validate file BTC, số đếm như bảng đầu. Không mở DB/Qdrant hoặc embedding API.
- Các probe F01/F02/F03 và kiểm field schema F07 chạy trực tiếp bằng chuỗi tổng hợp, không model/mạng. Số lượng WAV lấy từ header; không suy ra chất lượng âm thanh.
- Lần gọi pytest đầu có hai tên file viết nhầm (`test_cloudflare_embedding.py`, `test_bm25.py`), pytest dừng collection và không chạy test. Đã thay bằng tên tồn tại `test_policy_cloudflare.py`, `test_policy_bm25.py`; kết quả 193 ở trên là lần chạy thành công. Không chỉnh source để làm test qua.
- Không chạy full suite vì không thay hành vi ứng dụng; không lặp lại nhóm test đã đạt. Các số 569/541/524 trong báo cáo bàn giao cũ là lịch sử, không nhận là kết quả lần audit này.

Lệnh AI (từ `ai-services/`):

```bash
.venv/bin/python ../.superpowers/sdd/2026-11-04-cloudflare-bm25-knowledge/run_offline_tests.py \
  test/test_returning_opening.py test/test_scoped_context.py \
  test/test_memory_quality_contracts.py test/test_langmem_admission.py \
  test/test_langmem_worker.py test/test_memory_recovery.py \
  test/test_structured_handoff.py test/test_variant_contracts.py \
  test/test_mcp_business.py test/test_promotion_grounding.py \
  test/test_policy_rules.py test/test_policy_search.py test/test_policy_integration.py \
  test/test_policy_cloudflare.py test/test_policy_bm25.py \
  test/test_knowledge_lifecycle.py test/test_knowledge_revisions.py \
  test/test_knowledge_releases.py test/test_memory_erasure_workflow.py \
  eval_harness/test_eval_harness.py eval_harness/test_question_semantics.py \
  eval_harness/test_claim_semantics.py eval_harness/test_fact_usage.py \
  eval_harness/test_official_pipeline.py eval_harness/test_knowledge_comparison.py
```

Runner trên là file local git-ignored đang có trong workspace, không phải entrypoint được đóng gói của repo. Khi tái lập trên máy khác cần dựng tương đương settings tổng hợp/chặn mạng; không sao chép `.env` thật vào test. Lệnh speech (từ root):

```bash
ai-services/.venv/bin/python -m pytest \
  speech/test/test_text.py speech/test/test_entities.py \
  speech/test/test_evaluate.py speech/test/test_replay.py -q --tb=short
ai-services/.venv/bin/python -m dataloader_offline --dry-run
```

**Thứ tự xử lý đề xuất để bàn tiếp, chưa phải spec**

1. Khép các lỗ hổng bắt buộc và phép đo: F01–F06, kiểm combo/tool budget theo ca thực sự dùng. Không thêm mô hình/agent mới để giải quyết việc chưa đo.
2. Xác minh release Cloudflare/BM25 mới và luồng hai phiên trên stack triển khai; pin/search/fallback, worker, brief, tạo đơn/handoff có trace. Mọi gọi API/build/activate/reset thực tế nằm ngoài audit này.
3. Đóng băng bộ team đủ ≥20 đa phiên/≥5 khó, hoàn thiện mapping/corpus M1 và nghiệm thu ASR; giữ sample BTC nguyên vẹn, thống nhất scorer/hash/entrypoint.
4. Đo baseline/full trên bộ đủ chuẩn, kiểm nhãn extractor; thực hiện hai vòng Knowledge Gap với test cố định và reviewer; công bố cả regression.
5. Hoàn thiện customer memory timeline và hồ sơ nộp dựa trên dữ liệu thật. Chỉ chọn M2 tiếp theo sau khi bằng chứng M1 đủ.

**Chỉ mục bằng chứng code**

- E01: [graph](../app/agent/graph.py), [context/brief](../app/agent/harness/context.py), [opening](../app/agent/harness/brief_opening.py), [accept](../app/agent/harness/session_nodes.py).
- E02: [runtime](../app/agent/harness/runtime.py), [session identity](../app/agent/harness/session_identity.py), [CRM catalog service](../app/mcp_servers/mcp_catalog/services/catalog.py).
- E03: [memory schemas](../app/schemas/langmem.py), [extractor](../app/agent/memory/langmem_extractor.py), [admission](../app/mcp_servers/mcp_memory/services/langmem_admission.py), [distiller](../app/mcp_servers/mcp_memory/distiller_worker.py), [outcome](../app/agent/memory/episode_candidates.py).
- E04: [memory service](../app/mcp_servers/mcp_memory/services/memory.py), [LangMem projection](../app/mcp_servers/mcp_memory/repos/langmem_projection.py), [store adapter](../app/agent/memory/store.py).
- E05: [business tools/model schema/prompt](../app/agent/implementations/business_agent.py), [preconditions](../app/agent/harness/policy.py), [order service](../app/mcp_servers/mcp_order/services/order.py), [MCP order schema](../app/mcp_servers/mcp_order/schemas.py), [brief schemas](../app/schemas/brief.py), [handoff builder](../app/agent/harness/handoff_brief.py).
- E06: [agent nodes/verify/persist](../app/agent/harness/agent_nodes.py), [checks](../app/agent/guardrails/checks.py), [promotion grounding](../app/agent/guardrails/promotion_grounding.py), [commerce rules](../app/mcp_servers/mcp_shared/commerce_rules.py).
- E07: [events](../app/knowledge/events/runtime.py), [analysis](../app/knowledge/events/analysis.py), [revisions](../app/knowledge/services/revisions.py), [regression drafts](../app/knowledge/services/regression.py), [releases](../app/knowledge/services/releases.py), [permissions](../app/knowledge/services/permissions.py).
- E08: [knowledge search](../app/mcp_servers/mcp_knowledge/services/knowledge.py), [encoder](../app/mcp_servers/mcp_knowledge/services/embedding.py), [Cloudflare client](../app/mcp_servers/mcp_knowledge/services/cloudflare.py), [BM25](../app/mcp_servers/mcp_knowledge/services/bm25.py), [auth/handlers](../app/mcp_servers/mcp_knowledge/tools/handlers.py).
- E09: [Qdrant](../app/mcp_servers/mcp_knowledge/repos/qdrant.py), [publish](../app/knowledge/services/publish.py), [rules](../app/knowledge/policy/rules.py), [source parser](../app/knowledge/policy/source.py), [runtime config](../../config/policy-runtime.json).
- E11: [official runner](../eval_harness/run_official.py), [benchmark runner](../eval_harness/benchmark_runner.py), [trace extractor](../eval_harness/extractor.py), [reference adapter](../eval_harness/reference_adapter.py), [internal diagnostics](../eval_harness/scorer.py), [official pipeline](../eval_harness/official_pipeline.py), [dashboard reader](../eval_harness/dashboard_data.py).
- E12: [run 02/11](../eval_harness/results/20261102T095157Z-6f49f8a9/run.json), [score 02/11](../eval_harness/results/20261102T095157Z-6f49f8a9/btc_score.json). Local ignored artifacts, không bảo đảm hiện diện trên máy khác.
- E13: [knowledge comparison](../eval_harness/knowledge_comparison.py), [feedback import](../eval_harness/knowledge_feedback.py), [lifecycle verification](../app/knowledge/services/lifecycle.py).
- E14: [ASR](../../speech/asr.py), [normalization](../../speech/normalize.py), [number ITN/TN](../../speech/vi_numbers.py), [entities](../../speech/entities.py), [evaluate](../../speech/evaluate.py), [replay](../../speech/replay.py).
- E15: [dataset release guide](../../dataset/README.md), [dataset audit](../../dataset/BAO_CAO_RÀ_SOAT_DATASET_2026-11-03.md), [speech dataset/results notes](../../speech/README.md). WAV/GT local ở hai bundle team22, không đưa raw dữ liệu vào báo cáo.
- E16: [loader](../../dataloader_offline/__main__.py), [read/validate sources](../../dataloader_offline/source.py), [verification](../../dataloader_offline/verification.py), [loader guide](../../dataloader_offline/README.md).
- E17: [mask PII](../app/mcp_servers/mcp_shared/pii.py), [trace masking](../app/agent/harness/tracing.py), [tool log masking](../app/mcp_servers/mcp_shared/observability.py), [knowledge evidence](../app/knowledge/events/evidence.py), [settings](../app/configs.py).
- E18: [speech server](../../speech/serving/app.py), [frontend speech](../../frontend/speech.js), [speech deployment guide](../../speech/serving/README.md).
- E19: [memory erasure executor](../app/mcp_servers/mcp_memory/services/erasure_executor.py), [backend erasure](../../backend/app/services/erasure.py), [knowledge erasure](../app/knowledge/services/erasure.py).
- E20: [frontend](../../frontend/index.html), [brief/send](../../frontend/app.js), [call history](../../frontend/workspace.js), [knowledge UI](../../frontend/knowledge.js), [calls API](../../backend/app/api/calls.py), [chat boundary](../../backend/app/services/chat_service.py).
- E21: [MCP launcher](../app/mcp_servers/run.py), [factory](../app/agent/factory.py), [roles](../scripts/provision_mcp_roles.sh), [Compose](../../docker-compose.yml).
- E22: [LLM adapter](../app/infarstructure/llm.py), [settings](../app/configs.py).
- E23: [root README](../../README.md), [AI README](../README.md), [eval README](../eval_harness/README.md), [frontend README](../../frontend/README.md), [current knowledge runbook](mcp-knowledge-runbook.md).
- E24: [architecture report](architecture-review-2026-11-03/README.md).
- E25: [root eval runner](../../eval/run_eval.py), [paired scorer wrapper](../../eval/score_pair.py), [trace audit](../../eval/trace_audit.py), [BTC reference scorer](../../../BTC-Data-Vong1-TEAMS/eval/reference_eval.py).
- E26: [ingestion handover](superpowers/plans/2026-11-03-ingestion-verification-results.md), [Cloudflare handover](superpowers/plans/2026-11-04-cloudflare-bm25-knowledge-results.md). Đây là ghi nhận phiên trước, không thay xác minh deployment mới.

[E05]: ../app/agent/implementations/business_agent.py
[E08]: ../app/mcp_servers/mcp_knowledge/services/knowledge.py
[E09]: ../app/mcp_servers/mcp_knowledge/repos/qdrant.py
[E11]: ../eval_harness/run_official.py
[E12]: ../eval_harness/results/20261102T095157Z-6f49f8a9/btc_score.json
[E15]: ../../dataset/BAO_CAO_RÀ_SOAT_DATASET_2026-11-03.md

