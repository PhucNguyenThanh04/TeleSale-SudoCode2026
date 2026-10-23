# Reproducible M1 text harness evaluation

Run from the repository root with Python 3.12. BTC `reference_eval.py` is the only scorer. The root `eval/run_eval.py` replays real text turns through the production harness and writes BTC trace JSONL plus `.stages.json`, `.events.json`, and `.report.json` sidecars. The stages file contains keys/counts/statuses only; the trace's handoff brief is a masked projection, while the actual tool receives the original brief and validates it against the BTC schema.

## Preconditions

1. Prepare an eval-only PostgreSQL seed named `telesale_eval_seed` using the BTC dataloader and **all** AI migrations through `0009`. It must contain BTC catalog/policy/CRM seed and role grants, and no prior runtime turns, orders, callbacks, handoffs or consumed once-per-customer promotions. Hash a dump of this seed (`sha256sum`) and keep the digest as `seed_digest`. Never clone the demo/production `telesale` database to fabricate a clean seed.
2. Create `telesale_eval_full` and `telesale_eval_baseline` from that same quiescent seed. For a local PostgreSQL administrator using a configured `.pgpass` or `PGSERVICE` (credentials stay out of command history):

   ```bash
   createdb -h localhost -U "$EVAL_DB_ADMIN_USER" -T telesale_eval_seed telesale_eval_full
   createdb -h localhost -U "$EVAL_DB_ADMIN_USER" -T telesale_eval_seed telesale_eval_baseline
   ```

   Use fresh names or deliberately reset **only** these eval-named DBs. Verify both have the same seed digest, migration level and permissions before running. Do not point a running demo service at them.
3. For the first run, point all three MCP servers at `telesale_eval_full`; for the second, restart all three against `telesale_eval_baseline`. Use the same role-specific credentials, code, config, model and hardware. The runner probes all three MCP DB identities before the first turn and rejects non-eval names or mixed endpoints. `--isolated-db` is an assertion, not a reset operation. Set `EVAL_DB_ALLOWLIST=telesale_eval_full` or `telesale_eval_baseline` for each run.
4. Record the exact model ID, temperature/max tokens and other nonsecret settings, guardrail switches, tool mode, UTC start and CPU/GPU/RAM. Hash the source snapshot with `eval.trace_audit.source_snapshot_digest(Path.cwd())`. The source digest includes dirty and untracked implementation files; do not edit source between runs.

## Replay and score

Choose a new timestamped `eval/runs/<timestamp>/` directory and do not overwrite older runs. Set `RUN_DIR` to that directory. The three MCP servers must already point to the specified eval DB when each command runs.

```bash
mkdir -p "$RUN_DIR"
EVAL_DB_ALLOWLIST=telesale_eval_full ai-services/.venv/bin/python run_eval.py \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --config full --out "$RUN_DIR/full.jsonl" --isolated-db
ai-services/.venv/bin/python -m eval.trace_audit trace \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace "$RUN_DIR/full.jsonl" --config full
```

After switching/restarting **all three** MCP servers to the untouched baseline clone:

```bash
EVAL_DB_ALLOWLIST=telesale_eval_baseline ai-services/.venv/bin/python run_eval.py \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --config baseline_no_memory --out "$RUN_DIR/baseline_no_memory.jsonl" --isolated-db
ai-services/.venv/bin/python -m eval.trace_audit trace \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace "$RUN_DIR/baseline_no_memory.jsonl" --config baseline_no_memory
ai-services/.venv/bin/python -m eval.score_pair \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --full "$RUN_DIR/full.jsonl" --baseline "$RUN_DIR/baseline_no_memory.jsonl" \
  --out "$RUN_DIR/btc-score.json"
```

`eval.score_pair` invokes BTC's unmodified `reference_eval.py`, verifies that the
trace bytes did not change during scoring, and writes `btc-score.inputs.json`.
The manifest builder refuses a score lacking this provenance or referencing
different trace/scorer bytes.

Both traces must have all 39 public turns, one row per scenario/call/turn, and no schema errors. The runner's `.report.json` files include the probed DB identity. For each config, create a nonsecret metadata JSON containing `config`, `source_digest`, `seed_id`, `seed_digest`, `model_id`, `model_params`, `tool_mode`, `guardrails`, `database_identity` (copy exactly from the runner report), `hardware`, and `started_at_utc`. The metadata must not contain an API key, token, DSN, password, raw phone or address. Then:

```bash
ai-services/.venv/bin/python -m eval.trace_audit manifest \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace "$RUN_DIR/full.jsonl" --score "$RUN_DIR/btc-score.json" \
  --metadata "$RUN_DIR/full-metadata.json" --out "$RUN_DIR/full-manifest.json"
ai-services/.venv/bin/python -m eval.trace_audit manifest \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace "$RUN_DIR/baseline_no_memory.jsonl" --score "$RUN_DIR/btc-score.json" \
  --metadata "$RUN_DIR/baseline-metadata.json" --out "$RUN_DIR/baseline-manifest.json"
ai-services/.venv/bin/python -m eval.trace_audit pair \
  --full "$RUN_DIR/full-manifest.json" --baseline "$RUN_DIR/baseline-manifest.json"
ai-services/.venv/bin/python -m eval.failure_matrix \
  --scenarios ../BTC-Data-Vong1-TEAMS/test_set/public_sample \
  --trace "$RUN_DIR/full.jsonl" --stages "$RUN_DIR/full.stages.json" \
  --score "$RUN_DIR/btc-score.json" --out "$RUN_DIR/failure-matrix.json"
```

Read each failed call's agent text, tool args/results, memory writes and stage sidecar together. Spot-check the extracted `questions`, `claims` and `facts_used`; mark extraction errors separately from agent errors. The matrix reports only observed failure stages and explicitly lists stages that remain uncertain. Keep RQR, CCR, TSR, HR, guardrail violations and per-call evidence in the findings note. Seven public scenarios have 39 turns, so their latency is descriptive; BTC p95 compliance needs at least 100 turns, three warm-up turns excluded, measured at the backend/harness boundary.

## Environment check on 2026-10-22

The current `ai-services/.env` points its database setting at `telesale`, and no listeners were found on the configured MCP ports 8011–8013. `docker compose ps` failed because this user cannot access `/var/run/docker.sock`. No isolated eval seed, paired MCP endpoints or matching live `gemma4:31b` trace was available to verify. Therefore the historical `eval/runs/*.jsonl` and `report.json` must stay labeled historical; no new full/baseline score or Task Success repair can be selected from them.
