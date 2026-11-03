# Spec: MCP Knowledge và RAG chính sách BTC

Ngày: 03/11/2026.

Trạng thái: cập nhật các quyết định đã thống nhất sau rà soát thiết kế;
các thông số kỹ thuật còn mở ở mục 15.
Spec không phải báo cáo kết quả triển khai hoặc benchmark.

## 1. Mục tiêu và căn cứ

Xây dựng `mcp-knowledge` riêng trong nhánh MCP của dự án. Theo mục C.3 của
đề bài BTC, M2 bổ sung `mcp-order`, `mcp-knowledge` và phân quyền theo tool.
Server phải phục vụ agent thực tế và kiểm chứng được trên nhiều tình huống,
không chỉ chạy một case demo.

Nguồn đối chiếu:

- `/home/thanh-phuc/PyProject/sudocode/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf`.
- `/home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/policy/`:
  14 tài liệu, 99 mục chuẩn có mã BTC.
- `/home/thanh-phuc/PyProject/sudocode/BTC-Data-Vong1-TEAMS/rag/qa_labeled.json`:
  60 câu thuộc single, multi_hop, version_conflict, unanswerable, restricted, numeric.
- `BTC-Data-Vong1-TEAMS/eval/reference_eval.py`, `DIEU-CHINH-DE.md`,
  `GIAI-DAP-MENTOR.md`.
- Spec liên quan: `2026-11-02-knowledge-gap-loop-design.md` trong cùng thư mục.

Thiết kế ưu tiên quy tắc hệ thống có thể kiểm chứng. Không giao cho LLM quyết định
quyền truy cập, release hoặc hiệu lực chính sách.

Ưu tiên nghiệm thu là hoàn thành các yêu cầu BTC. Chưa bổ sung ngưỡng chất lượng
hoặc latency riêng của dự án; các thông số vận hành được chọn để phục vụ yêu cầu
BTC, không tự trở thành tiêu chí nghiệm thu mới.

## 2. Phạm vi và ranh giới trách nhiệm

Knowledge cung cấp bằng chứng cho:

- Đổi trả, bảo hành, vận chuyển và thanh toán.
- FAQ và thông số ba ngành hàng.
- Quy tắc áp dụng khuyến mãi.
- Playbook, quy trình COD/hoàn tiền và lịch nghỉ.
- Giới hạn kiến thức, giới hạn tiết lộ và hướng dẫn chuyển người phụ trách.

Knowledge không chốt giá cuối, xác nhận tồn kho, thực hiện đổi trả, tạo đơn,
đặt lịch gọi lại hoặc xóa dữ liệu. Các dịch vụ nghiệp vụ tương ứng thực hiện các việc đó.
Catalog/promotions vẫn là nguồn ưu tiên tại những nơi tài liệu BTC đã quy định.

Không thêm dashboard, fine-tuning, rerank model, LLM rewrite riêng hoặc provider
fallback trong phạm vi bản đầu.

## 3. Kiến trúc và tích hợp

```text
Agent
  -> MCP Gateway: ngữ cảnh tin cậy
  -> mcp-knowledge / policy.search
       -> FlagEmbedding / BGE-M3: dense + sparse
       -> Qdrant: hai prefetch + RRF trong một request
       -> PostgreSQL: xác minh và đọc nguồn theo release
       -> Quy tắc hệ thống: quyền, thời gian, liên kết, thứ hạng
       -> Bằng chứng có cấu trúc
```

- Tạo server MCP riêng, cấu hình endpoint và quyền DB riêng; giữ handler mỏng,
  nghiệp vụ nằm trong service/module dùng chung.
- Giữ tên tool `policy.search`; chuyển routing từ catalog sang knowledge.
  Không công bố hai implementation cạnh tranh cho cùng một tool trong gateway.
- Tái sử dụng logic hữu ích hiện có, thay vì nhân bản retrieval hoặc Knowledge Gap Loop.
- Agent không có tool duyệt, phát hành hoặc sửa tri thức.
- Quyền DB của knowledge chỉ đủ đọc dữ liệu phục vụ. Quyền nạp/phát hành tách riêng.
- PostgreSQL là nguồn nội dung và manifest có thẩm quyền. Qdrant phục vụ index
  dense/sparse; payload không được biến thành cách vượt quyền đọc nguồn.

