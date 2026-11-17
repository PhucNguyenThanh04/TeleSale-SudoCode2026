# Eval RAG độc lập

Đo MCP Knowledge hiện tại, không chạy eval harness, memory, hội thoại đa phiên hay
tool ghi dữ liệu. Stack: scorer BTC nguyên bản + Python diagnostics + Ragas
**0.4.4** (tùy chọn khi chấm đáp án). Không thay đổi retrieval của sản phẩm.

## Cài đặt

Chạy từ root repo với môi trường `ai-services/.venv` đã cài
`ai-services/requirements.txt` và PostgreSQL/Qdrant/MCP Knowledge đã được chuẩn bị.
Retrieval và replay không cần Ragas. Chỉ khi dùng `judge`, cài thêm:

```bash
uv pip install --python ai-services/.venv/bin/python -r ai-services/rag_eval/requirements.txt
```

Không cài extras `ragas[all]`. Có thể dùng môi trường eval riêng với cùng dependency
AI để tránh thay dependency môi trường phục vụ. Code dùng API
`ragas.metrics.collections`, không dùng các ví dụ legacy.

## Dữ liệu và phạm vi phép đo

Mặc định đọc đủ **60 QA** từ BTC, corpus `policy/`, ngày chuẩn **2026-10-15**.
`fixtures/contexts.json` là fixture **thành phần**: giả định đơn hiện hành được tạo
15/10, Q32 đơn 15/07, Q42 đơn 15/09, Q43 đơn 28/09 và hỏi ngày 09/10. Ngày giữa
tháng là đại diện cho tháng trong câu hỏi. `date_source=eval_fixture` không có
nghĩa agent đã tìm được ngày đơn trong CRM. Có thể thay bằng `--contexts FILE`;
không suy ra ngày từ `expected_answer`, không đưa labels vào query/prompt.

Generation có các dữ kiện catalog/pricing/inventory từ **read-tool tham chiếu BTC**
được khai báo trước trong context fixture. Q27 dùng một khách BTC có đơn AirPure
2024 đã giao, chỉ để thiết lập điều kiện trade-in. Không đưa hồ sơ/SĐT khách hoặc
giá sàn nội bộ vào model. Q31/Q58 dùng biến thể màu đen đại diện cho size trong
câu hỏi. Đây không phải phép đo khả năng agent chọn/gọi tools. Toàn bộ fixture
được lưu trong run để kiểm lại; bộ chấm và đáp án chuẩn không đi vào generator.

MCP chỉ trả evidence; generator của bộ eval dùng prompt riêng được pin hash,
model/temperature/seed/max_tokens từ cấu hình AI hiện tại. Điểm end-to-end ở đây
là **isolated RAG**, không phải chất lượng câu trả lời của agent sản phẩm.

## 1. Thu retrieval thật

Cần `MCP_KNOWLEDGE_URL`, `MCP_INTERNAL_TOKEN` trong `ai-services/.env`. Có thể đặt
`KNOWLEDGE_RELEASE_ID` để chọn release; nếu không sẽ ghim release active một lần.
Mặc định không đưa Knowledge supplements vào retrieval; thêm
`--include-supplements` khi muốn đo release đã cải tiến. Các mục an toàn đã biến
đổi từ nguồn nội bộ vẫn giữ ID BTC và phải được kiểm cả nội dung, không chỉ ID.

**Lệnh này có thể gọi embedding trả phí**; không reset/ghi DB:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval run \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --mode retrieval --allow-live \
  --out ai-services/rag_eval/results/retrieval-k0
```

Đảm bảo service Knowledge đang phục vụ corpus BTC tương ứng. Manifest lưu hash
corpus local và reference release từ MCP; reference release tự nó **không chứng
minh** toàn bộ corpus trên server trùng BTC. Evidence/source trong trace phục vụ
việc đối chiếu khi nghiệm thu. Config file local, nếu được cấu hình, cũng được
ghi hash; đây không phải chứng cứ config server trùng file local.

`--top-k` nhận 5–10, mặc định 5. Giữ nguyên thứ tự evidence service trả về,
kể cả `retrieved_via=linked`. Service có thể thêm liên kết vượt top_k: scorer
lấy prefix 3/5 thực tế, không lấy lại chunk đúng theo nhãn. Không coi top_k
đầu vào là tổng số chunk chắc chắn được trả về.

## 2. Chấm retrieval offline

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval score \
  --run ai-services/rag_eval/results/retrieval-k0 \
  --out ai-services/rag_eval/results/retrieval-k0-scores
```

