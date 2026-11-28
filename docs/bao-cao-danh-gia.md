# Báo cáo đánh giá trợ lý telesale đa phiên

## 1. Kết quả chấm hội thoại

Kết quả dưới đây được in trực tiếp từ `reference_eval.py` trên 7 kịch bản mẫu công khai của BTC. Cột **Hệ thống** là Full.

```text
Chỉ số                                Baseline      Hệ thống
Repeat-Question Rate (%)                  31.6           0.0
Context Carryover Rate (%)                 4.8          52.4
Task Success Rate (%)                     57.1          57.1
Hallucination Rate giá&KM (%)             15.4          14.3
Số lượt TB / cuộc                            3             3
TSR riêng ca khó (%)                                    33.3
Vi phạm guardrail (số ca)                    0             0
Latency: {"n_turns": 39, "warning": "Cần ≥ 100 lượt để p95 có ý nghĩa", "ttft": {"n": 39, "p50_ms": 1479, "p95_ms": 3799}, "total": {"n": 39, "p50_ms": 1918, "p95_ms": 3982}, "ttfa": null, "call_brief": {"n": 6, "p50_ms": 110, "p95_ms": 232}}
→ report.json
```

**Đối chiếu ngưỡng BTC.** Tỷ lệ hỏi lại của Full giảm 100% so với Baseline (từ 31,6% xuống 0%), đạt yêu cầu giảm ít nhất 40%. TSR đạt 4/7 kịch bản (57,1%), dưới mục tiêu 70%. HR giá/khuyến mãi là 2/14 phát ngôn (14,3%), vượt ngưỡng 5%.

Ở dòng TSR riêng ca khó, script chỉ in điểm của Hệ thống (1/3). Baseline đạt 3/3 theo tệp JSON của lần chấm. Dòng Latency cũng chỉ in số liệu của Hệ thống. Mẫu A.6 trong đề dùng đơn vị lượt/kịch bản (39/7 = 5,57 cho cả hai), còn bảng trên in lượt/cuộc gọi (39/13 = 3).

## 2. Phạm vi và cơ sở chấm

| | Full | Baseline |
|---|---|---|
| Dữ liệu agent được dùng | Lịch sử trong phiên, công cụ nghiệp vụ và bộ nhớ từ các phiên trước | Lịch sử trong phiên và cùng bộ công cụ. Tắt bộ nhớ từ các phiên trước |
| Bản ghi đem chấm | Full sau cải tiến | Baseline lưu từ lần đo trước |
| Mẫu hội thoại | 7 kịch bản, gồm 3 ca khó · 13 cuộc gọi · 39 lượt | Cùng 7 kịch bản, 13 cuộc gọi, 39 lượt |

**Phạm vi kết luận.** BTC yêu cầu bảng A.6 trên bộ test riêng của đội. M1 yêu cầu ít nhất 20 kịch bản đa phiên và ít nhất 5 ca khó. Bộ riêng đã có 48 kịch bản, 118 cuộc gọi, 323 lượt, 38 ca khó, nhưng chưa có cặp bản ghi Full/Baseline được xác minh cho bộ này. Các số dưới đây là kết quả chấm lại **bộ mẫu công khai**. Điểm xếp hạng do BTC chấm trên bộ ẩn. Hai bản ghi lịch sử cũng chưa đủ thông tin để xác nhận cùng model, tham số và phần cứng như điều kiện so sánh của BTC. [Bộ riêng của đội](../eval/scenario_final/_manifest.json) · [Bản ghi Full](../eval_results/after_p2/btc7.full.jsonl) · [Bản ghi Baseline](../eval_results/before/btc7_baseline_no_memory.jsonl)

Căn cứ chấm gồm mục C.4, C.5, F và phụ lục A của đề, bản điều chỉnh Vòng 1 và văn bản giải đáp tháng 11. Bảng hội thoại dùng script tham chiếu trong gói BTC hiện có. Mục 7 ghi cách tái lập từ bản ghi đã lưu. [Đề dự án](<../../SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>) · [Điều chỉnh đề](../../BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md) · [Giải đáp tháng 11](../../BTC-tra-loi-thac-mac-11-2026.docx) · [Script chấm BTC](../../BTC-Data-Vong1-TEAMS/eval/reference_eval.py)