Chuyển routing phải đi cùng chuyển hợp đồng đầu ra. Hiện các consumer đọc
`chunks[].body`, trong khi hợp đồng mới dùng `evidence[].content`. Khi triển khai,
cập nhật đồng bộ agent, guardrail/grounding, diagnostics, tracing/eval adapter và
các điểm thu bằng chứng của Knowledge Gap Loop; không chỉ đổi tên endpoint.
Hợp đồng ở mục 9 là đầu ra chuẩn. Nếu cần adapter tương thích, đặt tại một ranh
giới rõ ràng, giữ nguyên ID, nội dung, điều kiện, thứ tự và trạng thái thiếu bằng
chứng; không duy trì hai cách diễn giải độc lập. Kiểm thử xuyên luồng MCP -> agent
-> guardrail -> Knowledge Gap Loop trước khi chuyển routing phục vụ.

## 4. Embedding và readiness

Phương án thiết kế: FlagEmbedding chạy trong tiến trình MCP, BGE-M3 chạy local
trên RTX 3050 4 GB; ASR nằm trên máy khác. Không tạo thêm embedding HTTP server.
Khả năng đáp ứng VRAM và latency phải được đo trước nghiệm thu.

- Một tiến trình giữ một bản model; không nhân bản theo số web worker.
- Một worker encode, hàng đợi hữu hạn; không chặn event loop MCP.
- FP16, bật dense và sparse, tắt ColBERT.
- Model revision và tokenizer được cố định; Qdrant chạy CPU.
- Độ dài đầu vào được kiểm tra theo tokenizer. Không âm thầm cắt query hoặc bảng.
- Tách nạp tài liệu khỏi lượt phục vụ hội thoại; tài liệu được encode trước.

Khởi động tuần tự:

1. Kiểm tra cấu hình, nạp model lên đúng thiết bị.
2. Chạy thành công đúng 3 lượt warmup encode liên tiếp, bật dense và sparse như runtime.
3. Kiểm tra đầu ra hợp lệ.
4. Kiểm tra PostgreSQL, Qdrant, collection và manifest của release phục vụ.
5. Chuyển sang `ready`, nhận yêu cầu tra cứu.

Warmup dùng văn bản cố định, không có PII. Nếu một lượt thất bại, khởi động thất bại,
không chuyển CPU hoặc phương pháp retrieval ngầm. Không embedding corpus khi khởi động.
Ba lượt warmup này không thay thế quy trình warmup của phép đo latency BTC.

## 5. Chunking và nguồn an toàn

- Mỗi mục có mã BTC là đơn vị bằng chứng chuẩn; giữ nguyên mã như `DT-03`.
- Mặc định một mục là một chunk, không chia đều theo số token.
- Giữ nguyên bảng hiện tại cùng tiêu đề, đơn vị và ghi chú.
- Lời dẫn chứa quy định chung phải đi theo các mục chịu ảnh hưởng.
- Nếu cần chunk con, dùng ID riêng và ánh xạ về mã mục BTC gốc; công bố cách ánh xạ.
- Lưu nguồn gốc bất biến để đối chiếu; không sửa tài liệu hoặc nhãn BTC để tăng điểm.

Nội dung trộn công khai và hạn chế phải được xử lý trước khi embedding:

- `NB-02`: bản phục vụ khách chỉ giữ thông tin ngày hàng về dự kiến được phép nói;
  loại số lượng, nhà cung cấp và các phần không được công bố.
- `KM-06`: không đưa giá sàn nội bộ vào nội dung phục vụ khách; giữ quy tắc
  không tự giảm ngoài chương trình và chuyển quản lý khi phù hợp.
- `NB-01`, `NB-03`: có thể tạo bằng chứng an toàn về việc không được tiết lộ,
  liên kết đúng mục gốc nhưng không chứa giá nhập, biên lợi nhuận hoặc nhà cung cấp.
- Tài liệu hành chính gây nhiễu không tự động trở thành nguồn tư vấn khách.

Bản nội dung an toàn phải có hash, quy tắc biến đổi và quan hệ về nguồn.
Không gửi dữ liệu bí mật tới agent rồi trông chờ LLM tự che.
Không tạo bằng chứng an toàn hoặc liên kết từ đáp án của bộ QA.

## 6. Metadata

| Nhóm | Nội dung |
|---|---|
| Định danh | `chunk_id`, `section_id`, `document_id` |
| Truy nguồn | File, vị trí nguồn, hash nguồn và bản nội dung phục vụ |
| Phiên bản | Phiên bản tài liệu, quan hệ thay thế |
| Thời gian | `date_basis`, `effective_from`, `effective_until` |
| Quyền | Mức truy cập, mục đích sử dụng, quy tắc biến đổi nội dung |
| Điều kiện | Điều kiện áp dụng, dữ kiện cần để kết luận, nguồn chứng minh |
| Quan hệ | Mục liên quan, loại liên kết, nguồn được ưu tiên |
| Phát hành | `release_id`, phiên bản cấu hình xử lý |

