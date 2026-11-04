# BTC Eval Harness Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. Làm trực tiếp trong checkout hiện tại; không worktree, sub-agent, `git add` hoặc commit. Plan đã được người dùng duyệt và triển khai trong phạm vi offline; xem [báo cáo kiểm chứng](2026-11-04-btc-eval-harness-repair-progress.md), gồm giới hạn full regression/live.

**Goal:** Nối runtime text hiện có với hai CLI, trace trung thực và scorer BTC nguyên bản thành một quy trình full/baseline có kiểm chứng offline và trạng thái công bố rõ ràng.

**Architecture:** `benchmark_runner` sở hữu một đường thực thi cấu hình; root CLI chỉ chuyển tham số, `run_official` điều phối cặp. Tái sử dụng adapter, extractor, worker, release pinning, `eval.trace_audit` và `eval.score_pair`; tách kiểm tra offline khỏi preflight dịch vụ và reset. Chỉ bổ sung module nhỏ cho contract đầu vào, lịch sử CRM và bằng chứng redaction để không nhân đôi logic.

**Tech Stack:** Python hiện có, asyncio, pytest/unittest, jsonschema, asyncpg, runtime/gateway bốn MCP và LangMem worker; không thêm dependency.

**Spec:** [2026-11-04-btc-eval-harness-repair-design.md](../specs/2026-11-04-btc-eval-harness-repair-design.md), đã được người dùng duyệt ngày 2026-11-04.

## Global Constraints

- “Không thay business logic của agent để khớp đáp án trong lần sửa này.” Không sửa scenario/schema/scorer BTC hoặc dữ liệu nguồn để làm test qua.
- “Trong khi triển khai chỉ chạy test chức năng offline; không tự chạy live eval/benchmark, cài dependency hoặc reset DB.” Không restart/build dịch vụ hoặc activate knowledge release.
- Giữ `--config full|baseline_no_memory`, `--scenarios`, `--out` và các cờ an toàn root CLI. Internal `baseline` chỉ là alias của `baseline_no_memory`.
- “Baseline chỉ vô hiệu hóa việc đọc bộ nhớ dài hạn từ phiên trước”; giữ identity, context trong phiên, tools và đường ghi memory.
- “Không lưu PII thô vào trace/log.” Không mask tool names/call IDs hoặc thay business args để hợp thức hóa điểm.
- `failed` cho lỗi thực thi/kiểm tra bắt buộc; `invalid` cho mất bằng chứng do redaction; cả hai thoát khác 0. `validated` không đồng nghĩa đạt ngưỡng chất lượng/quy mô latency.
- Reset chỉ runtime/sequence trong phạm vi đã duyệt của DB đích khai báo rõ; giữ `btc_source`, knowledge và migration metadata. Không coi phê duyệt plan là phép reset thực tế.
- Không thêm dashboard/metric, ASR/RAG benchmark, simulator, judge hoặc agent riêng. Không chạy full suite trong giai đoạn viết plan.

## Review Focus

1. JSON có call đảo thứ tự, ID trùng hoặc ASR rỗng: phải chặn trước model/reset thay vì âm thầm đổi dữ liệu (Task 2).
2. Một customer xuất hiện ở nhiều kênh và có `seed_history` trùng session: không gán nhầm lịch sử hoặc nạp trùng; baseline không đọc lén qua CRM (Task 4).
3. Identity được nhận diện muộn và worker backfill source cũ: file JSONL cuối phải chứa accepted writes đúng lượt ở cả hai cấu hình (Task 5).
4. Mask tên/địa chỉ trong brief, evidence hoặc scored args: giữ kiểu dữ liệu và báo `invalid` nếu mất bằng chứng, kể cả khi scorer trả điểm đẹp (Tasks 7–8).
5. Lỗi ghi artifact cuối hoặc bị ngắt giữa hai cấu hình: không để report cũ/status `validated` xuất hiện như kết quả lần mới (Task 8).

## File map và thứ tự

