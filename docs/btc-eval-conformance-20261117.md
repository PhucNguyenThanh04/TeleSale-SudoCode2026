# Rà soát eval theo quy định BTC — 17/11/2026

Run đối chiếu: `20261117T124410Z-8d9e50eb`. Đây là audit mã nguồn và chấm lại
trace đã lưu, không phải một lần chạy model mới. Không sửa scorer BTC, nhãn,
trace, score hay checkpoint của run. Các thay đổi mã nguồn đang có từ trước
được giữ nguyên; lượt audit này không sửa implementation.

**Kết luận: số học của bảng khớp scorer BTC; chưa thể xác nhận toàn bộ phép đo
và toàn bộ M1 đã đúng/đủ quy định.** Có hai sai lệch rõ ở latency/gate, sai lệch
extraction đọc được trong trace, và phạm vi assertion chưa đủ để diễn giải
TSR 100% thành mọi yêu cầu của khách đều được đáp ứng.

## 1. Nguồn quy định và cách áp dụng

Đọc và đối chiếu các nguồn sau, thay vì lấy gate trong repository làm quy định BTC:

- [Đề gốc PDF](../../SUDO%20CODE%202026%20-%20Đề%20Bài%20Dự%20Án%20Cuối%20Kì.pdf):
  C.1 dữ liệu, C.2 harness/hiệu năng, C.3 MCP/A2A, C.4 đánh giá, C.5 cải tiến,
  C.6 demo, D ràng buộc, F hồ sơ nộp, phụ lục A công thức.
- [Điều chỉnh đề](../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md): áp dụng các
  điều chỉnh latency, tool, xác nhận lặp, ASR, kho chính sách, bộ ẩn và M2.
- [Giải đáp mentor](../../BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md): làm rõ
  Call Brief, baseline, phần cứng, audio, ASR local, phạm vi M1/M2.
- [README BTC](../../BTC-Data-Vong1-TEAMS/README.md): chấm chéo, bộ public/ẩn,
  kiểm tay ngẫu nhiên 20 lượt để phát hiện bỏ sót câu hỏi/claim.
- [Hướng dẫn latency](../../BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md),
  [định dạng scenario](../../BTC-Data-Vong1-TEAMS/schemas/scenario_format.md),
  các schema trace/tool/brief, `reference_eval.py`, `mock_tools.py` và rubric judge.

Khi bảng cũ khác bản điều chỉnh thì dùng bản điều chỉnh. Điểm chính thức được
tính bằng scorer BTC. Khác biệt/hạn chế trong scorer được ghi riêng, không tự
viết lại công thức để thay điểm chính thức.

## 2. Những phần đã xác nhận đúng trên run này

