# Repository Guidelines

## Architecture Rules

- `app/` is the Python service: `api/` (HTTP), `agent/` (chat graph), `mcp_servers/` (catalog, order, memory tools).
- Keep business rules in MCP services and shared modules; keep tool handlers thin.
- SQL changes go in numbered migrations: `migrations/NNNN_description.sql`.
- `eval_harness/` holds benchmark scenarios, validators, adapters and results. See `README.md` for runtime setup.

## Working Style (read first)

- Work directly in this repository. Do NOT create git worktrees or copy the project.
- Do exactly what was asked, nothing more. If you notice related work (dashboards, extra metrics, refactors), list it at the end and ask; do not build it.
- Small tasks (bug fix, 1-3 files): no spec, no plan, no sub-agents. Edit, test, show the diff.
- Larger features: propose a short plan (max ~10 lines) and wait for approval before coding.
- Ask before any costly or hard-to-undo action: resetting databases, killing processes, deleting directories, installing dependencies.
- Do not commit or `git add` unless asked.

## Commands

Run from `ai-services/`:

```bash
.venv/bin/python -m app                      # start API
.venv/bin/python -m app.mcp_servers.run      # start MCP tool services (needs PostgreSQL roles)
.venv/bin/python -m pytest path/to/test_file.py::test_name   # one test
.venv/bin/python -m pytest test eval_harness/test_eval_harness.py   # full regression
.venv/bin/python -m eval_harness.run_official --help         # official eval options
```

## Testing Rules

- While iterating, run only the tests for the file you changed.
- Run the full suite once, right before reporting done.
- Add a focused regression test for every behavior change, especially memory identity, policy grounding, MCP contracts, and trace/PII handling.
- Style: four spaces, `snake_case` functions/modules, `PascalCase` classes, `test_*.py` files. Match adjacent files; no repo-wide formatter.

## Eval Harness Rules

- Running the real eval (19 scenarios) calls the live model and costs quota. Never start it without explicit permission. Prefer replaying existing traces offline.
- Do not edit BTC scenarios or validators. Fix the adapter or the agent instead.
- Never publish or report a score from an incomplete or interrupted run.

## PII and Trace Rules

- Mask PII by field path (e.g. `args.customer_name`, `args.customer_phone`), never by key name alone.
- Never mask tool names, call ids, or any field the scorer compares (`args_match`).
- Any change to `reference_adapter.py` needs a test asserting every `tool_call["name"]` survives unchanged.
- Never commit `.env`, API keys, DB passwords, or raw customer data. Keep prompts, traces and logs free of raw PII.

## Commits and PRs

Short imperative subjects, optional type/scope (`fix:`, `feat(speech):`). One focused change per commit. PR descriptions list behavior change, affected services/migrations, test commands with results, and config changes.