Tất cả path dưới đây tính từ root repo. Thực hiện tuần tự Tasks 1–10.

| Thành phần | File | Trách nhiệm |
|---|---|---|
| Test offline | `ai-services/eval_harness/conftest.py` (mới) | Settings tổng hợp, bỏ credentials phát triển, chặn mạng thật trong test harness |
| Dataset contract | `ai-services/eval_harness/scenario_contract.py` (mới), `preflight.py` | Load/validate đầu vào và thống kê coverage; giữ API diagnostic cũ |
| Shared execution | `ai-services/eval_harness/benchmark_runner.py`, `eval/run_eval.py`, `run_eval.py` | Một runner, CLI mỏng, cùng trace transform |
| Seed CRM | `ai-services/eval_harness/seed_history.py` (mới), `ai-services/app/agent/factory.py` | Validate/áp lịch sử đầu vào vào context CRM theo identity; inject gateway trước khi build graph |
| Trace extraction | `extractor.py`, `reference_adapter.py`, `reextract_trace.py` | Questions, claims, facts_used, accepted writes và replay |
| Safe evidence | `ai-services/eval_harness/trace_evidence.py` (mới) | Kiểm trước mask, evidence an toàn và phát hiện thay đổi khả năng chấm |
| Lifecycle | `run_official.py`, `official_pipeline.py`, `runtime_reset.py`, `eval/trace_audit.py`, `eval/score_pair.py` | Preflight/reset, provenance, audit và công bố trạng thái |
| Tài liệu | `README.md`, `ai-services/README.md`, `ai-services/eval_harness/README.md` | Lệnh dùng được, giới hạn và cách đọc artifact |

Các path rút gọn như `extractor.py` trong bảng thuộc `ai-services/eval_harness/`. Thêm test vào file hiện có nếu phù hợp; các file test mới được ghi rõ trong task. Không tách/refactor các subsystem ngoài bảng.

## Task 1: Làm test harness an toàn và sửa setup release

**Files:** Create `ai-services/eval_harness/conftest.py`; modify `ai-services/eval_harness/test_run_official.py`, `test_benchmark_lifecycle.py` và test coordinator còn gọi `capture_release` thật tìm được khi rà patch sites.

**Interfaces:** Test fixture `offline_settings` trả Settings với `_env_file=None`, model/credentials tổng hợp và observability tắt; `fake_release` trả `{release_id, manifest_hash}`. Không thay Settings runtime production.

- [x] Thêm test setup chứng minh settings không đọc `.env`, không dùng secret môi trường; mọi network socket thật bị chặn. Xóa các biến secret/DSN/provider trong process test trước khi import module có cached settings; clear settings cache sau test. Test subprocess phải truyền môi trường tổng hợp và cài chặn mạng trong child, không chỉ chặn parent.
- [x] Patch `capture_release` tại nơi sử dụng bằng AsyncMock ở các test coordinator/runner; giữ test giả lập release lỗi. Các test DB opt-in vẫn skip và ép `EVAL_RESET_TEST_DB` tắt trong profile offline; không đổi skip để chạy DB thật.
- [x] Chạy focused tests từ `ai-services/`: `.venv/bin/python -m pytest eval_harness/test_run_official.py eval_harness/test_benchmark_lifecycle.py -q`. Kỳ vọng các test không truy cập DB/model; nếu fixture cũ `calls={}` không còn hợp lệ, thay bằng scenario tổng hợp có turn thật, không nới validator.

## Task 2: Contract dataset và preflight offline trước mọi side effect

**Files:** Create `ai-services/eval_harness/scenario_contract.py`, `test_scenario_contract.py`; modify `ai-services/eval_harness/preflight.py`, `test_preflight.py`.

**Interfaces:** `load_scenarios(path: Path, *, btc_root: Path) -> dict[str, dict]`; `dataset_coverage(scenarios: dict[str, dict]) -> dict`; lỗi contract là `ValueError` với mã lỗi/path an toàn. Giữ `inspect_eval_inputs(...)` cho diagnostic; CLI offline dùng cùng loader.

