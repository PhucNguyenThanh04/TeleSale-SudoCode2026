# Spec: MCP Knowledge và RAG chính sách BTC

Ngày: 03/11/2026. Cập nhật kiến trúc: 04/11/2026.

Trạng thái: người dùng đã duyệt thiết kế Cloudflare BGE-M3 dense + BM25 CPU +
Qdrant RRF và plan triển khai ngày 04/11/2026. Nội dung dưới đây là thiết kế được
duyệt; kết quả code/test và các bước vận hành chưa kiểm được ghi trong báo cáo triển khai. Xử lý khi Cloudflare lỗi hoặc hết
quota đã chốt tại mục 10; các thông số còn mở ở mục 15.
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
       -> Cloudflare Workers AI / BGE-M3: dense
       -> BM25 CPU: biểu diễn từ khóa theo cấu hình của release
       -> Qdrant: prefetch dense + prefetch BM25 sparse, RRF trong một request
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

## 4. Embedding, BM25 và readiness

### 4.1. Dense qua Cloudflare Workers AI

- Dùng model `@cf/baai/bge-m3` qua HTTPS từ backend. Ingestion và search dùng
  cùng model, hợp đồng API, tiền xử lý, chiều vector và normalization.
- Dùng HTTP client bất đồng bộ với giới hạn concurrency và hàng đợi hữu hạn;
  không chặn event loop MCP. Không tạo thêm embedding HTTP server trong Compose.
- `CLOUDFLARE_ACCOUNT_ID` và `CLOUDFLARE_API_TOKEN` lấy từ môi trường. Không lưu
  token trong runtime JSON, manifest, payload, log, lỗi trả agent hoặc Git.
  Token chỉ cần quyền Workers AI trên đúng tài khoản; không yêu cầu Global API Key.
- Hợp đồng đề xuất là REST synchronous embeddings. Cố định route và schema trong
  adapter sau khi đối chiếu API hiện hành; kiểm tra số vector, thứ tự ánh xạ đầu
  vào, chiều, giá trị hữu hạn và vector khác zero. Không chấp nhận output dở dang.
- Chiều dự kiến 1024, chuẩn hóa L2 nhất quán ở phía ứng dụng. Chiều thực tế phải
  được xác nhận trong kiểm tra kết nối được cho phép trước khi phát hành index.
- Không dùng learned sparse hoặc ColBERT từ Cloudflare. Không giả định API cung
  cấp đầy đủ các đầu ra của thư viện FlagEmbedding local.
- Bỏ model weights, FlagEmbedding, Torch, torchvision và CUDA khỏi dependency của
  đường knowledge; không ảnh hưởng dependency mà thành phần khác thực sự cần.
- Chỉ giữ tokenizer nhỏ chạy CPU để kiểm tra độ dài, có revision cố định, đóng gói
  sẵn trong image. Không tải weights hoặc tokenizer khi BTC khởi động hệ thống.
- Không âm thầm cắt query, bảng hoặc tài liệu. Giới hạn ứng dụng không vượt giới
  hạn API đã xác nhận; nếu API hỗ trợ tắt truncation thì phải tắt. Tài liệu quá dài
  phải được xử lý theo mục 5 trước phát hành; query quá dài bị từ chối rõ ràng.
- Tài liệu được embedding khi nạp, không embedding lại corpus mỗi request hoặc
  mỗi lần khởi động. Chỉ gửi nội dung an toàn đã xử lý quyền theo mục 5.
- Query gửi ra ngoài chỉ gồm thông tin cần tra chính sách; dùng cơ chế xử lý PII
  hiện có để loại thông tin định danh không cần thiết trước khi gọi provider.
  Không gửi toàn bộ hội thoại, hồ sơ CRM hoặc dữ liệu đơn hàng cho embedding API.

