# Execution ledger — 2026-11-02-knowledge-gap-loop
- User authorized implementation inline; no subagents/worktrees/commits.
- Existing deleted scenarios/results belong to current checkout; do not restore them.
- Ruling: serialize knowledge mutations with one PostgreSQL advisory transaction lock for M1 correctness; no new dependencies or DB reset.
- Ruling: backend authenticates actor/ownership, internal AI API owns knowledge business services; worker uses separate restricted DB credentials. PostgreSQL stores records in dedicated tables with JSONB payloads and indexed IDs.
- Preflight: ingestion feeds jobs; revisions reference source snapshots; release manifests reference immutable approved revisions; gateway carries trusted pinned release, eval compares manifests. Erasure must invalidate queued worker writes before purging evidence.
- Task 1: in progress. No live database/model operations authorized or performed.

- Tasks 1–7: implementation present; focused offline tests executed during each step. PostgreSQL migration/grant execution remains unverified and not authorized.
- Ruling: release index generation is lexical and stored atomically in the immutable manifest. Existing dense BTC index remains unchanged; no extra embedding costs or new collection. FAQ/aliases participate in lexical/hybrid selection.
- Ruling: analysis is conservative lexical/extractive by default, with no live LLM call. Reviewer decides source semantics; worker proposes aliases or sourced FAQ and regression drafts.
- Ruling: backend chat erasure remains a separate existing store operation; AI memory erasure now purges knowledge evidence/outbox in its existing verified scope. Exported files remain separate traces/backups scope, explicitly documented.
- Evidence: initial repository tests 3 passed; worker/revisions 8 passed; release/retrieval 5 passed; gateway/retrieval 13 passed; backend API 2 passed and feedback delivery 2 passed; lifecycle 2 passed; real Chrome console smoke passed using synthetic API. Subsequent edge regressions for positive feedback, erasure races/partial and first-release rollback passed individually.
- Task 8: documentation added; final review and the single full regression still pending. No commit, migration, reset, deployment or live evaluation performed.

- Final verification: initial full-regression invocation stopped at collection (0 executed) due existing official_pipeline root-package import dependency; added subprocess regression and fixed import. The actual full run then executed: 413 passed, 18 skipped, 1 failed (test_langmem_worker.py::QueueTests::test_commit_queues_distillation).
- Fixed the discovered disabled-feature hook; reran affected memory/ingest/lifecycle/business completion group: 13 passed. No further full-suite run.
- Final feature group: 40 passed, 1 skipped (PostgreSQL opt-in), 1 dependency deprecation warning. Chrome synthetic-API UI smoke is included. Backend API focused: 2 passed; delivery focused after lease/erasure fix: 3 passed. JavaScript parsed with installed GJS; shell syntax and git diff --check passed.
- Ruling: dispatcher releases its DB row lock before remote delivery, uses a 30-second lease, then checks lease/status before ACK; avoids erasure lock inversion and late-ACK resurrection. New feedback also checks the erasure tombstone under the shared lock.
- Read-only deployment preflight: configured database is telesale; knowledge schema absent; knowledge feature disabled; API/worker knowledge DSNs unset. No raw credentials printed. Deployment is not activated.
- Remaining authorized-code work: none identified in final offline review. Remaining operational verification: approve target DB migration/grants/configuration and workers, run PostgreSQL integration checks and stack walkthrough; separately authorize model/reset operations for C.5 evidence. No claim of live integration, a fully green rerun of the complete suite, or measured C.5 improvement.

- User subsequently authorized DB access and applying the new migration in this session.
- Applied migrations/0002_knowledge_gap_loop.sql transactionally to verified database telesale as postgres; migration SHA256 692f4d0b654fd030f78aeb46be2d372652e414af72859297b78b6b54a76eed31. Verified all 13 knowledge tables and least-privilege group checks; granted schema access/read to existing mcp_catalog and ingestion/erasure access to existing mcp_memory. BTC source fingerprint unchanged.
- Real PostgreSQL lifecycle checked through the production repository with savepoints: event/idempotency, worker, revision, review, prepare/activate, and source-derived retrieval passed. All verification writes were inside an outer transaction and rolled back. The first post-rollback inspection accidentally reused the closed test connection; a fresh production repository then verified no migration-check permissions/events remained and no active release existed.
- Operational status: schema/grants applied and PostgreSQL lifecycle verified. Feature remains disabled; API/worker DSNs and reviewer identity not provisioned, no workers restarted, no live model evaluation or DB reset performed.