Parser đọc cấu trúc Markdown; cấu hình tường minh xác định metadata quan trọng
về thời gian, quyền và quan hệ nguồn. Không dùng LLM tự gán các thuộc tính này.

Phân biệt nguồn không quy định với chưa xác định được. Không đoán ngày hiệu lực
từ tên file hoặc suy ra mọi tài liệu cùng bắt đầu hiệu lực một ngày.
Metadata sản phẩm/ngành hàng có thể dùng để kiểm tra và truy vết, không dùng làm
bộ lọc retrieval dựa vào phân loại của LLM.

Chunk thiếu metadata bắt buộc hoặc có mâu thuẫn chưa xử lý không được phát hành
như bằng chứng đủ điều kiện kết luận. Cấu hình phải ghi rõ trường hợp được giữ lại
như bằng chứng có điều kiện hoặc để giải thích mâu thuẫn.

Một mục BTC có thể chứa nhiều quy tắc theo sản phẩm, ngày hoặc ngoại lệ. Cấu hình
phải biểu diễn được phạm vi từng quy tắc và quan hệ ưu tiên/thay thế, không gán một
khoảng hiệu lực chung làm sai các phần còn lại của chunk. Ví dụ `BH-01` kết hợp
`CL-04` phải giữ được ngoại lệ Karofi/Kangaroo cho đơn trước 01/08/2026; dữ liệu
catalog hiện hành không mặc nhiên chứng minh quyền lợi của đơn lịch sử.
Giữ ánh xạ về mục BTC khi cần biểu diễn quy tắc hoặc chunk con.

Quy tắc ngày biên và múi giờ phải được khai báo nhất quán. Ngày chỉ biết theo tháng
không được tự đổi thành một ngày chính xác; nếu chưa đủ phân biệt phiên bản,
giữ kết luận có điều kiện và yêu cầu làm rõ.

## 7. Hợp đồng đầu vào

```json
{
  "query": "Đơn này đổi size có mất phí không?",
  "on": "2026-11-03",
  "order_date": "2026-09-20",
  "top_k": 5
}
```

| Trường | Quy tắc |
|---|---|
| `query` | Bắt buộc, không rỗng; agent truyền trong lần gọi tool vốn có |
| `on` | Bắt buộc, ngày ISO; gateway cấp từ thời gian thực thi hoặc kịch bản |
| `order_date` | Tùy chọn, ngày ISO; gateway chỉ bổ sung khi có dữ kiện đã xác minh |
| `customer_reported_order_date` | Tùy chọn, ngày ISO do khách khai; chỉ phục vụ giải thích có điều kiện, không phải ngày đã xác minh |
| `top_k` | Số kết quả mong muốn, mặc định 5, đầu vào giới hạn 1–10; có thể vượt để giữ đủ bằng chứng bắt buộc theo mục 8 |

Câu hỏi đầy đủ ưu tiên giữ nguyên; câu nối tiếp được bổ sung chủ đề từ hội thoại,
không tự thêm sự kiện. Không có lần gọi LLM rewrite riêng.
Hệ thống giữ câu khách gốc để đối chiếu theo quy tắc PII.

Quyền, `request_id`, release và nguồn xác minh thời gian đi qua ngữ cảnh tin cậy;
LLM không được tự khai hoặc ghi đè. Không có tham số lọc intent/ngành hàng/SKU.

Gateway giữ riêng ngày khách khai và ngày đơn đã xác minh, cùng nguồn của mỗi
dữ kiện; không nâng ngày khách khai thành `order_date`. Ngày khai chưa đủ độ chính
xác được giữ trong ngữ cảnh hội thoại để hỏi lại, không ép thành ngày ISO giả.
Nếu hai nguồn ngày khác nhau, ngày đã xác minh quyết định áp dụng cho đơn và
agent làm rõ khác biệt với khách khi cần.

Ngữ cảnh tin cậy phải được bảo vệ qua xác thực/phân quyền caller tại ranh giới
MCP. Việc đặt tên trường hoặc loại tham số do LLM truyền không tự chứng minh
nguồn dữ kiện. Lời gọi độc lập cũng phải tuân cùng quy tắc; không cho caller không
đủ quyền tự khai release, quyền hoặc nguồn xác minh thời gian.

## 8. Search, liên kết và thời gian

