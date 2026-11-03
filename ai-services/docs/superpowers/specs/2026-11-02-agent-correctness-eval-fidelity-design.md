# Sửa tính đúng nghiệp vụ và độ tin cậy của eval telesale

Trạng thái: người dùng đã duyệt spec, gồm yêu cầu chống hardcode/overfit,
ngày 2026-11-02. Implementation plan đã được duyệt và triển khai offline;
418 test full regression đạt, 14 bỏ qua theo môi trường. Chưa chạy live eval
hoặc publish prompt production. Chi tiết nằm trong progress của plan.

## 1. Mục tiêu và căn cứ

Sửa các lỗi đã xác minh trong luồng khách quay lại, tạo đơn, grounding ưu đãi
và phép đo memory. Mục tiêu là hành vi đúng có bằng chứng, đồng thời có thể
phân biệt lỗi sản phẩm với lỗi trích xuất/chấm điểm. Không cam kết đạt điểm
BTC trước khi có lượt chạy hoàn chỉnh được phép thực hiện.

Căn cứ là run `20261101T174223Z-c43720a3`, có đủ 39 lượt mỗi cấu hình,
`run.json.status=validated`, và source digest khớp checkout lúc điều tra:
`edfd05a180c090f629fff71cabb085cc4dc11e74f59f0d05a08a27b2d1874ce1`.
FULL đạt TSR 6/7, CCR 13/21, HR giá/khuyến mãi 1/4; baseline RQR 0/1.
Những tỷ lệ này là kết quả của artifact hiện có, chưa phải kết quả sau sửa.

Người dùng yêu cầu rõ: không hardcode hoặc overfit vào một sample/case.
Các lựa chọn thiết kế dưới đây thuộc bản spec đã được người dùng duyệt.
Spec này bổ sung cho thiết kế LangMem Primary và Text Eval
Harness hiện có; không triển khai Knowledge Gap Loop hoặc giao diện của nó.

## 2. Phạm vi và ràng buộc

- Giữ Python, LangGraph, MCP, LangMem và PostgreSQL hiện tại. Business rule
  nằm ở MCP service/shared module; agent không đọc DB nghiệp vụ trực tiếp.
- Giữ LangMem làm long-term memory, distillation bất đồng bộ và admission có
  bằng chứng. Không khôi phục memory legacy hoặc thêm lượt gọi LLM để chấm
  từng câu hỏi/claim trên đường trả lời.
- Giữ phân tách khách hàng, erasure barrier, che PII theo field path, tên
  tool/call id và tham số scorer so sánh.
- Không sửa scenario, ground truth, validator hoặc reference scorer BTC;
  không đưa expected output hay scenario ID vào quyết định runtime.
- Không thêm dashboard, benchmark mới, semantic search, dependency, đổi model
  hoặc tăng token budget trong đợt này.
- Làm trong checkout hiện tại, không sub-agent/worktree, không git add/commit.
- Không chạy live eval, reset DB, backfill hoặc thao tác tốn phí khi chưa được
  cho phép riêng. Không suy diễn quyền chạy từ việc duyệt spec.

### 2.1. Chống hardcode và overfit — yêu cầu bắt buộc

- Mỗi thay đổi phải mô tả được lớp lỗi và quy tắc nghiệp vụ/evidence tổng
  quát mà nó sửa. Sample lỗi là bằng chứng tái hiện, không phải đặc tả toàn
  bộ hành vi cần hỗ trợ.
- Không rẽ nhánh runtime hoặc prompt theo scenario/call/turn ID, khách hàng,
  SKU, promo code, giá, ngày hoặc nguyên câu thoại lấy từ sample để trả đáp
  án mong đợi. Giá, mã, thời hạn và quan hệ sản phẩm phải đến từ dữ liệu/tool
  có nguồn; quy tắc nghiệp vụ thật vẫn được phép tồn tại dưới dạng contract
  chung có căn cứ, không dưới dạng ngoại lệ cho sample.
- Không thêm ví dụ prompt chứa đáp án của ca đang trượt để buộc model bắt
  chước; không thêm regex chỉ nhận đúng câu đã thấy. Rule ngôn ngữ phải có
  phạm vi ngữ nghĩa rõ, test paraphrase và ca phủ định/gần giống khác nghĩa.
