# Text-turn harness

Copy `.env.example` to `.env` and set `LLM_API_KEY` to your API key.
`LLM_MODEL=gpt-6-luna` and `LLM_BASE_URL=https://api.openai.com/v1` configure
OpenAI access through `ChatOpenAI`. For a compatible provider, set its base URL
(including `/v1` when required) and supported model ID. GPT-6 Luna uses Chat
Completions with `reasoning_effort=none` to support business tool calls.
`LLM_TEMPERATURE` and
`LLM_MAX_TOKENS` control sampling and the response length limit. The settings
are loaded from this directory regardless of
the current working directory; process environment variables take precedence.
The API key is not included in `.env.example` and must not be committed.
Run `python -m app` from `ai-services/` to use `HOST`, `PORT` and `LOG_LEVEL`
from `.env`. Environment variables set by the shell override the file.

### Gemma 4 on Ollama Cloud

Use the direct Cloud endpoint; no local Ollama server or model download is needed:

```dotenv
LLM_BASE_URL=https://ollama.com/v1
LLM_MODEL=gemma4:31b
LLM_API_KEY=replace-with-ollama-cloud-api-key
LANGMEM_MODEL=
```

Check the current model IDs at <https://ollama.com/api/tags>. At the time of this
change, Cloud lists `gemma4:31b`, not `gemma4:12b`; a local library tag does not
establish Cloud availability. Do not reuse an OpenAI key for this endpoint.
The client sends `reasoning_effort=none` for Gemma 4 on `ollama.com`, which Ollama
maps to disabled thinking for models that support it. See the
[compatibility documentation](https://docs.ollama.com/api/openai-compatibility).
Other compatible providers do not receive this Gemma-specific setting.

An empty `LANGMEM_MODEL` uses the same model for the memory worker. Restart the
host AI process after changing `.env`, and restart the `langmem-worker` container
if it is running (`docker compose restart langmem-worker` from the repo root).
The backend and speech services do not need model-specific changes. Offline
request/tool tests do not verify Cloud credentials, model availability or latency;
no live model evaluation is performed by this migration.

### Switch between the API and a local model

Keep the existing `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` and `LANGMEM_MODEL`
in `ai-services/.env`. Add:

```dotenv
LLM_BACKEND=local
LOCAL_LLM_BASE_URL=http://localhost:8081/v1
LOCAL_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ
LOCAL_LLM_API_KEY=local-vllm
```

`local-vllm` is a client placeholder for an unauthenticated local server; use its
real key if authentication is enabled. Set `LLM_BACKEND=api` to switch back.
Omitting the selector keeps the existing API behavior. Local mode resolves the
active connection before building any models, and uses the local model for both
the agent and LangMem, ignoring the API profile's `LANGMEM_MODEL`. Sampling,
and token limits continue to use the common `LLM_*` settings. Local requests use
`LOCAL_LLM_TIMEOUT_SECONDS` (default 120 seconds) to allow for GPU queueing.

Set `LOCAL_LLM_CONTEXT_WINDOW=8192` to match vLLM's `--max-model-len` (change both
if using another context size). For nonstreaming requests carrying tools, a
`finish_reason=length` response is discarded and retried once with a larger
output budget, capped at 4096 tokens and the remaining context reported by the
server. Both attempts count toward token usage. A second truncated response,
missing usage or insufficient context raises `local_tool_output_truncated`;
partial tool output is never inserted into history. HTTP 400, normal responses,
plain text requests, streaming and the API backend do not use this retry policy.
Both local agent and LangMem tool bindings set `strict: true` on the initial
request, including already formatted dictionary tools, while preserving tool
choice and normal multi-call behavior. The local LangMem episode schema restricts
topic `consultation` to null instead of exposing the canonical consultation/offer
schemas to the model. Evidence, facts, topics and open/resolved items remain
typed and admitted as before; the worker derives consultation deterministically.
Cloud extraction continues to use its existing schema.
Local nonstreaming tool requests also detect Hermes `<tool_call>` markup leaked
as plain content and LangChain `invalid_tool_calls`, even with a `stop` finish
reason. Recovery reuses the original messages without the malformed output,
requires a tool call and disables parallel calls, preserving a named tool choice
when specified. Syntax-only failures keep the original output budget. Truncation
and parser recovery share one retry total; malformed or missing tool output on
that retry raises `local_tool_output_invalid` instead of becoming ordinary text.
This does not repair semantic schema validation errors or prompts exceeding the
server's input context limit.