1. Ghim release nhất quán với lượt agent, hoặc tại đầu request nếu gọi độc lập.
2. Encode query một lần, xuất dense và sparse.
3. Gửi một request Qdrant gồm hai prefetch và RRF.
4. Đối chiếu ứng viên với snapshot nguồn PostgreSQL, release và hash.
5. Kiểm tra quyền và điều kiện thời gian bằng quy tắc hệ thống.
6. Bổ sung mục liên quan được đánh dấu cần thiết, tối đa một cấp.
7. Loại trùng, xếp hạng theo quy tắc và chọn bằng chứng theo ngân sách ở dưới.

Quyền và release phải giới hạn cả hai prefetch; kiểm tra lại sau retrieval là lớp
bảo vệ bổ sung. Nguồn nội bộ thô không nằm trong index phục vụ khách.
Không lấy ít ứng viên rồi mới loại hàng loạt để lại kết quả thiếu giả tạo;
số ứng viên nội bộ cần lớn hơn `top_k` và được chọn qua kiểm chứng.

RRF là thứ hạng nền. Điều chỉnh phải có căn cứ, ổn định và kiểm thử được, không
cộng điểm tùy ý. Liên kết tham khảo không tự động chiếm vị trí kết quả.
Bằng chứng bổ sung phải nằm trong danh sách cuối, không có bằng chứng ngầm ngoài
danh sách mà agent hoặc eval được phép coi là đã truy hồi.

- Ưu tiên giữ đủ nhóm chính sách và ngoại lệ bắt buộc; giảm các kết quả ít cần
  thiết hơn để đáp ứng `top_k` trước.
- Nếu riêng nhóm bằng chứng bắt buộc vượt `top_k`, được tăng số kết quả đến giới
  hạn cứng cấu hình phía server. Agent không được tự ghi đè giới hạn này.
- Khi chạm giới hạn cứng mà vẫn thiếu, công bố nhóm phụ thuộc chưa đầy đủ và các
  mục bắt buộc còn thiếu được phép công khai. Không trình bày nhóm đó như đủ căn cứ.
- Chỉ trả lời phần độc lập đã đủ căn cứ; phần cần bằng chứng bị thiếu phải được
  nói rõ là chưa thể kết luận. Không bỏ ngoại lệ rồi khẳng định chính sách chung
  áp dụng cho tình huống cụ thể.
- Quy tắc ưu tiên nhóm và thứ tự trong danh sách cuối phải ổn định, kiểm thử được.
  Giới hạn cứng chưa chốt số cụ thể, được chọn theo corpus và ngân sách context.

Phân biệt ngày tra cứu và ngày quyết định chính sách:

- Hỏi chính sách chung: dùng `on` để trình bày chính sách hiện hành, nêu ngoại lệ
  cho đơn cũ khi liên quan. Không bắt hỏi ngày đơn cho mọi câu hỏi chung.
- Hỏi quyền lợi của đơn cụ thể: dùng ngày đã xác minh theo `date_basis`.
- Thiếu ngày quyết định: trả bằng chứng có điều kiện, chưa kết luận cho đơn.
- Chỉ có ngày khách khai: được giải thích chính sách theo ngày đó nhưng phải nêu
  rõ chưa xác minh được đơn/quyền lợi. Không xác nhận đủ điều kiện, hứa đổi trả,
  hoàn tiền hoặc thực hiện thao tác cần đơn đã xác minh.
- Không lấy `on` thay `order_date`; không xóa bản cũ khi hết thời gian hiện hành.
- Changelog vẫn dùng làm bằng chứng giải thích thay đổi và ngoại lệ.
- Ngày hàng về dự kiến đã qua không chứng minh hàng đã về; phải đối chiếu inventory.

Không thêm LLM reranker hoặc model reranker. RRF score không phải xác suất đúng;
không đặt ngưỡng tùy ý để tự khẳng định có/không đủ bằng chứng.

### 8.1. Mức căn cứ và hành vi của agent

Có kết quả retrieval không đồng nghĩa đủ căn cứ trả lời. Agent đối chiếu từng ý
khách hỏi với nội dung, điều kiện áp dụng và trạng thái phụ thuộc được MCP trả về
trong lượt xử lý sẵn có; không thêm lượt LLM đánh giá/rewrite riêng.

