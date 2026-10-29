# Text-turn harness

Copy `.env.example` to `.env` and set `LLM_API_KEY` to an Ollama Cloud API key.
`LLM_MODEL=gemma4:31b` and `OLLAMA_BASE_URL=https://ollama.com` configure
direct cloud access through `ChatOllama`. `LLM_TEMPERATURE` and
`LLM_MAX_TOKENS` control sampling and the response length limit. The settings
are loaded from this directory regardless of
the current working directory; process environment variables take precedence.
The API key is not included in `.env.example` and must not be committed.
Run `python -m app` from `ai-services/` to use `HOST`, `PORT` and `LOG_LEVEL`
from `.env`. Environment variables set by the shell override the file.

## Runtime settings

All settings below are validated in `app/configs.py`. Copy the grouped
defaults from `.env.example` into `ai-services/.env` and change only the
settings needed for your run.

| Group | Variables | Effect |
|---|---|---|
| API | `APP_NAME`, `APP_ENV`, `DEBUG`, `HOST`, `PORT`, `LOG_LEVEL`, `TIMEZONE` | API identity, environment label, debug flag, bind address, logging, callback timezone |
| Ollama Cloud | `LLM_API_KEY`, `LLM_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_SECONDS`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_SEED` | Model, authentication, timeout, response budget and reproducible sampling |
| Harness | `AGENT_KIND`, `FACT_EXTRACTION_MODE`, `AGENT_MAX_TOOL_CALLS`, `AGENT_PROMPT_HISTORY_TURNS`, `AGENT_GUARDRAILS_ENABLED` | Select `deep` or `react`, set tool and context limits, and toggle answer checks; old extraction is only for comparison mode |
| Memory | `MEMORY_MAX_EPISODES`, `LANGMEM_MODE`, `LANGMEM_MODEL` | Customer-scoped LangMem knowledge and a separate distillation model; `enabled` is the default |
| Langfuse | `LANGFUSE_ENABLED`, `LANGFUSE_CAPTURE_CONTENT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Optional one trace per chat turn, grouped by session; content capture is opt-in for development/test |
| Internal transport | `AI_INTERNAL_TOKEN`, `MCP_INTERNAL_TOKEN`, `MCP_CATALOG_URL`, `MCP_ORDER_URL`, `MCP_MEMORY_URL` | Backend-to-AI and AI-to-MCP authentication and endpoints |
| MCP process | `MCP_HOST`, `MCP_CATALOG_PORT`, `MCP_ORDER_PORT`, `MCP_MEMORY_PORT`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `MEMORY_DB_POOL_MIN_SIZE`, `MEMORY_DB_POOL_MAX_SIZE` | HTTP listener and PostgreSQL pools |
| MCP database | `DATABASE_URL` **or** `MCP_DB_HOST`, `MCP_DB_PORT`, `MCP_DB_NAME`, `MCP_DB_USER`, `MCP_DB_PASSWORD_FILE`; `MCP_INTERNAL_TOKEN_FILE` | Local connection or Compose role-specific secret files |

`DATABASE_URL` is held as a secret by the settings object.
Compose supplies each MCP process with its own DB role and secret file. Run
Compose with **both** env files so the nonsecret MCP ports and pool settings
come from `ai-services/.env` without injecting the Ollama key into MCP
containers. A plain `docker compose up` uses default MCP tuning instead.
When changing an MCP port, update its `MCP_*_URL` in the same file. `MCP_HOST`
is overridden to `0.0.0.0` inside Compose so the container can accept traffic;
it remains loopback-bound on the host. The legacy `BACKEND_URL` and
`BACKEND_INTERNAL_TOKEN` entries in older local `.env` files are not used by
this AI service; its inbound credential is `AI_INTERNAL_TOKEN`.

BTC's promotion rules, COD limit, exchange fees, holidays and scenario
reference date are source-of-truth rules, not tunable settings. Keep them in
the BTC-compatible business logic and scenario input.