After changing the selector, restart the host AI service and the memory worker.
For the first deployment of this code, rebuild/recreate the worker from the repo
root with `docker compose up -d --build langmem-worker`; later `.env` changes only
need `docker compose restart langmem-worker` plus restarting the host AI process.
The worker connects through `host.docker.internal:8081`, since its `localhost`
belongs to the container. To change this address, set
`LOCAL_LLM_CONTAINER_BASE_URL` in the root `.env` and recreate the worker with
`docker compose up -d langmem-worker`. The model server must listen on an address
reachable from Docker, rather than only host loopback.

The local server must support Chat Completions, SSE streaming, `tools` and
`tool_choice=auto` for the agent. A plain text curl response only verifies basic
chat. Enable the server's automatic tool-choice support and a tool parser
compatible with its model when needed. Offline tests cover request routing,
tool responses and streaming; they do not evaluate this local model's quality.

## Runtime settings

All settings below are validated in `app/configs.py`. Copy the grouped
defaults from `.env.example` into `ai-services/.env` and change only the
settings needed for your run.

| Group | Variables | Effect |
|---|---|---|
| API | `APP_NAME`, `APP_ENV`, `DEBUG`, `HOST`, `PORT`, `LOG_LEVEL`, `TIMEZONE` | API identity, environment label, debug flag, bind address, logging, callback timezone |
| OpenAI-compatible API | `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_SEED` | Model, authentication, timeout, response budget and reproducible sampling |
| LLM backend | `LLM_BACKEND`, `LOCAL_LLM_API_KEY`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_BASE_URL` | Select `api` (default) or `local` without overwriting the saved API profile |
| Harness | `AGENT_KIND`, `AGENT_MAX_TOOL_CALLS`, `AGENT_PROMPT_HISTORY_TURNS`, `AGENT_GUARDRAILS_ENABLED` | Select `deep` or `react`, set tool and context limits, and toggle answer checks |
| Memory | `MEMORY_MAX_EPISODES`, `LANGMEM_MODEL` | Customer-scoped LangMem knowledge and a separate distillation model; LangMem is the only runtime memory path |
| Langfuse | `LANGFUSE_ENABLED`, `LANGFUSE_PROMPTS_ENABLED`, `LANGFUSE_CAPTURE_CONTENT`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Optional tracing and production-labeled prompt management; content capture is opt-in for development/test |
| Internal transport | `AI_INTERNAL_TOKEN`, `MCP_INTERNAL_TOKEN`, `MCP_CATALOG_URL`, `MCP_ORDER_URL`, `MCP_MEMORY_URL` | Backend-to-AI and AI-to-MCP authentication and endpoints |
| MCP process | `MCP_HOST`, `MCP_CATALOG_PORT`, `MCP_ORDER_PORT`, `MCP_MEMORY_PORT`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `MEMORY_DB_POOL_MIN_SIZE`, `MEMORY_DB_POOL_MAX_SIZE` | HTTP listener and PostgreSQL pools |
| MCP database | `DATABASE_URL` **or** `MCP_DB_HOST`, `MCP_DB_PORT`, `MCP_DB_NAME`, `MCP_DB_USER`, `MCP_DB_PASSWORD_FILE`; `MCP_INTERNAL_TOKEN_FILE` | Local connection or Compose role-specific secret files |

`DATABASE_URL` is held as a secret by the settings object.
Compose supplies each MCP process with its own DB role and secret file.
From the repository root, use `docker compose up -d --build` and
`docker compose down`; no shell exports or `--env-file` arguments are needed.
Root `.env` configures Compose (database, published ports and resource tuning).
Knowledge and the LangMem worker read their provider settings from the read-only
mounted `ai-services/.env` at container startup; memory reads its diagnostics flag.
The entrypoint selects only settings needed by that process. Host DATABASE_URL,
admin credentials and host MCP URLs are not imported into the process environment.
The mounted file itself contains credentials: only trusted service containers
receive it. Changes require restarting the affected containers.

This starts an already initialized installation. BTC import, SQL migrations,
LangMem store setup and policy release preparation/activation remain one-time
setup steps; startup never resets data or invokes embedding/model APIs for setup.
Missing provider values are reported by the relevant container, not by Compose
while parsing a `down` command.

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
business tools. LangMem is the only supported runtime mode. The agent commits a masked turn
and successful order links to tables in `runtime`, then a separate worker uses LangMem
to extract profile facts and call episodes. The worker checks each proposal
against committed customer text or a successful business tool before writing
it to the customer namespace in `runtime.store`. Synchronous fact and episode
writes are disabled in the service runtime.
Voice calls first use authenticated `POST /v1/chat/sessions/prepare` with
`session_id`, `channel`, `channel_identity` and `on`. This prepares CRM identity,
context and an optional returning-customer Call Brief without calling the model,
committing a turn or enqueuing LangMem work. The gateway runs preparation alongside
STT setup and listening, then uses the same session for the first real transcript.
The runtime consumes prepared reads once within 30 seconds, only for the same
customer and business date. They are prior evidence, so a new quantity, product or
address can require a new quote. A process restart or another AI worker falls back
to the ordinary turn path; correctness does not depend on hitting a warm process.
The brief on every returning-customer turn is rebuilt from current memory and customer text using
the existing brief rules, including orders, open blockers, known slots and stale
warnings. The preliminary prepare response is not spoken or substituted for it.

`SessionState` keeps an owner/date/full-or-baseline scoped context view and the
current consultation decision across turns. A fresh memory read replaces that
view; failed reads invalidate it. Committed tool observations rebuild evidence
after a process restart, including failed-read barriers that invalidate stale
quotes. Prepared reads are attributed to their consuming turn when committed;
voice offers still require delivered speech. Baseline retains only the current
session context. Brief rendering alone does not refresh price or stock.

Working memory is read synchronously from `runtime.turns` for every turn in
the same session; recent customer and agent turns are passed to the model with
their conversation roles and do not wait for LangMem distillation.
When `AGENT_GUARDRAILS_ENABLED=false`, the outer graph returns the selected agent's
draft reply without `check_answer` or catalog fallback. PII masking, MCP tool
preconditions, identity checks, and memory evidence validation still apply.
Missing MCP URLs or token are a configuration error at runtime startup. Chat response caching remains process-local; writes through the MCP
services use PostgreSQL operation keys. A PostgreSQL LangGraph checkpointer is
not connected yet.

Policy questions use `policy.search` on the dedicated `mcp-knowledge` service.
Cloudflare BGE-M3 produces dense vectors and CPU BM25 produces sparse term weights; Qdrant applies IDF once and performs RRF and PostgreSQL supplies
safe source snapshots from one pinned hybrid release. See the [module map](app/knowledge/README.md) for the domain/MCP directory boundaries. Catalog no longer registers
policy tools or loads an embedding model. The agent, grounding checks, diagnostics
and Knowledge Gap Loop use `evidence[].content` and applicability metadata.

Configure `MCP_KNOWLEDGE_URL`, a separate reader role/secret and a reviewed
`KNOWLEDGE_POLICY_CONFIG_FILE`, `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`.
The CPU tokenizer is bundled and hash checked. No model weights/GPU are needed.
Missing credentials or invalid release/index/artifact fails closed; Cloudflare
errors do not trigger BM25-only fallback. Quality remains explicitly unmeasured
with `relevance_verified=false`; integrity/readiness is checked separately.
No dependency installation, model download, database migration or running-service
change is performed by startup. See the [knowledge runbook](docs/mcp-knowledge-runbook.md)
for migration 0003, CLI prepare/activate/rollback/revoke and operational limits.

The Knowledge Gap Loop keeps its existing approval/CAS/audit controls. With a
hybrid config, its prepare operation delegates to the hybrid builder. Historical
lexical review checks do not certify hybrid readiness. BTC source imports target
PostgreSQL; the loader's explicit `--prepare-policy` option also prepares a
Knowledge snapshot and Qdrant index. See the [loader guide](../dataloader_offline/README.md).
Functional tests use mocked HTTP, scripted models and in-memory dependencies.
Live Cloudflare, clean Docker deployment, quality and performance require separate verification.

### Langfuse Cloud tracing

To manage the sales-agent and LangMem extraction instructions in Langfuse,
configure the three Langfuse credentials and run
`python -m scripts.publish_langfuse_prompts` once from `ai-services/`.
This creates text prompts `telesale-sales-agent` and
`telesale-langmem-extraction` with the `production` label. Set
`LANGFUSE_PROMPTS_ENABLED=true` in both the API and LangMem worker environments,
then restart them. The SDK caches prompt versions and uses the checked-in
instructions if Langfuse cannot serve a prompt. Update instructions in Langfuse
and promote the desired version to `production`. The publisher skips existing
production prompts. The first prompt fetch requires network access;
subsequent calls use the SDK cache. Prompt management can be enabled without
enabling tracing.

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
tools to the four servers in `app/mcp_servers/`. DeepSeek is a possible model
choice through `LLM_MODEL` if supported by the configured endpoint, not a
separate agent architecture. Policy RAG runs in the dedicated knowledge MCP server.

```text
app/agent/
  chat.py                 # public chat() entrypoint
  factory.py              # assemble the active implementation and adapters
  graph.py                # outer LangGraph wiring
  implementations/        # selectable Deep/ReAct agents and shared business tools
  harness/                # runtime, graph nodes, state, tool policy
  memory/                 # candidate validation and MCP memory adapter
  guardrails/             # answer and fact evidence checks
  mcp/                    # client gateway for the four MCP servers