- Trước khi thêm workaround, rà prompt/logic liên quan xem đã có ngoại lệ
  phụ thuộc sample hay chưa. Nếu có trong đường sửa, thay bằng quyết định
  dựa trên metadata và evidence; không mở rộng thành refactor toàn repo.
- Ngoài regression gốc, mỗi lớp lỗi phải có test độc lập với sample: đổi
  sản phẩm, thuộc tính, số tiền, promo, ngày và cách nói khi phù hợp; có cả
  trường hợp phải chấp nhận và phải chặn. Kỳ vọng được xác định từ contract
  và dữ liệu test, không sao chép output của code đang kiểm thử.
- Có test bất biến: thay định danh và giá trị nhưng giữ quan hệ nghiệp vụ
  thì quyết định phải tương đương; đảo điều kiện nghiệp vụ như hết hạn,
  hết hàng, đổi scope/session thì quyết định phải đổi đúng. Có ca kết hợp
  nhiều sản phẩm/promo để phát hiện giả định chỉ có một đối tượng.
- Không lấy việc bảy public sample pass làm bằng chứng đủ về khả năng tổng
  quát. Chỉ báo đúng những contract và biến thể đã kiểm chứng; không khẳng
  định chắc chắn pass private set.

## 3. Tạo đơn theo đúng biến thể

### Lỗi đã xác minh

SC04 FULL đã tạo đơn với giá 1.521.000đ nhưng dùng SKU cha `SKU-SN-RUN2`.
`catalog_variant()` chỉ biết catalog trong session hiện tại; thiếu catalog
thì trả nguyên SKU đầu vào. `prepare_tool_call()` sau đó bỏ size/color.
Cuộc gọi mới có memory nên tiếp tục bằng SKU cha mà không lấy lại variants.

### Hành vi yêu cầu

1. Phân biệt sản phẩm không có variants với sản phẩm chưa biết có variants.
   Thiếu catalog không được coi là bằng chứng rằng SKU cha có thể đặt mua.
2. Khi khách yêu cầu tạo đơn và chưa có catalog đủ dùng, lấy metadata qua
   `catalog.search` theo SKU. Dùng lại kết quả trong session nếu đã đủ; không
   cần tải lại catalog mỗi lượt hoặc lưu catalog vào hồ sơ khách.
3. Chọn variant duy nhất từ catalog theo lựa chọn trực tiếp trong lượt này,
   rồi mới đến preference đã lưu đúng product scope. Lựa chọn mới của khách
   được ưu tiên; không chuyển size/color từ sản phẩm khác.
4. Không tự ghép variant SKU. Nếu chưa đủ để chọn duy nhất, hỏi đúng thuộc
   tính còn thiếu; không hỏi lại thông tin đã có. Nếu lựa chọn không tồn tại,
   nêu rõ và đề nghị lựa chọn khả dụng, không tự đổi lựa chọn.
5. Kiểm tra stock/quote của đúng SKU sẽ đặt theo ngày nghiệp vụ và điều kiện
   báo giá hiện tại. Bằng chứng SKU cha không thay thế bằng chứng variant;
   không dùng giá variant khác chỉ vì cùng tiền. Giữ qty và các điều kiện
   ảnh hưởng ưu đãi nhất quán giữa quote và create.
6. MCP order phải chặn SKU cha có variants dù agent bỏ qua bước chọn. Không
   ghi đơn/tiêu thụ promo khi bị chặn. Sản phẩm không có variants vẫn được
   tạo đơn bằng SKU sản phẩm như hiện tại.

Nghiệm thu bằng mock/offline: khách quay lại không có catalog trong session,
chọn size/màu và đặt hàng phải đi đến đúng variant, đúng quote; ca thiếu
size/màu, hết hàng, size bị loại khỏi promo và variant cộng giá phải được
xử lý đúng. Regression dùng thêm mã sản phẩm khác, không hardcode SC04.

## 4. Câu trả lời phải nhất quán với kết quả giao dịch

### Lỗi đã xác minh