Không cần model/API/DB. Lệnh kiểm hash và exact coverage rồi gọi hàm `rag_eval`
từ **bản scorer BTC đã snapshot**, xuất `rag_results.json` đúng định dạng BTC.
Chỉ chạy scorer trong gói BTC đáng tin cậy: đây là mã Python được thực thi.

- Điểm BTC giữ nguyên công thức: Recall@3/@5 = tỷ lệ câu có **ít nhất một** ID
  đúng; không phải tỷ lệ số chunk đúng. Bộ BTC có 59 câu có ID, Q51 không tính
  denominator retrieval. Multi-hop báo thêm full-recall trên 12 câu.
- Retrieval-only: các chỉ số abstain/đáp án là `null` (chưa đo), không giả thành 0.
- `report.json` có per-question, by-type, MRR@5, latency p50/p95 và coverage;
  `report.md` là bảng tóm tắt. BTC trả phần trăm 0–100; các metric bổ sung dùng 0–1.
- Câu retrieval lỗi vẫn có hàng kết quả và nằm trong denominator. Không loại câu
  restricted, no-evidence hoặc khó. Run đủ hàng không có nghĩa mọi hàng thành công.

## 3. Thu RAG end-to-end

Cần thêm cấu hình model AI hiện tại (`LLM_*` hoặc backend local). Để tránh JSON
bị cắt, chọn output budget phù hợp, ví dụ `LLM_MAX_TOKENS=768` cho phép thử này.
Không thay model/seed/prompt giữa hai lượt chỉ định để so sánh retriever.

**Có gọi embedding và LLM**:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval run \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --mode end-to-end --allow-live \
  --out ai-services/rag_eval/results/e2e-k0
```

Generator phải trả JSON có `answer` và `action`; JSON lỗi/truncated được giữ là
lỗi generation, không tự gọi lại mất phí. `action` trong trace là tự khai của
generator. Chấm `score` trước judge chỉ có abstention dạng self-report; không
dùng kết quả đó để tuyên bố chất lượng từ chối đã được đánh giá độc lập.

## 4. Judge đáp án đã lưu

Cấu hình riêng trong `ai-services/.env` hoặc biến môi trường:

```dotenv
RAG_EVAL_JUDGE_MODEL=<model hỗ trợ JSON và structured output>
RAG_EVAL_JUDGE_API_KEY=<key>
RAG_EVAL_JUDGE_BASE_URL=<OpenAI-compatible URL, có /v1 nếu provider yêu cầu>
RAG_EVAL_JUDGE_TIMEOUT_SECONDS=90
RAG_EVAL_JUDGE_MAX_TOKENS=2048
```

Judge không tự lấy model/key của generator. Chưa mặc định bất kỳ model nào là
judge chính xác cho tiếng Việt; phải đối chiếu người. Provider phải tương thích
Ragas/instructor structured output và Chat Completions JSON object. Instructor
được cấu hình một attempt, không tự thử lại metric lỗi. Lệnh này
**gọi model nhiều lần cho mỗi câu**, không gọi lại retrieval/generator:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval judge \
  --run ai-services/rag_eval/results/e2e-k0 \
  --allow-live --out ai-services/rag_eval/results/e2e-k0-judged
```

Kết quả:

- `judgments.jsonl`: từng câu, business verdict/reason, điểm Ragas và lỗi từng metric.
- `scores/report.json`, `scores/report.md`: correctness, version/numeric accuracy,
  leakage và Faithfulness/FactualCorrectness F1, luôn có số mẫu đo được/eligible.
- Faithfulness bỏ qua lời từ chối/hỏi thêm/handoff và ghi lý do; không lấy câu
  không có claim làm điểm groundedness hoàn hảo.
- Business judge phân loại hành vi từ lời đáp, không tin action self-report.
  Khi business judge chưa đủ coverage, điểm BTC abstention được để `null`.
- FactualCorrectness đối chiếu đáp án ngắn BTC có thể đánh giá thấp thông tin
  bổ sung đúng; đọc business reason và nguồn, không chỉ nhìn điểm trung bình.
- `fixtures/assertions.json` chứa kiểm tra literal cho một số số/ngày/nội bộ;
  đây chỉ là diagnostics, không chứng minh ngữ nghĩa/không có rò rỉ nói vòng.