| Điều khoản | Bằng chứng | Kết luận |
|---|---|---|
| C.4: ≥20 scenario đa phiên, mỗi scenario 2–3 cuộc; ≥5 ca khó | 29 scenario tổng; **28 đa phiên** gồm 18 ca hai cuộc và 10 ca ba cuộc; một ca một cuộc; 15 ca khó | Đủ ngưỡng. Không gọi cả 29 ca là đa phiên. |
| Latency: toàn bộ test, ≥100 lượt/config, 3 warm-up | 67 cuộc / 170 lượt mỗi phía; manifest và runner report ghi 3 warm-up tách riêng | Đủ quy mô của phép đo hội thoại. |
| Scorer và trace BTC | SHA-256 scorer trong snapshot trùng nguyên file BTC; chấm lại cả hai phía khớp toàn bộ mục `system`/`baseline` đã lưu | Bảng không bị tính bằng scorer khác. |
| Full/baseline cùng model/tham số/hardware/API | Cùng `gemma4:31b`, `ollama.com`, temperature 0.2, max_tokens 256, seed 7, history 6, streaming, CPU/RAM được ghi | Đúng đối chứng đã khai báo; không chứng minh phần cứng bên trong nhà cung cấp API. |
| Baseline không nhớ qua cuộc gọi | Runner đặt `include_prior=False`, mỗi cuộc có session mới; context loại profile/episode phiên trước. Working history trong cùng cuộc vẫn được dùng | Phù hợp đối chứng không memory. Tra cứu đơn từ business tool/CRM không tự đồng nghĩa bật memory hội thoại. |
| Ngày và input | Loader/runner cộng dồn `days_later`, ưu tiên `call_date`; ưu tiên `customer_turns_asr` khi có | Đúng contract đã kiểm. Nhãn `success_if`/GT không được truyền vào request làm đáp án. |
| RQR và ngưỡng | Scorer dùng giảm tương đối; Full 0/22, baseline 18/38; giảm 100% | Đúng số học trên phần câu hỏi extractor đã xuất. |
| TSR và HR giá/KM | TSR Full 29/29; HR giá/KM 0/36 | Đạt ngưỡng trên assertions/claims hiện có, với giới hạn ở mục 3. |
| TTFT p95 ≤3 giây | Mốc first guarded answer delta tại harness; Full 2484ms, baseline 2995ms | Đạt trên run này; baseline chỉ dưới ngưỡng 5ms. Không cần ép từng lượt ≤3 giây. |
| Tool tham chiếu | Có differential tests về catalog, tồn kho, giá/KM và điều kiện tool so với `mock_tools.py` | Các ca kiểm qua không chứng minh toàn bộ ca ẩn. Xem kết quả test ở mục 6. |

`validated` xác nhận pipeline/artifact hợp lệ. `execution_health=healthy` và
19/20 gate nội bộ pass không phải chứng nhận BTC đã nghiệm thu M1.

## 3. Sai lệch và giới hạn cần xử lý

### F1 — Total lấy sai mốc kết thúc theo định nghĩa BTC

BTC quy định Total kết thúc ở **token cuối của câu trả lời**, đo tại backend/
harness. Trong [benchmark_runner.py](../ai-services/eval_harness/benchmark_runner.py),
`measured_stream` đợi `done`, sau đó runner mới lấy `latency_ms` và dùng làm
`latency.total_ms`. Trong [runtime.py](../ai-services/app/agent/harness/runtime.py),
`stream.finish(...)` đứng trước `await persist_agent(...)`; `done` đến sau đó.
Vì thế Total đang gồm persistence sau khi lời trả lời đã phát xong.

Test `test_stream_ttft_is_first_delta_and_total_includes_terminal_persistence`
hiện còn khẳng định hành vi này: delta cuối ở 120ms, lưu thêm 20ms, kỳ vọng
Total=140ms. Test pass chỉ xác nhận implementation hiện tại, không xác nhận
đúng định nghĩa BTC.

Cần ghi timestamp delta trả lời cuối làm Total; giữ thời gian đến `done` ở
chỉ số vận hành riêng như `response_ms`. Total p95 đã lưu 2504/3015ms là thời
gian đến hoàn tất persistence, không phải số đo chính xác mốc BTC. Số này
đang bảo thủ hơn về thời gian kết thúc; không có bằng chứng làm nhanh giả.
Không suy ngược Total chuẩn bằng cách trừ median/p95 persistence, và không
sửa nhãn của số lịch sử để biến thành phép đo mới.

### F2 — Gate Call Brief dùng p95 thay cho giới hạn 5 giây

BTC ghi **Call Brief ≤5 giây**, không ghi p95. Nhưng
[m1_acceptance.py](../ai-services/eval_harness/m1_acceptance.py) lấy
`call_brief.p95_ms <= 5000` làm gate `call_brief_p95`.

Phản ví dụ: 99 lần 100ms, một lần 6000ms → p95 theo scorer BTC vẫn là 100ms;
gate hiện tại pass dù có lần vượt 5 giây. Cần kiểm giá trị lớn nhất của các
lần nạp có đo, đồng thời phân biệt thiếu sample với đạt ngưỡng.

