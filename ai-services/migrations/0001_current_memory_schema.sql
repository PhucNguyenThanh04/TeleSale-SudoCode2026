BEGIN;

CREATE TABLE IF NOT EXISTS runtime.tool_operations (
    operation_key text PRIMARY KEY,
    tool_name text NOT NULL,
    args_hash text NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime.turns (
    session_id uuid NOT NULL,
    turn_no integer NOT NULL,
    customer_id text,
    channel text NOT NULL,
    on_date date NOT NULL,
    customer_text text NOT NULL,
    agent_text text NOT NULL,
    client_msg_id uuid,
    attributed_after_verification boolean NOT NULL DEFAULT FALSE,
    PRIMARY KEY (session_id, turn_no)
);
ALTER TABLE runtime.turns
    ADD COLUMN IF NOT EXISTS client_msg_id uuid,
    ADD COLUMN IF NOT EXISTS attributed_after_verification boolean NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS memory_turns_customer_idx
    ON runtime.turns(customer_id, on_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS turns_session_client_msg_id_idx
    ON runtime.turns(session_id, client_msg_id)
    WHERE client_msg_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS runtime.order_links (
    customer_id text NOT NULL,
    order_id text NOT NULL,
    PRIMARY KEY (customer_id, order_id)
);

CREATE TABLE IF NOT EXISTS runtime.write_operations (
    operation_key text PRIMARY KEY,
    args_hash text NOT NULL,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runtime.erasure_requests (
    request_key uuid PRIMARY KEY,
    customer_id text NOT NULL,
    verification_ref text NOT NULL,
    verified_by text NOT NULL,
    scope jsonb NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'partial', 'failed', 'completed')),
    store_results jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_erasure_customer_idx
    ON runtime.erasure_requests(customer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime.langmem_distillation_jobs (
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
    accepted_writes jsonb NOT NULL DEFAULT '[]'::jsonb,
    accepted_proposals jsonb,
    verified_outcome text NOT NULL DEFAULT 'khac'
        CHECK (verified_outcome IN ('khac', 'hen_goi_lai', 'chot_don', 'tu_choi', 'chuyen_may')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, source_turn_id)
);
ALTER TABLE runtime.langmem_distillation_jobs
    ADD COLUMN IF NOT EXISTS accepted_writes jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS accepted_proposals jsonb,
    ADD COLUMN IF NOT EXISTS verified_outcome text NOT NULL DEFAULT 'khac'
        CHECK (verified_outcome IN ('khac', 'hen_goi_lai', 'chot_don', 'tu_choi', 'chuyen_may'));
CREATE INDEX IF NOT EXISTS langmem_jobs_claim_idx
    ON runtime.langmem_distillation_jobs(status, lease_until, created_at);

DO $check_legacy_memory$
DECLARE
    table_name text;
    has_rows boolean;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['facts', 'episodes', 'pending_facts'] LOOP
        IF to_regclass(format('runtime.%I', table_name)) IS NOT NULL THEN
            EXECUTE format('LOCK TABLE runtime.%I IN ACCESS EXCLUSIVE MODE', table_name);
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM runtime.%I)', table_name)
                INTO has_rows;
            IF has_rows THEN
                RAISE EXCEPTION 'Legacy memory table runtime.% contains rows; backfill and review before dropping it', table_name;
            END IF;
        END IF;
    END LOOP;
END $check_legacy_memory$;

DROP TABLE IF EXISTS runtime.pending_facts;
DROP TABLE IF EXISTS runtime.facts;
DROP TABLE IF EXISTS runtime.episodes;

DROP SCHEMA IF EXISTS ai_memory;
DROP SCHEMA IF EXISTS langmem_store;
DROP SCHEMA IF EXISTS public;

COMMIT;
