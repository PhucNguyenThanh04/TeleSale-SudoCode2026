# Các bất nhất nguồn BTC cần xác nhận

## Trạng thái sau khi sửa các lỗi runner và Call Brief

Trace và parser seed nhận số tiền hợp lệ theo trường nghiệp vụ, vẫn chặn CCCD/STK. Trace chấm dùng cùng cách xuất địa chỉ hợp lệ cho lượt trực tiếp và kết quả worker. Warm-up mô phỏng `memory.replay`. Seed trên SĐT dùng chung chờ danh tính được xác minh. Call Brief làm mới giá, khuyến mãi và tồn kho theo ngày cuộc gọi trước khi trả kết quả và che địa chỉ trong tóm tắt. Runner chấm áp dụng lịch callback của mock BTC. Demo áp dụng giờ tổng đài trong tài liệu chính sách.

Extractor ghi `cod_fee_vnd` và `first_exchange_fee_vnd` khi lời thoại khẳng định rõ. Scorer BTC chỉ tính các claim có trường tương ứng trong nhãn của ca. `eval-trace` dùng tên output riêng cho sidecar trích xuất để có thể chạy lại cùng cấu hình với tên trace mới.

Nguồn và scenario hiện vẫn khớp manifest; preflight lại qua 48/118/323/38. Không tìm thấy trace TEAM-* hoặc artifact judge/người chấm của bộ mới trong các thư mục kết quả hiện có. Corpus trong repo có 22 WAV duy nhất, 1173.13 giây (~19 phút 33 giây); WAV trong hai ZIP trùng hash với các file đã giải nén nên không cộng đôi. ZIP mã nguồn RC11 chưa có eval/scenario_final hoặc eval_harness/seed_memory.py. Các sửa đổi tương thích còn ở working tree, gồm file chưa tracked; cần chốt bản Git hoặc đóng gói mới trước khi bàn giao.

Nghiệm thu M1/M2 còn cần chạy Docker và Full/baseline bằng cấu hình chốt. Corpus M1 còn thiếu ít nhất 18 audio và khoảng 40 phút 27 giây. Audio public BTC, báo cáo ASR, simulator và nhãn người cho judge vẫn cần bằng chứng riêng.

## Kết quả sửa tương thích ngày 24/11/2026

Goal mới đã triển khai các thay đổi dưới đây trong checkout. Các quan sát lỗi ở mục rà soát ban đầu phía sau là trạng thái trước khi sửa. Simulator vẫn để sau; đây không phải nghiệm thu điểm M2 bằng model thật.