app/mcp_servers/          # catalog, order, memory, knowledge, shared infrastructure
```

## Structured MCP tools

Start PostgreSQL with `docker compose up -d postgres redis`, then import the
BTC release with `dataloader_offline`. Apply the runtime SQL in order:
`backend/migrations/0001_chat.sql`,
`backend/migrations/0002_tools.sql`, `backend/migrations/0003_channel_identity.sql`,
`backend/migrations/0004_erasure_suppressions.sql`,
`backend/migrations/0005_runtime_schema.sql`, then
`ai-services/migrations/0001_current_memory_schema.sql`. Apply them before starting
`mcp-db-roles`. Use the same PostgreSQL database
for the backend and all three MCP servers. Set matching `AI_INTERNAL_TOKEN`
values in `backend/.env` and `ai-services/.env`, and a separate
`MCP_INTERNAL_TOKEN` in `ai-services/.env`. The values in `.env.example` are
placeholders, not working credentials.

The final database has exactly two application schemas: `btc_source` for the
imported BTC data and `runtime` for chat, orders, memory jobs, and
`AsyncPostgresStore` tables. The AI service migration keeps existing
rows and removes the empty legacy schemas and the empty `public` schema; it
stops with an error if `public` contains other objects.

After importing BTC data and applying the migrations, create four ignored
secret files under `secrets/`: `mcp_catalog_password`, `mcp_order_password`, `mcp_knowledge_password`,
`mcp_memory_password` (hex strings) and `mcp_internal_token` (the same value as
`MCP_INTERNAL_TOKEN` in `ai-services/.env`). The repository's existing
`secrets/postgres_password` remains the PostgreSQL admin password. Then run:

```bash
# From the repository root:
docker compose --env-file .env --env-file ai-services/.env up -d --build mcp-catalog mcp-order mcp-memory mcp-knowledge
# In another terminal, from ai-services/:
python -m app
```

For a local run without the MCP Compose containers, start all four
MCP processes and the LangMem worker in one terminal with `python -m app.mcp_servers.run` from
`ai-services/`. The launcher uses `DATABASE_URL` to locate PostgreSQL, then
connects each child with its own `mcp_catalog`, `mcp_order`, `mcp_memory` or `mcp_knowledge`
role and the corresponding files under `../secrets/`. Provision those roles
first, apply migration 0003 and supply the reviewed policy config; see the knowledge runbook. Stop the launcher with Ctrl+C. You can then call
`app.agent.chat.chat(ChatRequest)` from another Python process; the AI HTTP
server is not required for that call.

`mcp-memory` owns `memory.read` and `memory.write` in PostgreSQL. `mcp-catalog`
exposes `crm.get_customer`, `catalog.search`, `inventory.check`,
`pricing.get_quote`, `policy.search`; `mcp-order`
exposes `order.create`, `order.update`, `order.status`, `schedule.callback`,
`handoff.transfer`. Each MCP has its own PostgreSQL connection pool and role;
catalog reads `btc_source`, order writes commerce tables in `runtime`, and
memory writes operational turns, jobs and erasure barriers to `runtime`,
and long-term facts and episodes to `runtime.store`. All connect to `postgres:5432` on the Compose
network. The one-shot `mcp-db-roles` service provisions roles on the existing
database volume. The MCP ports are published only on host loopback and require
the MCP bearer token. The backend business tool HTTP route is no longer mounted.

Each identified committed turn creates one durable
`runtime.langmem_distillation_jobs` row. Compose starts the worker with
`mcp-memory`; the local launcher starts it with the `mcp_memory` database role
and model credentials from `ai-services/.env`. Restart an already-running local
launcher after updating the code. The worker leases jobs in
session order, retries up to five times, and logs only error codes. A model
timeout never rolls back the already committed customer turn. If the store is
unavailable, customer memory reads fail closed instead of reading stale legacy facts.
Apply `0001_current_memory_schema.sql` after the backend SQL on a new database.
Then, once with an admin
`DATABASE_URL`, run `python -m scripts.setup_langmem_store` from `ai-services/`.
This invokes `AsyncPostgresStore.setup()` with `runtime` as the fixed
search path; LangGraph's concurrent index DDL must run outside a wrapping
transaction. Re-run `scripts/provision_mcp_roles.sh` after setup to grant the
`mcp_memory` role access to the new store tables and job sequence. Neither the
API nor the worker runs store DDL at startup. V1 has no vector index.
For an existing database with rows in `runtime.facts` or `runtime.episodes`,
run `python -m scripts.backfill_langmem_store` once before the AI service migration.
It copies active facts with source turn and date plus existing episodes,
skips records that lack provenance, and preserves newer LangMem facts.
Archive and clear legacy rows after verifying the backfill; the migration
refuses to remove tables that still contain rows. On an existing `runtime`
database, apply only `0001_current_memory_schema.sql`.
For a verified erasure request already registered in `runtime.erasure_requests`,
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

Each completed chat turn is written to `runtime.turns`; accepted long-term
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
customer's new session. The brief includes `orders`, `open_blockers` (excluding
blockers resolved in later sessions), `must_not_ask` across all 12 BTC slots,
outcome-aware `suggested_opening`, and concurrent refresh of up to the 3 most
recent advised SKUs with stale warnings for expired `valid_until`, discontinued
SKUs (`successor_sku`), and sessions older than 180 days. New chat turns may
create profile facts from validated model proposals grounded in customer text or
verified tool results, while the distillation worker compacts superseded store
revisions after each completed job.

## Theo dõi một lượt chat

### Bộ nhớ sau từng lượt

`POST /v1/chat/turns` trả thêm `memory_update`. Response không chờ LangMem:

```json
{"memory_update":{"turn_saved":true,"status":"pending","changes":[]}}
```

Khách chưa xác minh có `status: "not_applicable"`: hội thoại trong phiên vẫn
được lưu, chưa có job ghi fact dài hạn. `turn_saved: false` nghĩa là chưa xác
nhận đã lưu (ví dụ khi bị chặn bởi yêu cầu xóa dữ liệu).

Backend có thể gọi `POST /v1/chat/turns/memory` với header
`X-AI-Internal-Token` và body gồm `session_id`, `client_msg_id`, `channel`,
`channel_identity`, `on` của lượt. Response chứa hai UUID trên và `memory_update`.
Trạng thái là `pending`, `completed`, `failed`, `not_applicable` hoặc `unavailable`.
Chỉ job `completed` mới trả thay đổi từ `accepted_writes` thực sự đã ghi:

```json
{"turn_saved":true,"status":"completed","changes":[{"field":"room_area_m2","action":"added","value":25,"source":"customer","scope_type":"room","scope_id":"room_a"}]}
```

`action` là `added`, `updated`, `deleted`; xóa có `value: null`. Không suy ra giá
trị cũ. Danh sách rỗng khi hoàn tất nghĩa là không có fact hồ sơ mới; worker vẫn
có thể cập nhật episode. API chỉ trả các slot được phép và giá trị scalar đã
che PII; không trả proposal, bằng chứng gốc, customer ID hay chi tiết lỗi worker.
Lookup kiểm tra chủ session/lượt và barrier xóa dữ liệu, không gọi model.
MCP memory cần chạy phiên bản có tool read-only `memory.turn_status`; không cần
migration mới. Khởi động lại MCP memory, AI service và gateway để áp dụng.

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
xem cùng terminal; với Compose, dùng `docker compose logs -f mcp-catalog mcp-order mcp-memory mcp-knowledge`.
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
  --with 'langchain-openai>=1.7,<2' --with 'fastapi>=0.141.1,<0.142' \
  --with 'httpx>=0.28.1,<0.29' --with 'pydantic-settings>=2.10,<3' \
  --with 'fastmcp>=4.0.10,<4.1' --with 'asyncpg>=0.30,<1' \
  python -m unittest discover -s test -v
```

