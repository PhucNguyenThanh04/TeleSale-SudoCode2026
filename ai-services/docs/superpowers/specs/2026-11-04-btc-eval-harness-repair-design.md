# Sửa eval harness để chạy trọn luồng chấm text-to-text của BTC

Ngày: 2026-11-04. Trạng thái: đã được người dùng duyệt ngày 2026-11-04.

## 1. Mục tiêu và phạm vi

Luồng text-to-text của agent đã chạy được. Lần sửa này phải nối luồng đó với
runner, trace và scorer BTC thành một quy trình sử dụng được từ README: nhận
scenario, chạy full và baseline, kiểm tra trace, gọi nguyên bản
`reference_eval.py`, xuất kết quả cùng bằng chứng của lần chạy.

Không nghiệm thu chỉ bằng việc tạo được JSON hoặc một vài unit test chạy qua.
Kết quả cần phản ánh hành vi thực của harness, kể cả hành vi sai. Không dùng
đáp án kỳ vọng để điền trace, sửa lời agent hoặc làm điểm đẹp hơn.

Đáp ứng hợp đồng chấm của BTC không đồng nghĩa agent chắc chắn đạt mọi ngưỡng
chất lượng. Điểm và ngưỡng đạt/trượt phải lấy từ kết quả thực; không hứa trước
TSR, HR, RQR, CCR hoặc latency đạt yêu cầu khi chưa có phép đo.

Phạm vi: runner hội thoại text, adapter/extractor, memory evidence, latency,
kiểm tra đầu vào/đầu ra, CLI và README liên quan trực tiếp. Không thêm dashboard,
metric mới, ASR benchmark, RAG benchmark riêng, simulator hoặc LLM judge.
Không thay business logic của agent để khớp đáp án trong lần sửa này.

## 2. Nguồn hợp đồng và thành phần tái sử dụng

- BTC: `schemas/trace_log.schema.json`, `schemas/handoff_brief.schema.json`,
  `eval/reference_eval.py`, `eval/huong-dan-do-latency.md`, README và các điều
  chỉnh đề. Đọc từ `--btc-root`; không chỉnh sửa các file BTC.
- Giữ runtime text-to-text hiện có, gateway bốn MCP, LangMem worker và cơ chế
  ghim knowledge release. Không viết agent khác dành riêng cho benchmark.
- Tái sử dụng `eval.trace_audit`, `eval.score_pair` và cơ chế provenance hiện có.
  Scorer nội bộ chỉ là diagnostic; không thay điểm chính thức của BTC.

Đây là spec sửa luồng eval, thay thế các phần mâu thuẫn trong spec eval trước.
Các tính năng cũ ngoài phạm vi không bị mở rộng trong lần sửa này.

## 3. Một đường chạy và tạo trace thống nhất

`eval_harness.run_official` điều phối cặp full/baseline. `benchmark_runner`
thực thi từng cấu hình. Entry point `run_eval.py` ở root giữ giao diện BTC
đang yêu cầu và ủy quyền cho cùng phần chạy/tạo trace, không duy trì một bộ
regex, logic facts_used hoặc thu memory riêng.

Giữ tương thích `--config full|baseline_no_memory`, `--scenarios`, `--out`
và các cờ an toàn hiện có của root CLI. Tên nội bộ `baseline` phải được ánh
xạ thành `baseline_no_memory` trong trace BTC. README ghi rõ lệnh xuất một
trace và lệnh chạy cặp rồi chấm điểm.

Các lệnh trên cùng đầu vào, cấu hình và turn state phải dùng cùng phép biến
đổi trace. Không đặt yêu cầu lời agent giống từng byte giữa hai lần gọi LLM.

## 4. Dataset và kiểm tra trước khi chạy

Trước reset và trước gọi model:

1. Xác minh BTC root chứa schema/scorer cần thiết; dataset không rỗng, JSON
   hợp lệ, scenario ID duy nhất, call/turn hợp lệ và tiêu chí chấm được hỗ trợ.
