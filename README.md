# TeleSale SudoCode 2026

The text harness runs through `backend` → `ai-services` → four MCP
servers. Import BTC data with `dataloader_offline` and apply the SQL migrations
listed in [ai-services/README.md](ai-services/README.md). Configure the private
backend/MCP tokens and URLs in ignored `.env` files. Start the four MCP
containers with Compose after importing data and applying migrations; run the
backend and AI API on the host. The backend chat contract is documented in
[backend/CHAT_API_CONTRACT.md](backend/CHAT_API_CONTRACT.md).

The four MCP services are catalog, order, memory and knowledge. Knowledge uses
Cloudflare Workers AI BGE-M3 dense embeddings, CPU BM25 and Qdrant RRF; no NVIDIA
GPU, CUDA or model weights are required. Set `CLOUDFLARE_ACCOUNT_ID` and
`CLOUDFLARE_API_TOKEN` in `ai-services/.env`, prepare and activate a new policy
release with `config/policy-runtime.json`, then start all four services from root:

```bash
docker compose up --build -d
```

The first env file supplies root database/Compose settings; the second supplies
AI settings and overrides duplicate keys. Keep shared DB/port values consistent.
Ingestion and serving require Internet access. A successful build does not create
or activate an index. `relevance_verified=false` records unmeasured quality and
does not block an otherwise verified index. Follow the
[knowledge runbook](ai-services/docs/mcp-knowledge-runbook.md) for setup and migration
from local embeddings. The clean-machine deployment/API connection still needs
separate verification; offline functional tests do not prove BTC scores or latency.

The AI service exposes `app.agent.chat.chat(ChatRequest)` for one Python chat turn;
`session_id` may be `null` and is returned for later turns. The HTTP route uses
the same function. Both use MCP HTTP; run the AI API with one worker while
its session lock and duplicate-response cache are process-local. From the repo
root, with an **isolated evaluation database/backend** so mutable orders and
one-time promotions do not affect demo data, run:

```bash
ai-services/.venv/bin/python run_eval.py --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config full --out eval/runs/full.jsonl --isolated-db
ai-services/.venv/bin/python run_eval.py --btc-root ../BTC-Data-Vong1-TEAMS --expected-database telesale --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config baseline_no_memory --out eval/runs/baseline.jsonl --isolated-db
python ../BTC-Data-Vong1-TEAMS/eval/reference_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --trace eval/runs/full.jsonl --baseline eval/runs/baseline.jsonl
```

The runner emits real harness turns through the shared BTC runner. After explicit
live authorization it validates four MCP identities and resets mutable runtime
state before each configuration, including baseline. `--isolated-db` remains an
operator assertion; `--expected-database` identifies the approved reset target. The model is configured in
`ai-services/.env`. See the [eval runbook](ai-services/eval_harness/README.md) for
offline checks, paired runs, safe artifacts and failed/invalid status. See [memory policy](docs/memory-policy.md).

For a new comparison, write both traces into a new directory under
`eval/runs/` and audit each with `ai-services/.venv/bin/python -m
eval.trace_audit trace --scenarios ... --trace ... --config full` (or
`baseline_no_memory`). The auditor checks BTC JSON Schema and exact turn
coverage; its `manifest` and `pair` commands record nonsecret run hashes and
reject mismatched model, seed or source settings. The older files directly in
`eval/runs/` are historical and do not describe the current working tree.
Use `eval.score_pair` to invoke BTC's reference evaluator and bind the score
report to the exact trace hashes before creating manifests. See the
[evaluation runbook](docs/eval-runbook.md) for the reset and audit sequence.

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