- [x] Viết tests `test_rejects_empty_duplicate_or_invalid_dataset`, `test_call_order_and_asr_inputs_are_explicit`, `test_contract_failure_has_no_runtime_side_effects`. Assert: directory hoặc bundle `{scenarios: [...]}` được hỗ trợ; không ghi đè ID trùng vào dict; call theo `call_1..call_3`, không bỏ call/turn; ASR được chọn theo sự hiện diện field, ASR rỗng/sai kiểu/mismatched length bị lỗi thay vì fallback clean. Validate ngày, channel/input mode, supported success criteria từ contract BTC và đủ các file schema/scorer cần dùng.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_scenario_contract.py eval_harness/test_preflight.py -q` để xác nhận test mới đỏ đúng nguyên nhân.
- [x] Implement loader thuần file, giữ nguyên ID/text và bản dữ liệu chấm; tạo request chỉ từ identity, ngày và customer input, không truyền ground truth/success criteria vào runtime. Đọc call theo thứ tự chuẩn, báo lỗi gaps/định danh không hỗ trợ. Validate `seed_history` qua Task 4; trước Task 4, chặn rõ trường chưa hỗ trợ.
- [x] Thêm `--offline-check` ở CLI preflight; chỉ đọc file, báo scenario/call/turn/hard-case và hash đầu vào. Bundle cần materialize nguyên scenario thành directory tạm để scorer BTC hiện có đọc, không sửa nội dung; dùng cùng snapshot đó cho cả cặp và provenance. Giữ snapshot đã chấm trong run artifacts để chấm lại được.
- [x] Chạy lại đúng hai file tests trên; kỳ vọng PASS, không gọi factory/reset/model khi file đầu vào lỗi.

## Task 3: Preflight bốn MCP, DB đích và knowledge release

**Files:** Modify `ai-services/eval_harness/benchmark_runner.py`, `runtime_reset.py`, `run_official.py`, `test_runtime_reset.py`, `test_run_official.py`; create `ai-services/eval_harness/test_service_preflight.py`.

**Interfaces:** `preflight_runtime(runtime, settings, *, expected_database: str, release: dict) -> dict` chỉ đọc; `prepare_runtime_for_eval(runtime, settings, *, expected_database: str, release: dict) -> dict` gọi preflight rồi reset. Tách bước probe và mutation để coordinator kiểm tra trước full/baseline. Reset kiểm cùng endpoint/server identity qua chính connection reset, không chỉ tên DB.

- [x] Thêm test mock đầy đủ cho knowledge unavailable/auth failure, thiếu identity fields, khác host/server, target chưa khai báo và production. Assert reset/model chưa được gọi. Test release có bản ghi PostgreSQL nhưng `runtime.tools.knowledge_release()` không sẵn sàng phải fail.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_service_preflight.py eval_harness/test_runtime_reset.py -q`; tests DB vẫn skip.
- [x] Probe catalog/order/memory/knowledge và đối chiếu identity với DB runner thực sự kết nối. Thêm `--expected-database` dùng chung, nhận env `EVAL_EXPECTED_DATABASE` nếu không có flag; không mặc định suy ra tên từ DB probe. Giữ cờ `--isolated-db` ở root; không dùng hậu tố `_eval` để loại DB `telesale` đã được duyệt, nhưng vẫn yêu cầu khai báo đích và chặn production.
- [x] Capture release một lần tại coordinator, pin ID/hash qua subprocess và đối chiếu release phục vụ ở mỗi cấu hình; child không tự capture active release mới. Fingerprint source/release trước và sau từng nhánh. Không activate release hoặc đổi release đang phục vụ.
- [x] Giữ phạm vi reset đã có nhưng test bằng fake connection rằng không truncate knowledge/`btc_source`/migration metadata. Chạy lại nhóm focused trên cùng `test_run_official.py`; kỳ vọng PASS và mọi preflight failure đều trước reset/model.

## Task 4: Hỗ trợ seed_history bằng lịch sử CRM có nguồn

