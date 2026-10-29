# LangMem Long-Term Memory Design

## Intent

Improve cross-session recall and task completion on the BTC telesale scenarios while preserving customer isolation, evidence, policy freshness, and reproducible evaluation. The team chose to adopt LangMem for extracting and consolidating long-term memories, with project-specific admission rules.

## Scope and success

- Cover customer profile facts and per-call episodic memory. A sales playbook learned across customers is a later, separately evaluated feature.
- Keep working memory and handoff updated every turn. Form richer long-term memories after a committed turn through a durable background job so response latency does not depend on distillation.
- Compare the current system with the LangMem variant on identical scenarios, model, business tools, dates, and seeds. The BTC `reference_eval.py` and trace schema are the reporting authority.
- Report RQR, CCR, TSR, hard-case TSR, price/promotion HR, guardrail violations, call-brief p95, total/TTFT p95, and cost per call. Adoption requires a measurable gain in CCR or TSR, no regression in the other, no new customer-isolation or PII violations, and call brief p95 <= 5 seconds for M1. No improvement is assumed in advance.

## Architecture

CRM resolves a verified `customer_id` before any long-term read or write. `ai_memory` remains the canonical record of turns, accepted facts, episodes, supersession, provenance, and erasure barriers. LangMem 0.0.30 uses `create_memory_manager` with explicit Pydantic schemas to propose `ProfileFactCandidate` and `CustomerCallEpisodeCandidate`; it never writes canonical records directly. Existing validation and new typed rules admit only proposals supported by the current customer's turn or a successful business tool. Sales prices are labelled `quoted_at` and are never treated as current prices.

Each committed turn creates an idempotent, durable distillation job in `ai_memory`. A separate worker runs with the `mcp_memory` database role, reads committed session data through memory-service functions, calls LangMem with masked customer/agent turns and successful tool observations, then submits proposals for validation. Until a job is accepted, the existing fact and episode path remains fully functional. A failed or slow distillation job cannot make an already committed turn disappear; retries are bounded and observable.

`AsyncPostgresStore` from the already installed `langgraph-checkpoint-postgres` package stores a derived, validated read projection in a separate `langmem_store` schema of the same PostgreSQL database. It is not an alternate source of truth. V1 reads this projection by verified customer namespace and key; semantic vector search is deferred until relevance labels and pgvector are available. A stale, missing, or unavailable projection falls back to canonical `memory.read`. The projection includes only masked data and references to canonical records, not phone numbers or addresses. The AI API does not acquire direct database credentials; store access remains inside the memory service/worker boundary.

Call Brief uses the relevant accepted profile and episode plus a fresh catalog/quote/inventory check at call start. It includes no expired price or promotion as a current claim. `must_not_ask` is formed only from active, relevant, non-expired facts. The brief may be precomputed in part, but freshness checks are timed in the BTC call-brief latency.

## Memory schemas and admission

- `ProfileFactCandidate`: `key`, typed `value`, `scope_type`, `scope_id`, `source_kind`, `source_turn_id`, `evidence_quote`, `observed_on`, optional `valid_until`. Values include customer-stated room area, children, budget, size/color preference, payment preference, blocker, and objection. A question, hypothetical, negation, or speech from another person is not a confirmed fact.
- `CustomerCallEpisodeCandidate`: `customer_id`, `session_id`, `channel`, `on`, `topics` keyed by product/room where known, `customer_goal`, `products_discussed`, `quoted_prices` with quote date and tool reference, `open_blockers`, `open_questions`, `actions_completed` with successful tool reference, `outcome`, and evidence turn IDs. The record describes what happened in that call, not an inferred internal chain of thought.
- Identity fields remain in CRM. Order status remains in order tools. Current catalog, inventory, promotions, and policy remain in their respective tools; prior quotes may be recalled only as historical events.
- Conflict handling uses canonical supersession and explicit resolution of open items. A model proposal cannot replace a fact merely because it is newer; the source and customer intent must support the change.

## Storage, security, and operations

- Use a dedicated PostgreSQL schema for the LangGraph store tables. The installed store has no `schema=` argument; configure a fixed connection `search_path` for this one service, and run `setup()` once through a controlled migration/admin process. Its tables are separate from `ai_memory`.
- `mcp_memory` gets only the permissions needed for its tables and store projection. No credentials or raw PII enter prompts, traces, or logs. Namespace is derived from verified `customer_id`, never directly from a phone supplied in chat.
- Erasure blocks reads/writes first, purges canonical rows and every matching store namespace, and reports completion only when both are gone. If projection removal fails, erasure remains partial and retries; the barrier prevents resurfacing deleted data.
- Version the schemas and namespace format. Changing either requires a migration or rebuild of the derived projection from canonical memory.

## Evaluation and rollout

First correct the existing runner: it must derive `facts_used` from meaningful output or tool arguments, not from all loaded profile keys; preserve CRM identity in the no-memory baseline; emit BTC JSONL trace fields and call-brief latency; use ASR transcripts and per-call dates/channels from scenarios. Keep the public samples and 19 local scenarios separate from BTC's hidden set.

Run a shadow extraction pass without serving LangMem memories, inspect accepted/rejected proposals, then enable accepted episode recall behind a flag. Compare current, shadow, and enabled variants with the BTC reference script. A failing result retains the canonical implementation and produces a categorized error report.

## Exclusions

No replacement of CRM, order/catalog/policy services, MCP contracts, or current erasure workflow. No direct agent-facing `manage_memory` tool in V1. No automatic playbook promotion from customer conversations, no graph database, and no vector search in V1.