2. Giữ nguyên ID và nội dung scenario BTC. Không ghép trace `SCxx` với bộ
   scenario `SAMPLExx`, không lấy đáp án/ground truth làm đầu vào agent.
3. Kiểm tra đủ catalog, order, memory, knowledge: kết nối, xác thực và DB
   identity phù hợp. Kiểm tra knowledge release thực sự sẵn sàng ở dịch vụ
   knowledge, không chỉ có bản ghi release trong PostgreSQL.
4. Xác minh DB mà runner reset chính là DB các MCP sử dụng; chặn production.
   DB đích phải được cấu hình rõ trước khi chạy, không tự lấy DB đang kết nối
   làm sự chấp thuận reset.
5. Giữ fingerprint dữ liệu nguồn và knowledge release nhất quán cho cặp chạy;
   không thay đổi release đang phục vụ trong lúc eval.

Đã có quyết định trước cho phép reset dữ liệu thử nghiệm của DB `telesale`.
Không bắt buộc tạo DB mới chỉ vì tên chưa có hậu tố `_eval`. Spec này yêu cầu
khai báo DB đích rõ ràng, đối chiếu identity và giữ phạm vi reset đã duyệt:
chỉ dữ liệu runtime và sequence liên quan; giữ `btc_source`, dữ liệu knowledge
và migration metadata. Không mở rộng quyền reset sang DB hoặc dữ liệu khác.

Dataset do người chạy chỉ định là nguồn xác định coverage. Báo đúng số
scenario/call/turn và ca khó; tách public sample khỏi bộ bổ sung của team.
Không gọi 7 sample là toàn bộ test BTC hoặc tuyên bố đủ yêu cầu số lượng khi
dataset chưa đủ. Chạy được với bộ scenario hợp lệ khác mà không hard-code ID.

Không giữ một cờ tên `dry-run` nhưng âm thầm chạy model/reset: kiểm tra đầu vào
thuần offline phải không có các tác dụng đó; smoke chạy thật phải có tên/help
rõ ràng. Giữ tương thích cờ cũ bằng cảnh báo hoặc lỗi hướng dẫn, không đổi
ngầm thành một lần chạy thật.

## 5. Full và baseline

- Mỗi cấu hình bắt đầu từ runtime đã reset theo phạm vi trên.
- Giữ cùng scenario, CRM identity, model/API, tham số, seed và business tools.
  Baseline chỉ vô hiệu hóa việc đọc bộ nhớ dài hạn từ phiên trước; vẫn giữ
  ngữ cảnh trong phiên và hành vi ghi memory theo hệ thống hiện tại.
- Mỗi call có session riêng, các turn trong call giữ thứ tự. Dùng call_date,
  days_later và reference date của BTC, không dùng ngày máy để thay đề bài.
- Nếu call có `seed_history`, nạp lịch sử CRM đó trước khi chạy turn đầu,
  đúng customer identity, thời điểm lịch sử và provenance của phiên cũ.
  Hai cấu hình được khởi tạo cùng lịch sử; full được đọc memory phiên trước,
  baseline vẫn chặn việc đọc đó. Không chèn lịch sử vào prompt của baseline
  để đi vòng cơ chế no-memory, không tạo turn scored hoặc latency response
  từ bước nạp lịch sử. Không dùng `facts_established`, `ground_truth_facts`
  hoặc `memory_expectation` thay cho lịch sử đầu vào. Nếu định dạng lịch sử
  không được hỗ trợ, preflight phải báo lỗi trước reset/gọi model, không
  âm thầm bỏ qua. README mô tả định dạng được hỗ trợ và cách nạp.
- Nếu có `customer_turns_asr`, đưa chính văn bản đó vào agent và ghi đúng
  input mode theo schema BTC; không chạy ASR trong benchmark này.
- Cả full và baseline chờ job distillation đúng source turn và đọc accepted
  memory writes. Không coi dữ liệu đề xuất hoặc response rỗng tức thời là
  kết quả ghi cuối cùng. Giữ kiểm tra job thiếu/lỗi/timeout hiện có.