| Yêu cầu BTC | Thay đổi đã thực hiện | Bằng chứng |
|---|---|---|
| Ground truth v2 | Chép nguyên byte bản BTC cung cấp từ ground_truth copy.json sang ground_truth.json; D01 có sku/price list và D02 cùng khách D01. Không tự sửa nội dung scorer/mock/policy. | Hash mới 626092f31329b2cfd80ae28cc0ed7d9e5b832aec07a9e07048c112cb08d04363; hash cũ và provenance nằm trong manifest. |
| Seed có facts/phone/as_of | Parser nhận và chuẩn hóa, kiểm kiểu/ngày/PII; gateway xác minh đúng khách trên mọi định danh đã khai báo, không cho đổi chủ seed. | Test mẫu mới, ngày mặc định, ngày mâu thuẫn, kiểu sai, CCCD/STK, kênh xung đột và danh tính. |
| Seed vào memory trước hội thoại | SeedMemoryLoader dùng MemoryRepo/LangMemProjection hiện hành, tạo phiên UUID ổn định và fact/episode; chọn fact theo as_of, dùng extractor và evidence cho summary-only. Lịch sử không cấp quyền tạo đơn hoặc ownership; địa chỉ có private delivery/ngày gốc, summary trả lại được che cả contact đã biết dù thiếu dấu hiệu địa chỉ. | Test importer, lịch sử trích từ summary, giá/SKU có evidence, idempotency, thứ tự ngày, bảo vệ dữ liệu live, xóa dữ liệu và thứ tự chạy trước customer_turns ở cả Full/baseline. |
| Trace chấm và log | Trace giữ nguyên args đã thực thi và contact memory hợp lệ. Helper log vẫn che; dữ liệu CCCD/STK trong args bị từ chối xuất. Bộ kiểm redaction chỉ quét agent_text/memory_writes cho regex và vẫn bắt vi phạm trước khi che. | Test args/memory round-trip, regex chỉ nằm trong args, CCCD/STK, số tài khoản bắt đầu 0 và UUID có đuôi số không bị nhầm PII. |
| RQR baseline=0 | Hai RQR=0 được báo not_applicable, hiển thị CCR và yêu cầu BGK xét; Full>0 bị fail; thiếu số đo vẫn missing. | Regression cho 0/0, 0/>0, thiếu số đo, giảm đủ/không đủ; không sửa điểm BTC. |
| ASR public/private và entity | Đủ bốn public có binding hợp lệ có thể chứng minh pipeline, ranking_evidence=false. Oracle/per-dialogue dùng any-match list; chỉ số per-turn BTC được giữ trong report. | Test bốn public, nhóm BTC/team, hash audio/score, entity list và output per-dialogue; không chạy decode/model. |
| RAG restricted/unanswerable | Tiếp tục giữ retrieved IDs khi abstain; scorer mới được đóng snapshot. | Regression Recall@5 và abstain đều đạt 100% trong fixture hai câu, không phải kết quả model. |
| Key/endpoint/model và đóng gói | Env/Compose có endpoint Cloudflare, ASR model/device/precision và ElevenLabs tùy chọn; README ghi model/weights/phần cứng dự kiến, key BTC và audio public tự tạo. AI image kèm module speech để kiểm report ASR đã lưu; BTC snapshot có ground truth. | Test HTTP mock và CLI env; Compose config --quiet qua, không gọi provider. |
| Chốt bộ test | Manifest phiên bản m2-dataset-v2-btc-clarification-20261124 ghim 28 file BTC, hash DOCX và hash manifest/Git trước. TEAM-12 bổ sung facts có ngày từ summary CRM gốc. | Preflight: 48 ca, 118 phiên, 323 lượt, 38 ca khó. |

Kiểm chứng: nhóm compatibility có 198 test qua và một test lịch sử dùng artifact không còn trong checkout được deselect. Sau các chỉnh cuối, nhóm lifecycle/entrypoint có 66 test qua, một kiểm tra DB thật được skip theo chế độ offline; nhóm RQR/report có 46 test qua và một test artifact lịch sử deselect; bộ importer seed có 8 test qua, gồm factory cấu hình thật nhưng cấm kết nối mạng. Các nhóm có phần trùng nhau, không cộng số thành tổng test độc lập. Test tập trung cho endpoint/ASR CLI không chạy sinh/nhận dạng audio. Không chạy toàn bộ suite.

Giới hạn kiểm chứng: Docker config qua nhưng daemon từ chối quyền truy cập, nên chưa build/chạy lại image. Đã thử kiểm SQL trên instance tạm nhưng máy chỉ có PostgreSQL client, thiếu initdb/server nên chưa tạo hoặc kết nối DB nào. Môi trường AI test thiếu faster-whisper; bốn test decode/synth audio cũ chưa qua ở môi trường này, trong khi các test cấu hình mới đã qua. Bộ decoder thuộc image ASR riêng và không được thay đổi. Không có model live, API trả phí hoặc reset DB. Các điểm số lịch sử và ZIP cũ chưa được tạo lại hay coi là kết quả bản mới. Audio, nhãn người và đánh giá M2 thực nghiệm vẫn là công việc riêng.

## Cập nhật sau văn bản giải đáp BTC tháng 11/2026

