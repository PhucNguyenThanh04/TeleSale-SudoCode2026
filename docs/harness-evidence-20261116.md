# Tool-Call Accuracy và rollback — hướng dẫn bàn giao

Hai công cụ này chạy offline, không sửa agent/scorer/dữ liệu BTC, không cần
credentials model hoặc database. TCA đo quyết định tool trong trace đã lưu.
Rollback kiểm cơ chế bằng service/MCP thật với storage/embedding fixture trong
RAM. Chúng không thay số liệu Full/Baseline hay vòng cải tiến K0/K1 có người duyệt.

Spec: [harness-evidence-design](superpowers/specs/2026-11-16-harness-evidence-design.md).
Plan/ledger: [harness-evidence](superpowers/plans/2026-11-16-harness-evidence.md).

## 1. Tool-Call Accuracy (TCA)

Chạy từ root với venv AI đã cài. Ví dụ synthetic đã khai báo 6 lượt: 3 đúng,
1 sai SKU, 1 thiếu inventory và 1 tạo đơn khi chưa đồng ý. **50% là kết quả
fixture được thiết kế trước, không phải điểm của agent/model.**

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m eval_harness.tool_accuracy \
  --trace ai-services/eval_harness/fixtures/tool_accuracy/trace.jsonl \
  --labels ai-services/eval_harness/fixtures/tool_accuracy/labels.json \
  --out ai-services/eval_harness/results/harness-evidence/tool-fixture-01
```

Output: `report.json`, `report.md`. Mỗi lần dùng thư mục output mới. CLI exit 0
nghĩa là đo thành công, **không có nghĩa TCA=100%**. Input không hợp lệ trả mã 2,
không âm thầm bỏ lượt. Công cụ chỉ đọc trace/labels; không gọi LLM, tool hay DB.

### Nhãn cho trace thật

Không lấy danh sách tool agent đã gọi làm đáp án chuẩn. Người kiểm tra đọc yêu
cầu khách và ngữ cảnh được phép, xác định tool nào cần/không được gọi và tham
số đúng. Nhãn dưới đây là cấu trúc, hash placeholder cố ý không hợp lệ:

```json
{
  "schema_version": 1,
  "label_source": "team_review_of_dialogue_context",
  "cases": [{
    "id": "stock-variant",
    "scenario_id": "YOUR-SCENARIO",
    "call": "call_1",
    "turn": 1,
    "user_text_sha256": "REPLACE_WITH_SHA256_OF_EXACT_USER_TEXT",
    "scored_tools": ["inventory.check", "order.create"],
    "expected_calls": [{
      "name": "inventory.check",
      "args_match": {"sku": "SKU-EXACT-VARIANT", "on": "2026-10-15"}
    }]
  }]
}
```

- `scored_tools` là phạm vi đóng: trong ví dụ này phải kiểm tồn đúng một lần,
  không được tạo đơn. Catalog/CRM và các tool khác nằm ngoài phép đo, không
  được mặc định tính là đúng. Report công khai coverage/phạm vi từng case.
- `expected_calls=[]` yêu cầu không có call nào thuộc phạm vi. Lượt không gọi
  tool đúng vẫn nằm trong mẫu số. Muốn chấm mọi business tool thì liệt kê đủ
  tên trong `scored_tools`, cùng tất cả expected call hợp lệ.
- `args_match` so khớp tập con đệ quy của args; list giữ thứ tự, scalar phải
  cùng kiểu JSON. `{}` chỉ kiểm tên tool và được đếm riêng trong report.
- Mỗi actual call chỉ ghép một expected call. Sai args gây missing + unexpected;
  gọi trùng/gọi thừa cũng làm lượt sai. Không đánh giá thứ tự gọi tool.
- Trace phải đủ các lượt có nhãn, không duplicate locator, không trộn run/config.
  SHA256 câu hỏi phải khớp chính xác, không normalize trước khi băm. Có thể dùng
  `hashlib.sha256(row['user_text'].encode('utf-8')).hexdigest()`.
- Hash câu hỏi chỉ ràng buộc lượt hỏi; không chứng minh nhãn đúng hoặc ngữ cảnh
  trước đó giống nhau. Khi chấm trace khác, phải đối chiếu lại các nhãn phụ thuộc
  lịch sử/offer/consent. `label_source` là khai báo, không chứng thực human review.
- Trace đã mask PII chỉ chấm được args quan sát được. Không đưa PII gốc vào nhãn
  để cố so khớp placeholder. Không tuyên bố đã kiểm tham số mà trace không có.

Chạy trace thật với đúng file nhãn của nó:

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m eval_harness.tool_accuracy \
  --trace /path/to/full.jsonl --labels /path/to/reviewed-labels.json \
  --out ai-services/eval_harness/results/harness-evidence/full-tools-01
```

