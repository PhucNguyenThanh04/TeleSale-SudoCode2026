# Đối chiếu dự án với đề SUDO CODE 2026, điều chỉnh và giải đáp BTC

Ngày kiểm tra: 15/11/2026. Checkout: `dd85593` và trạng thái working tree tại thời điểm kiểm tra. Đây là báo cáo đối chiếu, không sửa implementation hoặc dữ liệu BTC.

**Cập nhật sau rà soát:** Đã sửa riêng blocker chuẩn bị BTC ở mục 10: runner tạo snapshot trực tiếp từ `--btc-root`, không cần patch riêng. 96 kiểm thử tập trung đã qua offline; chưa chạy model/DB thật. Các kết luận còn lại bên dưới giữ theo thời điểm audit.

**Kết luận:** Dự án đã triển khai được phần lõi của bài toán: chat tự trả lời, nhận diện đa kênh, bộ nhớ ba tầng, Call Brief, harness có kiểm soát, bốn MCP, nghiệp vụ bán hàng, handoff và hạ tầng đánh giá/cải tiến. Đã có một cặp full/baseline thực tế vượt ba ngưỡng chất lượng hội thoại theo số scorer lưu. Tuy nhiên **chưa đủ bằng chứng nghiệm thu toàn bộ M1**: extractor còn cần duyệt, TTFT vượt ngưỡng, corpus/audio chưa chứng minh đủ quy mô, ASR thiếu bộ bằng chứng có thể kiểm lại trên máy này, vòng cải tiến còn hồi quy, lệnh eval hiện bị lỗi chuẩn bị BTC và hồ sơ nộp còn thiếu.

**Cách đọc trạng thái**

- **Đã có:** implementation hoặc artifact cụ thể đã tìm và kiểm; phạm vi bằng chứng được ghi ngay trong dòng.
- **Một phần:** đã làm nhưng còn thiếu một điều kiện, còn ca lỗi hoặc mới có test giả lập.
- **Chưa chứng minh:** chưa tìm thấy artifact đủ để xác nhận; không có nghĩa chắc chắn chưa làm ở máy/kho khác.
- **Chưa đạt:** có phép kiểm cụ thể trả về không thỏa yêu cầu.
- Không chuyển số lượng unit test thành điểm chất lượng model. Không dùng một lần chạy lịch sử làm chứng nhận cho code hiện tại.

## 1. Nguồn và thứ tự áp dụng

Đã đọc nội dung toàn bộ 17 trang PDF, gồm A–G và các phụ lục A–C; đọc toàn bộ `DIEU-CHINH-DE.md`, `GIAI-DAP-MENTOR.md`, README gói BTC; đọc schema scenario/trace/brief/tool và hướng dẫn latency để kiểm các điều kiện liên quan. Đối chiếu với mã nguồn, scenario, audio cục bộ và artifacts đã lưu; kiểm hash/schema bằng công cụ offline của dự án.

| Nguồn | Cách sử dụng |
|---|---|
| [Đề gốc](../../SUDO%20CODE%202026%20-%20Đề%20Bài%20Dự%20Án%20Cuối%20Kì.pdf) | Yêu cầu chính C.1–C.6, D, F, rubric G và công thức phụ lục A. |
| [Điều chỉnh](../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md) | Ưu tiên khi thay/bổ sung đề gốc, đặc biệt latency, ASR, tool, RAG, trace, test ẩn. |
| [Giải đáp](../../BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md) | Làm rõ cách hiểu: đa phiên, đa kênh, handoff, baseline, cách đo, UI và model. |
| [Gói dữ liệu](../../BTC-Data-Vong1-TEAMS/README.md) | Quy trình chấm chéo, dữ liệu công khai/ẩn và ngày nghiệp vụ. |
| [Kiến trúc dự án](m1-architecture.md), [nghiệm thu](m1-acceptance.md) | Dùng tìm implementation; không coi phát biểu trong tài liệu là kết quả đo. |

Không lấy bảng tự đánh giá cũ `DANH_GIA_BTC_VA_AI_SERVICES.md` thay rubric BTC. Một số tài liệu dự án nói chỉ có 7 sample/39 lượt hoặc chưa có run mới đã lỗi thời so với artifacts tìm thấy dưới đây.

## 2. Bằng chứng hội thoại mới nhất tìm thấy

Run đầy đủ mới nhất có score trong cây kết quả:

`ai-services/eval_harness/results/knowledge-triplet-final/20261113T194849Z-e1e46a43/k0/20261113T194849Z-e62e734b/`

Thời gian bắt đầu: 13/11/2026 19:48 UTC, tức **14/11/2026 02:48 giờ Việt Nam**. Không chọn run có TSR cao nhất để đại diện; dùng run đầy đủ mới nhất đã tìm được. Đây là nhánh K0 của thí nghiệm knowledge, không phải bằng chứng thí nghiệm ba nhánh đã hoàn tất.

| Nội dung | Kết quả kiểm |
|---|---|
| Quy mô | 29 scenario, 67 phiên, 170 lượt mỗi cấu hình; 28 scenario đa phiên, 15 ca khó. |
| Định danh | 29 số khách khác nhau trong bộ scenario; 14 scenario có nhiều kênh. Đây là số đếm bộ test, không phải chứng nhận corpus C.1. |
| Model | `gemma4:31b`, provider ghi `ollama.com`, temperature 0,2, max_tokens 256, seed 7. |
| Đối chứng | Cùng model/tham số, source digest, seed digest, hardware và guardrails giữa full/baseline. |
| Tính toàn vẹn | Công cụ `m1_acceptance run` xác nhận score, hash, manifests và trace schema khớp. |
| Execution | `healthy`; answer guardrails bật ở cả hai cấu hình. |
| Warmup | Manifest và runner report đều ghi 3 lượt. |
| Code hiện tại | Source digest hiện tại khác digest của run. Các số là bằng chứng lịch sử đã kiểm, chưa phải lần đo lại checkout ngày 15/11. |