| Tình huống | Hành vi |
|---|---|
| Đủ căn cứ | Trả lời bám đúng nội dung và điều kiện của nguồn |
| Đủ một phần | Chỉ trả lời phần có căn cứ độc lập; nói rõ phần chưa xác nhận, không suy ra phần còn lại |
| Thiếu dữ kiện khách có thể bổ sung | Ưu tiên hỏi một câu làm rõ dữ kiện cần thiết trước khi kết luận thiếu tri thức |
| Chỉ gần chủ đề, không hỗ trợ kết luận | Không dùng để trả lời nội dung; nói thẳng chưa xác nhận được thông tin |
| Nguồn hợp lệ mâu thuẫn | Theo thứ tự ưu tiên BTC; nếu không phân xử được, nói rõ phần chưa xác nhận và xử lý theo nghiệp vụ hiện tại |

Không bắt hỏi thêm khi đã có đủ dữ kiện tin cậy, hoặc khi câu hỏi chính sách chung
không cần dữ kiện của đơn. Câu hỏi nối tiếp giữ ngữ cảnh đã biết để tránh hỏi lặp.
Giá hiện hành vẫn phải lấy từ tool giá, không lấy ví dụ tĩnh trong policy làm giá chốt.

Agent không chủ động đề nghị hẹn gọi lại chỉ vì thiếu thông tin hoặc bằng chứng.
Chuyển nhân viên tuân nghiệp vụ BTC và logic hệ thống hiện tại; không thêm điều
kiện chuyển máy hoặc luồng hẹn gọi lại mới trong spec này.

Bằng chứng `knowledge_limit` hoặc `disclosure_limit` có thể đủ căn cứ để nói chưa
có thông tin hoặc từ chối tiết lộ, dù không cung cấp được nội dung khách yêu cầu.
Thiếu dữ kiện hội thoại, nguồn mâu thuẫn và thiếu bằng chứng do giới hạn kết quả
không tự chứng minh kho tri thức thiếu nội dung.

## 9. Hợp đồng đầu ra

Ví dụ minh họa cấu trúc, không phải kết quả chạy thực tế:

```json
{
  "retrieval_status": "ok",
  "context": {
    "on": "2026-11-03",
    "order_date": "2026-09-20",
    "customer_reported_order_date": null,
    "knowledge_release_id": "..."
  },
  "truncated": false,
  "evidence_set": {
    "required_dependencies_complete": true,
    "missing_required_section_ids": []
  },
  "evidence": [
    {
      "chunk_id": "DT-OLD-03",
      "section_id": "DT-OLD-03",
      "content": "...nội dung được phép cung cấp...",
      "evidence_type": "business_rule",
      "source": {
        "file": "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md",
        "version": "2026-06"
      },
      "applicability": {
        "status": "applicable",
        "date_basis": "order_date",
        "required_context": []
      },
      "retrieved_via": "vector"
    }
  ]
}
```

- Loại bằng chứng: `business_rule`, `knowledge_limit`, `disclosure_limit`,
  `handoff_guidance`; khai báo từ nguồn/cấu hình, không thêm LLM classifier.
- Khả năng áp dụng theo từng bằng chứng: `applicable`, `conditional`, `conflict`.
  Đủ điều kiện thời gian không có nghĩa đã xác nhận mọi điều kiện nghiệp vụ.
- `required_context` phục vụ kết luận cho tình huống cụ thể; không ngăn giải thích
  chính sách chung. Định nghĩa các khóa theo registry, không tự sinh tên tùy ý.
- Trả khoảng hiệu lực và điều kiện khi nguồn có quy định, cùng ngày được dùng
  để đối chiếu để kiểm tra được lựa chọn phiên bản.
- `retrieved_via`: `vector` cho kết quả hybrid/RRF, `linked` cho bổ sung metadata.
- Nguồn/metadata xuất ra phải được phép cung cấp; bằng chứng từ nguồn restricted
  dùng biểu diễn an toàn, không lộ nội dung bí mật qua title, filename hoặc log.
- Không trả câu trả lời hoàn chỉnh cho khách trong MCP.
- Bản đầu không cắt nội dung âm thầm, `truncated` là false. Nếu có cơ chế cắt
  sau này, phải khai báo true và phạm vi thiếu; không coi bằng chứng đó là đầy đủ.
- Quy ước kỹ thuật cho tập bằng chứng: `evidence_set.required_dependencies_complete`
  mô tả có trả đủ các phụ thuộc bắt buộc đã xác định cho nhóm được chọn hay không;
  `missing_required_section_ids` liệt kê các mục còn thiếu được phép công khai.
  Đây không phải chứng nhận đã trả lời đầy đủ câu hỏi hoặc đã xác minh quyền lợi.
- `truncated: false` chỉ nói nội dung chunk không bị cắt, không thay thế trạng thái
  đầy đủ của tập bằng chứng. Nhóm thiếu phụ thuộc phải đánh dấu bằng chứng liên
  quan là `conditional` và chỉ rõ phụ thuộc thiếu để agent nhận biết phần bị ảnh hưởng.