Đã đọc toàn bộ `BTC-tra-loi-thac-mac-11-2026.docx` bên cạnh repo và đối chiếu gói BTC với manifest trước khi sửa. Văn bản giải đáp mới được ưu tiên khi README, scenario_format hoặc mô tả ground truth cũ chưa đồng bộ. Các quan sát dưới đây lưu lại lần rà ban đầu; trạng thái sau sửa ở mục trên.

- Trong 27 file BTC được manifest ghim: 26 file không đổi, chỉ `eval/reference_eval.py` khác hash. Catalog, CRM, promotion, toàn bộ 14 policy, schema tools/trace và persona/rubric đều giống bản đã rà trước.
- Scorer cũ: `cca362cf74bc070a37493af756a2963d02bfca8004c5d964e9e4ca0a67b48807`; scorer hiện cài: `730cc9cfc4b9531cebaf5936063fbb87805d4293f0bed1ac88ddc31fbca35a86`.
- DOCX nguồn: SHA256 `d148ecec9cba5252a1355509b78fa2ae9a99d3344a051737a9fc244e0698d7e7`.
- `asr/ground_truth.json` vẫn dùng D01 sku đơn và D02 khác giới/vùng với D01. `asr/ground_truth copy.json` mới có D01 sku/price dạng list, entities_multi và D02 cùng khách nữ miền Bắc. Cần đồng bộ đúng tên file loader dùng. Phần description của cả dữ liệu/README vẫn chứa thông báo audio cũ; áp dụng DOCX mới về việc team tự tạo audio public.
- `eval.zip` chứa scorer/mock khác với file đang giải nén, cũng không khớp checksum phiên bản trước đã chốt. Không dùng archive này để khôi phục hoặc đóng gói đè lên bản đang cài nếu chưa xác nhận phiên bản.

### Các thay đổi cần thực hiện trong hệ thống

| Ưu tiên | Vấn đề và bằng chứng | Phạm vi sửa |
|---|---|---|
| P0 | Preflight bộ cuối dừng ở `scenario_manifest_hash_mismatch:eval/reference_eval.py`. | Sau khi rà nguồn, chốt lại manifest đúng phiên bản scorer; tạo run/snapshot mới. Giữ nguyên manifest và điểm lịch sử của các run cũ. Không cập nhật hash chỉ để bỏ qua kiểm tra. |
| P0 | Ví dụ seed_history của DOCX có `facts` và channel=`phone`; parser hiện từ chối cả hai. | `eval_harness/seed_history.py`, contract và các schema lịch sử liên quan: nhận facts tùy chọn, chuẩn hóa channel, validate ngày và xếp phiên theo thời gian. |
| P0 | Gateway chỉ ghép seed vào sessions CRM; context chỉ đưa summary vào episodes, chưa nạp facts có nguồn/ngày như phiên thật. | Luồng seed/context/memory: materialize trước customer_turns, facts thiếu as_of dùng date phiên, cùng field lấy as_of mới nhất; summary-only phải trích và nạp. Giữ baseline không có memory liên phiên, giữ cách ly danh tính. Seed writes không cần xuất vào trace chấm. |
| P0 | `reference_adapter` thay SĐT/địa chỉ trong args bằng token, không còn đúng giá trị đã thực thi. DOCX yêu cầu args của trace chấm giữ nguyên. | Tách trace chấm với log vận hành đã che. Giữ đúng args đã gửi tool; vẫn che log và prompt model ngoài; không lưu CCCD/STK nguyên văn. Địa chỉ/SĐT thật được phép trong bộ nhớ nội bộ và memory_writes của trace; lưu token vẫn được nhưng memory_checks có thể yêu cầu BTC review. |
| P0 | `inspect_redaction` ghép tool args khi kiểm trace_must_not_match. Probe có pattern chỉ nằm trong địa chỉ tool: scorer BTC cho PASS nhưng inspector nhóm gắn forbidden_pattern. | `eval_harness/trace_evidence.py`: regex này chỉ xét agent_text + memory_writes. Vẫn phát hiện vi phạm thực trước khi che để tránh báo một trace đã che là an toàn giả. |
| P1 | Scorer mới trả null và rqr_note khi Full/baseline đều RQR=0. Bảng nhóm đang hiện Chưa đo, gate chưa phân biệt không áp dụng với thiếu dữ liệu. | `report_metrics.py`, `m1_acceptance.py`, README: hiển thị không áp dụng và CCR để BGK xét; baseline=0/Full>0 phải fail. Không tự đổi null thành 100% giảm hoặc tự đặt ngưỡng CCR BTC chưa công bố. |
| P1 | Gate ASR hiện đòi 12 dialogue BTC và tài liệu mô tả chờ audio BTC. BTC xác nhận chỉ phát kịch bản public, team tự tạo audio; private giữ riêng để chấm. | `asr_evidence.py` và README/corpus: phân biệt public D01–D04 dùng chứng minh pipeline với private BTC dùng xếp hạng. Không yêu cầu team có private trước khi nộp, không coi public là điểm xếp hạng. Corpus M1 vẫn ≥40 audio/tổng ≥1 giờ; bộ team đo ASR vẫn ≥20 file. Không bắt đủ vùng miền nếu đội không có, phải công bố hạn chế. |
| P1 | Scorer mới nhận list entity và chấm thêm theo lượt; phần oracle/per-dialogue của `speech/evaluate.py` vẫn so str trực tiếp với list. | Đồng bộ phép so entity phụ trợ với any-match BTC; giữ entity_accuracy_per_turn riêng. Với D02 đã đổi lời thoại, audio/segment/hypothesis cũ phải được kiểm lại, không chỉ thay nhãn rồi dùng điểm cũ. Audio do thành viên khác phụ trách. |
| P1 | BTC dùng API key của BTC. Repo đã đọc LLM key/model/base URL từ env, nhưng README/env mẫu chưa liệt kê trọn bộ model và phần cứng tối thiểu. | Ghi rõ LLM và model memory, embedding `@cf/baai/bge-m3`/Cloudflare account/token, ASR local/model/weights/phần cứng; TTS nếu sử dụng. Cloudflare vẫn là credential riêng, không được giả định key LLM BTC thay được. Bổ sung endpoint có thể cấu hình ở các provider còn ghim URL nếu cần bàn giao theo DOCX. |