**Bảng so sánh theo score đã lưu**

| Chỉ số | Baseline không nhớ | Full | So với đề |
|---|---:|---:|---|
| Repeat-Question Rate | 31,6% | 3,7% | Giảm tương đối 88,3%, vượt mốc 40% theo scorer. |
| Context Carryover Rate | 15,2% | 63,3% | Full cao hơn 48,1 điểm phần trăm; còn 29/79 fact bắt buộc chưa được tính dùng đúng. BTC không đặt ngưỡng CCR tối thiểu riêng. |
| Task Success Rate | 69,0% = 20/29 | 79,3% = 23/29 | Full vượt mốc 70%. |
| TSR ca khó | 73,3% | 80,0% | Đã báo tách theo điều chỉnh §11. |
| HR toàn bộ claim được scorer kiểm | 0/40 | 0/52 | Có số đo, nhưng không bao phủ mọi candidate. |
| HR giá/khuyến mãi | 0/34 = 0% | 0/38 = 0% | Qua mốc ≤5% trên phần claim scorer kiểm được. |
| Số lượt trung bình/cuộc | 2,54 | 2,54 | Kịch bản replay cố định; không chứng minh hệ thống làm cuộc gọi ngắn hơn. |
| Calls-to-Close | 1,35 trên 17 ca chốt | 1,48 trên 21 ca chốt | Full chưa tốt hơn ở chỉ số này; tập ca chốt của hai mode khác nhau. |
| Guardrail violations | 0 | 0 | Không có vi phạm bị scorer phát hiện trong run này; không suy thành bảo đảm mọi ca ẩn đều an toàn. |
| TTFT p95 | 3.811 ms | 4.068 ms | **Chưa đạt ≤3.000 ms.** |
| Total p95 | 3.811 ms | 4.068 ms | Đạt ≤8.000 ms trên run này. |
| Call Brief | Không áp dụng | p95 250 ms, tối đa 264 ms trên 38 mẫu | Trong giới hạn M1 ≤5 giây với mẫu đã ghi. |

Chat không streaming nên **TTFT = Total**, đúng quy tắc 7 của BTC; không được bỏ qua ngưỡng TTFT chỉ vì total dưới 8 giây.

**Giới hạn rất quan trọng của số đo:** `extraction_status = needs_review`. Ở full, extractor ghi 223 claim candidate, phát ra 141, còn 67 chưa giải quyết và 15 loại trừ; 28 câu hỏi đã phát còn không chắc về slot/type. Đây không phải 223 claim đã được xác minh, cũng không phải recall của extractor. Scorer chỉ đối chiếu được 52 claim, trong đó 38 giá/KM. Vì vậy phát biểu đúng là “HR=0% trên claim đã trích và chấm”, không phải “hệ thống không còn bịa”. BTC còn kiểm tay ngẫu nhiên 20 lượt theo README gói dữ liệu.

Kết quả công cụ nghiệm thu phần hội thoại: **`conversation_accepted = false`**. Hai check fail là `extraction_review` và `ttft_p95`. Công cụ này cũng ghi rõ còn cần ASR, hai vòng cải tiến có duyệt, demo và chi phí; kể cả nó pass cũng chưa chứng nhận toàn bộ M1.

## 3. Đối chiếu bốn case và năm mục tiêu B

| Mục tiêu | Trạng thái và bằng chứng |
|---|---|
| Case 1: khách gọi lại, không hỏi từ đầu | **Đã có, còn lỗi.** Identity → memory → brief → opening đã triển khai; RQR full 3,7% so với 31,6%, CCR 63,3%. Chưa thể nói không hỏi lại bất kỳ thông tin nào. |
| Case 2: hợp nhất Facebook/Zalo/hotline và giải quyết giá lệch | **Đã có nền tảng.** `session_identity.py` resolve phone/fb_id/zalo_id về CRM; `context.py` tách giá lịch sử và giá hiện tại, refresh quote/stock; 14 ca đa kênh. Chưa chứng minh mọi tình huống ba nguồn giá mâu thuẫn đều xử lý đúng. |
| Case 3: bàn giao có ngữ cảnh | **Đã có.** Working state ghi theo lượt; `handoff_brief.py` dựng brief từ trạng thái hiện tại, tool `handoff.transfer` có trong trace thật. Test kiểm câu hỏi đã giải quyết không bị đưa lại vào brief. Không bắt buộc routing tổng đài. |
| Case 4: tự đánh giá và học từ cuộc gọi | **Một phần.** Có scorer, feedback, knowledge worker, reviewer, regression/release/rollback. Chưa có kết luận cải tiến hai vòng hoàn chỉnh không hồi quy; xem mục 7. |
| B.1: audio/text tiếng Việt → ngữ cảnh cấu trúc | **Đã có implementation**, ASR local, chuẩn hóa, extraction và replay; **thiếu bằng chứng ASR đủ tập** trên máy này. |
| B.2: nhớ xuyên phiên và mở đầu tiếp nối | **Đã có bằng chứng định lượng**, nhưng CCR còn thiếu và extractor cần review. |
| B.3: harness truy hồi → lập kế hoạch/tool → quan sát → nhớ, guardrail/fallback | **Đã có.** Graph chung và business tool-loop; không chỉ là chuỗi prompt đặt tên agent. |
| B.4: đo tốt hơn baseline không nhớ | **Đã có cặp so sánh**, tốt hơn về RQR/CCR/TSR trong run mới nhất; chất lượng phép trích vẫn là điều kiện chưa đóng. |
| B.5: cải tiến không fine-tune | **Đã có cơ chế**, chưa đủ chứng minh hiệu quả vòng cải tiến theo C.5. |

## 4. C.1 — Dữ liệu và xử lý tiếng Việt