**Riêng run này không có vi phạm được quan sát:** Full có 38 lần, lớn nhất
229ms. Baseline không có Brief là hợp lý khi không mang bộ nhớ sang cuộc sau.
Prepare chạy trước lượt đầu; context ghi thời gian từ bắt đầu prepare và có
refresh giá/tồn kho. Tóm tắt episodic được khai báo ở `precomputed_parts`.

### F3 — Extractor chưa bao phủ đầy đủ phát ngôn

Review candidate chỉ thấy phần detector đã bắt được. Nó không phát hiện được
mệnh đề bị bỏ qua hoàn toàn. Rà 20 lượt ngẫu nhiên trong 340 lượt hai phía,
seed `20261117`, đọc cả `agent_text`, `questions`, `claims` và sidecar cho thấy:

- **Full / SC-T13 / call_2 / turn 1:** nói AirPure Y có khóa trẻ em nhưng không
  có projection/candidate riêng cho claim tính năng này. Gate từ khóa ở
  [extractor.py](../ai-services/eval_harness/extractor.py) không có cue khóa trẻ em.
- **Baseline / SC-T13 / call_1 / turn 2:** cùng câu có “không có tính năng khóa
  trẻ em” và “bảo hành 24 tháng”, nhưng chỉ xuất `warranty_months=24`.
- **Baseline / SC-T02 / call_2 / turn 2:** câu xin phép làm thủ tục đổi sang
  size L bị gán `open/size`, dù nội dung đang xin consent thực hiện. Full cũng
  có dạng tương tự. `must_not_ask` call này không gồm size nên ví dụ này
  **không làm tăng tử số RQR** hiện tại; chưa có cơ sở kết luận mức giảm RQR
  100% là giả chỉ từ ví dụ này.
- Cùng lượt SC-T02, câu miễn phí đổi lần đầu bị loại
  `qualified_not_representable`; phần shop chịu ship hai chiều chưa có
  projection riêng. Đây là claim có điều kiện cần giữ ngữ nghĩa, không được
  tự bỏ điều kiện rồi gán mọi phí vận chuyển bằng 0.
- **Full / SC-T21 / call_2 / turn 1:** miễn phí thu hộ COD đã có candidate
  `unsupported_mapping`, nhưng chưa có projection. Đây là khoảng trống
  mapping đã được khai báo, khác với claim bị detector bỏ qua hoàn toàn.

Run có 156 candidate cần xem: 63 unresolved claim, 4 question bất định,
49 qualified và 40 unsupported mapping. Không được duyệt hết thành đúng.
Mẫu 20 do Codex đọc là audit bổ sung, **không phải người chấm và không thay
thủ tục BTC kiểm tay ngẫu nhiên 20 lượt** ở README.

### F4 — GT/assertions giới hạn ý nghĩa của HR và TSR

Full xuất 144 claim nhưng BTC chỉ đối chiếu 58; baseline xuất 124 nhưng chỉ
đối chiếu 50. Theo đúng scorer, claim thiếu field tương ứng trong
`ground_truth_facts` bị bỏ qua. Đây là cách scorer hoạt động, không phải lỗi
số học của wrapper; cần tăng chất lượng nhãn ở bộ phát triển khi có căn cứ.

Ví dụ SC-T13 call_1/call_2 có GT rỗng. Sửa extractor về khóa trẻ em riêng lẻ
vẫn không làm claim đó được tính HR trong hai call này. Call_3 có mục tiêu
hỏi thời hạn/phạm vi bảo hành, nhưng assertion chính chỉ yêu cầu
`catalog.search(max_price_vnd=5500000)` và cấm tool thay đổi trạng thái. Nó
không kiểm nội dung trả lời bảo hành. Vì thế **TSR=100% là đạt bộ assertion,
chưa phải mọi nhu cầu thực tế của khách đã được hoàn thành**.

Ngay trong trace đã lưu, cả hai cấu hình trả lời câu hỏi bảo hành ở
SC-T13/call_3/turn_2 bằng “Em cần xác minh đơn hàng của mình trước khi xác
nhận quyền lợi áp dụng cho đơn ạ.” Khách đang tham khảo trước khi mua;
assertion hiện tại vẫn cho call này pass. Đây là ví dụ thực tế về khoảng
trống của nhãn, không chỉ một tình huống giả định.