- Ngữ cảnh và applicability phải phân biệt ngày khách khai với ngày đã xác minh.
  Nếu chỉ dựa vào ngày khách khai, bằng chứng cho quyền lợi của đơn là `conditional`.
  Bằng chứng mâu thuẫn chưa phân xử được mang trạng thái `conflict`.

## 10. Lỗi, retry và circuit breaker

| Trạng thái | Ý nghĩa |
|---|---|
| `ok` | Retrieval thành công; không chứng nhận đủ căn cứ, agent vẫn phải đọc nội dung, điều kiện và phần thiếu |
| `no_evidence` | Pipeline hoàn tất nhưng không có bằng chứng đạt tiêu chí |
| `unavailable` | Phụ thuộc hoặc dịch vụ chưa sẵn sàng |
| `timeout` | Hết ngân sách thời gian |
| `overloaded` | Hàng đợi đầy, từ chối nhanh |

Đầu vào sai bị từ chối bằng lỗi validation trước retrieval.
Lỗi vận hành trả trạng thái phân loại và `evidence: []`, không trả dữ liệu dở dang
như một kết quả thành công. Log ghi thành phần lỗi, mã nguyên nhân và request/release ID.

- Một worker encode, hàng đợi hữu hạn; fail fast khi đầy.
- Có deadline tổng, gồm cả thời gian chờ hàng đợi và retry.
- Retry tối đa một lần với lỗi tạm thời đã phân loại, chỉ khi còn đủ ngân sách.
- Không retry GPU OOM, cấu hình sai, manifest/hash không hợp lệ hoặc dữ liệu sai quyền.
- Circuit breaker theo phụ thuộc, có ngưỡng lỗi, cooldown và probe phục hồi hữu hạn.
- Timeout ở bên chờ không được làm GPU chạy nhiều tác vụ chồng lên nhau: giữ quyền
  worker cho đến khi tác vụ thực sự hoàn tất; loại tác vụ hết hạn còn trong hàng đợi.
- Khi unavailable/timeout/overloaded, agent không dùng kiến thức LLM để thay tài liệu;
  thông báo chưa tra được và chuyển tiếp theo luồng nghiệp vụ.

Trong luồng search -> Knowledge Gap Loop, chỉ `no_evidence` đủ điều kiện tạo tín
hiệu thiếu tri thức; không tự động chuyển mọi sự kiện như vậy thành một gap đã xác nhận.
Lỗi kỹ thuật theo luồng xử lý kỹ thuật, không làm nhiễu số liệu thiếu tri thức.
Các nguồn feedback khác của Knowledge Gap Loop đã được duyệt vẫn giữ phạm vi của chúng.

`no_evidence` không được xác định chỉ bằng danh sách ứng viên rỗng hay có phần tử.
Ứng viên chỉ gần chủ đề không tự trở thành bằng chứng đủ điều kiện. Tiêu chí loại
bằng chứng yếu phải được xác định và kiểm chứng trước khi hoàn thiện luồng search;
không để đến cuối nghiệm thu mới quyết định. MCP chịu trách nhiệm tiêu chí retrieval,
quyền, thời gian và phụ thuộc; agent chịu trách nhiệm đối chiếu từng ý cần trả lời
theo mục 8.1. Không đồng nhất `no_evidence` với mọi trường hợp agent chưa thể kết luận.

Bản đầu không fallback. Nếu bổ sung sau này, coi là chế độ riêng với cờ cấu hình,
nhãn pipeline và đánh giá riêng, không chuyển ngầm.

## 11. Nạp, upsert và tính đồng nhất release

Không quét định kỳ. Người phụ trách chủ động chạy lệnh:

```text
Nguồn + cấu hình đã duyệt
  -> Parse/chunk/nội dung an toàn
  -> Kiểm tra metadata và liên kết
  -> Encode dense + sparse
  -> Upsert release đang chuẩn bị
  -> Kiểm tra đầy đủ
  -> Chủ động kích hoạt
```

- Chạy lại cùng đầu vào không tạo bản ghi trùng; ID index ổn định và không phụ
  thuộc chỉ số thứ tự nhất thời của vòng lặp.
- Thay đổi nguồn/cấu hình/model tạo release mới; active release bất biến.
- Mỗi bản ghi nguồn phục vụ, payload Qdrant và snapshot tri thức bổ sung thuộc
  cùng release. Nguồn BTC gốc có thể giữ riêng bất biến, không sửa để thêm release.