### Công thức và phạm vi

`TCA = 100 × lượt có nhãn khớp hoàn toàn / tổng lượt có nhãn`.

Đơn vị là **quyết định tool của lượt được gán nhãn**, không phải mọi lượt hội
thoại. Report có tử/mẫu, matched/missing/unexpected call counts, các index để
tra ngược input, số lượt chưa có nhãn và hash hai input. Không copy lời nói,
args hoặc kết quả tool vào report. Một tool timeout vẫn có thể đúng tên/tham
số: execution success phải báo riêng. Không suy TCA thành TSR hay tuân thủ
toàn bộ schema. Đây là metric bổ sung của đội, không sửa/chấm thay scorer BTC.

## 2. Kiểm chứng rollback

```bash
PYTHONPATH=ai-services ai-services/.venv/bin/python -m eval_harness.knowledge_rollback \
  --btc-root ../BTC-Data-Vong1-TEAMS \
  --out ai-services/eval_harness/results/harness-evidence/rollback-01
```

Không cần server đang chạy, Docker, tokenizer download hay API key. Qdrant dùng
RAM, dense backend trả vector cố định. Các kết nối network bị chặn trong quá
trình rehearsal; settings được thay bằng cấu hình fixture trong tiến trình,
không đọc `.env`. Không kết nối/reset PostgreSQL hoặc activate release thật.

CLI thực hiện:

1. Parse corpus policy BTC thật và dựng/activate hybrid K0.
2. Tạo FAQ từ nguyên nội dung DT-02. Build khi chưa duyệt phải bị từ chối.
3. Duyệt mô phỏng source/test qua lifecycle thật, build K1; FAQ chưa xuất hiện
   qua MCP trước activate.
4. Activate K1; MCP search có FAQ và nguồn gốc. Pin K0 vẫn trả evidence cũ.
5. Rollback sai expected-active hoặc sai quyền đều phải bị chặn, không đổi
   active/audit. Rollback hợp lệ trở về K0 và ghi đúng actor/previous/target.
6. Search mới khôi phục evidence K0. Search pin K1 vẫn đọc snapshot K1 bất biến.
7. Kiểm corpus không đổi và gap không tự resolved sau publish/rollback.

`report.json` lưu 11 checks, revision/approval/test, release/manifest/snapshot
hashes, config, search observations và audit; `report.md` tóm tắt các bước.
Một check fail làm CLI fail, không xuất báo cáo passed. Output tồn tại hoặc nằm
trong gói BTC bị từ chối; kể cả đường dẫn symlink được resolve trước khi kiểm.

**Giới hạn bắt buộc ghi trong báo cáo nộp:** đây là `offline_rehearsal`, review
`simulated_not_human`, ngày đơn là fixture và dense embedding giả lập. Nó chứng
minh lifecycle/serving/pinning/rollback bằng code thật, không chứng minh người
đã duyệt, retrieval quality, lời agent tốt hơn, PostgreSQL/remote Qdrant chạy
được, latency production hoặc nhiều phiên đồng thời. Rollback thay default
release; nó không phải thu hồi/xóa snapshot đã pin.

## 3. Verification ledger

Ngày 16/11/2026, đã thực hiện tự spec → plan → triển khai → self-review tại
checkout hiện tại. Không worktree, subagent, commit, full suite, model/embedding
live, PostgreSQL, Docker hoặc thay đổi active release thật.