| Yêu cầu | Hiện trạng kiểm được | Kết luận |
|---|---|---|
| ≥120 cuộc transcript | Bộ test có 67 phiên. `speech/dialogues/` có 11 synthetic +11 clone template +22 phiên 2 =44 bản thoại; có quan hệ tái sử dụng với scenario. Chưa có manifest corpus hợp nhất loại trùng đạt 120. | **Chưa chứng minh đủ**; không cộng lặp speech và scenario để tăng số lượng. |
| ≥40 audio và ≥1 giờ | Tìm thấy 22 WAV trong `dataset/`, tổng 1.173,131 giây =19 phút 33 giây. Hai ZIP chứa lại các bộ này, không phải audio mới. 22 thoại phiên 2 là JSON, chưa thấy WAV tương ứng. | **Chưa đạt trên dữ liệu cục bộ:** thiếu ít nhất 18 file và khoảng 40 phút 27 giây. |
| ≥30 khách có ≥2 cuộc | Bộ scenario có 28 ca đa phiên, 29 số khách tổng. Bộ thoại speech phiên 2 liên kết 22 nguồn nhưng chưa có manifest tổng xác nhận thêm khách độc lập. | **Chưa chứng minh đủ 30 khách**, dù đã đủ ngưỡng 20 scenario của C.4. |
| ≥10 khách có cả gọi và chat | 14 scenario có nhiều kênh; mapping phone/Zalo/Facebook được khai báo theo CRM và preflight qua. | **Đủ về độ phủ bộ scenario M1**; giữ mapping khi đóng gói corpus. |
| ≥1 ngành, ≥30 SKU | BTC có 40 sản phẩm thuộc 3 ngành, 96 biến thể; có loader, catalog service và tool sử dụng nguồn đó. | **Đã có**, dùng dữ liệu chung là đúng điều chỉnh. |
| ≥2 miền giọng | Có nhãn Bắc/Nam, nhưng bản audit dataset ghi các nhãn vùng đang dùng cùng hai Edge voice ID HoaiMy/NamMinh. | **Chưa chứng minh** có hai accent thật; nhãn metadata không đủ. |
| ≥3 persona: do dự/người nhà, so giá, hậu mãi đổi size/khiếu nại | Có đủ loại trong scenario và speech. | **Đã có về thiết kế dữ liệu.** |
| Dữ liệu hợp lệ, ẩn danh/được phép | Nguồn khai báo synthetic/TTS, có manifest; không thấy cơ sở để kết luận dùng ghi âm khách thật trái phép. | **Có mô tả nguồn**, chưa nghe/kiểm độc lập toàn bộ audio. |
| ASR local, không train | `speech/asr.py` có faster-whisper/PhoWhisper local, VAD, cleanup và model loading; speech serving cũng có STT riêng. | **Đã có implementation**, không cần API ASR cho M1. |
| WER/CER trên audio BTC +≥20 file team | Có 22 file team. Gói BTC hiện chỉ có 4 GT mẫu D01–D04, chưa thấy WAV BTC. Không tìm thấy `speech/data` hoặc `score.json`/`comparison.json` ASR trên checkout này. | **Chưa chứng minh đo đủ**. Thiếu audio BTC đầy đủ có phần phụ thuộc BTC phát dữ liệu. |
| Entity Accuracy tiền/SĐT, chuẩn hóa đúng BTC | Có `speech/entities.py`, `normalize.py`, `vi_numbers.py`, scorer adapter và kiểm evidence. | **Đã có code**, thiếu báo cáo hash-bound kiểm lại được ở đây. |
| Số tiền/số điện thoại/ngày hẹn | Có TN/ITN, entity extraction, callback parser và ngày nghiệp vụ tin cậy. Test text/entity trong batch kiểm tra đã qua. | **Đã có implementation**, chưa bảo đảm mọi cách nói/ASR đều đúng. |
| Teencode/không dấu/code-switching | Có lexicon, folding trong catalog/query, input ASR/teencode của scenario và prompt/tool hiểu tiếng Việt. | **Đã có xử lý**, chưa có điểm chất lượng riêng trên một tập phủ đầy đủ. |
| Intent/sản phẩm/size/màu/giá/hẹn/người quyết định/outcome | Có schema LangMem/episode, consultation state, decision makers, tool facts và outcome. Không chỉ lưu transcript thô. | **Đã có**, correctness toàn tập chưa được đo độc lập. |
| PII khi log/gửi model ngoài | `mcp_shared/pii.py`, `context.py`, guardrails và observability mask số/email/địa chỉ/tên; handoff/business giữ riêng thông tin cần nghiệp vụ. | **Đã có cơ chế**, 0 vi phạm bị phát hiện trong run; regex không phải chứng minh bao phủ tuyệt đối. |
| Working memory | Committed turns, session history, tool observations; runtime/session state. | **Đã có.** |
| Episodic memory | Worker/tóm tắt và episode state có topic, open item, outcome, source. | **Đã có.** |
| Profile memory | Fact theo customer/scope, admission, projection và nguồn. Trace mới nhất có memory_writes ở 98/170 lượt. | **Đã có**, số lượt ghi không phải độ chính xác memory. |
| Ghi gì/không ghi gì | Admission đối chiếu owner, customer/tool evidence, slot/type và nguồn lượt; không mặc định mọi lời agent là fact khách. | **Đã có.** |
| Khách đổi ý, vô hiệu giá trị cũ | Có set/supersede/delete, revision barrier/tombstone; test memory carryover qua. Scorer có một check budget “likely_ok”, chỉ là heuristic. | **Đã có cơ chế**, không coi “likely_ok” là kiểm toàn bộ state. |
| M2 TTL/provenance/chống poisoning | Có valid_until, cảnh báo >180 ngày, source turn, identity ambiguous, admission và erasure barrier. | **Một phần M2 đã triển khai**, chưa kiểm toàn bộ ca ẩn/người chung SĐT thực tế. |

Speech README ghi kết quả lịch sử trên team22: B2 WER 14,1%, CER 10,0%, Entity 74,8%; B0 WER 38,3%. Đây là **số được tài liệu báo lại**, không phải artifact ASR đã xác minh được trong lần kiểm này. Baseline B0/B1/B2 speech cũng **không thay** baseline bỏ memory của harness.