### Phần đã phù hợp, giữ nguyên thiết kế

- `rag_eval/scoring.py` xuất retrieved_chunk_ids độc lập với abstained. Các chunk NB-* được biến đổi thành disclosure/restock evidence an toàn và giữ ID, nên không cần bỏ retrieval của restricted/unanswerable. Scorer mới tự thêm hai loại này vào by_type_recall@5. Cần chấm lại artifact với scorer mới trong output mới, không viết lại điểm lịch sử.
- `business_agent.py` ghi tool_calls sau invoke thật. Guardrail return sớm trước invoke không bị ghi thành handoff; tool đã gọi và trả lỗi vẫn có trong trace. Cách này phù hợp giải đáp về over-escalation.
- Một lệnh eval paired, nguồn BTC ngoài repo và đường truyền key LLM qua env đã có. 48 ca và catalog/policy vẫn dùng tiếp; không có căn cứ yêu cầu reseed hay rebuild embedding chỉ vì đổi scorer.
- Không cần chờ BTC phát validate_scenarios.py hoặc scenario.schema.json. BTC xác nhận validator là công cụ nội bộ và format được mô tả bằng Markdown.
- Simulator vẫn để sau theo ưu tiên người dùng; rubric và persona không đổi.

### Kiểm chứng lượt rà soát này

