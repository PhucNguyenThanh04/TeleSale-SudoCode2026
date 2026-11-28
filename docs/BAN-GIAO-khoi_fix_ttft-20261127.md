# Bàn giao nhánh `khoi_fix_ttft` (27/11/2026)

Nhánh tách từ `main` tại `a14c782` (code mới của anh Phúc). Mục tiêu: chạy được trên Windows theo README, sửa lỗi tồn đọng, giảm TTFT.

## 1. Các commit

| Commit | Nội dung | Test |
|---|---|---|
| `736ce5e` | Sửa chạy trên Windows: bỏ `uvloop` trên Windows, `av==18.1.1`, `.gitattributes` giữ JSON/JSONL dạng LF, selector event loop cho psycopg, `_ram_bytes()` thay `os.sysconf`, khóa file bằng `msvcrt` thay `fcntl`, đóng file trace trước khi ghi đè. Guardrail nhận `total_vnd` của `order.create` thành công làm bằng chứng giá. | 2 test |
| `0768022` | Sau khi tự bổ sung báo giá/tồn kho (P1), kiểm tra lại bản nháp gốc trước khi gọi model viết lại. Fallback hỏi size/màu khi sản phẩm có biến thể (sửa test P1 vốn đang fail). `seed_btc.py`, `run_eval.py`, `run_knowledge_eval.py` tự chạy lại với `-X utf8` trên Windows. README: dung lượng đĩa cho image GPU, cấu trúc thư mục dataset ASR. | 3 test |
| `4a9c41a` | Guardrail: câu trả lời về đơn cũ đã tra bằng `order.status` không còn bị chặn `order_creation_unverified`. Lỗi này làm 23 lượt hỏi trạng thái đơn trả câu xin lỗi chung. | 6 test |
| `744bc5f` | Sau `order.create` thành công (1 dòng hàng, khách không hỏi thêm), xác nhận đơn bằng mẫu câu từ kết quả tool, không gọi model thêm. Câu vẫn qua guardrail. | 2 test |
| `fb10551` | `catalog.search` ra đúng 1 sản phẩm không biến thể thì tra luôn `pricing.get_quote` + `inventory.check` song song, kèm vào kết quả (`current_quote`, `current_stock`). | 2 test |
| `323dd6e` | `build_commerce_evidence` giữ kết quả `order.status` thành công của các lượt trước trong phiên. Trước đó câu hỏi tiếp ("Đơn đó đã bàn giao vận chuyển chưa?") mất bằng chứng và bị chặn `order_creation_unverified`. | 1 test |

Mỗi commit đã so danh sách test fail trước/sau: không phát sinh fail mới.

## 2. Kết quả eval (48 kịch bản, 323 lượt mỗi cấu hình)

