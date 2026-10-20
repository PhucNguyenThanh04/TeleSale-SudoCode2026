CREATE TABLE IF NOT EXISTS app_runtime.erasure_suppressions (
    customer_id text PRIMARY KEY,
    request_key uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