**Files:** Create `ai-services/eval_harness/seed_history.py`, `test_seed_history.py`; modify `scenario_contract.py`, `benchmark_runner.py`, `ai-services/app/agent/factory.py`.

**Interfaces:** `parse_seed_history(value: object, *, call_date: date) -> list[dict]`; `SeedHistoryGateway` ủy quyền gateway thật và bổ sung history cho CRM identity đã resolve. Mở rộng factory thành `build_runtime(settings: Settings, *, gateway=None) -> AgentHarnessRuntime`: mặc định vẫn tạo gateway thật như hiện tại; khi inject thì dùng cùng object ở graph/runtime/memory store, không đổi `runtime.tools` sau khi graph đã được build. Wrapper chuyển tiếp `invoke_trusted`, identity/release probes và mọi phương thức khác không thuộc CRM history.

- [x] Chốt dạng hỗ trợ ban đầu theo CRM sessions hiện có: `seed_history` là list object `{session_id, date, channel, summary, outcome?}`; ngày ISO trước call, ID không rỗng/không xung đột, channel/outcome hợp lệ. Object/string hoặc dạng chưa hỗ trợ bị preflight từ chối trước reset. Đây là lựa chọn triển khai, không khẳng định BTC đã định nghĩa JSON Schema đầy đủ cho field này.
- [x] Viết `test_old_crm_history_is_visible_only_in_full`, `test_history_is_scoped_to_resolved_customer`, `test_conflicting_history_session_fails_preflight`: hai cấu hình cùng history; hotline/Zalo cùng customer không nạp trùng; ambiguous/unknown không gán history; customer khác không đọc được. History không tạo scored turn hoặc memory write giả.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_seed_history.py eval_harness/test_scenario_contract.py -q` để thấy đỏ; sau đó implement wrapper chỉ bổ sung `sessions` của CRM response thành công sau resolve identity, không sửa giá, đơn, kết quả business tool hoặc `btc_source`. Không giả CRM found=true; identity không resolve được gây run failure có lý do an toàn.
- [x] Ghi nguồn seed riêng trong metadata: hash đầu vào, mapping scenario/call → seeded session; không đưa raw summary vào manifest/log. Giữ provenance session cũ ở context, không đổi thành source của turn scored. Cùng session ID/nội dung thì deduplicate, cùng ID/khác nội dung thì reject. Scope seed theo scenario và các call sau của scenario đó, không rò sang scenario kế tiếp.
- [x] Chạy lại hai file tests trên và test baseline trong `test_eval_harness.py`; chứng minh cơ chế `include_prior=False` hiện hành chặn cả CRM sessions, không chèn seed vào prompt riêng cho baseline.

## Task 5: Một đường thực thi và trace cuối có accepted writes

**Files:** Modify `ai-services/eval_harness/benchmark_runner.py`, `reference_adapter.py`, `eval/run_eval.py`, `run_eval.py`, `eval/test_run_eval.py`, `ai-services/eval_harness/test_eval_harness.py`, `test_benchmark_lifecycle.py`; create `ai-services/eval_harness/test_entrypoint_parity.py`.

**Interfaces:** `async run_configuration(*, scenarios: dict[str, dict], config: str, runtime, run_id: str, out: Path, wait_for_jobs, capture_writes, on_row=None) -> dict` sở hữu chạy và flush trace; trả coverage, safe issues và runner metadata. `run_scenario_call`/`run_scenario_stream` tiếp tục dùng cùng `trace_line`; CLI thực hiện preflight/reset trước khi gọi interface này.

- [x] Viết test stateful fake runtime/gateway/worker qua hai entry point và hai cấu hình: session mỗi call riêng, turn đúng thứ tự, ngày cộng dồn, ASR đúng text/mode, tools/args/call IDs nguyên vẹn. Không mock row hoàn chỉnh. Cùng turn state phải cho cùng trace transform, không yêu cầu LLM output giống nhau giữa các run.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_entrypoint_parity.py eval_harness/test_benchmark_lifecycle.py -q` để thấy đỏ.
- [x] Chuyển root `_questions`/claim/facts/memory path sang shared runner; giữ `--report-out` và các evidence/report hiện có bằng cách đọc cùng rows, không tạo pipeline trace thứ hai. Baseline giữ CRM customer ID, chỉ tắt đọc prior memory; bỏ namespace baseline nếu nó đổi customer identity trong memory store.
- [x] Cả hai nhánh truyền waiter và accepted-write reader. Chờ đúng source turn trước lượt sau; cuối call đọc lại attribution, bao gồm nhận diện muộn/backfill. Thiếu turn/job, job fail, timeout hoặc final read lỗi phải đánh dấu failed thay vì chỉ log warning. Không thay bằng proposed writes hay mảng rỗng do capture lỗi.
- [x] Streaming chỉ giữ partial artifact đã mask; sau final attribution ghi lại JSONL qua file tạm rồi replace. Test đọc file thực sau late backfill ở baseline/full, không chỉ assert rows trong RAM. Giữ mapping source `call_N#turnM` của lượt gốc.
- [x] Chạy lại hai file trên cùng `test_eval_harness.py`; root `eval/test_run_eval.py` chạy bằng Python venv từ root với môi trường offline tương đương Task 1. Không làm mất test tool names khi sửa adapter.