FULL có 12/39 lượt trả FALLBACK. Trong đó có lượt order đã tạo thành công
nhưng câu trả lời cuối lại nói chưa kiểm tra được và sẽ nhờ nhân viên.
Artifact hiện có không chứa đủ rejected draft/reason để quy nguyên nhân
cho từng lượt; không mặc định mọi fallback đều do cùng một guardrail.

### Hành vi yêu cầu

- Nếu draft bị verifier từ chối, vẫn giữ nguyên kết quả side effect đã xảy
  ra. Tạo câu xác nhận tối thiểu từ tool thành công: đơn đã tạo và mã đơn,
  kèm giá/tổng tiền khi có bằng chứng tương ứng. Câu phục hồi cũng phải đi
  qua verifier và che PII.
- Không gọi lại `order.create` để sửa câu trả lời; không tạo đơn thứ hai.
  Không tự hủy/sửa đơn hoặc báo thành công cho thao tác chưa thành công.
- Kết quả lỗi xác định phải được phản ánh đúng. Timeout/kết quả không rõ
  không được diễn đạt thành thành công hoặc chắc chắn chưa tạo đơn; dùng
  trạng thái chưa xác minh và đường tra cứu hiện có nếu đủ điều kiện.
- Nếu tool trả thành công nhưng đã vi phạm lựa chọn SKU đã xác minh, không
  gửi xác nhận như thể đơn hoàn toàn đúng. Nêu cần hỗ trợ kiểm tra đơn;
  không tự phát sinh thao tác bù. Rào chặn ở mục 3 phải ngăn ca này trước
  khi ghi đơn trong luồng bình thường.
- Không hứa đã chuyển nhân viên khi chưa có ticket thành công. Câu fallback
  chỉ mô tả trạng thái thực tế và bước tiếp theo có thể thực hiện.
- Với lượt chỉ đọc, dùng bằng chứng hợp lệ để phục hồi phần trả lời có thể
  xác minh. Không tắt hoặc nới verifier toàn cục để giảm fallback.

Nghiệm thu: draft sai ngày giao nhưng order thành công vẫn trả xác nhận đơn
có căn cứ; draft hứa quà sai không làm mất thông tin đơn; timeout không
được xác nhận thành công; không có thêm write tool trong bước phục hồi.
Phân tích các fallback cũ bằng diagnostic hiện có; không đặt mục tiêu xóa
mọi fallback vì có những lượt cần từ chối đúng.

## 5. Grounding giá và từng quyền lợi khuyến mãi

SC02 call_2 turn_2 nói về `GIFT-FILTER` còn hiệu lực trong quote, trong khi
sample gán `promo_active=false`. Đây là mâu thuẫn phạm vi claim/ground truth,
không phải bằng chứng agent nói `AP-SEP` còn hiệu lực. Tuy vậy, kiểm tra
offline cho thấy guardrail chấp nhận hứa quà khi quote chỉ có `COD-0`.

Yêu cầu kiểm chứng từng nội dung được khẳng định:

- Giá cuối, số tiền giảm, tỷ lệ giảm, quà, số lượng quà, hạn dùng và freeship
  phải có bằng chứng tương ứng cho đúng SKU/ngày/điều kiện. Việc tồn tại một
  applied promo bất kỳ không chứng minh mọi quyền lợi đều đúng.
- `COD-0` không chứng minh có giảm tiền hay tặng quà. Promo đã hết hạn,
  ineligible hoặc không được chọn không được mô tả là đang áp dụng.
- Hạn dùng lấy từ đúng promo; không lấy hạn của chương trình khác. Không
  suy đoán tên/quy cách quà từ gift SKU nếu chưa có metadata phù hợp.
- Phân biệt phủ định, thông tin lịch sử, câu hỏi và khẳng định hiện tại.
  Có thể nói mã cũ đã hết hạn và quyền lợi khác đang áp dụng trong cùng câu
  nếu từng phần đều có bằng chứng.
- Thiếu bằng chứng thì bỏ phần chưa xác minh hoặc nêu rõ chưa kiểm tra được
  phần đó; giữ phần giá/đơn/quyền lợi đã được xác minh. Không bịa ưu đãi để
  duy trì hội thoại và không thêm tool promotion mới chỉ để sửa ca này.