- Manifest ghi source/config hashes, collection cụ thể, snapshot bổ sung, model
  revision, tokenizer, max length, normalization, prefix, dtype và kết quả kiểm tra.
- Dựng collection và snapshot nguồn mới song song với bản đang phục vụ.
- PostgreSQL giữ con trỏ active có thẩm quyền, kích hoạt bằng transaction/CAS sau
  khi release hoàn tất và được kiểm tra.
- Request ghim manifest rồi dùng collection cụ thể; không phụ thuộc alias mutable
  cho từng truy vấn. Đổi alias Qdrant không tạo giao dịch nguyên tử với PostgreSQL.
- Giữ bản cũ phục vụ request đang chạy và rollback. Không xóa collection đang được ghim.
- Release không đầy đủ hoặc model fingerprint không tương thích phải bị từ chối.

Đổi model phải dựng index mới. Bản đầu chuyển model có kiểm soát, nạp model đúng
và warmup trước phục vụ; không giả định hỗ trợ đổi model nóng hoặc giữ hai model
trong 4 GB VRAM. Rollback khác model cũng phải kiểm tra tương thích runtime.

## 12. Tích hợp Knowledge Gap Loop

- Giữ nguồn BTC nguyên bản; FAQ/aliases bổ sung có nguồn chứng minh và được duyệt.
- Nội dung bổ sung đi qua cùng kiểm tra metadata, quyền, encode và release.
- Không ghi thẳng nội dung mới vào bản đang chạy.
- Kết quả chuẩn bị lexical hiện có không tự được xem là hybrid release sẵn sàng;
  cần manifest/index tương ứng trước kích hoạt.
- Thay đổi này phải tái sử dụng quyền, quyết định duyệt, audit và khả năng so sánh
  vòng cải tiến đã có, không tạo một luồng duyệt thứ hai độc lập.
- Alias trỏ về chunk BTC có thể ánh xạ về mã gốc. FAQ bổ sung có ID riêng và source
  references; không giả làm chunk BTC chỉ vì có chung một nguồn tham khảo.
- Thu hồi/xóa bằng chứng phải làm release liên quan không còn phục vụ trái phép;
  không để request ghim release hoặc rollback vượt qua tombstone/quyền hiện tại.

## 13. Đánh giá BTC và khả năng tổng quát

Ưu tiên hoàn thành các mục BTC yêu cầu. Các kiểm tra bổ sung dưới đây nhằm xác
minh đúng thiết kế và tránh hồi quy, không đặt thêm ngưỡng điểm/latency riêng.

Tách bốn nhóm nghiệm thu:

1. Hệ thống: chunk/metadata, bảng, quyền, ngày, liên kết, lỗi, warmup, release và rollback.
2. Retrieval: đủ 60 câu BTC; Recall@3/@5, multi-hop full recall.
3. Câu trả lời: abstention/false abstention, trả lời thiếu căn cứ, đúng phiên bản,
   số liệu, không tiết lộ dữ liệu nội bộ.
4. Performance: đúng phần cứng triển khai, concurrency 1/3/5, p50/p95 và lỗi.

Mỗi kết quả BTC lấy mã mục từ danh sách bằng chứng thực tế theo đúng thứ tự cuối:

```json
{
  "Q01": {
    "retrieved_chunk_ids": ["DT-03"],
    "abstained": false,
    "answer": "...câu trả lời thực tế của agent..."
  }
}
```

Đây là format xuất eval, không phải schema MCP. Không lấy expected answer hoặc
relevant IDs để sinh kết quả, thêm ID hay gán abstained giả.

- BTC script chấm retrieval và abstain; version accuracy/chất lượng answer cần
  đánh giá tay hoặc judge. Không báo các metric chưa đo như đã đạt.
- Kiểm tra đủ 60 QID, không trùng/thiếu, trước khi báo điểm; script có thể bỏ qua
  câu thiếu kết quả ở một số mẫu số nên không dựa riêng vào output script.
- Retrieval eval đi qua MCP thực, không chỉ gọi trực tiếp hàm retrieve.
- Công bố biến đổi nguồn an toàn và mapping về mã mục BTC, gồm restricted cases.
- Dùng bộ câu hỏi riêng ngoài BTC để kiểm tra câu nối tiếp, paraphrase, ngoài phạm vi,
  nhiều điều kiện, mâu thuẫn và lịch sử; không tinh chỉnh quá khớp bộ công khai.
- Ngữ cảnh thời gian của eval được khai báo/freeze; không dùng ngày chạy hiện tại
  cho mọi câu lịch sử, không tự điền ngày mua chính xác khi nguồn chỉ nêu tháng.