Replay lại scores sau judge hoàn toàn offline:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval score \
  --run ai-services/rag_eval/results/e2e-k0 \
  --judgments ai-services/rag_eval/results/e2e-k0-judged \
  --out ai-services/rag_eval/results/e2e-k0-rescored
```

## 5. Đối chiếu judge với người

Copy `scores/human_labels.template.json` ra ngoài thư mục artifact đã seal. Điền
`reviewer`, chấm `correct: true|false` cho ít nhất 20 câu (giữ `null` cho chưa
chấm), đọc câu hỏi/reference/answer/source độc lập trước khi xem điểm judge.
Nên có đủ nhóm, đặc biệt version conflict, restricted và unanswerable.

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval score \
  --run ai-services/rag_eval/results/e2e-k0 \
  --judgments ai-services/rag_eval/results/e2e-k0-judged \
  --human-labels /path/to/reviewed-labels.json \
  --out ai-services/rag_eval/results/e2e-k0-calibrated
```

Báo agreement và Cohen's kappa trên correctness nhị phân; <20 mẫu đánh dấu chưa
đủ calibration. Khi mọi nhãn cùng một lớp, kappa có thể không xác định (`null`).
Đây chưa phải calibration riêng cho tất cả các metric Ragas.

## 6. So sánh trước/sau

Chạy round mới với output mới, giữ dataset/context/assertions, generator và judge
giống nhau; được đổi release/retrieval config. Có thể thêm `--include-supplements`
khi đo release mới; sự khác biệt này xuất hiện trong comparison.

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m rag_eval compare \
  --before ai-services/rag_eval/results/e2e-k0-judged/scores \
  --after ai-services/rag_eval/results/e2e-k1-judged/scores \
  --out ai-services/rag_eval/results/k0-vs-k1
```

Xuất delta retrieval theo điểm phần trăm, delta đáp án theo thang 0–1, câu cải thiện/hồi quy và coverage hai
phía. Không gộp thành một điểm RAG tổng; không kết luận ý nghĩa thống kê từ một run.
Bộ BTC là benchmark công khai: nếu dùng để chỉnh hệ thống phải ghi rõ, bổ sung
held-out của team để kiểm khái quát. Dataset khác cần context/assertion fixture
tương ứng; không mặc định dùng override Qxx của BTC.

## Lỗi, gián đoạn và artifact nghiệm thu

Mã thoát: 0 chạy/chấm hoàn tất; 1 collection/judge có câu hoặc metric lỗi; 2 lỗi
đầu vào/cấu hình/hash; 130 người dùng ngắt. Không ghi đè output, không tự resume
hoặc chạy lại. Khi bị ngắt, giữ những hàng đã flush và manifest `interrupted`;
offline scorer từ chối coi run thiếu là một phép đo hoàn chỉnh. Kiểm lỗi trước
khi chủ động cho phép một run trả phí mới.

Chọn output mới **nằm ngoài** các thư mục artifact đầu vào; không đặt scores
trong collection vì sẽ làm thay đổi run đã seal.

Run lưu snapshot BTC, fixtures, implementation hashes, pinned release, model và
prompt identities, trace và timings. Hash phát hiện artifact thay đổi ngoài quy
trình, không phải chữ ký chống người có chủ ý sửa cả manifest. Không gửi `.env`,
keys hay config riêng. Snapshot BTC có CRM **giả lập BTC**; chỉ dùng dữ liệu team
đã ẩn danh khi làm bộ riêng.

Gửi lại: **thư mục collection + thư mục judged hoặc scores + comparison nếu có
+ file nhãn người đã chấm**. Cần `trace.jsonl`, `manifest.json`, `report.json`,
`report.md`, `rag_results.json`, `judgments.jsonl` và fixtures/snapshot đi kèm để
kiểm provenance, lỗi từng câu và tái lập điểm. Không chỉ gửi ảnh bảng điểm.

Kiểm thử code offline:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m pytest -q ai-services/rag_eval
```

Các test giả lập network/model ở ranh giới và kiểm phép chấm bằng scorer BTC thật;
không phải bằng chứng chất lượng retrieval hoặc model thật.
`test_ragas_api.py` chỉ chạy khi đã cài Ragas; nó dùng HTTP MockTransport cho cả
business judge và hai metric thật, không gọi provider. Ragas có thể phát cảnh
báo deprecation từ dependency langchain-community; đây không phải lỗi đánh giá.
