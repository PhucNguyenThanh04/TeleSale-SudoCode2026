# Runtime Schema Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `btc_source` and one `runtime` application schema while preserving all existing rows and role boundaries.

**Architecture:** Backend migration `0005` renames `app_runtime` to `runtime`; AI migration `0002` moves `ai_memory` tables and LangGraph store tables into it, then removes the empty source schemas and empty `public`. Update qualified SQL, LangGraph `search_path`, role provisioning, and setup instructions in one coordinated rollout. Retain all existing application data, including legacy memory rows.

**Tech Stack:** PostgreSQL, Python, asyncpg, SQLAlchemy, LangGraph `AsyncPostgresStore`.

**Spec:** User-approved schema mapping in this conversation: `btc_source` for supplied data, `runtime` for backend, operational memory, and LangMem store, to simplify database operations.

## Review Focus

- Existing fact and episode records and worker jobs survive the move.
- `mcp_memory` cannot access order or backend tables after the shared schema gains usage grants.
- Fresh setup and repeated migration produce the same schema layout.
- The LangGraph `store_migrations` table moves with `store`; setup does not create a second store.
- Backend and all three MCP services use the new qualified table names.

## Task 1: Move existing tables safely

**Files:** `../backend/migrations/0005_runtime_schema.sql`, `migrations/0002_runtime_schema.sql`, `test/test_runtime_schema_migration.py`.

- [x] Add a database integration test on an isolated PostgreSQL fixture: seed a turn, job, and LangGraph row; run migration; assert rows survive, `runtime.store` exists, and old application schemas are gone.
- [x] Run the test and confirm it fails because migration is absent.
- [x] Add idempotent migrations: rename `app_runtime`, move all `ai_memory` and `langmem_store` tables plus any remaining sequence, grant schema usage, and drop old schemas without `CASCADE`.
- [x] Run the integration test and inspect schema/table counts.

## Task 2: Update applications and role boundaries

**Files:** `../backend/app/**/*.py`, `app/mcp_servers/**/repos/*.py`, `scripts/provision_mcp_roles.sh`, `scripts/backfill_langmem_store.py`, `app/mcp_servers/mcp_memory/repos/langmem_projection.py`, affected tests.

- [x] Add failing tests for LangGraph `search_path=runtime` and the data migration.
- [x] Replace qualified runtime SQL in both services; preserve `btc_source` references.
- [x] Give each MCP role `USAGE` on `runtime` but only its required tables and sequences; no schema-wide table grants.
- [x] Run AI and backend suites; check existing role privileges after migration.

## Task 3: Setup and live verification

**Files:** `README.md`, `../README.md`, `eval_harness/README.md`, migration references.

- [x] Document the new migration order: backend `0001`–`0005`, AI `0001`, AI `0002`, LangGraph setup, role provisioning.
- [x] Back up the current database and apply the two new migrations.
- [x] Verify the schema layout, representative row counts, and existing MCP role privileges.
- [x] Run full regression suites and `git diff --check`.
