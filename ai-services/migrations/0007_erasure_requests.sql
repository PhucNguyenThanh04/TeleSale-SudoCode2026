CREATE TABLE IF NOT EXISTS ai_memory.erasure_requests (
    request_key uuid PRIMARY KEY,
    customer_id text NOT NULL,
    verification_ref text NOT NULL,
    verified_by text NOT NULL,
    scope jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','partial','failed','completed')),
    store_results jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_erasure_customer_idx
    ON ai_memory.erasure_requests(customer_id,created_at DESC);