### Memory demo and manual preflight

Before starting the existing MCP services, apply the current AI service migration
to their PostgreSQL database, then rerun role provisioning.
A table created after provisioning does not inherit the earlier table grants.
With the administrative `psql` connection (never put passwords in the command), verify:

```sql
SELECT to_regclass('runtime.pending_facts') IS NULL;
SELECT to_regclass('runtime.facts') IS NULL;
SELECT to_regclass('runtime.episodes') IS NULL;
SELECT to_regclass('runtime.erasure_requests');
SELECT has_table_privilege('mcp_memory', 'runtime.erasure_requests',
                          'SELECT,INSERT,UPDATE,DELETE');
```

If the table lacks grants, rerun `scripts/provision_mcp_roles.sh` with the
documented administrative connection. For the memory tables alone, the
administrator can run:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON runtime.erasure_requests TO mcp_memory;
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
customer's episode; they are not converted into profile facts. The former 0006
section in the consolidated migration
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

### Knowledge Gap Loop

Feedback nhân viên, tín hiệu runtime và lỗi từ eval được xử lý thành gap,
revision có nguồn, test được duyệt và release FAQ/aliases cho `policy.search`.
Chức năng mặc định tắt; cần migration `0002_knowledge_gap_loop.sql`, provision
roles và cấu hình riêng cho API/worker. Xem [runbook](docs/knowledge-gap-loop-runbook.md)
để cấp reviewer, chạy workers, thao tác UI, rollback và xuất bằng chứng BTC.
Không tự chạy eval live hoặc reset DB khi bật giao diện.