Các yêu cầu dữ liệu/xử lý M2 được tách riêng để không bỏ sót bảng đề gốc:

| Yêu cầu M2 | Đối chiếu |
|---|---|
| ≥250 transcript, ≥100 audio/≥3 giờ | Chưa có corpus chứng minh; 22 WAV/19 phút 33 giây hiện có chưa đủ. |
| ≥60 khách đa phiên, có khách ≥3 phiên | Có nhiều scenario 3 phiên, nhưng chưa đủ 60 khách. |
| ≥30 khách gọi+chat | 14 scenario đa kênh hiện kiểm được, chưa đủ 30. |
| 3 ngành, 3 miền giọng | Catalog/speech có gia dụng, thời trang, mẹ-bé; chưa chứng minh ba miền giọng thật. |
| ≥20% audio nhiễu | Audit bộ 22 file ghi 7 file có nhãn noisy (31,8%); chưa nghe kiểm mức nhiễu. Nhãn đạt tỷ lệ không bù thiếu tổng số audio/thời lượng. |
| ≥100 SKU | Catalog chung có 40 sản phẩm và 96 biến thể; không cộng sản phẩm và biến thể để tự nhận ≥100 sản phẩm. Điều chỉnh yêu cầu dùng catalog BTC; chưa có xác nhận riêng cách BTC áp ngưỡng catalog M2 khi dùng bộ chung. |
| Diarization agent/khách | Segment A/C của dataset là annotation có sẵn. `speech/replay.py` dùng oracle boundaries, không phải diarization dự đoán; chưa có điểm diarization. |
| Sửa tên sản phẩm/ASR, nhiễu, streaming | Có lexicon/hotwords/cleanup và speech serving; chưa có số đo đầy đủ trên audio BTC hoặc TTFA real-time chuẩn M2. |
| Objection/cách xử lý, sentiment, cam kết | Có slot objection, episode/open item và trường sentiment trong brief; chưa chứng minh extraction/đánh giá đầy đủ tất cả trường nâng cao. |
| Tokenization PII và xóa toàn bộ khách | Có masking và workflow erasure phối hợp memory/knowledge, barrier chặn hồi sinh dữ liệu. Chưa kiểm xóa toàn bộ trên DB/artifact thực tế; masking không đồng nghĩa đã có tokenization nghiệp vụ đầy đủ. |
| Semantic/KB memory | Có MCP Knowledge, Cloudflare dense embeddings + BM25/Qdrant và kiểm hiệu lực nguồn; chất lượng retrieval vẫn cần benchmark hiện hành. |

Các lựa chọn công nghệ/lộ trình mục E là **gợi ý**, không phải điều kiện phải dùng đúng framework, model hoặc phải fine-tune.

## 5. C.2 — Harness và Session Continuity

| Yêu cầu | Bằng chứng / giới hạn | Kết luận |
|---|---|---|
| Nhận diện qua SĐT | `initialize_identity` gọi `crm.get_customer`; có ownership và ambiguous handling. | **Đã có.** |
| Call Brief trước lượt đầu | `prepare_session` → `load_context`; UI nhận brief khi session bắt đầu. Có products/giá cũ/blocker/số phiên/next action/must_not_ask. | **Đã có.** |
| Mở đầu xác nhận tiếp nối | `brief_opening.py`, business prompt và test `test_returning_opening.py`. | **Đã có**, chưa hoàn hảo trong trace. |
| Không hỏi lại thông tin đã biết | Có known slots/must_not_ask và memory context. Full vẫn có 1 câu bị scorer tính thừa trong mẫu mới nhất. | **Một phần**, RQR tốt nhưng không bằng 0. |
| ≥3 business tools, schema rõ | Trace thật chứa CRM/catalog/inventory/pricing/order create-update-status/callback/handoff/policy. | **Đã có, vượt mức tối thiểu.** |
| Giá/KM từ tool | Có quote hiện hành, stock, accepted offer, check_grounding/check_answer và chống nhầm discount với giá bán. | **Đã có cơ chế**; HR=0% có giới hạn extraction nêu trên. |
| Giải thích prompt/context dài | `context.py` mask và tách customer facts/sales history/episodes; session history cắt theo `prompt_history_turns` (run ghi 6). | **Đã có thiết kế**, chưa chứng minh nén tự động ngữ cảnh dài M2. |
| Khi gọi tool/khi không | BusinessTools/tool budget/precondition/consent; không tạo đơn khi chỉ hỏi, không lấy catalog result làm consent. | **Đã có.** |
| Tool timeout/ASR rác/LLM lỗi format | Schema validation, diagnostics, fallback và recovery; câu trả lời không chỉ dựa lời hứa tạo đơn. | **Đã có nhánh xử lý**, chưa đo đầy đủ mọi lỗi dịch vụ thật. |
| Khi chuyển người và bàn giao gì | Structured handoff có required fields và kiểm nguồn; ngoài phạm vi có thể transfer. | **Đã có**; routing thật không bắt buộc. |
| Chat text + file audio offline | Chat runtime thật; speech/replay/asr_inputs dùng cùng pipeline, có mapping và hash. | **Đã có các khớp nối**, chưa có run ASR→harness đủ corpus để nghiệm thu. |
| Call Brief ≤5 giây | 38 mẫu run mới nhất, tối đa 264 ms; refresh current quote/stock nằm trong prepare path. | **Đạt trên run đã lưu**; không suy thành SLA mọi trường hợp. |
| TTFT p95≤3 giây | 4.068 ms full, 3.811 ms baseline. | **Chưa đạt.** |
| Total p95≤8 giây | 4.068 ms full. | **Đạt trên run đã lưu.** |
| Demo 1 phiên | Có gateway/chat/session lifecycle, kiểm offline. | **Có khả năng triển khai**, chưa chạy lại demo dịch vụ thật trong lần audit. |
| M2 refresh KM/tồn kho | `context.py` kiểm theo ngày, cảnh báo giá cũ/hết hàng/ngừng bán/successor. Có giới hạn với nhiều SKU mơ hồ, sẽ cảnh báo chưa refresh. | **Đã có một phần M2**, không khẳng định mọi brief refresh toàn bộ sản phẩm. |
| M2 barge-in | Frontend/backend có interruption/playback ack; memory chỉ commit phần đã phát. | **Đã có implementation**, chưa đo TTFA/tải đồng thời với model thật. |
| M2 khách gọi từ số lạ | Có cơ chế ranh giới danh tính và tài khoản demo gắn CRM; chưa có bằng chứng nhận lại đúng khách từ số lạ hoặc voiceprint. | **Chưa chứng minh đầy đủ.** |