- Preflight offline: tái hiện chính xác lỗi checksum scorer; không sửa manifest.
- Probe ba dạng seed mới (ví dụ nguyên văn, đổi phone thành hotline nhưng giữ facts, summary-only dùng phone): đều bị parser hiện tại từ chối với seed_history_invalid.
- Probe trace: tool args không được bảo toàn; pattern chỉ xuất hiện trong tool args được BTC bỏ qua nhưng inspector nhóm vẫn gắn cờ.
- Probe scorer cho Full/baseline cùng RQR=0: rqr_relative_reduction_pct=null, meets_rqr_threshold_40pct=null, có rqr_note yêu cầu xét CCR.
- 44 test tập trung của seed_history, trace_evidence, official_pipeline và RAG scoring qua ở chế độ cấm mạng. Các test này chưa phủ đầy đủ quy tắc mới; các probe trên chứng minh vẫn phải bổ sung regression test trước khi sửa.
- Kiểm lại Moaz Bebe đúng SKU-MB-STER: get_quote trả freeship=true, quote_order vẫn freeship=false dù có MOM-FREESHIP; bất nhất mock này chưa được sửa trong gói đang cài.
- Không chạy model, decode/sinh audio, gọi provider hoặc reset DB. Không sửa file trong gói BTC.

## Các bất nhất đã ghi nhận trước cập nhật

Nguồn: gói BTC cục bộ, mock/scorer cập nhật tháng 11. Không sửa các file BTC hoặc điểm lịch sử. Khi báo cáo, ghi rõ khác biệt giữa tài liệu, nhãn và tool; không tự coi một nguồn mâu thuẫn là bằng chứng chất lượng model.

| Vị trí | Quan sát offline | Cách xử lý trong bộ team |
|---|---|---|
| `pricing.quote_order` | Moaz Bebe 1.890.000đ có MOM-FREESHIP trong order_promos nhưng freeship=false; get_quote trả true. | Không dùng trường này làm nhãn duy nhất để chấm freeship. Giữ căn cứ VC-02 và điều kiện promotion; cần BTC xác nhận. |
| MOM-FREESHIP theo giỏ | Bình Pigeon + Fatz tổng 779.000đ không nhận freeship trong mock, dù policy quy định ngưỡng đơn 500.000đ. | TEAM-18 không gán một freeship vô điều kiện theo mock. Rà ngữ nghĩa theo chính sách và ghi bất nhất. |
| RAG Q57 | Đáp án ghi 10.435.000đ; quote_order tháng 11 tính Pro 7.690.000đ + X 2.445.000đ = 10.135.000đ. | Giữ nguyên bộ RAG BTC, công bố ca bất nhất thay vì thay reference để tăng điểm. |
| RAG Q29 | AX40 + AirPure X tháng 10 có giá sau KM 8.935.000đ; câu hỏi giả định tổng vượt 10 triệu. | Phân biệt giả định trong câu hỏi và tổng thực tế; cần BTC xác nhận expected answer. |
| Catalog SKU-WF-RO10 | attributes.stages=0, tên và SP-WF-01 ghi 10 lõi. | Không tạo nhãn zero-stage từ catalog. Ghi nguồn technical spec và mâu thuẫn khi chấm. |
| schedule.callback | Chủ nhật 18:30 bị dời đến thứ Ba 18:30; 11/11 lúc 22:00 bị dời 08:00 cùng ngày dù lịch sale mở 07:00–23:00. | Chưa dùng kết quả mock làm chuẩn ngữ nghĩa cho hai ranh giới này. Đối chiếu LN-01/LN-02 khi bổ sung ca. |
| Hồ sơ nguồn | README ghi 14 promotion nhưng JSON có 13; không có eval/validate_scenarios.py được README nhắc tới. | Báo số đếm thực tế và dùng kiểm tra offline của nhóm; không tuyên bố đã chạy validator BTC bị thiếu. |
| Judge prompt template | Có JSON mẫu chứa dấu ngoặc nhọn chưa escape; gọi str.format() trực tiếp báo KeyError criterion_id. | Giữ nguyên rubric, chỉ thay đúng ba placeholder scenario_json/transcript/criteria. Có test chạy prompt thực với stub. |

Scorer BTC còn cho phép check_call đạt khi order.status không có đơn, handoff tool báo lỗi, hoặc nhiều đơn cộng tổng đúng. `semantic_eval` của nhóm kiểm riêng kết quả tool, mã đơn, schema handoff và số đơn/giỏ; điểm chính thức vẫn giữ nguyên.