## BTC text eval sau sửa harness

Xem [runbook eval](eval_harness/README.md) cho kiểm file offline, test chặn mạng,
CLI một cấu hình/cặp và chấm lại bằng scorer BTC nguyên bản. Hai CLI dùng chung
runner, bốn MCP và accepted memory writes. Cần khai báo `--btc-root` và DB đích
`--expected-database` (hoặc `EVAL_EXPECTED_DATABASE`); không suy quyền reset từ
DB đang kết nối. Chỉ chạy live/reset sau ủy quyền riêng. Trạng thái `invalid`
cho bằng chứng chấm bị mất sau redaction; `validated` không bảo đảm đạt chất
lượng/latency BTC.

## Voice playback receipts

`POST /v1/chat/turns` defaults to `delivery_mode: text` and retains immediate
conversation persistence. The trusted voice gateway uses `delivery_mode: voice`:
the harness verifies/generates once but defers the conversation commit until
`POST /v1/chat/turns/playback`. This token-protected endpoint takes the session/turn
IDs, original channel identity/date, `played_chars` and `interrupted`; it commits
only the confirmed original-text prefix, retaining customer speech and successful
tool observations. It never invokes business tools again. Repeated identical
receipts are idempotent; conflicting or mismatched receipts return 409.

A missing receipt is finalized with no confirmed assistant speech after 300
seconds, before a subsequent turn, or on orderly shutdown. These pending states
share the existing process-local session/cache boundary: keep a session on the
same worker. The change adds no crash recovery or cross-process receipt storage.
See [voice protocol](../backend/VOICE_API_CONTRACT.md) for playback markers,
interruption and offline verification.