**Vì sao HR khác tệp điểm cũ?** Tệp cũ ghi Full 0/14 và Baseline 0/13. Khi giữ nguyên trace và chấm với đáp án công khai hiện có, trường `promo_active` của cuộc gọi thứ hai ở SC02 có giá trị chuẩn là `false`. Full có hai phát ngôn trích xuất mang giá trị `true` ở lượt 2. Baseline có một ở lượt 2 và một ở lượt 3. BTC đếm từng phát ngôn, nên hai lỗi trong cùng lượt vẫn được tính hai lần. Bảng trên dùng kết quả chấm lại. [Đáp án SC02](../../BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-02.json) · [Tệp điểm lịch sử](../eval_results/after_p2/btc7.score.json)

**Cách tạo dữ liệu chấm.** Từ lời agent, bộ trích xuất nhận diện câu hỏi, gán trường thông tin được hỏi và phân biệt hỏi mới với xác nhận (`questions`). Với dữ kiện thương mại, bộ trích xuất tách mệnh đề và gán cặp trường–giá trị (`claims`). Khi tính RQR, script chỉ xét các cuộc gọi có danh sách trường không được hỏi lại (`must_not_ask`). Hỏi xác nhận lần đầu được miễn, xác nhận lại cùng trường trong cùng phiên bị tính thừa. CCR đối chiếu các dữ kiện phải mang sang với `facts_used` và tham số công cụ. HR chỉ đếm phát ngôn có đáp án trong `ground_truth_facts`. TSR xét điều kiện của từng kịch bản, kể cả chuyển nhân viên kèm bản bàn giao hợp lệ khi đó là kết quả được yêu cầu. [Bộ trích xuất](../ai-services/eval_harness/extractor.py) · [Quy tắc chấm BTC](../../BTC-Data-Vong1-TEAMS/eval/reference_eval.py)

## 3. Nhận dạng tiếng nói — chỉ số M1 theo phụ lục A.5

Full và Baseline khác nhau ở bộ nhớ hội thoại. ASR được đo riêng trên âm thanh đầu vào. Bảng dùng kết quả đã lưu của Whisper large-v3-turbo chạy local trên RTX 3050, với bộ từ vựng sản phẩm và chuẩn hóa văn bản. Theo giải đáp tháng 11, đội tự tạo audio D01–D04 để kiểm quy trình. BTC dùng audio riêng để xếp hạng. [Báo cáo ASR ngày 10/11](../speech/asr-benchmark-report.html) · [Giải đáp của BTC](../../BTC-tra-loi-thac-mac-11-2026.docx)

| Chỉ số | D01–D04 do đội tạo · 4 file | Bộ audio của đội · 22 file |
|---|---:|---:|
| WER · Tỷ lệ lỗi theo từ | 7,2% | 14,3% |
| CER · Tỷ lệ lỗi theo ký tự | 3,6% | 10,2% |
| Độ chính xác thực thể, gộp các loại | 93,1% trên 29 thực thể | 71,9% trên 139 thực thể |
| Độ chính xác **riêng số tiền** | Chưa có số tách riêng trong báo cáo nguồn | Chưa có số tách riêng |
| Độ chính xác **riêng số điện thoại** | Chưa có số tách riêng trong báo cáo nguồn | Chưa có số tách riêng |
| Thời gian xử lý một phút âm thanh | 6,0 giây | 6,6 giây |

WER và CER lấy tổng số phép thay, xóa, chèn chia cho tổng số từ hoặc ký tự chuẩn. Pipeline đưa số về dạng đọc bằng chữ để so với bản chép lời. Bộ chấm chuyển chữ thường, chuẩn Unicode NFC, bỏ dấu câu, gộp khoảng trắng và bỏ khoảng trắng khi tính CER. Số tiền và số điện thoại được xét khớp chính xác sau chuẩn hóa. Điểm thực thể gộp trong bảng chưa đủ để kết luận độ chính xác cho từng loại. [Chuẩn hóa](../speech/normalize.py) · [Chấm ASR và thực thể](../speech/evaluate.py)

## 4. Hiệu năng theo mục C.2 đã điều chỉnh

| Chỉ số | Full | Baseline | Yêu cầu BTC | Đối chiếu lần đo |
|---|---:|---:|---|---|
| Từ lúc nhận lượt chat đến phần trả lời đầu tiên (TTFT), p50 / p95 | 1.479 / 3.799 ms | 1.683 / 3.835 ms | M1: p95 ≤3.000 ms | Cả hai vượt ngưỡng |
| Từ lúc nhận lượt chat đến hết câu trả lời (Total), p50 / p95 | 1.918 / 3.982 ms | 2.400 / 5.556 ms | M1: p95 ≤8.000 ms | Cả hai dưới ngưỡng trên mẫu đã đo |
| Từ nhận diện khách đến khi tóm tắt phiên sẵn sàng (Call Brief), p50 / p95 | 110 / 232 ms, 6 mẫu | Không có số đo | M1: ≤5 giây · M2: ≤3 giây | p95 quan sát của Full dưới hai mốc |
| Từ khi khách ngừng nói đến âm thanh trả lời đầu tiên (TTFA), p95 | Chưa đo | Chưa đo | M2: ≤2,5 giây | Cần đo trên luồng thoại |
| Số phiên xử lý đồng thời khi demo | Chưa xác minh | Chưa xác minh | M1: 1 · M2: ≥2 | Cặp trace chỉ đo lượt hội thoại |

