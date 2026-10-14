CREATE TABLE IF NOT EXISTS app_runtime.tool_operations (
    operation_key text PRIMARY KEY,
    tool_name text NOT NULL,
    args_hash text NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ai_memory.write_operations (
    operation_key text PRIMARY KEY,
    args_hash text NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