Thư mục run nằm ngoài Git (`results-submission/` bị ignore): `065208Z` ở `D:\Github\TeleSale-SudoCode2026\results-submission\`, các run còn lại ở `D:\Github\TeleSale-khoi_fix_ttft\results-submission\` trên máy chạy eval. Log tương ứng trong `logs/` của từng worktree.

| Chỉ số | Code cũ `main` 26/11 (run `065208Z`) | Code mới + fix Windows, trước các fix TTFT (run `084346Z`) | Nhánh này `323dd6e`, review bật (run `113656Z`) | Nhánh này, review tắt (run `124247Z`) |
|---|---:|---:|---:|---:|
| Execution | degraded (1 `GraphRecursionError`) | healthy | healthy | healthy |
| RQR Full / Baseline | 4,5% / 21,6% | 1,5% / 25,6% | 3,0% / 26,6% | 1,7% / 31,1% |
| CCR Full | 49,0% | 61,5% | 65,6% | 67,7% |
| TSR Full / Baseline | 77,1% / 64,6% | 81,2% / 60,4% | 81,2% / 62,5% | 77,1% / 66,7% |
| TSR ca khó Full | 73,7% | 78,9% | 78,9% | 73,7% |
| HR Full (giá/KM) | 2,1% (2,8%) | 0,9% (0,0%) | 3,8% (0,0%) | 1,0% (0,0%) |
| TTFT p50 / p95 Full | 2,6 s / 6,5 s | 3,6 s / 7,4 s | 3,4 s / 6,4 s | 3,3 s / 8,0 s (API chậm hơn, xem dưới) |
| Lượt Full > 3 s | 135 | 206 | 182 | 180 |
| Tổng số lần gọi model (Full) | — | 703 | 597 | 607 |
| Lượt rơi về câu xin lỗi chung (Full) | 62 | 70 | 52 | 52 |
| Call Brief p95 | 259 ms | 300 ms | 287 ms | 377 ms |
| Nghiệm thu M1 harness | chưa đạt (TTFT, health, extraction, Call Brief 69/70) | chưa đạt (TTFT, extraction, Call Brief 69/70) | chưa đạt (TTFT, extraction, Call Brief 69/70) | chưa đạt (TTFT, Total p95 8,0 s, safety: 1 over-escalation, extraction, Call Brief 69/70) |

**Tác dụng của các fix TTFT** (so `084346Z` với `113656Z`, cùng code nền và cùng bật review, tốc độ API như nhau: mỗi lần gọi model p50 975 ms và 977 ms): TTFT p95 Full giảm 7,4 s → 6,4 s, p50 3,6 s → 3,4 s; số lần gọi model giảm 15%; lượt rơi về câu xin lỗi giảm 70 → 52; `order_creation_unverified` giảm 24 → 3. TSR, RQR, CCR giữ hoặc tốt hơn.

**Bật hay tắt semantic review** (`113656Z` với `124247Z`): run tắt review chạy lúc Ollama Cloud chậm hơn (mỗi lần gọi model p50 1356 ms so với 977 ms) nên không so TTFT thô được. Đo trực tiếp: bước verify khi review bật p50 840 ms, khi tắt 13 ms. Ước tính trên run `113656Z` nếu tắt review (bỏ thời gian verify ở các lượt được chấp nhận ngay): TTFT p50 ~2,5 s, p95 ~5,8 s, vẫn trên 3 s. Về chất lượng, run tắt review có HR 1,0% (thấp hơn run bật 3,8%, vì lỗi freeship TEAM-33 bên dưới phụ thuộc lần chạy), nhưng TSR Full thấp hơn (77,1% so với 81,2%) và có 1 vi phạm over-escalation (TEAM-44 call_2: agent `handoff.transfer` yêu cầu xóa dữ liệu). Hai run chưa đủ để kết luận review ảnh hưởng chất lượng thế nào; nhánh giữ nguyên mặc định review bật. Nhóm tự chọn bằng `AGENT_SEMANTIC_REVIEW_ENABLED`.

Ba run đầu (`065208Z`, `084346Z`, `113656Z`) và run review tắt đều chạy một mình trên stack. Các run `094146Z`, `094850Z` và `branch-fix3` không hợp lệ: hai phiên chạy eval cùng lúc trên một stack, nên memory của lần này lẫn sang lần kia (25 kịch bản có sẵn episode từ call_1), worker LangMem quá tải (`memory_error`) và TTFT bị nhiễu.

HR 3,8% ở run `113656Z`: cả 4 claim sai là "miễn phí giao hàng" ở TEAM-33. Model gọi `pricing.get_quote` với địa chỉ cũ "Cần Thơ" (lấy từ bộ nhớ) dù khách đã đổi nơi nhận sang Hà Nội; báo giá Cần Thơ có freeship nên guardrail coi là có bằng chứng. Run `084346Z` cũng gọi báo giá Cần Thơ y như vậy, nhưng lần đó model báo giá lại theo Hà Nội trước khi trả lời. Lượt này không đi qua thay đổi `fb10551` (không có `current_quote`). Xem mục 4.

## 3. Nguyên nhân TTFT cao

Đo trên run `084346Z` (Full, 323 lượt):

1. **Mỗi lần gọi `gemma4:31b` qua Ollama Cloud mất ~1 s** (p50 975 ms, p95 1,8 s); chế độ thinking đã tắt. TTFT gần như bằng số lần gọi model × 1 s. Lượt có ≥3 lần gọi: 121/323.
2. **Semantic review đang bật lại.** Commit `9cc4628` ("tat review answer") tắt bước LLM duyệt câu trả lời; commit `fd4792b` ("fixxx") đổi `agent_semantic_review_enabled` mặc định thành `True` trong `ai-services/app/configs.py`. Bước này tốn ~0,8 s mỗi lượt (bước verify p50 840 ms khi bật, 13 ms khi tắt) và không hiện trong `model_timing`. Chưa đổi mặc định vì là đánh đổi chất lượng; số đo bật/tắt ở mục 2. Tắt bằng `AGENT_SEMANTIC_REVIEW_ENABLED=false` (biến môi trường hoặc `.env`).
3. **Viết lại câu trả lời:** ~100 lượt bị guardrail chặn bản nháp đầu, mỗi lượt thêm 1–2 lần gọi model; ~65–70 lượt cuối cùng vẫn rơi về câu xin lỗi chung. Lý do chặn nhiều nhất: `price_without_quote` (~40), `order_creation_unverified` (24, do lỗi đã sửa ở `4a9c41a`).
4. **Bỏ hẳn kiểm tra không đạt 3 s:** ước tính trên trace, kể cả không còn lần viết lại nào, TTFT p95 vẫn ~4,2 s. Không nên tắt guardrail.
5. **Lách bằng câu mở đầu** ("Dạ anh,") trước khi gọi tool sẽ kéo TTFT xuống <1 s nhưng là lách định nghĩa đo của BTC; code đang chặn kiểu này. Không làm.

Sau các fix của nhánh (run `113656Z`): lượt có ≥3 lần gọi model còn 74/323, TTFT p95 6,4 s. Riêng bỏ semantic review ước tính p95 ~5,8 s.

Muốn đạt p95 ≤3 s cần đa số lượt chỉ 1 lần gọi model và tắt semantic review, hoặc dùng model/endpoint nhanh hơn (model chính thức hiện là `gemma4:31b`).

## 4. Vấn đề tồn đọng

| # | Vấn đề | Trạng thái |
|---|---|---|
| 1 | TTFT p95 > 3 s | Chưa đạt; xem mục 3 |
| 2 | Bước reset runtime đầu eval không chặn job LangMem còn chạy dở của lần trước (run bị ngắt, hoặc hai run song song) → memory lẫn giữa các run, `memory_error` làm cả cặp `pair_failed` | Chưa sửa. Trước khi chạy: chỉ một run trên một stack, chờ `langmem-worker` hết log ≥2 phút |
| 3 | Một lượt `memory_error`/lỗi trả lời làm hỏng cả run 48 kịch bản (`trace_audit` vẫn coi `memory_error` là lỗi dù P0 đã đổi thành cảnh báo) | Chưa sửa |
| 4 | `m1_acceptance` báo Call Brief 69/70: TEAM-48 call_2 là ca định danh mới, không có lịch sử nên không có brief là đúng. `reference_eval.py` của BTC chỉ tính giá trị có đo nên không ảnh hưởng điểm | Ghi nhận, không sửa |
| 5 | Extraction review cần người duyệt | Việc thủ công |
| 6 | Bộ test: 180 fail + 92 error có sẵn trên `main` (chạy cả thư mục `ai-services/test` với `BTC_DATA_DIR`); `test_memory_update_api.py` lỗi khi thu thập nên phải dùng `--continue-on-collection-errors` | Chưa sửa |
| 7 | Lượt rơi về câu xin lỗi chung sau 2 lần viết lại: 70/323 trước fix, 52/323 (16%) sau fix; lý do chính `price_without_quote`, `unsupported_policy_or_internal_claim`, `unsupported_product_spec` | Cần xem lại guardrail `price_without_quote` |
| 8 | Vòng Knowledge K0→K1: các run `084346Z`, `113656Z`, `124247Z` đã sinh proposals (`results-submission/<run>.knowledge/`), chưa duyệt/phát hành K1. Với nhánh này dùng `113656Z`: duyệt tại `http://127.0.0.1:8000/knowledge?run_id=20261127T113656Z-0cb1b876.knowledge`, rồi `python run_knowledge_eval.py --base-run results-submission/20261127T113656Z-0cb1b876` | Việc thủ công |
| 9 | ASR: chưa chạy lại whisper-turbo B0/B1/B2 để kiểm tra tái lập; chưa chạy README ASR với whisper-small | Chưa làm |
| 10 | Báo giá theo địa chỉ cũ trong bộ nhớ: TEAM-33 khách đổi nơi nhận sang Hà Nội nhưng model gọi `pricing.get_quote(address="Cần Thơ")`, rồi nói "miễn phí giao hàng" (HR freeship). Guardrail chấp nhận vì có báo giá freeship trong bằng chứng, không đối chiếu địa chỉ với lời khách mới nhất | Chưa sửa |
| 11 | Một lượt không trả lời được làm dừng cả run: khi verify hết đường sửa mà không có fallback (ví dụ model lỗi lúc sửa), runtime báo `agent_reply_unavailable` → `StreamingMeasurementError` → cả cấu hình dừng. Đã gặp ở run `123210Z` (review tắt): TEAM-09 call_1 lượt 2 bị chặn `stock_result_mismatch` một lần rồi bước sửa ném lỗi, run dừng ở kịch bản 9/48; chạy lại riêng TEAM-09 hai lần không tái hiện. Nếu gặp trên bộ ẩn của BTC sẽ mất toàn bộ trace. Thiết kế có chủ đích: `test_infra_or_empty_or_internal_repair_never_uses_safe_fallback` yêu cầu không dùng fallback khi model lỗi lúc sửa. Đã thử đổi sang dùng fallback khi đã có bản nháp, nhưng bỏ vì trái test này | Cần nhóm quyết định |
| 12 | Lý do chặn không có trong `DIAGNOSTIC_REASONS` (ví dụ `unsupported_answer_claim` của semantic review) hiện thành `unknown_reason` trong diagnostics; trace cũng không lưu bản nháp bị chặn, nên không phân loại được chặn đúng/chặn nhầm | Chưa sửa |
| 13 | Câu trả lời bị cụt: mỗi run có khoảng 1 lượt agent_text chỉ còn đoạn cuối (`084346Z` TEAM-20 call_2 lượt 3: "s"; `113656Z` TEAM-44 call_2 lượt 3: "và chị vui lòng chờ trong giây lát nhé."). Có từ trước các fix của nhánh này | Chưa điều tra |

