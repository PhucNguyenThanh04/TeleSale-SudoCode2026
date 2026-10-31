-- Consolidate application tables without deleting existing data.
-- Apply after backend 0001-0005 and ai-services 0001_memory.sql.
BEGIN;

ALTER TABLE IF EXISTS ai_memory.turns SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.episodes SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.facts SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.order_links SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.write_operations SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.pending_facts SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.erasure_requests SET SCHEMA runtime;
ALTER TABLE IF EXISTS ai_memory.langmem_distillation_jobs SET SCHEMA runtime;
ALTER SEQUENCE IF EXISTS ai_memory.langmem_distillation_jobs_job_id_seq SET SCHEMA runtime;

ALTER TABLE IF EXISTS langmem_store.store SET SCHEMA runtime;
ALTER TABLE IF EXISTS langmem_store.store_migrations SET SCHEMA runtime;

DROP SCHEMA IF EXISTS ai_memory;
DROP SCHEMA IF EXISTS langmem_store;
-- public is empty in the application database; refuse to remove it if another
-- deployment has put objects there instead of cascading away their data.
DROP SCHEMA IF EXISTS public;

DO $grant_runtime$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_catalog') THEN
        GRANT USAGE ON SCHEMA runtime TO mcp_catalog;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_order') THEN
        GRANT USAGE ON SCHEMA runtime TO mcp_order;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_memory') THEN
        GRANT USAGE ON SCHEMA runtime TO mcp_memory;
    END IF;
END $grant_runtime$;

COMMIT;
