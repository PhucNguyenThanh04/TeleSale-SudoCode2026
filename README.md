# TeleSale SudoCode 2026

**Eval RAG độc lập:** xem [runner retrieval, generation và chấm offline](ai-services/rag_eval/README.md).
Không chạy chung eval hội thoại; model/embedding thật chỉ chạy khi có `--allow-live`.

**Eval ba cấu hình, duyệt knowledge trên frontend:** xem
[eval thường hai cấu hình → duyệt/phát hành → file Full K1 riêng](ai-services/eval_harness/KNOWLEDGE_TRIPLET.md#luồng-duyệt-trên-frontend).

**Bản nộp M1:** xem [hướng dẫn máy mới và lệnh BTC chấm chéo](docs/submission-runbook.md).
CLI `run_eval.py` mặc định chat text; cần cấu hình model/Knowledge và không chạy
chat hoặc eval khác đồng thời trên cùng DB. Eval dùng hạ tầng đang chạy, reset
runtime/memory trước mỗi cấu hình và giữ nguyên knowledge/BTC.

Một lệnh chạy **full + baseline → trace → scorer BTC → bảng so sánh và nghiệm thu
hội thoại M1** (LIVE, cần cho phép gọi model/reset DB eval riêng):

```bash
PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.run_official --btc-root ../BTC-Data-Vong1-TEAMS --scenarios ai-services/eval_harness/scenarios --expected-database telesale_eval_m1
```

Mặc định text; có thể đính kèm báo cáo ASR BTC/team đã lưu. Xem [lệnh và cách đọc
kết quả](ai-services/eval_harness/README.md#lệnh-nghiệm-thu-hội-thoại-m1).
`validated` không đồng nghĩa đã đạt M1; bảng cuối ghi rõ các điều kiện chưa đạt.

Lệnh ngắn tương đương, không gọi Docker hoặc khởi động lại hệ thống:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true python3 run_system.py eval --expected-database telesale -- --btc-root ../BTC-Data-Vong1-TEAMS --scenarios ai-services/eval_harness/scenarios
```

**Khởi động demo mới, tự tạo/reset bảng cả backend và AI:**
[quy trình mới](docs/fresh-system-startup.md). Sau khi nạp BTC một lần:

```bash
python run_system.py demo --expected-database telesale
```

Không cần chạy migration riêng. Knowledge đã học/duyệt của lượt trước cũng được
reset; chỉ policy BTC nền và tài khoản/quyền mặc định được tạo lại từ cấu hình.

Quy trình chạy chat M1, nhận replay ASR, kiểm bằng chứng và so sánh hai vòng cải
tiến: [M1 acceptance](docs/m1-acceptance.md). Chat demo hiện nằm tại `/chat` trên
gateway `app.voice_main:app`; entrypoint backend cũ không phải đường chạy demo.

The text harness runs through `backend` → `ai-services` → four MCP
servers. Import BTC data once with `dataloader_offline`; managed startup creates
the operational schemas automatically. Configure the private
backend/MCP tokens and URLs in ignored `.env` files. Start the four MCP
containers, backend and AI API through `run_system.py` for a fresh system boot.
The backend chat contract is documented in
[frontend/README.md](frontend/README.md).

The four MCP services are catalog, order, memory and knowledge. Knowledge uses
Cloudflare Workers AI BGE-M3 dense embeddings, CPU BM25 and Qdrant RRF; no NVIDIA
GPU, CUDA or model weights are required. Set `CLOUDFLARE_ACCOUNT_ID` and
`CLOUDFLARE_API_TOKEN` in `ai-services/.env` and the reviewed policy config.
Managed startup restores or builds and activates the BTC-only baseline before
starting the services:

```bash
python run_system.py demo --expected-database telesale
```

The first env file supplies root database/Compose settings; the second supplies
AI settings and overrides duplicate keys. Keep shared DB/port values consistent.
Ingestion and serving require Internet access. A Docker image build alone does
not activate an index; managed startup initializes the BTC-only policy release.
`relevance_verified=false` records unmeasured quality and
does not block an otherwise verified index. Follow the
[submission runbook](docs/submission-runbook.md) for setup and migration
from local embeddings. The clean-machine deployment/API connection still needs
separate verification; offline functional tests do not prove BTC scores or latency.

The AI service exposes `app.agent.chat.chat(ChatRequest)` for one Python chat turn;
`session_id` may be `null` and is returned for later turns. The HTTP route uses
the same function. Both use MCP HTTP; run the AI API with one worker while
its session lock and duplicate-response cache are process-local. From the repo
root, with an **isolated evaluation database/backend** so mutable orders and
one-time promotions do not affect demo data, run:

```bash
ai-services/.venv/bin/python run_eval.py --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale_eval_m1 --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config full --out eval/runs/full.jsonl --isolated-db
ai-services/.venv/bin/python run_eval.py --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale_eval_m1 --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config baseline_no_memory --out eval/runs/baseline.jsonl --isolated-db
python eval/runs/full.btc-release/eval/reference_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --trace eval/runs/full.jsonl --baseline eval/runs/baseline.jsonl
```

The runner emits real harness turns through the shared BTC runner. After explicit
live authorization it validates four MCP identities and resets mutable runtime
state before each configuration, including baseline. `--isolated-db` remains an
operator assertion; `--expected-database` identifies the approved reset target. The model is configured in
`ai-services/.env`. See the [eval runbook](ai-services/eval_harness/README.md) for
offline checks, paired runs, safe artifacts and failed/invalid status. See [memory architecture](docs/m1-architecture.md).

For a new comparison, write both traces into a new directory under
`eval/runs/` and audit each with `ai-services/.venv/bin/python -m
eval.trace_audit trace --scenarios ... --trace ... --config full` (or
`baseline_no_memory`). The auditor checks BTC JSON Schema and exact turn
coverage; its `manifest` and `pair` commands record nonsecret run hashes and
reject mismatched model, seed or source settings. The older files directly in
`eval/runs/` are historical and do not describe the current working tree.
Use `eval.score_pair` to invoke BTC's reference evaluator and bind the score
report to the exact trace hashes before creating manifests. See the
[evaluation runbook](ai-services/eval_harness/README.md) for the reset and audit sequence.

Each trace also gets a `.report.json` sidecar containing `catalog_search`:
`calls_per_turn`, total calls, and the share of search turns with exactly one
call. To measure N independent turns with the configured model and either the
BTC adapter or the deployed catalog MCP, run:

```bash
ai-services/.venv/bin/python eval/catalog_search_benchmark.py --source adapter --runs 10 --fact-extraction-mode off --text 'Tư vấn máy lọc không khí có khóa trẻ em cho phòng 25m2, giá tối đa 5 triệu.' --out eval/runs/catalog-adapter.json
ai-services/.venv/bin/python eval/catalog_search_benchmark.py --source mcp --runs 10 --fact-extraction-mode off --text 'Tư vấn máy lọc không khí có khóa trẻ em cho phòng 25m2, giá tối đa 5 triệu.' --out eval/runs/catalog-mcp.json
```

The benchmark uses a fresh session and in-process memory for each turn. MCP
mode reads the deployed catalog through HTTP; other business tools are disabled
in this measurement. The report stores a hash of the question, not its text.

The offline Vietnamese–English speech pipeline for M1 (TTS test audio, Silero
VAD, local faster-whisper/PhoWhisper, normalization, BTC `hypotheses.json` and
WER/CER/entity scoring) is independent of the text harness; see
[speech/README.md](speech/README.md).