Đã kiểm tra theo README trên Windows (clone sạch): bước 1 lỗi `uvloop` (đã sửa), `compose_up.py` chạy được khi đủ dung lượng đĩa, `seed_btc.py` trên `main` lỗi `InterfaceError` (đã sửa), eval chạy hết 48 kịch bản trên nhánh này.

## 5. Chạy trên Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r config/requirements/host.txt
Copy-Item .env.example .env
```

Điền `LLM_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` trong `.env`, rồi:

```powershell
.\.venv\Scripts\python.exe scripts/compose_up.py
.\.venv\Scripts\python.exe seed_btc.py --data-dir ..\BTC-Data-Vong1-TEAMS
.\.venv\Scripts\python.exe run_eval.py
```

- Không cần đặt `PYTHONUTF8` nữa.
- Image speech GPU cần nhiều dung lượng; Docker Desktop lưu dữ liệu ở ổ C mặc định. Thiếu chỗ thì Docker dừng giữa lúc giải nén image (`rpc error ... EOF`). Dọn bằng `docker builder prune -a`.
- Muốn chạy song song hai bản mà không ghi đè image của nhau: đặt `COMPOSE_PROJECT_NAME` và `SUBMISSION_IMAGE_TAG` khác nhau trong `.env`.
- Clone cũ đã checkout JSON dạng CRLF: sau khi pull `.gitattributes` mới, xóa và checkout lại các file JSON (`git ls-files -z '*.json' '*.jsonl' | xargs -0 rm -f; git checkout -- .`). Nếu không, hash manifest và fingerprint nguồn BTC sẽ lệch (`scenario_manifest_hash_mismatch`, `BTC source differs from the initialized database`).
- Trước khi chạy eval, đảm bảo `langmem-worker` đã xử lý xong job của lần chạy trước (xem mục 4).