Test phải có lời hứa quà không kèm từ “ưu đãi/khuyến mãi”, quote chỉ freecod,
quà đúng nhưng hạn sai, nhiều promo có hạn khác nhau, miễn phí vận chuyển
không được chứng minh, và promo hợp lệ vẫn được chấp nhận.

## 6. Khách quay lại và trạng thái blocker

- Mở đầu bằng nhu cầu/giải pháp đã biết dưới dạng khẳng định ngắn; không yêu
  cầu khách cung cấp lại diện tích, trẻ nhỏ, ngân sách hoặc sản phẩm đã biết.
- Được hỏi tiến độ giải quyết blocker còn mở, vì đó là trạng thái mới cần
  cập nhật. Tách câu nhắc nhu cầu khỏi câu hỏi này để người nghe hiểu rõ.
- Nếu khách đã nói blocker được giải quyết, tiếp tục bước phù hợp; không hỏi
  lại. Nếu khách đã yêu cầu đặt hàng, ưu tiên xử lý đặt hàng thay vì lời chào
  hoặc thăm dò tiến độ.
- `suggested_opening` và prompt phải cùng tuân thủ quy tắc trên. Không ép
  mọi lượt khách quay lại dùng một câu cố định hoặc nhắc mọi fact trong brief.

Ví dụ: “Mẫu lần trước có khóa trẻ em, phù hợp nhu cầu nhà mình. Về việc trao
đổi với anh nhà, chị đã có quyết định chưa ạ?” là hỏi trạng thái blocker,
không phải hỏi nhà có trẻ nhỏ hay không. Biến thể diễn đạt tương đương phải
được kiểm thử, không chỉ sửa đúng câu trong SC01.

## 7. Phép đo phải phản ánh phát ngôn và provenance

### 7.1. Câu hỏi và claim

- Trích slot theo điều được hỏi, không theo từ xuất hiện ở bất kỳ đâu trong
  câu. Một câu hỏi nhiều slot phải giữ các slot thực sự được hỏi; phần nhắc
  bối cảnh không trở thành câu hỏi mới. Phân biệt hỏi lại hồ sơ với hỏi tiến
  độ blocker; chỉ xác nhận khi ngữ nghĩa thực sự là xác nhận.
- Claim phải phản ánh điều agent đã nói. Tool chỉ giúp liên kết đối tượng
  được nói tới, không được tự tạo claim hoặc đổi một claim sai thành đúng.
- Giữ giá niêm yết, giá cuối và loại quyền lợi/phạm vi chương trình riêng
  khi trace schema BTC hỗ trợ; không tự thêm field vào public trace trái
  schema. Claim nói rõ về một chương trình phải giữ chương trình đó.
- Không lược bỏ claim bất lợi, gắn mã promo agent chưa nói chỉ để tránh
  ground truth, hoặc ép claim vào field thuận lợi hơn để tăng điểm.
- Nếu schema/ground truth không diễn đạt đúng một quyền lợi có bằng chứng,
  giữ nguyên nội dung phát ngôn và kết quả chấm gốc, ghi rõ bất đồng trong
  bản phân tích đi kèm. Không override kết quả official bằng tool truth.

Bộ fixture gán nhãn thủ công hiện có phải bổ sung cặp câu dương/âm, phủ
định, lịch sử, câu hỏi nhiều slot, nhắc trẻ em rồi hỏi blocker, quà hiện tại
cùng mã giảm giá đã hết hạn. Fixtures phải có kỳ vọng độc lập với output
của extractor; dùng thêm cách diễn đạt ngoài bảy sample.

### 7.2. `facts_used` và CCR

- Xác định nguồn session theo định dạng thực `langmem:<session>:<turn>`,
  không coi token `langmem` là session. Giữ tương thích định dạng cũ được
  xác định trong test; nguồn thiếu/sai định dạng không đủ để tính carryover.
- Chỉ tính fact từ session trước của đúng khách khi phát ngôn hoặc tham số
  tool sử dụng đúng giá trị/ngữ nghĩa. Nạp vào context chưa đủ để tính dùng.
- Fact cùng session không thành cross-session carryover; fact được khách
  nhắc lại trong call mới không tự chứng minh agent đã nhớ từ call cũ.