- Bản JSONL cuối cùng phải chứa dữ liệu được cập nhật sau khi chờ worker ở
  cả hai nhánh, kể cả khi trước đó đã stream từng row ra đĩa.

## 6. Trace trung thực và đầy đủ

Mỗi turn có đủ trường bắt buộc của BTC, đúng kiểu dữ liệu và định danh;
`memory_writes` xuất nhất quán, kể cả mảng rỗng khi thực sự không có ghi.
Tool names, call IDs, thứ tự, SKU, mã đơn và tham số nghiệp vụ được giữ nguyên.
Không biến lỗi tool thành thành công hay bịa một tool call còn thiếu.

### Questions và claims

Lựa chọn kỹ thuật đề xuất: extractor offline theo quy tắc, không thêm một
LLM/API vào đường chấm. Tách khỏi agent để có thể replay trên trace hiện có.

- Questions gồm câu hỏi và lời xin dữ kiện không có dấu hỏi; gán đúng slot
  và open/confirm. Bao phủ slot thực tế của BTC và runtime, gồm mã đơn,
  địa chỉ, thanh toán, thông tin sản phẩm và các slot memory.
  Câu hỏi đã nhận diện nhưng không xác định được slot vẫn phải giữ với
  slot dự phòng `other`, type và đoạn lời nói tương ứng; không loại khỏi
  mẫu số RQR hoặc số đếm `max_agent_questions`. `other` không được dùng thay
  slot nghiệp vụ đã xác định được. Đếm mỗi yêu cầu hỏi độc lập một lần;
  câu có nhiều yêu cầu độc lập được tách theo từng yêu cầu, không nhân số
  questions chỉ vì nhiều regex cùng khớp một yêu cầu. Fixture kiểm chứng
  cả câu hỏi chung như “Chị cần em hỗ trợ gì thêm không ạ?”.
- Claims chỉ đến từ phát biểu agent đã gửi khách. Bao phủ giá, giá niêm yết,
  tồn kho, khuyến mãi theo mã, freeship, thời gian giao/hàng về, thời hạn đổi
  trả, phí đổi, bảo hành và phiên bản/hiệu lực chính sách.
  Giữ claim an toàn `is_human=true` khi agent thực sự nhận là người thật hoặc
  phủ nhận mình là AI/bot; scorer BTC dùng field này để đếm `claims_human`.
  Phải phân biệt với câu phủ định việc là người thật, câu hỏi, trích dẫn
  hoặc lời thuật lại không phải agent tự nhận; không suy claim từ tool.
- Xử lý số tiền nhỏ, cách viết số tiếng Việt có trong fixture, câu phủ định,
  lịch sử, điều kiện và phạm vi quyền lợi. Không biến câu hỏi hoặc quyền lợi
  giả định thành khẳng định hiện tại. Không suy ra phần agent chưa nói.
- Tool evidence được dùng để xác định đối tượng/ngữ cảnh rõ ràng của lời
  nói, không dùng để thay giá trị sai agent đã nói bằng giá trị đúng.
- Giữ đoạn lời nói làm bằng chứng cho mỗi question/claim khi schema cho phép.
  Không khẳng định regex hiểu mọi diễn đạt; ghi rõ phương pháp và giới hạn
  trong README để BTC có thể đối chiếu tay.

### Facts used và memory

Parse provenance theo định dạng runtime hiện tại, kể cả `langmem:<session>:<turn>`.
Chỉ ghi facts_used khi fact từ phiên trước được dùng có ý nghĩa trong lời
agent hoặc tham số tool; không tính mọi fact đã đọc, fact của phiên hiện tại
hoặc đáp án BTC. Bao phủ giá trị false, zero và dữ kiện được cập nhật/thay thế.
Memory writes giữ op, source `call_N#turnM`, customer identity đã bảo vệ và
giá trị thực được chấp nhận, không lấy memory_expectation để tạo writes.

### Handoff và PII

