BEGIN;
ALTER TABLE runtime.turns ADD COLUMN IF NOT EXISTS request_hash text;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcp_memory') THEN
        GRANT SELECT ON runtime.tool_operations TO mcp_memory;
    END IF;
END $$;
COMMIT;
