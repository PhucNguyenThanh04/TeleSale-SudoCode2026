CREATE TABLE IF NOT EXISTS ai_memory.langmem_distillation_jobs (
    job_id bigserial PRIMARY KEY,
    session_id uuid NOT NULL,
    customer_id text NOT NULL,
    source_turn_id uuid NOT NULL,
    turn_no integer NOT NULL,
    tool_observations jsonb NOT NULL DEFAULT '[]'::jsonb,
    mode text NOT NULL CHECK (mode IN ('shadow', 'enabled')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'leased', 'completed', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    lease_until timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, source_turn_id)
);
CREATE INDEX IF NOT EXISTS langmem_jobs_claim_idx
    ON ai_memory.langmem_distillation_jobs(status, lease_until, created_at);