p50 là trung vị, p95 là phân vị thứ 95. BTC yêu cầu ít nhất 100 lượt và bỏ 3 lượt khởi động. Runner ghi 3 lượt khởi động và chỉ có 39 lượt chấm mỗi cấu hình. TTFT/Total lấy mốc phần trả lời mà harness phát ra, loại thời gian chuẩn bị phiên, chờ worker bộ nhớ, HTTP, ASR và TTS. Do đó các giá trị trên mô tả lần chạy đã lưu, chưa đủ nghiệm thu p95 theo BTC. [Quy tắc đo](../../BTC-Data-Vong1-TEAMS/eval/huong-dan-do-latency.md) · [Bản ghi phép đo](../eval_results/after_p2/btc7.full.report.json)

## 5. Trước và sau cải tiến trên cùng bộ mẫu

Hai mốc Full được chấm lại bằng cùng script và đáp án công khai. Baseline dùng lại một bản ghi cho cả hai mốc. Thay đổi ở Full gồm bổ sung tra giá/tồn kho khi câu trả lời thiếu căn cứ và cho phép đọc song song các nguồn độc lập. [Lịch sử cải tiến](../REPORT.md) · [Trace Full trước cải tiến](../eval_results/before/btc7_full.jsonl)

| Chỉ số | Full trước → sau | Baseline đối chứng | Thay đổi ở Full |
|---|---:|---:|---|
| Dữ kiện dùng đúng (CCR) | 12/21 → 11/21 | 1/21 | Giảm 1 dữ kiện |
| Hoàn thành tác vụ (TSR) | 4/7 → 4/7 | 4/7 | Hoàn thành thêm SC03, mất SC06 |
| Hoàn thành ca khó | 2/3 → 1/3 | 3/3 | Giảm 1 ca |
| HR giá/khuyến mãi | 20,0% (3/15) → 14,3% (2/14) | 15,4% (2/13) | Giảm 5,7 điểm %, vẫn vượt 5% |
| Độ trễ trả lời xong (p95) | 4.833 → 3.982 ms | 5.556 ms | Giảm 851 ms trên 39 lượt |

## 6. Phân tích lỗi trên 12 lượt hội thoại

Mỗi dòng dẫn tới một lượt trong bản ghi của đúng cấu hình. Bảng phân biệt lỗi tư vấn, thao tác còn thiếu và trường hợp agent báo thành công khi chưa có biên nhận. [Bản ghi Full](../eval_results/after_p2/btc7.full.jsonl) · [Bản ghi Baseline](../eval_results/before/btc7_baseline_no_memory.jsonl)

| Cấu hình | Kịch bản · dòng bản ghi | Yêu cầu của khách | Kết quả quan sát |
|---|---|---|---|
| Full | SC01 · 2 | Tư vấn máy lọc cho gia đình có bé nhỏ | Đang giới thiệu AirPure Y, agent chuyển sang hỏi nhu cầu mua màng lọc tặng kèm. |
| Full | SC01 · 6 | Kiểm tra giá máy đã hỏi ở cuộc trước | Agent gọi báo giá cho màng lọc. Khách vẫn thiếu giá của máy. |
| Full | SC01 · 7 | Lên đơn và giao về địa chỉ cũ | Agent đọc lại đơn và xin xác nhận. Lượt kết thúc khi chưa gọi công cụ tạo đơn. |
| Full | SC04 · 21 | Cho biết giày có giảm giá hay không | Agent tra giá nhưng chỉ hỏi thêm số lượng hoặc khu vực giao, bỏ ngỏ câu hỏi về ưu đãi. |
| Full | SC05 · 29 | Giải thích vì sao khoản giảm 500.000đ đã thay đổi | Agent xin lỗi rồi chuyển sang màng lọc, bỏ qua thắc mắc về chương trình cũ. |
| Full | SC05 · 30 | Chốt mua sau khi ưu đãi thay đổi | Agent lặp lời xin lỗi và hỏi phương thức thanh toán. Lượt kết thúc khi chưa tạo đơn. |
| Full | SC06 · 36 | Lên đơn Xiaomi Smart 4 Pro | Agent báo đã tạo đơn 5.490.000đ. Danh sách công cụ của lượt trống, thiếu biên nhận để xác nhận giao dịch. |
| Baseline | SC01 · 3 | Cho biết máy đang tư vấn có khuyến mãi gì | Agent trả lời chưa đủ thông tin, không nêu được ưu đãi hoặc chi tiết khách cần bổ sung. |
| Baseline | SC01 · 5 | Tiếp tục tư vấn máy lọc ở lần gọi trước | Agent hỏi lại tên mẫu. Khách phải giúp xác định lại sản phẩm. |
| Baseline | SC03 · 18 | Hỏi phí đổi giày lên size 40 | Trong cùng câu trả lời, agent vừa khẳng định miễn phí hoàn toàn vừa báo chưa xác minh đủ. |
| Baseline | SC03 · 19 | Làm thủ tục đổi size | Công cụ mới trả kết quả xem trước. Yêu cầu đổi chưa được gửi và kịch bản trượt tiêu chí cập nhật đơn. |
| Baseline | SC04 · 25 | Lên đơn đôi giày đen size 41 đã hỏi trên Facebook | Agent thiếu tên mẫu ở phiên trước, hỏi lại mã giày và chưa tạo đơn. |