## Query-aware memory retrieval

`memory.read` accepts an optional `query` (up to 8000 characters); existing callers
can omit it. The harness passes the current masked customer text through
`MCPMemoryStore`. Stores without `supports_retrieval_query = True` retain their
original two-argument `read_context` call.

Completed, authorized active prior episodes are ranked before `max_episodes`
is applied: exact product scope, accent-insensitive text overlap, open blockers,
then date. This is deterministic lexical retrieval, without embedding/model
calls. An empty query keeps the MCP's existing chronological shortlist. Current
session context remains separate, and `include_prior=false` suppresses both prior
episodes and prior-session IDs. Accepted blocker/question resolutions remain
visible even if the resolving session is outside the selected shortlist.

`ReadResponse` validates history, profile facts, room/product scopes and episode
envelopes at MCP output, store and harness boundaries. Malformed required fields
return `invalid_tool_result`; canonical extension fields and legacy optional
fields are retained. Fact context now includes masked `evidence_quote` and source
turn/session IDs when available, alongside `on` and `valid_until`. These identify
historical evidence; they do not authorize current prices, stock or consent.

The local sales prompt explains these source fields and that missing retrieved
context does not prove the customer never supplied information. No managed prompt
is published by this change. Deployments using Langfuse production prompts need
the reviewed local prompt published through the existing release workflow.
