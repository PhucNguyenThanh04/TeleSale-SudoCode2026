# TeleSale SudoCode 2026

The first text harness runs through `backend` → `ai-services` → three MCP
servers. Import BTC data with `dataloader_offline` and apply the SQL migrations
listed in [ai-services/README.md](ai-services/README.md). Configure the private
backend/MCP tokens and URLs in ignored `.env` files. Start the three MCP
containers with Compose after importing data and applying migrations; run the
backend and AI API on the host. The backend chat contract is documented in
[backend/CHAT_API_CONTRACT.md](backend/CHAT_API_CONTRACT.md).

The AI service exposes `app.agent.chat.chat(ChatRequest)` for one Python chat turn;
`session_id` may be `null` and is returned for later turns. The HTTP route uses
the same function. Both use MCP HTTP; run the AI API with one worker while
its session lock and duplicate-response cache are process-local. From the repo
root, with an **isolated evaluation database/backend** so mutable orders and
one-time promotions do not affect demo data, run:

```bash
python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config full --out eval/runs/full.jsonl --isolated-db
python run_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --config baseline_no_memory --out eval/runs/baseline.jsonl --isolated-db
python ../BTC-Data-Vong1-TEAMS/eval/reference_eval.py --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample --trace eval/runs/full.jsonl --baseline eval/runs/baseline.jsonl
```

The runner emits real harness turns. Restore the same seed and clear mutable
runtime state before baseline. `--isolated-db` is an operator assertion; it
does not reset or isolate PostgreSQL itself. The model is configured in
`ai-services/.env`. See [memory policy](docs/memory-policy.md).