## Task 6: Extractor questions/claims và facts_used trung thực

**Files:** Modify `ai-services/eval_harness/extractor.py`, `reference_adapter.py`, `reextract_trace.py`, `fixtures/text_extraction_labels.json`, `test_question_semantics.py`, `test_claim_semantics.py`, `test_fact_usage.py`, `test_trace_extraction.py`, `test_reextract_trace.py`.

**Interfaces:** Giữ `extract_questions(agent_text)`, `extract_claims(agent_text, tool_calls)` và `facts_used(...)`; output theo BTC schema. Mapping field lấy tên contract BTC, không lấy expected value của scenario để suy claim.

- [x] Bổ sung nhãn độc lập cho mọi nhóm spec: câu xin dữ kiện không dấu hỏi; `other`; nhiều yêu cầu và nhiều regex cùng khớp; tiền nhỏ/số tiếng Việt; list price/promo theo mã/stock/freeship/delivery/restock/return window/exchange fee/warranty/policy version. Case nói sai phải giữ giá trị sai; tool chỉ cung cấp ngữ cảnh sản phẩm. Thêm `is_human` tự nhận/phủ định/câu hỏi/trích dẫn và phủ định AI/bot.
- [x] Thêm fact cases `false`, `0`, superseded, scope SKU, same-session, customer tự nhắc lại, provenance `langmem:<session>:<turn>`. Assert chỉ observable use từ phiên trước được tính; không đổi historical claim thành hiện tại hoặc bỏ claim sai để đẹp HR.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_question_semantics.py eval_harness/test_claim_semantics.py eval_harness/test_fact_usage.py -q` để xác nhận nhãn mới chưa qua.
- [x] Implement rule extractor theo mệnh đề/evidence span; một request hỏi độc lập chỉ một question, fallback `other`; không dùng `other` thay slot biết rõ. Giữ text evidence đã mask sau khi trích trên output gốc trong RAM. Deduplicate theo span/ý nghĩa, không gộp hai lần hỏi thật sự khác nhau.
- [x] Re-extraction dùng cùng extractor, giữ facts_used cũ nếu public trace thiếu provenance. Chạy lại ba file trên cùng `test_trace_extraction.py`, `test_reextract_trace.py`; test mọi tool name/call ID sống nguyên và replay không model/MCP/DB.

## Task 7: Handoff có kiểu dữ liệu và safe redaction evidence

**Files:** Create `ai-services/eval_harness/trace_evidence.py`, `test_trace_evidence.py`; modify `reference_adapter.py`, `test_trace_extraction.py`, `test_eval_harness.py`.

**Interfaces:** `inspect_redaction(raw_row: dict, safe_row: dict, *, call_spec: dict) -> list[dict]` chỉ xử lý RAM; mỗi issue chỉ chứa code/type, field path, scenario/call/turn. `trace_line` vẫn trả public row; truyền safe issues qua collector riêng, không đưa raw row vào report/exception.

- [x] Test schema handoff trước mask; after mask giữ enum/number/bool/list/object và business fields. Test tool names/call IDs nguyên byte, scored args không bị sửa âm thầm. Fixture có PII tổng hợp trong agent text, memory writes/evidence_quote và nested brief/args; assert giá trị thô không xuất hiện trong bất cứ artifact/log nào.
- [x] Test redaction ảnh hưởng `args_match`, `must_say_any`, `agent_must_say`, `trace_must_not_match`, guardrail PII và memory checks. So sánh điều kiện chấm có liên quan trước/sau mask trong RAM; không cần coi mọi phép mask là invalid nếu không ảnh hưởng bằng chứng chấm. Khi không thể chứng minh giữ nguyên khả năng chấm, đánh dấu `redaction_affects_scoring` bảo thủ và nêu path an toàn.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_trace_evidence.py eval_harness/test_trace_extraction.py -q` để thấy đỏ; implement field-path masking, bỏ hành vi thay cả brief bằng placeholder. Không log raw exception, summary hoặc request khi capture thất bại.
- [x] Thu claim/question từ raw output trước mask, rồi mask evidence text/giá trị nhạy cảm; nếu việc mask field cần chấm làm mất giá trị thì issue phải đi cùng. Không bịa claim thay PII và không sửa scorer/report.
- [x] Chạy lại nhóm trên; kỳ vọng PASS, evidence an toàn có thể đưa vào manifest của Task 8.