- Boolean phải đúng polarity; số tiền diễn đạt `1.521.000đ` hoặc `1521k`
  phải khớp đúng giá trị, không dựa vào substring hay số trùng ngẫu nhiên.
- Với cùng slot ở nhiều product/room scope, phải liên kết đúng scope; không
  tính fact của sản phẩm khác chỉ vì cùng giá trị. Public `facts_used` vẫn
  theo schema BTC; chứng cứ scope được kiểm tra trước khi xuất tên slot.

CCR official vẫn do scorer BTC tính, bao gồm cách scorer xem tool args.
Không sửa công thức để ép CCR về giá trị kỳ vọng hoặc dùng lại 61,9% như
bằng chứng chính xác sau khi đổi adapter.

### 7.3. RQR và recall/precision nội bộ

- Baseline RQR bằng 0 làm relative reduction không xác định. Giữ `null` và
  boolean gốc của scorer, giải thích “chưa chứng minh được giảm ≥40%”. Không
  đổi thành pass, không làm baseline hỏi lặp thêm để tạo mức giảm.
- Memory recall/precision hiện đối chiếu slot theo call với danh sách sample
  không đầy đủ. Mô tả rõ đây là diagnostic khớp expected slot/value, không
  phải tỷ lệ fact đúng hoặc số record rác. Giữ số đếm gốc có thể kiểm tra.
- Chuẩn hóa dấu/Unicode và alias tương đương cho free text khi đủ nghĩa;
  không biến hai blocker khác nghĩa thành một. SKU và tiền vẫn so theo
  contract chính xác hiện có, không fuzzy match để tăng recall.
- ID đơn động phải kiểm chứng bằng tool/link nghiệp vụ thực tế. Nếu expected
  ID cố định không có ánh xạ được xác minh, giữ discrepancy; không thay bằng
  ID expected hoặc bịa alias.
- `channel` có thể nằm ở episode metadata; không ép nó thành profile fact.
  `alt_suggested` chỉ ghi khi thực sự tư vấn và có bằng chứng sản phẩm.

## 8. Chất lượng memory thực tế

Giữ ba lớp: customer facts có bằng chứng; episode ghi lịch sử tư vấn, giá
và blocker; tool cung cấp trạng thái hiện tại. Không xóa dữ liệu hữu ích
chỉ vì sample không liệt kê nó hoặc agent chưa nhắc lại trong call sau.

- Điều tra fact thiếu bằng cách đối chiếu input đã commit, proposal,
  admission và accepted write của cùng source turn. Dùng diagnostic/reason
  hiện có; không ghi raw PII hoặc mở thêm hệ thống observability.
- Với giá đối thủ ở SC02, helper offline đã nhận được 4.590.000đ. Cần xác
  định tầng mất fact trước khi sửa. Proposal không hợp lệ không được ngăn
  một ứng viên có bằng chứng hợp lệ cho cùng slot được xét bổ sung.
- Blocker phải giữ nghĩa, scope và trạng thái open/resolved. Không đổi “cần
  cân nhắc thêm” thành “so sánh giá” chỉ vì sample expected như vậy.
- Kiểm tra các write không đổi giá trị theo đúng customer/scope/key. Có thể
  cập nhật bằng chứng/ngày quan sát mới; không được làm mất provenance hoặc
  cơ chế revision/retry để chỉ giảm số write. Thuật toán compaction mới nằm
  ngoài phạm vi nếu chưa chứng minh cần thiết cho các lỗi này.
- Tồn kho cũ là quan sát lịch sử có ngày; không dùng như stock hiện tại.
  Không thêm TTL tùy ý cho mọi slot trong đợt sửa này.

## 9. Thành phần dự kiến chịu ảnh hưởng

| Phần | Điểm sửa chính |
| --- | --- |
| Variant/order | `harness/policy.py`, `implementations/business_agent.py`, MCP order service và shared commerce rules nếu cần |
| Phản hồi giao dịch | `harness/agent_nodes.py`, helper phục hồi và verifier hiện có |
| Grounding | `guardrails/checks.py`, dữ liệu catalog/quote đã có |
| Khách quay lại | `harness/brief_opening.py`, prompt và context liên quan |
| Trích xuất/chấm nội bộ | `eval_harness/extractor.py`, `reference_adapter.py`, `memory_recall.py` |
| Memory thiếu | extractor/admission/worker, chỉ sửa nơi có bằng chứng mất fact |