| Kiểm tra | Kết quả |
|---|---|
| TCA RED→GREEN | Test fail khi module chưa có, rồi qua các trường hợp missing/wrong/extra/duplicate/abstention, nested args và maximum matching |
| Rollback RED→GREEN | Qua MCP thật; fixture ban đầu dùng sai principal bị từ chối, sửa fixture theo authentication contract `harness`, không nới auth |
| Output nằm trong BTC | Hai test RED trước khi thêm guard; sau sửa bị chặn trước rehearsal |
| Focused tests cuối | **36 passed**, 9,03 giây: 21 TCA +6 rollback +3 publish/search +6 release lifecycle |
| CLI help, JSON/Markdown, refusal overwrite | Qua; tests dùng wrapper chặn network và loại credentials/.env |
| TCA fixture | 3/6=50%, đúng các lỗi được thiết kế trước, **không phải điểm model** |
| TCA trace lịch sử, mẫu có chủ đích | 3/6=50%; coverage 6/170 lượt, 20 calls ngoài phạm vi; không holdout/human review độc lập hoặc kết quả code mới |
| Rollback CLI thực offline | **11/11 checks qua**, source digest trước/sau khớp, config hash có trong report |
| Whitespace | `git diff --check` qua |

Command focused cuối:

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  ai-services/eval_harness/test_tool_accuracy.py \
  ai-services/eval_harness/test_knowledge_rollback.py \
  ai-services/test/test_knowledge_publish_search_loop.py \
  ai-services/test/test_knowledge_releases.py --tb=short
```

Artifacts đã chạy và kiểm input hashes:

- [TCA fixture](../ai-services/eval_harness/results/harness-evidence/20261116-tool-fixture-01/report.md).
- [TCA sáu lượt lịch sử](../ai-services/eval_harness/results/harness-evidence/20261116-historical-tools-01/report.md),
  [nhãn](../ai-services/eval_harness/results/harness-evidence/20261116-historical-targeted-labels.json).
- [Rollback cuối](../ai-services/eval_harness/results/harness-evidence/20261116-rollback-02/report.md),
  [JSON đầy đủ](../ai-services/eval_harness/results/harness-evidence/20261116-rollback-02/report.json).

Mẫu lịch sử dùng nguyên `measurement-audit/20261115-m1-round1-final/full.jsonl`
(trace agent ngày 13/11 được re-extract 15/11). Bốn nhãn inventory lấy yêu cầu
khách, SKU/biến thể catalog và ngày trong snapshot scenario: SC-T01/call_1/1,
SC-T09/call_1/1, SC-T19/call_1/1, SC-T20/call_2/1; hai nhãn không giao dịch:
SC04/call_1/1 và SC-T06/call_3/1. Đây là assistant self-review các tình huống đã
biết để kiểm công cụ, không đại diện toàn bộ 170 lượt và không khẳng định các
sửa runtime sau đó đã cải thiện. Hash input trong report vẫn khớp source sau chạy.

Các kết quả/nhãn lịch sử nằm dưới `results/` đang Git ignore; khi gửi BTC phải
kèm artifact bundle nếu muốn dùng chúng trong báo cáo. Fixture synthetic và
code/test/hướng dẫn là file source mới, phải đưa vào bản nộp.

Một phép kiểm mở rộng ngoài hai công cụ phát hiện ca có sẵn:
`test_policy_integration.py::test_functional_policy_path_through_mcp_business_tools_and_guardrail`
với `reported=None, order_date=2026-10-10, answer='Chính sách đổi trả trong 7 ngày.'`.
Verifier trả fallback nhưng test muốn accept. Chạy riêng file đó trong tiến
trình không nạp hai module mới vẫn **1 failed, 4 passed**. Không sửa production
guardrail hoặc đổi expectation ngoài phạm vi này. Không gọi toàn bộ suite xanh.

Cập nhật 17/11: ca đó đã được xử lý bằng cách sửa fixture theo followup contract
và giữ nguyên guardrail/expected; xem [biên bản policy/timeline](policy-timeline-20261117.md).