## 6. C.3 và C.4 — MCP, test và phép đo

| Yêu cầu | Hiện trạng | Kết luận |
|---|---|---|
| Chọn MCP hoặc A2A, giải thích lý do | Kiến trúc chọn MCP; agent gọi nghiệp vụ qua `MCPGateway`. Không cần đồng thời làm A2A. | **Đã có.** |
| ≥2 MCP, bắt buộc mcp-memory | Có mcp-memory, mcp-catalog, mcp-order, mcp-knowledge; entrypoint/server/handlers và Compose riêng. | **Đã có, vượt M1 về số server.** |
| Tích hợp thật, không chỉ đặt tên | Manifest ghi tool_mode=mcp; execution healthy; trace có quan sát nghiệp vụ, memory và tool result. | **Có bằng chứng run thật**, chưa kiểm lại dịch vụ đang chạy. |
| M2 phân quyền tool đọc/ghi | Có token nội bộ, ownership, trusted policy context, reviewer permissions. Không thấy bằng chứng hoàn tất một ma trận quyền riêng cho mọi business tool. | **Một phần M2.** |
| ≥20 ca đa phiên +≥5 ca khó | Offline checker: 28 đa phiên, 15 khó, 38 phiên quay lại có nhãn memory, 29/29 có success criteria cuối. | **Đạt về quy mô/contract.** |
| Scenario độc lập của team | 22 ca team và 7 ca dựa public sample, tổng 29; không gọi cả 29 là bộ holdout mới. | **Có bộ phát triển**, tính độc lập/khóa holdout chưa chứng minh. |
| Một lệnh eval, bảng chỉ số | Có root `run_eval.py`, paired runner, report_metrics, scorer BTC và trace audit. | **Có implementation**, nhưng lệnh khởi chạy với gói BTC được gửi hiện bị blocker ở mục 10. |
| 5 chỉ số bắt buộc | Có RQR/CCR/TSR/HR; WER/CER/entity có code riêng. | **Một phần:** thiếu evidence ASR xác minh được trên máy này. |
| Baseline cùng test/model/tham số | Cặp mới nhất qua hash/pair audit; baseline tắt prior memory, giữ current-session history. | **Đã có**, baseline đúng không phải xóa toàn bộ working memory. |
| RQR giảm≥40%, TSR≥70%, HR giá/KM≤5% | 88,3%; 79,3%; 0% theo scorer mới nhất. | **Qua số đo đã lưu có điều kiện review extraction.** |
| Trích questions/claims minh bạch | Có extractor, sidecar, fingerprint, unresolved counters. | **Có giải thích nhưng chưa đóng review**; không được bỏ candidate khó rồi công bố không sai. |
| Assertions theo scenario | `success_if` và scorer tham chiếu; có call/order/status/args/guardrail checks. | **Đã có**, 6/29 ca mới nhất vẫn fail. |
| Phân tích≥10 lỗi | [m1-error-analysis-20261109.md](m1-error-analysis-20261109.md) phân tích 15 trường hợp với vị trí trace. | **Đã có**, cần hiểu đây là mốc cũ; không gán nguyên lỗi đó cho model mới. |
| M2≥40 scenario + simulator | Hiện có 29; chưa tìm thấy customer simulator thực thi đúng 8 luật/3 seed/patience logs. | **Chưa đạt/chưa chứng minh M2 này.** |
| M2 LLM judge, rubric, chấm tay≥20, Cohen's kappa | BTC có rubric tham chiếu; chưa tìm thấy bộ kết quả human/judge/kappa của team. | **Chưa chứng minh.** |
| M2 RAG Recall@3/@5, multi-hop, abstain/false-abstain | Có hybrid retrieval và policy guards. Tài liệu RAG 29/10 ghi baseline lexical cũ đã bị thay; không có benchmark hiện hành đủ 60 QA/metric chuẩn được xác minh. | **Có RAG, chưa đủ số đo M2.** |
| M2 Tool-Call Accuracy | Có diagnostics, schema validation và assertion nghiệp vụ; chưa tìm thấy một số đo Tool-Call Accuracy hiện hành có công thức/đáp án tương ứng. | **Chưa chứng minh chỉ số này.** |

Sáu scenario fail trong run mới nhất: SC-T06 (inventory ở call_3), SC-T09 (inventory ở call_1), SC-T18 (order.create call_2), SC-T19 (order.create call_1), SC-T20 (order.update call_2), SC04 (order.create call_2). Đây là failure theo assertion scorer; cần đọc trace để phân biệt lỗi agent, lời khách cố định và precondition nghiệp vụ, không tự sửa nhãn cho pass.

## 7. C.5 — Feedback và hai vòng cải tiến