Kiểm tra brief thật với schema BTC trước khi che dữ liệu. Mask theo field
path; giữ enum, số, array, object và thông tin nghiệp vụ cần chấm. Không thay
cả brief bằng các chuỗi placeholder.

Không lưu PII thô vào trace/log. Kiểm tra PII trên đầu ra thực trong bộ nhớ
trước khi mask; lưu bằng chứng an toàn về loại vi phạm và vị trí, không lưu
giá trị nhạy cảm. Việc mask không được biến một lần có vi phạm thành kết luận
“không vi phạm”. Nếu redaction làm mất bằng chứng BTC cần hoặc làm thay đổi
args_match, lần chạy phải có trạng thái cuối `invalid`, không được đánh dấu
`validated` hoặc kết luận đạt đầy đủ. Manifest ghi mã lý do
`redaction_affects_scoring`, loại bằng chứng bị mất, field path và
scenario/call/turn liên quan; không ghi giá trị PII. Bằng chứng an toàn lưu
riêng không phải đầu vào thay thế mà scorer BTC có thể tự đọc.
Nếu vẫn tạo report bằng scorer nguyên bản trên trace đã mask, chỉ giữ nó
làm artifact đối chiếu có liên kết rõ với trạng thái `invalid`; không công
bố là kết quả chấm đầy đủ của hành vi trước mask. Không sửa scorer, sửa
điểm report hoặc điền claim giả để bù cho redaction.

## 7. Latency

Đo tại ranh giới harness bằng đồng hồ monotonic; không tính thời gian extractor,
ghi file, scoring hoặc chờ distillation sau khi câu trả lời đã hoàn tất vào
response latency. Các thao tác nằm trên đường trả lời thật vẫn phải tính.
Không streaming: TTFT = Total và khai báo rõ chế độ.

Chạy ba lượt warm-up riêng cho mỗi cấu hình trước lượt scenario được chấm,
không đưa chúng vào trace scored và không để chúng tạo memory/đơn/ticket ảnh
hưởng dataset. Không bỏ ba lượt scenario để lấy mẫu latency vì sẽ mất coverage.

Call Brief latency chỉ có ở turn 1 của call_2/call_3 khi có phép đo thật:
từ nhận diện khách đến brief sẵn sàng, gồm freshness check hiện hành. Không
dùng toàn bộ thời gian trả lời hoặc thời gian chạy formatter thay thế.

Scorer BTC tính trên trace scored nguyên vẹn. Báo số lượt đo; sample dưới
100 lượt phải báo chưa đủ quy mô phép đo latency BTC. Ghi model, API provider,
tham số, phần cứng khả dụng và thời điểm, không ghi secret.

## 8. Chấm điểm và trạng thái lần chạy

Kiểm tra JSON Schema, coverage chính xác, thứ tự, cấu hình, provenance,
memory jobs và metadata cặp trước khi công bố kết quả. Lỗi turn, reset,
provider, worker, release hoặc thiếu trace khiến lần chạy failed; giữ trace
dở dang và lỗi đã che dữ liệu để sửa. Không tính lỗi thành điểm 0 hợp lệ và
không coi mẫu số không tồn tại là đạt.

Phân biệt trạng thái cuối: `failed` khi có lỗi thực thi/kiểm tra bắt buộc;
`invalid` khi trace mất bằng chứng chấm do redaction như mục 6; `validated`
chỉ khi cặp chạy đầy đủ và qua mọi kiểm tra tính hợp lệ. `validated` không
đồng nghĩa đạt các ngưỡng chất lượng hoặc đủ quy mô latency BTC. Nếu có cả
lỗi thực thi và mất bằng chứng do redaction, trạng thái là `failed` và vẫn
giữ lý do redaction trong manifest. CLI phải trả mã thoát khác 0 cho
`failed`/`invalid`; README nêu cách đọc trạng thái và artifact tương ứng.

Chỉ scorer BTC nguyên bản tạo điểm chính thức. Đầu ra gồm full/baseline JSONL,
report BTC, manifest/hash và trạng thái lần chạy. Kết quả chưa đủ coverage
không được xuất thành một lần validated. Không để report cũ cùng thư mục bị
hiểu nhầm là report của lần thất bại; hoàn tất công bố bằng trạng thái cuối
chỉ khi các artifact cần thiết đã ghi thành công.

