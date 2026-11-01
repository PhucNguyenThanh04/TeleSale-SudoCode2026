# Legacy memory table audit (2026-10-31)

This audit covers the `telesale` database used by `ai-services`. Before the
cleanup, `runtime.facts`, `runtime.episodes`, and `runtime.pending_facts` each
contained zero rows. There were no foreign keys, triggers, or views on these
tables. A full custom-format backup was taken before changing the schema.

| Component | Location | Reason | Evidence | Risk | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Legacy fact projection | `runtime.facts` | HIGH CONFIDENCE: custom fact extraction no longer writes or reads it | Live row count 0; `memory.write` queues LangMem jobs; `memory.read` selects from LangMem store. Remaining SQL was in erasure and one-time backfill. | A deployment with unbackfilled legacy rows would lose customer facts. | Remove only when empty; migration checks this inside the transaction. |
| Legacy episode projection | `runtime.episodes` | HIGH CONFIDENCE: LangMem store owns episodes | Live row count 0; worker projects episodes to `runtime.store`; current reads use the LangMem projection. The old owner fallback and `prior_open_items` method were the remaining runtime references. | A deployment with legacy rows could lose session ownership or episode history. | Remove only when empty; backfill and review populated deployments first. |
| Pending custom facts | `runtime.pending_facts` | HIGH CONFIDENCE: legacy claim pipeline is disabled | Live row count 0; no runtime writer; only old erasure cleanup and integration tests referenced it. | Pending anonymous facts in another deployment could be discarded. | Remove only when empty. |
| Operational memory | `runtime.turns`, `runtime.write_operations`, `runtime.order_links`, `runtime.langmem_distillation_jobs`, `runtime.store`, `runtime.store_migrations`, `runtime.erasure_requests` | ACTIVE | Current repository and worker read or write these tables; several contain rows. | Dropping them would break memory, idempotency, or erasure. | Preserve. |
| Historical backfill utility | `scripts/backfill_langmem_store.py` | MEDIUM CONFIDENCE: needed only before the current migration on databases with legacy rows | Queries old fact and episode tables; no longer runs on the current empty legacy tables. | Removing it would strand other populated deployments. | Preserve until all deployments have applied the current migration. |

Apply `0001_current_memory_schema.sql` after deploying compatible MCP memory
code. It creates only current AI service tables and removes empty legacy tables.
The old migration chain was removed after the active database had already
moved its operational data to `runtime`.