- Bộ 60 câu không kiểm chứng đủ khả năng agent tạo query trong hội thoại; cần các
  trường hợp riêng cho câu hỏi nối tiếp.
- Numeric/multi-hop cần phối hợp tool giá, catalog và đơn hàng khi phù hợp;
  không yêu cầu knowledge suy ra dữ liệu hiện hành từ ví dụ tĩnh trong policy.
- Kiểm tra hành vi đủ một phần, hỏi làm rõ, ngày khách khai chưa xác minh, nguồn
  mâu thuẫn, vượt `top_k` và nhóm thiếu phụ thuộc khi chạm giới hạn cứng.
- Kiểm tra schema mới xuyên MCP -> agent -> guardrail -> Knowledge Gap Loop,
  bảo đảm ID/nội dung/thứ tự bằng chứng và trạng thái điều kiện không bị mất.
- `abstained` lấy từ hành vi trả lời thực tế theo cách diễn giải BTC được ghi rõ
  trong adapter; không tự gán chỉ từ `retrieval_status`. Trả lời một phần, hỏi làm
  rõ, từ chối tiết lộ và lỗi kỹ thuật phải được phân biệt khi rà soát kết quả.

## 14. Performance và truy vết

Đo thời gian chờ hàng đợi, encode, Qdrant/RRF, PostgreSQL, xử lý liên kết/serialization,
tổng MCP và LLM/tổng lượt ở cấp agent. Ghi số token bằng chứng, phiên bản pipeline,
release, cấu hình và số lần retry.

Tách cold start khỏi warm state. Báo concurrency 1/3/5, VRAM đỉnh, lỗi/OOM,
timeout/overload và p50/p95. Không chỉ báo request thành công rồi bỏ qua lỗi tải.
Không cộng p95 các chặng để suy ra p95 toàn luồng.

Giữ nguyên bảng trước, đo tổng ảnh hưởng đến LLM rồi mới thay đổi thiết kế nội dung.
Ngân sách phải tính toàn lượt hội thoại và phần ASR/TTS khi tích hợp; benchmark
retrieval riêng không chứng minh đạt toàn bộ latency BTC.

Mask PII theo field path, không mask tool name/call ID hoặc trường scorer so sánh.
Không đưa raw query chứa PII hoặc nội dung restricted vào log tự do. Tận dụng tracing
hiện có; không xây dashboard mới trong phạm vi này.

## 15. Thông số còn mở và ranh giới thực hiện

Các quyết định hành vi tại mục 8.1 đã chốt. Những chi tiết kỹ thuật sau còn mở;
cần chốt ở giai đoạn tương ứng, không suy ra đã đạt từ nội dung spec:

- Model revision cụ thể, giới hạn token và batch nạp phù hợp bảng dài nhất.
- Số ứng viên dense/sparse, RRF configuration, quy tắc thứ hạng nhóm liên kết và
  giới hạn cứng số bằng chứng; chốt trước khi hoàn thiện lựa chọn kết quả.
- Tiêu chí bằng chứng yếu/no_evidence; chốt và kiểm chứng trước khi hoàn thiện
  luồng search, bao gồm câu ngoài phạm vi và bằng chứng giới hạn kiến thức.
- Deadline, dung lượng hàng đợi và timeout phụ thuộc để đáp ứng yêu cầu BTC.
- Tham số circuit breaker và điều kiện cho phép retry trong deadline.
- Khả năng GPU 4 GB đáp ứng VRAM/p95 tại concurrency yêu cầu.
- Ngữ cảnh ngày eval và xử lý các điểm chưa thống nhất trong nguồn BTC.

Khả năng GPU cần được kiểm chứng sớm với độ dài query/tài liệu dự kiến, gồm bảng
dài nhất và tải đồng thời yêu cầu, trước khi hoàn thiện pipeline phụ thuộc vào
phương án này. Ba lượt warmup khởi động không thay thế phép kiểm chứng đó.

Thông số vận hành do dự án chọn phải phân biệt với ngưỡng BTC. Chưa bổ sung mục
tiêu chất lượng/latency riêng ngoài BTC trong lần cập nhật này.
Không có số đo nào trong spec chứng minh local đã nhanh hơn API.

Viết spec không cho phép tự tải model, cài dependency, chạy benchmark, live model
evaluation, reset DB hoặc đổi dịch vụ đang chạy. Các hành động cần phê duyệt theo
AGENTS.md phải được xin phép riêng. Không git add/commit khi chưa được yêu cầu.