Tương tự CCR 54/79 là kết quả scorer BTC, không phải tỷ lệ lưu/đọc memory
thành công. Scorer còn lấy tên tham số tool làm tín hiệu sử dụng slot; cần
giữ điểm chính thức và đánh giá ngữ nghĩa riêng khi phân tích memory.

## 4. Các yêu cầu M1 mà pair text chưa chứng minh

| Điều khoản BTC | Yêu cầu | Bằng chứng hiện tại |
|---|---|---|
| C.1 corpus phát triển | ≥120 transcript; ≥40 audio và ≥1 giờ; ≥30 khách đa phiên; ≥10 khách đa kênh; 1 ngành/2 miền giọng; ≥30 SKU; ≥3 persona | Run có 29 khách và 14 ca đa kênh, catalog chung 40 sản phẩm. Không dùng 67 cuộc eval để kết luận corpus đủ/thiếu 120. Chưa thấy manifest corpus tổng đáp ứng đầy đủ trong evidence của run. |
| C.1/D + điều chỉnh §8 | ASR local; WER/CER và entity tiền/SĐT theo normalization BTC; audio BTC cộng ≥20 file team | Pair text chưa có score ASR. Checkout hiện tại không thấy WAV/score ASR trong `speech/data`; gói public chỉ có GT 4 mẫu D01–D04 và không có WAV. BTC giữ 8 mẫu còn lại tới lúc chấm. Không lấy số lịch sử trong README speech làm artifact đã xác minh. |
| C.5 feedback | Ít nhất 2 nguồn feedback, ít nhất 1 cơ chế cải tiến | Có code knowledge feedback/experiment, nhưng code và một checkpoint lỗi chưa chứng minh loop đã hoàn tất. |
| C.5 hai vòng | Vòng 0 → feedback → cải tiến → vòng 1 trên cùng fixed test, có chênh lệch và xét duyệt phù hợp | Chỉ cần hai vòng tổng cộng. Hai lần chạy sau sửa lỗi không tự chứng minh Knowledge Gap Loop; cần nối nguồn feedback, thay đổi được duyệt, before/after và controls. Knowledge checkpoint hiện dừng với FileNotFoundError. |
| C.6/F demo | UI chat, Brief khi quay lại, timeline; demo hai cuộc; video 5–8 phút, slide ≤15 | Không được kiểm chứng chỉ từ trace hoặc tests. |
| F báo cáo | Bảng baseline và trước/sau, ≥10 ca lỗi | Có bảng baseline. Mẫu audit 20 lượt không thay báo cáo phân tích ≥10 ca lỗi. |
| Tiêu chí chi phí | Ước tính chi phí/cuộc gọi, ghi model/API/hardware | Manifest có môi trường, pair chưa có evidence chi phí/cuộc đã đối chiếu. |
| D/C.3 | Không fine-tune; PII/đồng ý; tiếng Việt; không giả người; MCP hoặc A2A | Có cơ chế và tool/guardrail trong repo; scorer phát hiện 0 vi phạm trên tập này. Không suy thành bảo đảm an toàn cho mọi phát ngôn/ca ẩn. |

Các gate `execution_health`, hash integrity, candidate review, worker readiness
là kiểm soát nội bộ hữu ích. Tên gate và số gate không phải rubric chính thức.

## 5. Phạm vi M2 và lưu ý công cụ

- TTFA ≤2,5s, diarization, ≥2 phiên demo đồng thời là M2; không lấy thiếu các
  mục này làm lỗi nghiệm thu chat M1.
- Customer simulator 3 seed và rubric 12 PASS/FAIL kèm ≥20 mẫu người/kappa
  thuộc M2. Không nhầm với BTC kiểm 20 lượt extractor.
