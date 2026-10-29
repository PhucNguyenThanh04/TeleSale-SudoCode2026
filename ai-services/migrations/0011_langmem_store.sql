CREATE SCHEMA IF NOT EXISTS langmem_store;
REVOKE ALL ON SCHEMA langmem_store FROM PUBLIC;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcp_memory') THEN
        GRANT USAGE ON SCHEMA langmem_store TO mcp_memory;
    END IF;
END $$;
