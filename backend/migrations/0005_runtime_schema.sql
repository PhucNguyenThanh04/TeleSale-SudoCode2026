-- Consolidate backend operational tables into the shared runtime schema.
-- Existing rows, constraints, sequences and schema privileges survive a rename.
BEGIN;

DO $runtime_schema$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app_runtime')
       AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runtime') THEN
        ALTER SCHEMA app_runtime RENAME TO runtime;
    ELSIF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app_runtime')
          AND EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runtime') THEN
        RAISE EXCEPTION 'refusing to merge non-unique app_runtime and runtime schemas';
    ELSIF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runtime') THEN
        CREATE SCHEMA runtime;
    END IF;
END $runtime_schema$;

COMMIT;