Cloudflare quản lý model phục vụ; tên model không chứng minh weights/revision
bất biến như snapshot Hugging Face local. Manifest ghi provider, model ID, phiên
bản adapter, tokenizer revision, giới hạn đầu vào và normalization; không tự điền
model commit hoặc dtype phía provider khi không có thông tin đó. Fingerprint phát
hiện thay đổi cấu hình do dự án quản lý, không bảo đảm phát hiện mọi thay đổi weights
của provider. Khi provider thông báo thay đổi có ảnh hưởng, phải kiểm tra tương
thích và dựng release mới nếu cần; không tái dùng vector local chỉ vì cùng tên BGE-M3.

Theo tài liệu Cloudflare được đối chiếu ngày 04/11/2026, Free có 10.000 Neurons/ngày;
BGE-M3 được niêm yết 1.075 Neurons/một triệu input token. Hạn mức dùng chung cho
Workers AI trong tài khoản, không phải quota riêng từng token hoặc từng container.
Không mã hóa các con số giá/quota thành cam kết vận hành vĩnh viễn. Hết quota phải
được phân loại, không retry liên tục hoặc tự chuyển gói trả phí. Không thêm dịch vụ
Cloudflare Vectorize/AI Search; dữ liệu index vẫn nằm trong Qdrant của hệ thống.

### 4.2. BM25 chạy CPU, lưu sparse vector trong Qdrant

Đề xuất kỹ thuật để duyệt: tự tính BM25 trên CPU, không thêm model embedding hoặc
server lexical riêng. Cùng nội dung an toàn dùng cho dense cũng là đầu vào BM25,
gồm lời dẫn và tiêu đề chunk theo mục 5; aliases đã duyệt tuân cơ chế hiện có.

- Chuẩn hóa Unicode NFC, casefold, giữ dấu tiếng Việt; tách token chữ/số Unicode,
  giữ mã ghép bằng dấu nối như `DT-OLD-03`. Quy tắc dấu phân cách phải được cố
  định, kiểm thử trên mã chính sách, SKU, đơn vị và số liệu; không xóa dấu tùy tiện.
- Bản đầu không thêm word segmentation model, stemming tiếng Anh hoặc stopword
  tiếng Anh. Đây là BM25 theo token chữ/số, không tuyên bố đã tách từ tiếng Việt
  hoàn chỉnh hoặc đã đạt chất lượng trên bộ BTC.
- Vocabulary của mỗi release được dựng ổn định từ corpus an toàn của release đó,
  lưu ánh xạ term -> index và hash; query dùng đúng vocabulary đã ghim. Token
  ngoài vocabulary bị bỏ khỏi nhánh lexical, không tạo hoặc sửa vocabulary lúc search.
- Dùng độ dài tài liệu và trung bình độ dài của đúng corpus trong release; đề xuất
  `k1=1.2`, `b=0.75`. Lưu tham số, thống kê corpus, tokenizer version và hash trong
  manifest; thay đổi bất kỳ thành phần nào phải dựng lại index.
- Trọng số document: `tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))`.
  Query dùng mỗi token phân biệt một lần với trọng số 1. IDF do sparse index Qdrant
  tính bằng modifier `idf`; không nhân IDF lần nữa ở encoder CPU.
- Cố định và kiểm tra Qdrant version hỗ trợ modifier này, cấu hình sparse index và
  công thức scoring trước triển khai. Dense và BM25 cùng thuộc collection/release.
  Đề xuất collection một shard cho corpus nhỏ này để IDF tính trên toàn release;
  không giả định payload filter tự tính lại IDF. Cấu hình shard thuộc manifest.
- Query không có term trong vocabulary thì không chạy prefetch BM25 rỗng; nhánh
  dense vẫn hoạt động. Đây là trường hợp không khớp lexical, khác lỗi Cloudflare.
  Lỗi tải/hash vocabulary hoặc lỗi tính BM25 là lỗi pipeline, không giả làm zero match.
- Corpus vocabulary/thống kê chỉ gồm nội dung được phép index, không gồm tài liệu
  restricted thô. Thu hồi tri thức và quyền vẫn tuân mục 12.