| Yêu cầu | Bằng chứng | Kết luận |
|---|---|---|
| Không fine-tune | Cơ chế dùng runtime memory/knowledge revisions/release; không thấy pipeline train là cơ sở của cải tiến đang báo. | **Phù hợp thiết kế.** |
| ≥2 nguồn feedback | Event schema nhận business_outcome, runtime_signal, evaluation_result, operator_feedback; turn commit có enqueue runtime/outcome; exporter nối score→feedback. | **Đã triển khai nhiều nguồn**, chưa kiểm DB để xác nhận lượng thu thực tế từng nguồn. |
| ≥1 cơ chế cải tiến | Knowledge Gap: event→job/gap→draft nguồn/test→approval→release→activate. | **Đã có implementation và UI.** |
| Tự thêm regression | `build_regression_draft` sinh expected source/answer; approval ràng test hash; publish giữ snapshot. | **Đã có**; check lexical không thay kiểm đúng câu trả lời LLM. |
| Thay đổi cần người duyệt | Revision/source/regression approval, permission, reason và activate/rollback; có trang `/knowledge`. | **Có workflow duyệt**. Nhánh experiment tự duyệt nguồn không được tự gọi là bằng chứng người đã duyệt. |
| Hai vòng trên test giữ nguyên | Có K0-final và K1-final; `improvement_evidence` xác nhận controls so sánh hợp lệ. | **Đã có hai lần chạy so được.** |
| Chứng minh cải thiện | K0→K1: TSR79,3→82,8%; CCR62,0→63,3%; HR giá11,1→10,5%; nhưng RQR0→7,7%. Extractor cả hai needs_review. | **Một phần**; có tăng ở vài chỉ số và có hồi quy, chưa phải kết luận cải tiến hoàn chỉnh. |
| Bảo vệ khi học nhầm/rollback | Có validate public source/hash/date, không biến giá động thành FAQ, activation CAS và rollback release. | **Đã có cơ chế**, chưa chứng minh rollback thực tế trong thí nghiệm hoàn chỉnh. |
| M2≥2 cơ chế, ≥3 vòng, phân tích hại | Chưa tìm thấy bằng chứng Exemplar Bank/Reflection/A-B đạt yêu cầu; triplet mới nhất chỉ chạy K0. | **Chưa chứng minh M2.** |

Lệnh kiểm offline K0→K1 trả: `comparability_valid=true`, `complete=false`, `improvement_demonstrated=false`, regression=`repeat_question_rate`. Đây là cổng kiểm riêng của dự án, không phải tuyên bố BTC cấm mọi tradeoff; báo cáo cần trình bày thẳng cả lợi lẫn hại thay vì chỉ lấy TSR tăng.

Thí nghiệm mới nhất `knowledge-triplet-final/20261113T194849Z-e1e46a43/experiment.json` có `status=no_eligible_gaps`, phase=`reviewed`, approved=[]; chưa có K1/K2. Vì vậy tên “triplet” không chứng minh đã chạy ba vòng hay đã học thêm tri thức.

## 8. C.6, D, F và tiêu chí G

| Yêu cầu | Hiện trạng | Kết luận |
|---|---|---|
| Web chat agent nói trực tiếp với khách | `/chat`, backend text API/WebSocket và runtime chung. | **Đã có implementation.** |
| Hiện Call Brief khi khách quay lại | `frontend/chat.js` render brief trước tin đầu; voice UI cũng render. | **Đã có.** |
| Timeline khách: tương tác gì/khi nào | Chat hiện brief, số phiên và memory changes từng lượt. Chưa thấy timeline lịch sử tất cả phiên với thời điểm/nội dung đầy đủ. Voice có ngày phiên gần nhất nhưng cũng không thay timeline toàn bộ khách. | **Một phần UI M1.** |
| Demo hai cuộc: tư vấn/hỏi người nhà→quay lại/chốt | Có kịch bản, docs và trace đa phiên thực tế. | **Có nền tảng**, chưa có video/rehearsal hiện hành được kiểm. |
| Chạy eval trực tiếp trong demo | Có CLI và artifacts; hiện bị thiếu patch khi khởi chạy mới. | **Chưa sẵn sàng theo hướng dẫn hiện tại.** |
| Tiếng Việt tự nhiên/xưng hô theo ngữ cảnh | Prompt, honorific CRM, câu opening/fallback tiếng Việt. | **Đã có**, chưa có chấm người đủ tập về độ tự nhiên. |
| Không giả là người nếu bị hỏi | Guardrail/prompt và scorer guardrail_violations; run mới không phát hiện claims_human. | **Có cơ chế/bằng chứng trong tập đã chạy**, không suy thành bao phủ mọi cách hỏi. |
| README/cài/chạy/khởi tạo dữ liệu | Có loader, Compose, run_system và runbook. | **Đã có tài liệu/code**, chưa chứng minh máy sạch; blocker eval là cụ thể cần khắc phục. |
| Dataset kèm cách sinh/phân bố/hạn chế/PII | Có speech guide, dataset manifest và audit; audio đang ignored, README yêu cầu chia sẻ riêng. | **Một phần hồ sơ**; cần gói dữ liệu và manifest bàn giao thật. |
| Tài liệu kiến trúc/sơ đồ/memory/tools/quyết định | Có `m1-architecture.md`, READMEs và cấu hình MCP. | **Đã có.** |
| Báo cáo metric/baseline/trước-sau/≥10 lỗi | Có score/manifests/error analysis; trước-sau chưa đóng review, ASR chưa bind đủ. | **Một phần**, chưa có bộ báo cáo nghiệm thu hoàn chỉnh. |
| Video5–8 phút và slide≤15 trang | Không tìm thấy MP4/WebM/PPTX/ODP trong phạm vi dự án đã kiểm, không có liên kết bàn giao xác nhận trong tài liệu đã đọc. | **Chưa chứng minh**, có thể nằm ở kho ngoài. |
| Ước tính chi phí/cuộc | Có công thức và hướng dẫn; các aggregate xem được còn `cost_per_call_usd=null`. | **Chưa có con số xác minh** gồm tool-loop/retry/memory/ASR và giả định hạ tầng. |
| Khả năng mở rộng | Tách MCP/DB/worker, dễ thêm nghiệp vụ; lock/cache runtime process-local, README yêu cầu AI 1 worker. | **Có thiết kế**, chưa có kiểm tải/quy mô. |
| M2 copilot/cảnh báo nhân viên/dashboard | Có UI review knowledge và script visualize benchmark; chưa thấy copilot cho nhân viên hoặc cảnh báo cam kết sai của người thật hoàn chỉnh. | **Một phần hạ tầng**, không coi UI knowledge là copilot. |
| M2 voice TTFA≤2,5 giây/≥2 phiên đồng thời | Có voice/STT/TTS/ngắt lời; score mới không có TTFA, chưa có phép đo đồng thời đủ điều kiện. | **Chưa chứng minh.** |
| Điểm thưởng toàn bộ local | Model run mới ghi provider ollama.com; Knowledge dùng Cloudflare embeddings. | **Không có cơ sở nhận thưởng toàn bộ local** với cấu hình đã đo. |
| Điểm thưởng voiceprint/playbook tự học/drift/tích hợp MCP ngoài đời | Chưa tìm thấy bằng chứng hoàn thành các tính năng đó. Shared-phone safeguards không đồng nghĩa có voiceprint. | **Chưa chứng minh**, không phải blocker M1. |