## Task 8: Công bố cặp trace/scorer với trạng thái cuối nguyên tử

**Files:** Modify `ai-services/eval_harness/run_official.py`, `official_pipeline.py`, `test_run_official.py`, `test_official_pipeline.py`, `eval/trace_audit.py`, `eval/score_pair.py`, `eval/test_trace_audit.py`, `eval/test_score_pair.py`.

**Interfaces:** `publish_pair(..., *, btc_root: Path, safety_issues: list[dict] | None = None) -> dict` trả score/manifests/status. `run_pair` giữ trả run directory; `main` đọc final status và trả exit nonzero khi failed/invalid. Status authority là `run.json`, không suy từ sự hiện diện `btc_score.json`.

- [x] Test full fail/baseline fail/release đổi/coverage thiếu/duplicate/out-of-order/source hoặc dataset đổi, lỗi ghi manifest, ngắt giữa hai nhánh, output cũ và redaction invalid. Đường lỗi giữ partial trace an toàn, không công bố score như valid; lỗi execution ưu tiên `failed` và giữ cả redaction issue.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_official_pipeline.py eval_harness/test_run_official.py -q` để thấy đỏ.
- [x] Tạo run directory unique và `run.json` ban đầu `running`; gom artifact ở staging, ghi JSON atomic bằng temp+replace cùng filesystem. Chỉ ghi `validated` cuối sau schema/exact coverage/order/config/runner report/memory/provenance/pair audit và mọi artifact thành công. Ghi trạng thái failed ở đường exception có thể bắt; nếu process bị kill đột ngột, `running` còn lại chỉ là run chưa hoàn tất, không hợp lệ.
- [x] Trace đầy đủ nhưng có `redaction_affects_scoring` kết thúc `invalid`, manifests chứa safe issues; mặc định không công bố report chính thức. Nếu giữ report đối chiếu, tên `btc_score.redacted.diagnostic.json` và liên kết rõ với invalid. Không thay report values. Metadata gồm hash scorer/schema/scenario/trace, seed/source digest, DB identity an toàn, release ID/hash, model/provider/params/hardware/time, warm-up và measured counts.
- [x] Tái sử dụng `audit_trace`, `build_manifest`, `audit_pair`, `score_pair`; bổ sung check còn thiếu thay vì viết scorer thứ hai. Manifest failed/invalid có thể thiếu hash của artifact chưa được tạo nhưng phải nêu rõ, không fake input/report; strict manifest của validated vẫn đủ.
- [x] Chạy lại tests trên; từ root chạy focused `eval/test_trace_audit.py eval/test_score_pair.py` bằng Python venv. Test direct BTC score == report công bố trên fixture, không sửa scorer khi gặp discrepancy.

## Task 9: Latency thực và warm-up không làm bẩn dataset

**Files:** Modify `ai-services/eval_harness/benchmark_runner.py`, `reference_adapter.py`, `run_official.py`, `test_eval_harness.py`; create `ai-services/eval_harness/test_latency_contract.py`. Chỉ nếu phép đo brief hiện có không đủ: sửa instrumentation trong `ai-services/app/agent/harness/runtime.py`, `context.py`, `session_nodes.py` và `test/test_scoped_context.py`, không đổi business behavior.

**Interfaces:** `async warm_up_configuration(runtime, *, turns: int = 3) -> dict`; shared runner dùng `time.perf_counter` tại ranh giới request/response. Test fake clock quyết định số ms, không assert wall time máy CI.

- [x] Test nonstream TTFT=Total, response timer không chứa extractor/file/scoring/post-response distillation; các await nằm trên đường trả lời vẫn được tính. Test ba warm-up cho mỗi config không xuất hiện trong trace scored và không tạo memory/order/ticket ảnh hưởng dataset.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_latency_contract.py -q` để thấy đỏ. Implement warm-up qua cùng model/runtime và session riêng với tools/memory bị chặn ghi; reset được duyệt cho cấu hình diễn ra sau warm-up, trước seed/scored turns, rồi tạo runtime mới để xóa cache phiên. Không dùng câu hỏi kỳ vọng BTC làm warm-up. Mọi warm-up gọi model thật chỉ được chạy sau ủy quyền live.
- [x] Brief đo từ nhận diện customer đến object sẵn sàng, có freshness; harness chỉ xuất ở turn 1 call_2/call_3 nếu có phép đo thật. Thiếu phép đo dùng null/omit hợp schema, không thay bằng total hoặc đo formatter. Nếu cần timestamp mới, chỉ thêm instrumentation vào các file runtime đã nêu.
- [x] Trace giữ mọi lượt scored; BTC scorer nhận nguyên trace, không bỏ ba lượt scenario. Metadata ghi warm-up=3, input counts, measured counts và cảnh báo dưới 100. Full/baseline cùng hardware/API/model/params/seed; model/provider config được ghi không secret.
- [x] Chạy lại `test_latency_contract.py` cùng tests context nếu có sửa instrumentation; assert 39 lượt fixture vẫn 39, không thành 36, và warm-up hoàn toàn không vào mẫu số scorer.