Không dự kiến migration SQL, đổi public API hoặc cấu hình bắt buộc. Nếu
implementation cần các thay đổi này, phải nêu rõ ảnh hưởng trước khi mở rộng
phạm vi. Không tạo dependency vòng agent ↔ MCP để tái sử dụng helper.
Nếu runtime dùng prompt production từ Langfuse, bản triển khai phải xác định
prompt nào thực sự được nạp; sửa local fallback không được báo là đã áp dụng
cho production. Spec này không cho phép tự publish prompt từ xa.

## 10. Nghiệm thu và thứ tự xác minh

Hai nhóm tiêu chí độc lập: contract nghiệp vụ/đo lường phải đạt offline;
điểm BTC chỉ được kết luận từ lượt chạy mới đầy đủ được cho phép.

1. Viết regression tái hiện các lỗi trước khi sửa từng nhóm hành vi. Mock
   model và MCP để không gọi model thật. Test đúng kết quả quan sát được,
   không chỉ mirror cấu trúc helper.
2. Kiểm thử tập trung cho file/hành vi đang đổi: variant, phản hồi sau write,
   grounding, opening, extraction, provenance, admission tương ứng. Mọi đổi
   `reference_adapter.py` phải giữ test mọi tên tool/call id và args scorer.
   Bắt buộc đáp ứng mục 2.1: review code/prompt không có nhánh chữa riêng
   sample, và test biến thể độc lập cùng bất biến nghiệp vụ phải đạt.
3. Re-extract offline từ trace đã lưu vào artifact mới, không ghi đè run
   gốc. Cố định agent text/tool results; chỉ các field được adapter suy ra
   mới được tái tạo. Đây là kiểm tra phép đo, không chứng minh agent tốt hơn.
4. Đối chiếu từng thay đổi số đo với nhãn fixture và nội dung trace, giữ cả
   trường hợp bất đồng. Không tạo “điểm agent sau sửa” từ hội thoại cũ.
5. Chạy full regression repo một lần trước khi báo hoàn tất implementation.
   DB integration chỉ chạy trên môi trường được cho phép; nếu thiếu điều
   kiện thì nêu giới hạn, không báo đã kiểm chứng phần đó.
6. Chỉ khi được cho phép riêng mới chạy lại FULL/baseline, giữ cùng model,
   seed, dữ liệu và điều kiện nghiệp vụ. Phải đủ coverage và job hoàn tất;
   không publish score từ run lỗi/gián đoạn.

Nghiệm thu offline bắt buộc: chọn variant đúng và chặn SKU cha không hợp lệ;
không xác nhận giao dịch chưa thành công; không mất xác nhận hợp lệ sau
verifier; không bịa quyền lợi; không hỏi lại hồ sơ đã biết; không nhầm hỏi
blocker thành hỏi has_children; không tính fact cùng session là carryover;
giữ nguyên BTC schema/scorer và ranh giới PII/customer identity.

Sau live run được phép, báo nguyên kết quả TSR ≥70%, HR giá/khuyến mãi ≤5%,
RQR reduction ≥40% theo scorer cùng trạng thái đo được. Nếu baseline RQR
bằng 0 hoặc sample/tool truth mâu thuẫn, ghi rõ giới hạn và trạng thái BTC
thực tế; không dùng test offline để tuyên bố đã qua ngưỡng.

## 11. Quyết định giao cho người triển khai

Người triển khai chọn vị trí helper, cấu trúc evidence nội bộ và cách phục
hồi câu trả lời ngắn nhất đáp ứng contract. Ưu tiên tái sử dụng code hiện
có, không thêm framework. Các quyết định đó không được thay đổi semantics
claim, phân tách session/customer, kiến trúc LangMem hoặc nguồn chấm BTC.

Thứ tự đề xuất: variant và phản hồi giao dịch; sửa phép đo; grounding và
opening; rồi sửa tầng memory thực sự làm mất fact. Đây là thứ tự ưu tiên,
không phải implementation plan đã được phê duyệt.