### 4.3. Khởi động và readiness

1. Kiểm tra cấu hình provider, sự hiện diện của credentials và giới hạn vận hành.
2. Nạp tokenizer CPU và artifact BM25 của release; đối chiếu phiên bản/hash.
3. Kiểm tra PostgreSQL, Qdrant, schema dense/BM25, manifest và trạng thái release.
4. Chuyển sang ready khi các kiểm tra cấu hình và index đạt; trạng thái này không
   chứng nhận provider đang phản hồi nếu chưa có lần gọi thật.

Tách readiness chức năng khỏi trạng thái đã đo chất lượng. Nếu runtime cũ bắt buộc
`relevance_verified`, phải sửa hợp đồng kiểm tra khi triển khai để cho phép phục vụ
với chất lượng chưa được đánh giá, đồng thời giữ trạng thái đó trung thực; không
đổi cờ thành true hoặc buộc chạy eval ngoài phạm vi chỉ để khởi động.

Bỏ yêu cầu nạp GPU và ba lượt warmup encode bắt buộc. Healthcheck định kỳ không
được gọi embedding API hoặc tiêu quota. Lỗi provider được xử lý trong request và
circuit breaker theo mục 10; không biến lỗi quota thành vòng restart container.
Kiểm tra kết nối thật dùng văn bản cố định không có PII là thao tác riêng, chỉ chạy
khi được cho phép; không gộp vào test offline hoặc chạy eval ngầm. Không embedding
corpus khi khởi động. Các kiểm tra này không thay phép đo latency BTC khi được yêu cầu.

Nguồn kỹ thuật:

- [Cloudflare BGE-M3](https://developers.cloudflare.com/workers-ai/models/bge-m3/).
- [Giá và quota Workers AI](https://developers.cloudflare.com/workers-ai/platform/pricing/).
- [Giới hạn Workers AI](https://developers.cloudflare.com/workers-ai/platform/limits/).
- [Qdrant sparse vectors và IDF](https://qdrant.tech/documentation/manage-data/indexing/#idf-modifier).

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
2. Gọi Cloudflare một lần cho dense query, tạo BM25 query trên CPU với vocabulary
   của release đã ghim; các lần retry có giới hạn tuân mục 10.
3. Gửi một request Qdrant gồm prefetch dense và BM25 sparse, hợp nhất bằng RRF;
   bỏ riêng prefetch lexical khi không có term trong vocabulary theo mục 4.2.
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
Ngưỡng learned sparse BGE-M3 cũ không có ý nghĩa tương đương với BM25; không sao
chép sang cấu hình mới. Tiêu chí bằng chứng yếu phải có test chức năng riêng; chưa
có kết quả eval thì không khai báo retrieval đã được xác nhận chất lượng.

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

- Số HTTP request embedding đồng thời có giới hạn, hàng đợi hữu hạn; fail fast khi đầy.
- Có deadline tổng, gồm cả thời gian chờ hàng đợi và retry.
- Retry tối đa một lần với lỗi tạm thời đã phân loại, chỉ khi còn đủ ngân sách.
- Không retry token sai/hết hạn/thiếu quyền, account hoặc model sai, quota ngày đã
  hết, đầu vào quá dài, manifest/hash không hợp lệ hoặc dữ liệu sai quyền.
- Phân biệt rate limit tạm thời với quota ngày khi provider trả mã đủ rõ. Rate limit
  chỉ retry trong deadline, tôn trọng Retry-After; nếu mã không rõ thì xử lý có giới
  hạn như lỗi provider, không kết luận là kho tri thức thiếu dữ liệu.
- Không đưa token, authorization header hoặc raw response có thông tin nhạy cảm
  vào lỗi trả agent. Ghi mã nguyên nhân an toàn: auth/config/quota/rate_limit/network/
  invalid_response, kèm request/release ID.
- Circuit breaker theo phụ thuộc, có ngưỡng lỗi, cooldown và probe phục hồi hữu hạn.
- Timeout hủy request HTTP đang chờ và loại tác vụ hết hạn trong hàng đợi; quản lý
  semaphore theo vòng đời tác vụ thực tế, không rò slot. Provider có thể vẫn tính
  usage cho request đã nhận dù client hủy; không giả định timeout là miễn phí.
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

**Đã thống nhất:** không chuyển sang BM25-only khi Cloudflare lỗi hoặc hết quota.
Trả `unavailable`/`timeout` theo nguyên nhân, `evidence: []`. Giao diện/agent báo
“Tạm thời chưa tra cứu được thông tin, vui lòng thử lại sau.”; không đưa chi tiết
quota, credentials hoặc hạ tầng vào thông báo cho khách. Không tự hẹn gọi lại
hoặc chuyển nhân viên ngoài nghiệp vụ BTC hiện có. BM25 là nhánh hỗ trợ bình
thường của hybrid, không phải chế độ dự phòng khi provider lỗi.

Log vận hành phải phân biệt nguyên nhân thực tế với thông báo chung ở giao diện:

- Khi phản hồi Cloudflare xác nhận hết quota, ghi `reason=quota_exhausted`,
  `provider=cloudflare`, model ID, HTTP status, provider error code nếu có,
  request ID và release ID; MCP trả `retrieval_status=unavailable`.
- Phân biệt `rate_limited` với `quota_exhausted`; không suy ra hết quota chỉ từ
  HTTP 429. Khi thông tin provider chưa đủ phân loại, ghi `provider_error` và
  mã phản hồi an toàn đã nhận, không ghi một nguyên nhân chưa xác nhận.
- Không log API token, Authorization header, toàn bộ raw response hoặc query
  có PII. Không biến lỗi quota thành `no_evidence` hoặc tín hiệu thiếu tri thức.
- Test mock phải xác nhận cùng lỗi hết quota tạo thông báo giao diện chung nhưng
  log vẫn giữ đúng `quota_exhausted`, không retry và không chạy BM25-only.

## 11. Nạp, upsert và tính đồng nhất release

Không quét định kỳ. Người phụ trách chủ động chạy lệnh:

```text
Nguồn + cấu hình đã duyệt
  -> Parse/chunk/nội dung an toàn
  -> Kiểm tra metadata và liên kết
  -> Cloudflare encode dense + tạo BM25 document sparse trên CPU
  -> Upsert release đang chuẩn bị
  -> Kiểm tra đầy đủ
  -> Chủ động kích hoạt
```

- Chạy lại cùng đầu vào không tạo bản ghi trùng; ID index ổn định và không phụ
  thuộc chỉ số thứ tự nhất thời của vòng lặp.
- Thay đổi nguồn/cấu hình/model tạo release mới; active release bất biến.
- Mỗi bản ghi nguồn phục vụ, payload Qdrant và snapshot tri thức bổ sung thuộc
  cùng release. Nguồn BTC gốc có thể giữ riêng bất biến, không sửa để thêm release.
- Manifest ghi source/config hashes, collection cụ thể, snapshot bổ sung, provider,
  model ID, adapter version, tokenizer revision, max length, normalization, prefix,
  dimension, BM25 tokenizer/vocabulary hash/thống kê corpus/k1/b/IDF configuration
  và kết quả kiểm tra. Không ghi credentials hoặc tự gán revision/dtype của provider.
- Dựng collection và snapshot nguồn mới song song với bản đang phục vụ.
- PostgreSQL giữ con trỏ active có thẩm quyền, kích hoạt bằng transaction/CAS sau
  khi release hoàn tất và được kiểm tra.
- Request ghim manifest rồi dùng collection cụ thể; không phụ thuộc alias mutable
  cho từng truy vấn. Đổi alias Qdrant không tạo giao dịch nguyên tử với PostgreSQL.
- Giữ bản cũ phục vụ request đang chạy và rollback. Không xóa collection đang được ghim.
- Release không đầy đủ hoặc model fingerprint không tương thích phải bị từ chối.

Chuyển local BGE-M3 dense/learned sparse sang Cloudflare dense/BM25 phải dựng
release và collection mới; không upsert đè vector mới vào release cũ. Không xóa
collection cũ chỉ để chuyển đổi. Preflight kiểm tra cấu hình, quyền nạp và nội dung
an toàn trước khi gọi API; nạp theo batch hữu hạn, dừng rõ ràng khi quota/auth lỗi.
Release đang nạp dở không được kích hoạt. Có thể tái sử dụng artifact đã hoàn tất
khi chạy lại chỉ nếu hash nội dung và toàn bộ fingerprint tương thích; không gọi lại
API chỉ để kiểm tra payload/vector đã có.

BM25 cần vocabulary và thống kê corpus ổn định trước khi tạo vector. Dựng chúng
trước encode/upsert; không thay avgdl hoặc IDF configuration giữa các batch. Kiểm
tra số lượng điểm, nội dung/metadata/hash, dense vector và BM25 vector với artifact
trước khi kích hoạt. Giữ đủ dữ liệu ngày hết hạn, gồm chính sách cũ cho đơn lịch sử.

Rollback phải kiểm tra runtime hỗ trợ provider/lexical encoder của release đích.
Runtime mới không có Torch/CUDA không mặc nhiên phục vụ được release local cũ;
muốn quay về release đó phải dùng runtime cũ tương thích, không chỉ đổi con trỏ DB.

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

Mục này mô tả phép đánh giá BTC có thể thực hiện khi được yêu cầu, không phải
ủy quyền chạy eval. Trong đợt chuyển kiến trúc này chỉ chạy test chức năng offline,
mock Cloudflare; không gọi model, benchmark hoặc judge thật. Không dùng kết quả
mong đợi hoặc relevant IDs làm dữ liệu ingestion, vocabulary, aliases hay logic search.

Test chức năng cần bao phủ: mapping batch/chiều vector/normalization, auth/quota/429/
5xx/timeout, retry và deadline, không lộ token, tokenizer tiếng Việt/mã/số liệu,
BM25 reference calculation và IDF không bị nhân đôi, OOV, RRF, release fingerprint,
ngày hết hạn, quyền, ingestion chạy lại và từ chối kích hoạt release thiếu dữ liệu.
Các tham số BM25 và ngưỡng mới chưa được coi là tối ưu chỉ vì test chức năng đạt.

Tách bốn nhóm nghiệm thu:

1. Hệ thống: chunk/metadata, bảng, quyền, ngày, liên kết, lỗi API, readiness, BM25, release và rollback.
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

Khi được yêu cầu đo, tách thời gian chờ hàng đợi, Cloudflare HTTP, BM25 CPU,
Qdrant/RRF, PostgreSQL, xử lý liên kết/serialization,
tổng MCP và LLM/tổng lượt ở cấp agent. Ghi số token bằng chứng, phiên bản pipeline,
release, cấu hình và số lần retry.

Tách cold start khỏi warm state. Báo concurrency 1/3/5, RAM/CPU, lỗi provider/quota,
timeout/overload và p50/p95; không dùng VRAM làm điều kiện chạy knowledge. Không chỉ báo request thành công rồi bỏ qua lỗi tải.
Không cộng p95 các chặng để suy ra p95 toàn luồng.

Giữ nguyên bảng trước, đo tổng ảnh hưởng đến LLM rồi mới thay đổi thiết kế nội dung.
Ngân sách phải tính toàn lượt hội thoại và phần ASR/TTS khi tích hợp; benchmark
retrieval riêng không chứng minh đạt toàn bộ latency BTC.

Mask PII theo field path, không mask tool name/call ID hoặc trường scorer so sánh.
Không đưa raw query chứa PII hoặc nội dung restricted vào log tự do. Tận dụng tracing
hiện có; không xây dashboard mới trong phạm vi này.

## 15. Thông số còn mở và ranh giới thực hiện

Các quyết định nghiệp vụ tại mục 8.1 và hướng Cloudflare dense + BM25 CPU + RRF
đã chốt. Các lựa chọn BM25/readiness/migration nêu trên là đề xuất kỹ thuật của
lần cập nhật này để người dùng duyệt, không phải kết quả đã triển khai.

Hành vi lỗi provider đã chốt: không fallback BM25-only; giao diện báo tạm thời
chưa tra cứu được, log phân loại rõ hết quota khi có căn cứ từ provider theo mục 10.

Chi tiết kỹ thuật cần xác định khi viết plan/triển khai, không yêu cầu chạy eval:

- Schema API thực tế, dimension, batch limit, tokenizer revision và giới hạn đầu
  vào an toàn; tài liệu model hiện có ví dụ và phần parameter không hoàn toàn đồng
  nhất, cần kiểm tra adapter bằng contract fixture và smoke test riêng khi được phép.
- Qdrant version và sparse modifier idf; artifact vocabulary và công thức BM25 phải
  đồng nhất giữa ingestion và query, không phụ thuộc một model tải lúc startup.
- Số ứng viên dense/BM25, RRF configuration, quy tắc nhóm liên kết và giới hạn cứng
  số bằng chứng; không giữ ngưỡng learned sparse cũ như ngưỡng BM25.
- Tiêu chí bằng chứng yếu/no_evidence và các test chức năng chứng minh hành vi;
  test đạt không thay thế đánh giá chất lượng khi người dùng yêu cầu sau này.
- Deadline, timeout HTTP, hàng đợi, concurrency, batch nạp, retry và circuit breaker.
  Không khẳng định latency API tốt hơn local khi chưa đo.
- Ngữ cảnh ngày eval và điểm chưa thống nhất trong nguồn BTC chỉ được giải quyết
  khi chuẩn bị lượt eval đã được yêu cầu; không trì hoãn test chức năng vì chưa có eval.

### 15.1. Docker, cấu hình và tài liệu chạy

- Cả bốn MCP server tiếp tục chạy trong Docker Compose. Knowledge dùng image
  Python CPU với HTTP client, tokenizer nhỏ và BM25; không NVIDIA base image,
  GPU reservation, CUDA hoặc mount cache model weights cho service này.
- Compose truyền credentials từ `ai-services/.env` tới đúng service cần dùng;
  lưu ý đường dẫn env_file khác cơ chế nội suy `${...}` của Compose. Không giả
  định file có biến là container đã nhận được biến. Không bake secrets vào image.
- CLI dataloader chạy trên host cũng phải dùng cùng cấu hình provider/BM25 với
  runtime; không để dataloader dùng local model còn MCP dùng Cloudflare.
- Cập nhật `.env.example`, runtime config mẫu, dependency và README: cách lấy
  credentials, chuẩn bị/nạp/kích hoạt release, khởi chạy Compose, test offline,
  yêu cầu Internet và cách nhận biết quota/auth lỗi. Ví dụ không chứa token thật.
- Không tự chuyển gói trả phí, push image Docker Hub, dọn Docker data hoặc thay
  cấu hình phân vùng. Không cam kết toàn hệ thống chạy offline vì embedding dùng API.

### 15.2. Ranh giới ủy quyền

Viết spec không cho phép tự cài dependency, gọi Cloudflare thật, chạy benchmark,
live model evaluation, reset DB, xóa collection hoặc đổi dịch vụ đang chạy.
Các thao tác cần phê duyệt theo AGENTS.md phải được xin phép riêng. Chỉ test chức
năng offline nằm trong phạm vi triển khai đã thảo luận; không thêm eval gate bắt
buộc hay tự đặt `relevance_verified=true` để vượt kiểm tra chưa thực hiện.
Sau khi duyệt spec mới viết plan triển khai. Không git add/commit khi chưa được yêu cầu.