## Task 10: Nghiệm thu offline qua CLI, README và bàn giao

**Files:** Create `ai-services/eval_harness/test_offline_end_to_end.py`, `fixtures/btc_harness_repair/` (scenario và nhãn tổng hợp); modify ba README trong file map, CLI help và các tests CLI tương ứng.

**Interfaces:** CLI root và paired hỗ trợ `--btc-root`, `--expected-database`; `benchmark_runner --dry-run N` trả lỗi hướng dẫn dùng `--limit-scenarios N` cho smoke thật hoặc `preflight --offline-check` cho kiểm file. `--limit-scenarios` phải chọn snapshot scenario tương ứng cho scorer và ghi rõ subset, không tự gọi là đủ BTC.

- [x] Viết integration stateful fake model/gateway/worker chạy qua shared execution của hai CLI; giữ scorer/schema BTC thật từ `--btc-root`. Fixture nhỏ có claim sai, câu hỏi other và lặp, carryover đúng/sai, human claim, memory backfill và invalid PII riêng. Dùng dữ liệu tổng hợp, không ghi trace khách thật vào repo.
- [x] Gán expected bằng tay: ít nhất một case HR có wrong=1/total=2, RQR redundant=1/total_questions=3 (có `other`), CCR used=1/required=2 và `claims_human=1`; bố trí `success_if` độc lập để assert `max_agent_questions` và TSR. Đọc công thức scorer BTC trước khi chốt fixture; giữ tool args không vô tình cộng thêm CCR slots. Assert raw report và direct `reference_eval.py` tái tạo cùng giá trị, không chỉ diagnostic nội bộ.
- [x] Chạy `.venv/bin/python -m pytest eval_harness/test_offline_end_to_end.py -q`; cần fixture runtime/gateway có trạng thái, không patch `trace_line`/row/publish kết quả hoàn chỉnh. Mọi connection thật bị chặn như Task 1; scorer subprocess được phép vì chỉ đọc file.
- [x] README cung cấp lệnh chạy được cho offline preflight, một cấu hình, cặp và re-score qua `reference_eval.py`; help test xác nhận các cờ tồn tại. Ghi rõ env/model/MCP/worker/DB đích/release cần có, nơi đọc run status, schema/hashes, `seed_history` supported shape, extractor limits, nonstream latency, sample/team counts và yêu cầu ủy quyền live. Sửa câu cũ mặc định coi directory có 19 scenario nếu thực tế chỉ có 7.
- [x] Chạy focused tests của Task 10 và các CLI thay đổi. Trước bàn giao implementation, chạy full regression đúng một lần theo repository từ `ai-services/`: `.venv/bin/python -m pytest test eval_harness/test_eval_harness.py`, với profile offline đã chặn mạng và Settings tổng hợp; kèm nhóm harness/root tests thay đổi chưa nằm trong lệnh đó, không lặp focused checks đã đạt nếu không có thay đổi mới. Nếu test ngoài harness cần bootstrap an toàn, mở rộng test fixture offline có phạm vi rõ; không đọc secret hay bật mạng để làm suite qua. Ghi chính xác pass/fail/skip; không tự gọi suite offline là live verification.
- [x] Rà diff chỉ gồm phạm vi plan, không stage/commit. Bàn giao “đã kiểm chứng offline; chưa xác minh live”, liệt kê giới hạn extractor/dataset/latency và lỗi còn lại nếu có.