Chạy trực tiếp reference_eval với cùng scenario và hai trace phải tái tạo
cùng giá trị chính thức. Diagnostic nội bộ nếu giữ lại phải được ghi nhãn rõ.

## 9. Kiểm chứng và tiêu chí nghiệm thu

1. Test offline có gán nhãn độc lập cho questions/claims/facts_used, bao gồm
   tất cả nhóm field BTC hiện có và các lỗi đã nêu trong review. Fixture
   phải có cả ca đúng, sai, không được trích và diễn đạt chưa từng khớp regex
   cũ; không sinh expected bằng chính implementation cần kiểm tra.
   Có nhãn cho `is_human` ở câu tự nhận, phủ định, câu hỏi và trích dẫn;
   questions có slot `other`, nhiều yêu cầu trong một câu và nhiều regex
   khớp cùng yêu cầu để kiểm tra số đếm không bị thiếu hoặc trùng.
2. Integration offline dùng runtime/gateway/worker giả có trạng thái chạy qua
   cả hai entry point và full/baseline; xác nhận session, ngày, tool, accepted
   writes và trace cuối. Không chỉ mock trực tiếp row hoàn chỉnh.
   Có fixture `seed_history` cho khách quay lại sau nhiều tháng: xác nhận
   ngày/provenance, cùng dữ liệu khởi tạo ở hai cấu hình, full đọc được
   lịch sử còn baseline không đọc; lịch sử không sinh thêm turn scored.
   Định dạng lịch sử không hỗ trợ phải bị chặn ngay ở preflight.
3. Chạy scorer BTC thật trên cặp trace fixture; kiểm tra các số liệu có thể
   tính tay. Có ca agent nói sai để chứng minh HR/TSR không bị làm đẹp, ca hỏi
   lại để kiểm tra RQR và ca dùng memory để kiểm tra CCR.
   Kiểm tra `claims_human`, `max_agent_questions` và mẫu số RQR bằng fixture
   có câu hỏi slot `other`, không chỉ kiểm extractor trả đúng JSON.
4. Test lỗi xác nhận không reset nhầm DB, không gọi model khi preflight thất
   bại, không công bố điểm khi thiếu lượt/job lỗi, không che mất tool names,
   không mất kiểu brief và không báo vi phạm PII thành sạch sau redaction.
   Có ca redaction làm mất bằng chứng PII hoặc thay đổi `args_match`:
   trạng thái `invalid`, CLI thoát khác 0, manifest có lý do an toàn,
   report đối chiếu nếu có không được công bố là kết quả đầy đủ/validated.
5. Sửa ba lỗi setup test do capture_release mới; mặc định test không được
   vô tình kết nối DB, API hay dùng secret từ môi trường phát triển.
6. README có lệnh thực thi được cho kiểm tra offline, chạy một cấu hình,
   chạy cặp, chấm lại bằng BTC, biến môi trường cần có và nơi đọc kết quả.
   Không cần dashboard để xác nhận thành công.
7. Sau khi người dùng cho phép chạy thật: thực hiện một cặp đầy đủ trên bộ
   scenario đã chọn, qua runtime và bốn MCP thật; kiểm tra schema, coverage,
   memory và report BTC. Chỉ sau bước này mới khẳng định đã xác minh end-to-end
   trên môi trường thực. Nếu dataset không đủ yêu cầu quy mô, ghi rõ còn thiếu.

Trong khi triển khai chỉ chạy test chức năng offline; không tự chạy live
eval/benchmark, cài dependency hoặc reset DB. Phê duyệt spec/plan không tự
thay thế sự cho phép chạy các thao tác đó. Nếu chưa được phép chạy thật,
báo chính xác “đã kiểm chứng offline; chưa xác minh live”, không nghiệm thu
giả là đã chạy toàn bộ thực tế.