Không quy đổi các dòng trên thành “đạt X% dự án” hay điểm chính thức: rubric G chấm chất lượng theo 8 nhóm, không chia đều theo số checkbox. Phần mạnh hiện nằm ở kiến trúc/harness/MCP; phần thiếu bằng chứng ảnh hưởng trực tiếp dữ liệu, đánh giá, cải tiến và demo.

## 9. Đối chiếu riêng cả 12 điều chỉnh và giải đáp mentor

| Điều chỉnh BTC | Trạng thái áp dụng |
|---|---|
| §1 Latency mới | Đã lưu TTFT/total/brief và warmup; total/brief qua run mới, TTFT fail. Không lấy latency trung bình thay p95. |
| §2 Catalog chung, dataset riêng, trace/scorer chuẩn | Có 22 ca team +7 sample, catalog chung và traces/schema/scorer; corpus còn thiếu và extractor cần review. |
| §3 Tên/params tool | Có tất cả tên bắt buộc, thêm quote_order/policy.search hợp lệ. Có schema/handlers, ngày tin cậy và test; chưa chứng nhận toàn bộ parity mọi args. |
| §4 Handoff tính task success | Đã có tool/brief/assertion và guardrail over-escalation; không đòi tổng đài/routing thật. |
| §5 Xác nhận lại nhiều lần vẫn bị phạt | Scorer BTC xử lý quy tắc; extractor phải phân loại đúng. Có case câu tiếp nối bị gán product/open cần duyệt, không chỉ nhìn số RQR. |
| §6 Precompute brief | Có `precomputed_parts`, episode summary, kiểm quote/stock khi prepare. Trường hợp nhiều SKU chưa xác định có warning, chưa khẳng định refresh toàn bộ. |
| §7 Recall@k trên QA BTC | Có RAG nhưng thiếu báo cáo hiện hành chuẩn@3/@5 trên 60 QA và corpus BTC. |
| §8 ASR local +BTC +≥20 file team | Local có, team có22 file; BTC WAV và score provenance hiện chưa đủ. |
| §9 Policy bẫy/version/nội bộ/multi-hop/abstain | Có metadata ngày/phiên bản, apply_policy_rules và safe transformations nội bộ. Chưa có số Recall/abstain/full-recall hiện hành đủ tập. |
| §10 Tool theo thời gian/variant/combo/promo | Code có inventory timeline, successor, variant delta, promo conditions, best exclusive promo, basket pricing và once-per-customer. Không từ code suy ra parity toàn bộ; có focused tests lịch sử. |
| §11 Test ẩn41/19 khó/PII/guardrail/hard TSR | Runner đọc schema mở rộng, có ca khó và chỉ số hard TSR/violations. Team chưa có test ẩn nên không thể kết luận pass41 ca. |
| §12 Simulator/judge chuẩn M2 | Chưa có simulator đủ8 luật/3seed và kết quả human≥20/Cohen's kappa. |

| Giải đáp mentor | Đối chiếu cụ thể |
|---|---|
| Team5 Q1: tự sinh dataset từ tuần1, không đợi hidden | Đã sinh transcript/audio/scenario riêng dựa BTC; chưa đủ corpus. |
| Team5 Q2: inbox rồi gọi vẫn là Case2 | Mapping đa kênh có thật trong scenario/CRM, không chỉ metadata nhắc tên kênh. |
| Team5 Q3: ghi working memory từng lượt, handoff giữa cuộc | Runtime persist từng lượt, brief đọc current state; không đợi cuối cuộc mới lưu toàn bộ. |
| Team5 Q4–5: handoff là success, không cần routing | Đã chọn structured transfer; không đánh trượt chỉ vì thiếu tổng đài thật. |
| Team5 Q6: brief từ identity→ready, refresh tính latency | Prepare path có load/refresh; số brief đo được tốt. Có giới hạn multi-SKU như trên. |
| Team5 Q7:≥100 lượt, bỏ3warmup, cùng ranh giới/model | Run mới có170/mode và warmup3; measurement ghi nonstreaming_total_btc_rule_7. |
| Team5 Q8: metric thêm không thay5metric | Có hard TSR/Calls-to-Close/diagnostics; thiếu ASR evidence thì metric thêm không bù được. |
| Team5 Q9: M1 agent tự trả lời, UI brief/timeline | Chat tự trả lời có; timeline khách vẫn một phần. |
| Team5 Q10: model gợi ý, không giới hạn size/tier | gemma4:31b/API không vi phạm; không cần đổi sang model nhỏ để đạt M1. Chưa có cost/cuộc. |
| Team5 Q11: xác nhận nhiều/đọc vẹt bị trừ | Có opening ngắn và checker; chưa chấm người đầy đủ chất lượng hội thoại. |
| Team8 Q1: cùng catalog/mock và hidden/scorer | Đã có nguồn chung/trace/pair audit; không gọi điểm team set là điểm hidden. |
| Team8 Q2: simulator chuẩn, 3 seed | Chưa chứng minh M2. Replay fixed customer_turns không phải simulator thích ứng. |
| Team8 Q3: Calls-to-Close | Đã xuất số, full 1,48 vs baseline 1,35; chưa chứng minh tốt hơn. |
| Team8 Q4: Recall cần labels BTC | Có QA BTC và RAG implementation; baseline lexical cũ không đủ chứng nhận retrieval hiện tại. |
| Team10 Q1: multi-turn/đa phiên, metric agent trên text; ASR riêng | Scenario và runner đúng hướng; chưa có bundle ASR đủ bằng chứng. |
| Team10 Q2: ASR local, M1 text đủ, voice là M2 | Đã có localASR/chat; thiếu TTFA không làm trượt riêng M1. Các blocker M1 nằm ở mục khác. |