## Cổng live riêng, không nằm trong các lệnh thực thi tự động

Sau khi người dùng cho phép riêng: người chạy chọn dataset và DB đích, xác nhận phạm vi reset; chạy cặp qua runtime/bốn MCP/worker thật, không đổi release phục vụ. Kiểm schema, exact coverage, accepted writes, PII/status và tái chấm bằng BTC nguyên bản. Chỉ lúc đó mới ghi nhận đã xác minh live; dataset thiếu quy mô vẫn phải báo thiếu. Lỗi agent thật giữ nguyên trong score, không chuyển thành lỗi harness chỉ vì không đạt ngưỡng.

## Đối chiếu spec và self-review

| Spec | Task chịu trách nhiệm |
|---|---|
| 1–2: phạm vi, tái sử dụng runtime/scorer | Global constraints, 5, 8, 10 |
| 3: thống nhất entry point và CLI | 5, 10 |
| 4: dataset/preflight/DB/release/coverage/dry-run | 2, 3, 8, 10 |
| 5: full/baseline, seed, ngày/ASR, accepted writes | 4, 5 |
| 6: extraction/facts/provenance/handoff/PII | 5, 6, 7 |
| 7: warm-up/latency/brief/metadata | 9 |
| 8: official score/hash/trạng thái/artifact | 8 |
| 9: offline functional/scorer/CLI và live gate | 1, 10, cổng live riêng |

Đã rà tên interface giữa các task, mapping của năm Review Focus và tách bạch lỗi harness với chất lượng agent. Các interface mới là quyết định của plan cần người dùng duyệt; không phải API đã tồn tại trong checkout. Không có bước gọi model, reset DB hoặc cài dependency trong giai đoạn triển khai offline.
