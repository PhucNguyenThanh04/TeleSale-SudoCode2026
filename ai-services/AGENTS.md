# Repository Guidelines

## Project Structure & Module Organization

`app/` contains the Python service: `api/` exposes HTTP routes, `agent/` builds and runs the chat graph, and `mcp_servers/` hosts catalog, order, and memory tools. Keep business rules in MCP services and shared modules; keep tool handlers thin. SQL changes belong in numbered `migrations/` files. Unit and contract tests live in `test/`; benchmark scenarios, validators, and results live in `eval_harness/`. Use `README.md` for runtime architecture and setup details.

## Build, Test, and Development Commands

Run commands from `ai-services/` unless stated otherwise:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m app
.venv/bin/python -m app.mcp_servers.run
.venv/bin/python -m unittest discover -s test -v
.venv/bin/python -m pytest test eval_harness/test_eval_harness.py
```

The requirements file installs runtime and test dependencies. `python -m app` starts the API; the MCP launcher starts the three local tool services and requires configured PostgreSQL roles. The final two commands run the regression suites. From the repository root, use `docker compose --env-file .env --env-file ai-services/.env up -d --build mcp-catalog mcp-order mcp-memory` after loading data and applying migrations in the order documented in `README.md`.

## Coding Style & Naming Conventions

Use four spaces in Python, `snake_case` for modules, functions, and variables, and `PascalCase` for classes. Follow the surrounding type hints and async patterns. Name tests `test_*.py` and migrations `NNNN_description.sql`. No repository-wide formatter or linter is configured; keep imports and formatting consistent with adjacent files.

## Testing Guidelines

Most tests use `unittest`, including `IsolatedAsyncioTestCase`; some use `pytest` parametrization. Add focused regression tests for changed behavior, especially memory identity, policy grounding, and MCP contracts. There is no stated coverage percentage. Database and HTTP integration tests require dedicated environment variables and should target isolated test services.

## Commit & Pull Request Guidelines

Recent commits use short imperative subjects, sometimes with a type and scope such as `feat(speech): ...` or `fix: ...`. Keep each commit focused. In pull requests, describe the behavior change, affected services or migrations, test commands and results, and any configuration changes; link the relevant issue when one exists. Include screenshots only for visible UI changes.

## Security & Configuration

Copy `.env.example` to `.env` and supply local credentials. Never commit `.env`, API keys, database passwords, or customer data. Keep prompts, traces, and logs free of raw customer PII; see `README.md` for tracing and credential settings.