The API invokes an outer one-turn LangGraph. It resolves identity through
mcp-catalog, reads mcp-memory, and runs the selected Deep or ReAct agent for
business tools. In the default `enabled` mode, the agent commits a masked turn
and successful order links to `ai_memory`, then a separate worker uses LangMem
to extract profile facts and call episodes. The worker checks each proposal
against committed customer text or a successful business tool before writing
it to the customer namespace in `langmem_store`. The old synchronous fact
proposal tool and schema are hidden from the model in this mode. `off` and
`shadow` remain available only for controlled comparisons.
When `AGENT_GUARDRAILS_ENABLED=false`, the outer graph returns the selected agent's
draft reply without `check_answer` or catalog fallback. PII masking, MCP tool
preconditions, identity checks, and memory evidence validation still apply.
Missing MCP URLs or token are a configuration error at runtime startup. Chat response caching remains process-local; writes through the MCP
services use PostgreSQL operation keys. A PostgreSQL LangGraph checkpointer is
not connected yet.

Policy questions use `policy.search` on mcp-catalog. PostgreSQL filters
`btc_source.policy_chunks` for public access and the applicable call or verified
order date before ranking. By default this uses the existing lexical baseline.
With `POLICY_RAG_ENABLED=true`, the catalog MCP combines lexical ranking with
Qdrant dense retrieval, validates candidate IDs and source hashes against the
dated PostgreSQL rows, and falls back to lexical ranking on dense errors. The
retrieval implementation lives in `app/rag/policy_retrieval.py`; catalog keeps
the MCP tool, business service boundary and PostgreSQL repository. The
tool returns `retrieval_status`; candidate IDs and scores are in local catalog
logs, without query text or policy bodies. Build the policy index with
`python -m dataloader_offline --data-dir <BTC directory>` using the same
`EMBEDDING_MODEL` in the loader and catalog process. Install
`requirements-rag.txt` in the catalog environment; Compose installs it when
`POLICY_RAG_ENABLED=true` is set during build. Rebuild `mcp-catalog` after
changing that flag. The first query loads the local model and may be slow.
The answer
guard checks that a policy lookup succeeded and rejects day counts absent from
the returned chunks; it is not a general semantic proof of every policy claim.

### Langfuse Cloud tracing

