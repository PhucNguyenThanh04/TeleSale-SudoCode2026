# Architecture and Cleanup Audit — 2026-10-31

## Scope and method

This audit covers the `ai-services` application tree, its scripts, tests,
runtime configuration, dependency manifests, and the root Compose wiring that
starts its containers. It traces static imports, command/module entry points,
FastAPI and FastMCP registrations, settings access, environment-driven paths,
and the LangMem worker. It also treats dynamic optional integrations and
database migration/backfill paths as reachable unless evidence establishes
otherwise.

The working tree already contains an uncommitted LangMem-only migration. Those
changes are treated as in-scope current architecture, not as stale code to
overwrite.

## Current architecture

`python -m app` starts FastAPI. `POST /v1/chat/turns` authenticates with the
internal HMAC token, then calls `AgentHarnessRuntime`. The runtime invokes the
explicit LangGraph (`accept -> retrieve_context -> run_agent -> verify ->
persist`) and selects the Deep or ReAct implementation through `AGENT_KIND`.
Business calls go through `MCPGateway` to catalog, order, and memory FastMCP
servers.

The only live long-term-memory path is `memory.write(action=commit_turn)` to
the memory MCP. It records a masked turn and durable job; `distiller_worker`
uses LangMem, admission checks, and deterministic business-tool observations
to write accepted facts and episodes to the `runtime.store` projection.
`memory.read` reads that projection and fails closed on an outage. Session
history remains synchronous in `runtime.turns`.

The module entry points are `app.__main__`, the three MCP `server` modules,
`app.mcp_servers.run`, `mcp_memory.distiller_worker`, and the explicitly
documented operational/evaluation scripts. No importlib/plugin discovery or
package entry-point registry is used in application code.

## Cleanup candidates

| Component | Location | Classification | Reason and evidence | Risk | Recommendation |
|---|---|---|---|---|---|
| PyJWT declaration | `requirements.txt` | HIGH CONFIDENCE | No `jwt`/`PyJWT` imports or dynamic references exist in the AI service, tests, scripts, docs, or root Compose. The API authenticates with `hmac.compare_digest` in `app/api/chat.py`. | Low; backend has its own manifest and is unaffected. | Remove from the AI-service manifest. |
| Redis client declaration | `requirements.txt` | HIGH CONFIDENCE | No AI-service `redis` import, setting, or connection exists. Root Compose and the backend use Redis independently; they do not consume this Python dependency declaration. | Low; retain the Compose Redis service and backend dependency. | Remove only from the AI-service manifest. |
| Structlog declaration | `requirements.txt` | HIGH CONFIDENCE | No imports or configuration exist. Application and MCP observability use the standard `logging` module. | Low. | Remove from the AI-service manifest. |
| `langchain[mcp]` extra | `requirements.txt` | MEDIUM CONFIDENCE | Active code imports `langchain.agents`, while actual MCP transport is `fastmcp.Client`; no code imports LangChain MCP adapter symbols. The extra could still affect supported dependency resolution. | Medium; a packaging-only change may alter transitive dependencies. | Preserve pending a clean-environment install/lock verification. |
| Historical custom fact extractor | `app/agent/memory/fact_candidates.py` and proposal-only tests | HIGH CONFIDENCE | A granular reachability pass found `extract_customer_candidates`, `model_candidates`, `accepted_candidates`, `literal_blocker_candidates`, and `resolved_blockers` have no production callers. Only JSON parsing, child-safety cue detection, and blocker resolution remain live; relocate those helpers to their consumers before deleting the extractor. | Low after relocation; live LangMem extraction is `langmem_extractor.py`. | Remove the legacy file and proposal-only tests. |
| Legacy fact/episode tables and backfill | migrations, `scripts/backfill_langmem_store.py`, memory integration tests | MEDIUM CONFIDENCE | Live reads/writes no longer use legacy fact or episode tables, but migrations preserve historical data and the backfill script imports it into the active store. | High; user explicitly excluded schema, migrations, and persistent-memory-format changes. | Preserve. |
| Historical `current`/`shadow` evaluation variants | `eval_harness/benchmark_runner.py`, `compare_langmem.py`, aggregates and docs | MEDIUM CONFIDENCE | Runtime mode selection was removed, but CLI evaluation and tests still exercise historical comparisons; existing aggregate reports are evidence artifacts. | Medium; removal would reduce regression/comparison capability. | Preserve until evaluation policy explicitly retires comparisons. |
| Optional dense policy RAG | `app/rag/policy_retrieval.py`, `requirements-rag.txt`, Qdrant Compose service | NOT A CANDIDATE | Environment-driven `POLICY_RAG_ENABLED` dynamically imports SentenceTransformers and Qdrant; lexical fallback is active. | High; static import-only analysis is insufficient. | Preserve. |
| Langfuse tracing | `app/agent/harness/tracing.py`, settings, tests | NOT A CANDIDATE | Feature-flagged construction in the runtime, shutdown flush, redaction behavior, and focused tests are present. | High; observability/security boundary. | Preserve. |
| Direct demo `main()` | `app/agent/chat.py` | LOW CONFIDENCE | Not a normal service entry point, but it is an executable module and the public `chat()` API in the same module is documented. | Low-to-medium; may be used manually by operators. | Preserve unless operators explicitly retire the demo command. |

## Validation baseline

Before cleanup, the following commands completed successfully:

```text
.venv/bin/python -m compileall -q app scripts eval_harness test
.venv/bin/python -m unittest discover -s test -v
# 270 passed, 16 environment-gated integration tests skipped
.venv/bin/python -m pytest test eval_harness/test_eval_harness.py -q
# 346 passed, 16 skipped, 1 third-party deprecation warning
```

The skipped tests require isolated PostgreSQL/MCP integration environment
variables and were not enabled in this workspace.

## Executed cleanup: custom fact extraction

Removed `app/agent/memory/fact_candidates.py`, including the obsolete
model-prompt extractor, proposal parsing, candidate admission, and blocker
write/delete proposal path. Removed proposal-only episode helpers and their
tests. The production JSON reply parser now lives with `AgentNodes`, the
child-safety cue stays with `SessionNodes`, and blocker resolution stays with
the active episode logic. LangMem extraction, deterministic tool observations,
and evidence-backed episode handoff remain intact.

Validation after this batch:

```text
.venv/bin/python -m pytest test/test_catalog_recovery.py::test_recover_sourced_price_and_child_lock_when_model_claim_is_wrong -q
# 1 passed
.venv/bin/python -m pytest test eval_harness/test_eval_harness.py -q
# 326 passed, 16 skipped, 1 third-party deprecation warning
```
