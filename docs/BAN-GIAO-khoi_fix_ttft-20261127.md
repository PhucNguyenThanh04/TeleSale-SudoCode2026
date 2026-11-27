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

Mỗi commit đã so danh sách test fail trước/sau: không phát sinh fail mới.

## 2. Kết quả eval (48 kịch bản, 323 lượt mỗi cấu hình)

| Chỉ số | Code cũ `main` 26/11 (run `065208Z`) | Code mới + fix Windows, trước các fix TTFT (run `084346Z`) |
|---|---:|---:|
| Execution | degraded (1 `GraphRecursionError`) | healthy |
| RQR Full / Baseline | 4,5% / 21,6% | 1,5% / 25,6% |
| CCR Full | 49,0% | 61,5% |
| TSR Full / Baseline | 77,1% / 64,6% | 81,2% / 60,4% |
| HR Full (giá/KM) | 2,1% (2,8%) | 0,9% (0,0%) |
| TTFT p50 / p95 Full | 2,6 s / 6,5 s | 3,6 s / 7,4 s |
| Total p95 Full | 6,5 s | 7,4 s |
| Call Brief p95 | 259 ms | 300 ms |
| Nghiệm thu M1 harness | chưa đạt (TTFT, health, extraction, Call Brief 69/70) | chưa đạt (TTFT, extraction, Call Brief 69/70) |

**Chưa có số liệu sạch sau các fix TTFT.** Hai lần chạy `094850Z` và `branch-fix3` không hợp lệ: hai phiên chạy eval cùng lúc trên một stack, nên memory của lần này lẫn sang lần kia (25 kịch bản có sẵn episode từ call_1) và TTFT bị nhiễu vì dùng chung Ollama/CPU. Phiên "M1/M2 yêu cầu và tiến độ" đang chạy lại eval sạch trên nhánh này; điền số liệu đó vào đây khi có.

Ghi nhận từ lần chạy nhiễu, chỉ để tham khảo: số lượt cần ≥3 lần gọi model giảm từ 121 xuống 73 (cơ chế giảm vòng gọi có tác dụng); mẫu câu xác nhận đơn và lấy kèm giá/tồn kho đã được kiểm tra chạy đúng trong vòng lặp agent thật trên TEAM-01.

## 3. Nguyên nhân TTFT cao

Đo trên run `084346Z` (Full, 323 lượt):

1. **Mỗi lần gọi `gemma4:31b` qua Ollama Cloud mất ~1 s** (p50 975 ms, p95 1,8 s); chế độ thinking đã tắt. TTFT gần như bằng số lần gọi model × 1 s. Lượt có ≥3 lần gọi: 121/323.
2. **Semantic review đang bật lại.** Commit `9cc4628` ("tat review answer") tắt bước LLM duyệt câu trả lời; commit `fd4792b` ("fixxx") đổi `agent_semantic_review_enabled` mặc định thành `True` trong `ai-services/app/configs.py`. Bước này tốn ~0,7–0,8 s mỗi lượt (p50 815 ms, p95 1,8 s) và không hiện trong `model_timing`. Chưa đổi mặc định vì là đánh đổi chất lượng: run tắt review có HR giá/KM 2,8%, run bật có 0%. Đo thử bằng `AGENT_SEMANTIC_REVIEW_ENABLED=false` trong `.env`.
3. **Viết lại câu trả lời:** ~100 lượt bị guardrail chặn bản nháp đầu, mỗi lượt thêm 1–2 lần gọi model; ~65–70 lượt cuối cùng vẫn rơi về câu xin lỗi chung. Lý do chặn nhiều nhất: `price_without_quote` (~40), `order_creation_unverified` (24, do lỗi đã sửa ở `4a9c41a`).
4. **Bỏ hẳn kiểm tra không đạt 3 s:** ước tính trên trace, kể cả không còn lần viết lại nào, TTFT p95 vẫn ~4,2 s. Không nên tắt guardrail.
5. **Lách bằng câu mở đầu** ("Dạ anh,") trước khi gọi tool sẽ kéo TTFT xuống <1 s nhưng là lách định nghĩa đo của BTC; code đang chặn kiểu này. Không làm.

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
| 7 | ~19–22% lượt rơi về câu xin lỗi chung sau 2 lần viết lại | Cần xem lại guardrail `price_without_quote` |
| 8 | Vòng Knowledge K0→K1: run `084346Z` đã sinh proposals (`results-submission/20261127T084346Z-4bd4d5b5.knowledge/`), chưa duyệt/phát hành K1 | Việc thủ công |
| 9 | ASR: chưa chạy lại whisper-turbo B0/B1/B2 để kiểm tra tái lập; chưa chạy README ASR với whisper-small | Chưa làm |

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