Create a project in [Langfuse Cloud](https://cloud.langfuse.com/), copy its
project public and secret API keys into `ai-services/.env`, and set
`LANGFUSE_BASE_URL` to that project's regional endpoint. Set
`LANGFUSE_ENABLED=true`, then restart the AI service. The keys are read by the
AI process only. The application starts without Langfuse when the flag is
`false`; enabling it without all three connection settings fails startup.

Each uncached `chat()` turn creates a `chat-turn` trace and groups turns by
`session_id`. The LangGraph callback records the outer graph, selected nested agent,
model generations, and tool steps. Trace names, channel, input mode, handoff
status, tool and memory write counts, model name and token usage remain visible.
By default, the export mask removes prompts, responses, customer identifiers,
tool arguments/results and other arbitrary metadata before transfer. For
synthetic development data, set `LANGFUSE_CAPTURE_CONTENT=true` to export the
full chat request, answer, model I/O and tool payloads; known credential
attributes and configured secret values remain redacted. This flag is rejected
when `APP_ENV=production`. Previously exported masked traces stay masked.
Spans carrying OpenTelemetry events or status descriptions are dropped because
those fields cannot be edited by the SDK export mask.
The HTTP service flushes on shutdown. Do not flush after each API request, since that adds
latency. With credentials configured, check the Langfuse Traces and Sessions
views after one real turn. No Cloud authentication or remote trace was verified
by the repository's credential-free tests.

The agent code is grouped by responsibility under `app/agent/`: `chat.py` is
the public entrypoint, `factory.py` assembles the runtime, `graph.py` wires
the turn, `implementations/` contains
the selectable Deep and ReAct agents plus shared business tools, `harness/` contains runtime, nodes and tool policy,
`memory/` contains fact proposals and the MCP memory adapter, `guardrails/`
contains answer and evidence checks, and `mcp/gateway.py` routes business
tools to the three servers in `app/mcp_servers/`. DeepSeek is a possible model
choice through `LLM_MODEL` if supported by the configured endpoint, not a
separate agent architecture. No fourth MCP server is needed for policy RAG.

```text
app/agent/
  chat.py                 # public chat() entrypoint
  factory.py              # assemble the active implementation and adapters
  graph.py                # outer LangGraph wiring
  implementations/        # selectable Deep/ReAct agents and shared business tools
  harness/                # runtime, graph nodes, state, tool policy
  memory/                 # candidate validation and MCP memory adapter
  guardrails/             # answer and fact evidence checks
  mcp/                    # client gateway for the three MCP servers
app/mcp_servers/          # catalog, order, memory, shared infrastructure
```

## Structured MCP tools

Start PostgreSQL with `docker compose up -d postgres redis`, then import the
BTC release with `dataloader_offline`. Apply the additive
runtime SQL migrations in order: `backend/migrations/0001_chat.sql`,
`backend/migrations/0002_tools.sql`, `backend/migrations/0003_channel_identity.sql`,
`backend/migrations/0004_erasure_suppressions.sql`,
then `ai-services/migrations/0001_memory.sql`,
`ai-services/migrations/0002_operations.sql`,
`ai-services/migrations/0003_memory_provenance.sql`, and
`ai-services/migrations/0004_pending_facts.sql`, and
`ai-services/migrations/0005_memory_evidence_quote.sql`, then
`ai-services/migrations/0006_episode_identity_boundary.sql`,
`ai-services/migrations/0007_erasure_requests.sql`, and
`ai-services/migrations/0008_scoped_facts.sql`, then
`ai-services/migrations/0009_structured_episodes.sql`,
`ai-services/migrations/0010_langmem_distillation_jobs.sql`, and
`ai-services/migrations/0011_langmem_store.sql`, and
`ai-services/migrations/0012_langmem_accepted_writes.sql`, and
`ai-services/migrations/0013_langmem_job_proposals.sql`. Apply them before starting
`mcp-db-roles`. Use the same PostgreSQL database
for the backend and all three MCP servers. Set matching `AI_INTERNAL_TOKEN`
values in `backend/.env` and `ai-services/.env`, and a separate
`MCP_INTERNAL_TOKEN` in `ai-services/.env`. The values in `.env.example` are
placeholders, not working credentials.

After importing BTC data and applying the migrations, create four ignored
secret files under `secrets/`: `mcp_catalog_password`, `mcp_order_password`,
`mcp_memory_password` (hex strings) and `mcp_internal_token` (the same value as
`MCP_INTERNAL_TOKEN` in `ai-services/.env`). The repository's existing
`secrets/postgres_password` remains the PostgreSQL admin password. Then run:

```bash
# From the repository root:
docker compose --env-file .env --env-file ai-services/.env up -d --build mcp-catalog mcp-order mcp-memory
# In another terminal, from ai-services/:
python -m app
```

For a local run without the three MCP Compose containers, start all three
MCP processes in one terminal with `python -m app.mcp_servers.run` from
`ai-services/`. The launcher uses `DATABASE_URL` to locate PostgreSQL, then
connects each child with its own `mcp_catalog`, `mcp_order` or `mcp_memory`
role and the corresponding files under `../secrets/`. Provision those roles
first. Stop the launcher with Ctrl+C. You can then call
`app.agent.chat.chat(ChatRequest)` from another Python process; the AI HTTP
server is not required for that call.

`mcp-memory` owns `memory.read` and `memory.write` in PostgreSQL. `mcp-catalog`
exposes `crm.get_customer`, `catalog.search`, `inventory.check`,
`pricing.get_quote`, `policy.search`; `mcp-order`
exposes `order.create`, `order.update`, `order.status`, `schedule.callback`,
`handoff.transfer`. Each MCP has its own PostgreSQL connection pool and role;
catalog reads `btc_source`, order writes commerce tables in `app_runtime`, and
memory writes operational turns, jobs and erasure barriers to `ai_memory`,
and long-term facts and episodes to `langmem_store`. All connect to `postgres:5432` on the Compose
network. The one-shot `mcp-db-roles` service provisions roles on the existing
database volume. The MCP ports are published only on host loopback and require
the MCP bearer token. The backend business tool HTTP route is no longer mounted.

When `LANGMEM_MODE=enabled`, each identified committed turn creates one durable
`ai_memory.langmem_distillation_jobs` row. Compose starts the worker with
`mcp-memory`; locally run `python -m app.mcp_servers.mcp_memory.distiller_worker` under the
`mcp_memory` database role and model credentials. The worker leases jobs in
session order, retries up to five times, and logs only error codes. A model
timeout never rolls back the already committed customer turn. If the store is
unavailable, customer memory reads fail closed instead of reading stale legacy facts.
Apply `migrations/0010_langmem_distillation_jobs.sql` and
`migrations/0011_langmem_store.sql`, `0012_langmem_accepted_writes.sql`, and
`0013_langmem_job_proposals.sql` after `0009`. Then, once with an admin
`DATABASE_URL`, run `python -m scripts.setup_langmem_store` from `ai-services/`.
This invokes `AsyncPostgresStore.setup()` with `langmem_store` as the fixed
search path; LangGraph's concurrent index DDL must run outside a wrapping
transaction. Re-run `scripts/provision_mcp_roles.sh` after setup to grant the
`mcp_memory` role access to the new store tables and job sequence. Neither the
API nor the worker runs store DDL at startup. V1 has no vector index.
For an existing database, run `python -m scripts.backfill_langmem_store` once
after store setup. It copies active facts with source turn and date plus
existing episodes, skips records that lack provenance, and preserves newer
LangMem facts.
For a verified erasure request already registered in `ai_memory.erasure_requests`,
run `python -m scripts.execute_memory_erasure REQUEST_UUID` with the memory
role. It removes operational rows, queued jobs and the customer's LangGraph
namespace under the per-customer barrier. A store outage leaves the
request `partial`; retry the same UUID after recovery.
Use the BTC reference evaluator on a separately seeded database before a demo.
The harness waits for jobs and attributes only accepted writes to their source
turns in the official trace. See `eval_harness/README.md` for the runbook.

The code for each server lives in `app/mcp_servers/mcp_catalog`, `app/mcp_servers/mcp_order` or
`app/mcp_servers/mcp_memory`: `tools/` validates MCP calls, `services/` holds business
rules, and `repos/` owns SQL. Shared pure pricing/stock rules, masking and
connection setup live in `app/mcp_servers/mcp_shared`. Order and memory write services use
an operation key derived from the chat message to return the same stored result
when a write is retried.

Each completed chat turn is written to `ai_memory.turns`; accepted long-term
knowledge is written to the LangGraph store by the worker. A failed turn write fails the chat
request so callers can retry with the same session and message IDs. Use an
isolated eval database and reset mutable business tables between configurations.

`app.infarstructure.llm.build_llm(get_settings())` constructs the LangChain
chat model used by the graph. Model and tool gateway can be injected in tests.

From `ai-services/`, run `.venv/bin/python -m app`. Use the AI service virtual
environment even if the shell is currently activated in the backend virtual
environment. The HTTP API and `app.agent.chat.chat()` use the same runtime and
require the three MCP servers and their migrated PostgreSQL database.
The OpenAPI document is at `/openapi.json`; interactive docs are at `/docs`.

`app.agent.chat.chat(ChatRequest)` can be called directly from Python. It accepts
`session_id=None`, creates a UUID and returns it with the answer. Keep the
`AgentHarnessRuntime` instance shared within one process; process-local locks and
idempotency do not span multiple workers.

`POST /v1/chat/turns` uses the same function and accepts a request with the
`X-AI-Internal-Token` header:

```json
{
  "client_msg_id": "11111111-1111-4111-8111-111111111111",
  "session_id": null,
  "channel": "chat_fanpage",
  "channel_identity": "fb.hạnh.274",
  "on": "2026-10-15",
  "text": "shop oi ...",
  "input_mode": "chat_teencode"
}
```

The backend creates `session_id` before calling this endpoint. A frontend's
first-turn `session_id: null` is not valid here. The response echoes both IDs,
returns `agent_text`, handoff fields, and an optional `call_brief` on a returning
customer's new session. The brief includes refreshed quote and stock warnings
when an existing profile has an advised SKU. New chat turns may create profile
facts from validated model proposals grounded in customer text or verified
tool results.

## Theo dõi một lượt chat

Đặt `LOG_LEVEL=INFO` trong `ai-services/.env` rồi chạy `python -m app`.
Outer graph ghi log các bước nhận yêu cầu, xác định khách, đọc ngữ cảnh,
chạy agent đã chọn, kiểm tra câu trả lời và ghi bộ nhớ. Agent tự lặp giữa
model và tool. Harness ghi tên tool, kết quả, thời gian và số fact đã ghi.
Nếu kiểm tra câu trả lời không đạt, harness chỉ trả câu trả lời có thể xác minh
từ catalog hoặc câu fallback. Giá bán vẫn cần `pricing.get_quote` cùng ngày.

Ví dụ: `Gọi công cụ: kết quả công cụ | công cụ: inventory.check, kết quả: thành công`.
Với `LOG_LEVEL=INFO`, log có tham số đã gửi cho tool và kết quả nghiệp vụ đã
lọc PII. Ba MCP process cũng ghi từng tên tool, tham số nhận vào,
kết quả trả ra và thời gian thực thi. Chạy qua `python -m app.mcp_servers.run` thì
xem cùng terminal; với Compose, dùng `docker compose logs -f mcp-catalog mcp-order mcp-memory`.
Log chỉ hiện các trường được phép; thông tin định danh, số điện thoại,
địa chỉ và trường tự do nhạy cảm được lược bỏ hoặc che. Mỗi payload tối đa 3.000
ký tự. Kết quả CRM chỉ hiện `found`, `ambiguous` và số đơn/phiên; không hiện hồ sơ.
Log không hiện UUID của phiên hoặc message; khi nhiều lượt chat chạy đồng thời,
các dòng của chúng có thể xen kẽ nhau.
Log không ghi prompt hoặc request gốc. Kết quả memory chỉ hiện số lượt, tên fact
và thao tác, không hiện nội dung hội thoại hay giá trị fact. Để xem trace đầy đủ,
dùng eval trong môi trường kiểm soát.

Run contract checks from `ai-services/` with
`.venv/bin/python -m unittest discover -s test -v` after installing `requirements.txt`.
For an isolated smoke test without changing the active Python environment:

```bash
uv run --no-project --with 'langgraph>=1.2.12,<1.3' \
  --with 'deepagents>=0.7.23,<0.8' \
  --with 'langchain-ollama>=1.1,<2' --with 'fastapi>=0.141.1,<0.142' \
  --with 'httpx>=0.28.1,<0.29' --with 'pydantic-settings>=2.10,<3' \
  --with 'fastmcp>=4.0.10,<4.1' --with 'asyncpg>=0.30,<1' \
  python -m unittest discover -s test -v
```

### Memory demo and manual preflight

Before starting the existing MCP services, apply migrations through
`0009_structured_episodes.sql` to their PostgreSQL database, then rerun role provisioning.
A table created after provisioning does not inherit the earlier table grants.
With the administrative `psql` connection (never put passwords in the command), verify:

```sql
SELECT to_regclass('ai_memory.pending_facts');
SELECT to_regclass('ai_memory.erasure_requests');
SELECT has_table_privilege('mcp_memory', 'ai_memory.pending_facts',
                          'SELECT,INSERT,UPDATE,DELETE');
SELECT has_table_privilege('mcp_memory', 'ai_memory.erasure_requests',
                          'SELECT,INSERT,UPDATE,DELETE');
```

If either table lacks grants, rerun `scripts/provision_mcp_roles.sh` with the
documented administrative connection. For the memory tables alone, the
administrator can run:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_memory.pending_facts TO mcp_memory;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_memory.erasure_requests TO mcp_memory;
```

These are deployment operations; chat continues to access PostgreSQL through MCP.
The servers do not automatically apply migrations or check the full schema on startup.

From `ai-services/`, edit the `ChatRequest` in `app/agent/chat.py`, then run one turn:

```bash
.venv/bin/python -m app.agent.chat
```

The script prints the full response, including `session_id`. To continue a session,
reuse that UUID in the request and set a new `client_msg_id`. Set `on` to the call's
business date. Without `channel_identity`, the conversation is anonymous and
customer facts are not written to a long-term profile.

Short-term history is read from MCP for each turn, including after process restart.
`AGENT_PROMPT_HISTORY_TURNS` accepts 1–12 (default 6), matching the existing MCP read
limit. Long-term profile facts are customer-scoped. Previous episodes are deduplicated
by session, preferring memory over CRM, then limited by `MEMORY_MAX_EPISODES`.
Anonymous turns remain available during the unverified session. After identity
verification, prior anonymous turns are excluded from the model history and the
customer's episode; they are not converted into profile facts. Migration 0006
retracts legacy claims from anonymous turns and rebuilds mixed episodes from
attributed turns, including facts whose anonymous commit lacked an operation key
but whose claim result was logged. The old app always logged claim operations;
direct MCP clients that omitted the claim operation key cannot be reconstructed
from this migration and require a separate audit or quarantine of their legacy
memory. If a claimed fact superseded an earlier fact, migration does not revive
the earlier value automatically; confirm it with the customer before storing it
again. A failed memory read skips
the model and returns a neutral outage message; failed commits fail the request.

Run regression tests with `python -m unittest discover -s test -v`. HTTP memory tests
are opt-in: set `MEMORY_TEST_URL` and `MEMORY_TEST_TOKEN` to a dedicated eval MCP memory
instance, then run `python -m unittest discover -s test -p test_memory_http.py -v`.
They write synthetic namespaced data and must not target a production database.