- Làm RAG trên policy BTC thì báo `reference_eval.py --rag`:
  Recall@3/@5, multi-hop/abstain và phân tích version/restricted/numeric.
  Điểm retrieval không thay 5 chỉ số M1 hay ASR; scorer ghi rõ answer/version
  accuracy còn cần judge/tay. Trên tài liệu riêng chỉ chấm phương pháp.
- `paired-knowledge` là tên thư mục/orchestration của repository, không phải
  tiêu chuẩn hay bộ metric mới của BTC. Lỗi follow-up knowledge tách biệt
  với hai trace đã chấm hoàn tất.
- Snapshot của run nằm ở đường dẫn `run.json.btc_root` thuộc run trước.
  Không có `btc-release` trong run mới không tự chứng minh thiếu scorer.
  Các consumer đã có sửa đường dẫn trong working tree trước audit này.
- Khi đính kèm ASR, lưu ý snapshot hiện chỉ sao chép catalog/policy/schema/
  rag/simulator và mã eval, không sao `asr/ground_truth.json`. Đưa snapshot
  này làm `--btc-root` cho `collect_asr_evidence` sẽ thiếu GT; dùng gói BTC có
  GT phù hợp khi chấm/đính kèm ASR, hoặc sửa quy trình snapshot trong tác vụ
  riêng. Đây chưa phải nguyên nhân khiến pair text hiện tại sai điểm.
- README BTC liệt kê `eval/validate_scenarios.py` nhưng file không có trong
  gói cục bộ; docstring scorer có ví dụ `--catalog` nhưng argparse không nhận
  cờ đó. Ghi nhận bất nhất tài liệu, không tự sửa gói BTC.

## 6. Kiểm chứng và thứ tự xử lý

Artifact audit tại
`ai-services/eval_harness/results/measurement-audit/20261117-btc-conformance/`:

- `audit.json`: hash nguồn quy định/run, đối chiếu scorer, độ phủ, brief max,
  phản ví dụ p95; xác nhận các file run gốc giữ nguyên byte.
- `rescored.json`: kết quả gọi lại hàm evaluate nguyên bản BTC trên trace cũ;
  Full/Baseline đều khớp score đã lưu.
- `spotcheck-20.json`: 20 lượt, seed, trace hashes, lời thoại và ghi chú audit;
  trường `human_review=false`, không dùng làm approval candidate.

Offline runner chặn network, không dùng credential và không reset DB:

- `20261117-btc-conformance-tests.txt`: **79 passed / 6,40s** — contracts,
  scorer, baseline/seed, streaming, latency, ASR evidence và acceptance.
- `20261117-btc-tool-parity-tests.txt`: **60 passed, 1 failed / 2,81s** —
  commerce/tool parity và regression. Failure:
  `test_actual_policy_recovery_is_not_rejected_as_product_price`, kỳ vọng
  “7 ngày” nhưng nhận câu chưa xác minh đủ chính sách. Chạy riêng vẫn fail
  (`20261117-btc-policy-recovery-isolated.txt`). Diagnostic cho thấy tool
  matching thành công; fixture cắt CL-01 còn đuôi `## ` của heading CL-02.
  Parser `content.split('\n\n', 1)[-1]` lấy đúng phần đuôi đó, mất nội dung
  chính sách. Đây là lỗi tương thích giữa cách fixture cắt đoạn và parser;
  chưa chứng minh retrieval thực tế cũng tạo cấu trúc này. Diagnostic ở
  `20261117-btc-policy-recovery-diagnostic.txt`. Không sửa policy/expectation
  để ép pass trong tác vụ audit.

Thứ tự sửa đề xuất: (1) mốc Total và gate Call Brief; (2) extraction/GT và
assertions trên nhánh replay mới, không đè run gốc; (3) xem failure recovery
trước khi tuyên bố regression xanh; (4) hoàn thiện evidence ASR/corpus và
hai vòng cải tiến. Chỉ chạy lại live sau khi phần cần sửa đã được kiểm offline
và có yêu cầu chạy live. Không cần chạy lại cùng cấu hình chỉ để hy vọng gate
review tự chuyển sang pass.
