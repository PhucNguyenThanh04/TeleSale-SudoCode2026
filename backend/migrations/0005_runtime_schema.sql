-- Preserve backend rows while moving the application schema to runtime.
DO $rename_runtime$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app_runtime') THEN
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runtime') THEN
            RAISE EXCEPTION 'Both app_runtime and runtime exist; resolve schema conflict';
        END IF;
        ALTER SCHEMA app_runtime RENAME TO runtime;
    ELSIF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'runtime') THEN
        RAISE EXCEPTION 'Expected app_runtime or runtime schema';
    END IF;
END $rename_runtime$;