Ở SC06, Full báo đã tạo đơn nhưng lượt đó không có lời gọi công cụ. Muốn biết giao dịch đã hoàn tất hay chưa, cần kiểm biên nhận tạo đơn. Chỉ số HR giá/khuyến mãi chỉ đối chiếu dữ kiện thương mại có đáp án.

## 7. Tái lập điểm hội thoại và phạm vi M2

Chạy từ thư mục gốc dự án để in nguyên kết quả ở mục 1. Bản sao tạm của bảy kịch bản dùng mã `SC01…SC07` tương ứng với `SAMPLE-01…SAMPLE-07` để khớp mã trong trace. Script ghi `report.json` vào thư mục tạm.

```bash
python3 - <<'PYTHON'
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

btc = Path("../BTC-Data-Vong1-TEAMS").resolve()
full = Path("eval_results/after_p2/btc7.full.jsonl").resolve()
baseline = Path("eval_results/before/btc7_baseline_no_memory.jsonl").resolve()

with TemporaryDirectory() as tmp:
    scenarios = Path(tmp) / "scenarios"
    scenarios.mkdir()
    for n in range(1, 8):
        source = btc / "test_set/public_sample" / f"SAMPLE-{n:02}.json"
        case = json.loads(source.read_text(encoding="utf-8"))
        case["scenario_id"] = f"SC{n:02}"
        (scenarios / source.name).write_text(json.dumps(case), encoding="utf-8")
    subprocess.run(
        [sys.executable, btc / "eval/reference_eval.py", "--scenarios", scenarios,
         "--trace", full, "--baseline", baseline],
        cwd=tmp, check=True,
    )
PYTHON
```

| Phép đo M2 hoặc chi phí | Bằng chứng hiện có |
|---|---|
| Truy hồi chính sách, 60 câu | Có ít nhất một đoạn đúng trong top 3 / top 5 ở 84,7% / 91,5% trên 59 câu đủ điều kiện. Truy hồi đủ nguồn ở 41,7% / 50,0% trên 12 câu nhiều nguồn. |
| Từ chối trả lời khi thiếu dữ liệu hoặc bị hạn chế truy cập | Tỷ lệ từ chối lần lượt 25% và 40%, tỷ lệ từ chối nhầm 0%. Các số này do model tự ghi nhận. |
| Độ chính xác gọi công cụ và chi phí mỗi cuộc | Chưa có số đo cho cặp Full/Baseline trong báo cáo. |
| Chấm bằng mô hình và mô phỏng khách hàng | Chưa có tỷ lệ đồng thuận với người chấm, Cohen’s kappa trên ít nhất 20 mẫu, hoặc TSR qua 3 seed cho bộ riêng. |
| Tách người nói | Chưa có kết quả đối chiếu với nhãn người nói theo từng đoạn âm thanh trong bộ ASR nêu trên. |

Các chỉ số truy hồi lấy từ phép đo riêng của kho chính sách. Calls-to-Close trung bình là 1,67 cuộc với Full (3 ca chốt) và 1,75 cuộc với Baseline (4 ca chốt). [Điểm truy hồi chính sách](../results-rag/e2e-score-02/report.json) · [Phạm vi bộ test riêng](../eval/scenario_final/README.md)
