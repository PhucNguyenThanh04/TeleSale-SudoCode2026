# AI service audit — 2026-10-15

This review covers the AI API, LangGraph harness, agent implementations,
guardrails, MCP gateway, catalog/order/memory services, repositories, settings,
and tests under `ai-services/`. It compares runtime paths with BTC contracts;
the public sample labels are not read by runtime code.

## Changes made

- The outer graph now selects `deep` or `react` through `AGENT_KIND`. Both use
  the same business tools, tool preconditions, answer checks, and memory path.
  `LLM_MODEL` still selects the model; DeepSeek is a model choice if supported
  by the configured Ollama endpoint.
- The agent's final JSON `{"answer": ..., "fact_candidates": [...]}` and
  business-tool proposals remain valid fact sources. The default extraction
  mode now calls a second model only when no customer fact from those proposals
  passed evidence checks. `FACT_EXTRACTION_MODE=off` uses only the agent;
  `always` runs extraction for every identified turn.
- `policy.search` reads public, effective policy chunks through the existing
  catalog MCP server. PostgreSQL filters access and the applicable call/order
  date before lexical ranking. The harness supplies `on` and derives an old
  order's date only from a verified `order.status` result. The answer guard
  requires returned policy evidence and checks stated day counts against it.
- Removed the fixed customer identity and room area from the `chat.py` demo
  entrypoint and a fixed room-area example from the agent prompt.

## Hard-coded values retained because BTC defines them

- Commerce rules such as COD limits, delivery holidays, exchange fees and
  freeship thresholds match `BTC-Data-Vong1-TEAMS/eval/mock_tools.py`. They
  are source rules, not shortcuts for a sample answer.
- Slot names and BTC tool names are explicit contract allowlists. They are
  intentionally controlled by code, rather than inferred by the model.

## Remaining gaps

- Qdrant has a Compose service, but no runtime collection or semantic
  retrieval path. The local Qdrant instance had no collections at review time.
  PostgreSQL remains the source of structured facts and policy access/date
  filtering.
- The architecture retains three MCP servers. Policy lookup belongs to
  catalog; a fourth process would duplicate the existing trust boundary.
- The current policy answer guard checks lookup presence, day counts and
  quoted money against returned chunks. It does not prove every natural
  language policy claim. Product feature checks and catalog query cleanup
  also use finite heuristics; these need broader evaluation before claiming
  full coverage.
- `run_eval.py` imports a missing `eval/` package in this checkout. Full and
  baseline public-sample traces cannot be produced until that runner is
  restored. No isolated eval database was modified in this review.
- The graph has no PostgreSQL checkpointer; worker locks and reply cache are
  local to one AI process. The `address_ref` PII design remains unimplemented.

## Verification

- AI service unit suite: 67 tests passed after the changes.
- Deep and ReAct each completed a synthetic live-model turn with
  `FACT_EXTRACTION_MODE=off`, proposed `room_area_m2`, and passed it to memory
  without a separate extraction call. Direct inspection of both raw agent
  finals found JSON keys `answer` and `fact_candidates`, with one fact each.
  Memory was mocked for these turns.
- PostgreSQL policy lookup was tested with the `mcp_catalog` role and over MCP
  HTTP: the 2026-10-15 query returned the current return-policy document;
  the 2026-09-20 query returned the older effective document.
- `git diff --check` passed. Docker Compose status could not be read because
  this shell has no Docker socket permission.