## 10. Blocker tái lập tại thời điểm audit — đã sửa sau đó

Working tree ban đầu đã có ba file BTC update bị xóa; báo cáo không khôi phục hay sửa chúng:

- `BTC-cap-nhat-11-2026/eval/mock_tools.py`
- `BTC-cap-nhat-11-2026/eval/reference_eval.py`
- `BTC-cap-nhat-11-2026/schemas/tools.schema.json`

`eval/run_eval.py` và `eval_harness/run_official.py` vẫn gọi `prepare_btc_release`, còn `btc_release.py` mặc định yêu cầu thư mục đã xóa. Gọi **riêng hàm chuẩn bị dữ liệu**, không chạy model/DB, với gói BTC bạn cung cấp tái hiện được:

```text
btc_patch_missing:eval/reference_eval.py
```

Ba file tương ứng trong gói BTC bên ngoài hiện **đã có SHA-256 bằng bản snapshot của run mới nhất**. Vì vậy vấn đề nhìn thấy là code chuẩn bị còn yêu cầu cấu trúc patch riêng cũ; không có bằng chứng cần tìm/tải thêm một bản scorer khác. Cần sửa tương thích đường dẫn/định dạng release trước khi khẳng định lệnh README chạy được với gói hiện tại. Báo cáo chỉ ghi nhận, chưa sửa vì yêu cầu là đối chiếu.

## 11. Kiểm chứng đã chạy trong lần rà soát này

Không gọi live model, ASR, TTS, benchmark, embedding API; không query/reset/migrate DB và không khởi động hệ thống. Không chạy full suite.

| Phép kiểm offline | Kết quả |
|---|---|
| `eval_harness.preflight --offline-check` với scenario hiện tại/gói BTC | Qua: 29 scenario/67 phiên/170 lượt/15 ca khó. |
| `m1_acceptance dataset` | `dataset_ready=true`, 28 ca đa phiên, 38 phiên quay lại đủ hai nhãn memory. Chỉ chứng nhận conversation dataset contract. |
| `m1_acceptance run` trên K0 mới nhất và BTC snapshot đi kèm | Hash/schema/pair/execution/coverage qua; extraction và TTFT fail; `conversation_accepted=false`. |
| `improvement_evidence` trên K0-final/K1-final | So sánh controls hợp lệ; còn review extraction và hồi quy RQR; chưa chứng minh cải tiến hoàn chỉnh. |
| Đếm/header WAV cục bộ | 22 file, 1.173,131 giây. |
| Kiểm đường chuẩn bị BTC hiện tại | Tái hiện `btc_patch_missing` trước khi có bất kỳ model/DB call. |
| Batch test tập trung dưới đây | **100 passed**, 1 warning deprecation thư viện; không có test fail. |

Batch test đã chạy:

```bash
PYTHONPATH=.:ai-services:ai-services/test ai-services/.venv/bin/python -m pytest -q \
  ai-services/test/test_returning_opening.py \
  ai-services/test/test_structured_handoff.py \
  ai-services/test/test_memory_freshness_contract.py \
  ai-services/test/test_memory_carryover_repairs.py \
  ai-services/test/test_mcp_gateway.py \
  ai-services/test/test_policy_rules.py \
  ai-services/eval_harness/test_m1_acceptance.py \
  speech/test/test_text.py speech/test/test_entities.py
```

Các test này chứng minh các nhánh chức năng với fixture/mock, không thay điểm BTC hoặc demo dịch vụ thật.

## 12. Những việc còn cần để có thể tuyên bố hoàn thành M1

1. Khôi phục khả năng chạy CLI với gói BTC hiện tại; giữ nguồn/scorer đúng bản và không sửa ground truth để lấy điểm.
2. Duyệt/sửa extraction questions/claims, kiểm tay tối thiểu mẫu kiểm tra phù hợp rồi đánh giá lại trên cùng trace đã lưu khi có thể; không cần gọi model chỉ để kiểm lại phép trích.
3. Đạt TTFT p95 ≤3 giây trên đủ ≥100 lượt/mode; run hiện tại 4,068 giây chưa đạt. Sau thay đổi cần lần đo thật được cho phép và ghi cấu hình.
4. Bàn giao corpus hợp nhất ≥120 transcript, ≥40 audio/1 giờ, ≥30 khách đa phiên; chứng minh hai vùng giọng thật và không đếm trùng.
5. Có ASR evidence kiểm hash/score được trên ≥20 file team và audio BTC được phát; báo riêng tiền/SĐT/normalization, không lấy proxy TTS làm audio BTC.
6. Đóng vòng feedback→duyệt→release→đo lại; trình bày delta và ca hồi quy, giải quyết việc RQR tăng thay vì chỉ công bố TSR tăng.
7. Hoàn thiện timeline khách theo yêu cầu UI; rehearsal hai cuộc và eval thật, có video 5–8 phút, slide ≤15 trang, ước tính chi phí/cuộc và bộ artifact nộp có thể tải lại.

Không cần thêm voiceprint, simulator, copilot hoặc dashboard mới để đóng M1. Đây là các phần M2/điểm thưởng hoặc ngoài những thiếu sót M1 đã xác định.
