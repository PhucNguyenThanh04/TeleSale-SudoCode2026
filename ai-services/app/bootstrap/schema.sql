-- Canonical managed schema for a fresh demo/eval boot. BTC data is imported separately.
CREATE SCHEMA IF NOT EXISTS runtime;

-- Run after the BTC source import. Runtime conversations stay separate from btc_source.
CREATE SCHEMA IF NOT EXISTS runtime;

CREATE TABLE IF NOT EXISTS runtime.chat_sessions (
    id uuid PRIMARY KEY,
    created_by text NOT NULL,
    caller_phone text NOT NULL CHECK (caller_phone ~ '^0[0-9]{9}$'),
    channel text NOT NULL CHECK (channel IN ('hotline', 'chat_fanpage', 'zalo_oa', 'web_chat', 'other')),
    call_date date NOT NULL,
    customer_id text,
    identity_status text NOT NULL CHECK (identity_status IN ('known', 'unknown', 'ambiguous')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_sessions_customer_idx
    ON runtime.chat_sessions (customer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime.chat_messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES runtime.chat_sessions(id) ON DELETE CASCADE,
    turn_no integer NOT NULL CHECK (turn_no > 0),
    role text NOT NULL CHECK (role IN ('customer', 'agent')),
    content text NOT NULL CHECK (length(content) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, turn_no, role)
);

CREATE INDEX IF NOT EXISTS chat_messages_session_idx
    ON runtime.chat_messages (session_id, turn_no);

CREATE SCHEMA IF NOT EXISTS runtime;
CREATE SEQUENCE IF NOT EXISTS runtime.tool_order_seq START WITH 600001;
CREATE TABLE IF NOT EXISTS runtime.tool_orders (
    order_id text PRIMARY KEY, customer_id text, customer_phone text NOT NULL,
    sku text NOT NULL, qty integer NOT NULL, price_vnd bigint NOT NULL,
    total_vnd bigint NOT NULL, payment text NOT NULL, address text,
    promos jsonb NOT NULL DEFAULT '[]', created_on date NOT NULL,
    status text NOT NULL DEFAULT 'created'
);
CREATE INDEX IF NOT EXISTS tool_orders_phone_idx ON runtime.tool_orders(customer_phone);
CREATE TABLE IF NOT EXISTS runtime.tool_updates (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id text NOT NULL, action text NOT NULL, result jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime.tool_callbacks (
    callback_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_phone text NOT NULL, callback_at timestamptz NOT NULL, note text
);
CREATE TABLE IF NOT EXISTS runtime.tool_handoffs (
    ticket_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, brief jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime.promo_uses (
    customer_phone text NOT NULL, promo_code text NOT NULL,
    PRIMARY KEY(customer_phone, promo_code)
);

ALTER TABLE runtime.chat_sessions ADD COLUMN IF NOT EXISTS channel_identity text;
ALTER TABLE runtime.chat_sessions ALTER COLUMN caller_phone DROP NOT NULL;
UPDATE runtime.chat_sessions SET channel_identity=caller_phone
WHERE channel='hotline' AND channel_identity IS NULL;

CREATE TABLE IF NOT EXISTS runtime.erasure_suppressions (
    customer_id text PRIMARY KEY,
    request_key uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Preserve original scalar order fields for single-item consumers.
ALTER TABLE runtime.tool_orders ADD COLUMN IF NOT EXISTS lines jsonb NOT NULL DEFAULT '[]';
UPDATE runtime.tool_orders
SET lines = jsonb_build_array(jsonb_build_object('sku', sku, 'qty', qty, 'price_vnd', price_vnd))
WHERE lines = '[]'::jsonb;

CREATE SCHEMA IF NOT EXISTS runtime;
CREATE TABLE IF NOT EXISTS runtime.demo_users (
    id text PRIMARY KEY,
    username text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    customer_id text NOT NULL UNIQUE REFERENCES btc_source.customers(customer_id),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- AI service operational memory tables.
-- LangGraph creates runtime.store and runtime.store_migrations via its own setup().



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


-- Knowledge is reset only at system boot, never between arms of an experiment.
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE TABLE IF NOT EXISTS knowledge.events (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.gaps (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.revisions (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.decisions (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.regression_cases (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.releases (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.active (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.jobs (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.audit (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.permissions (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.verification_runs (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE TABLE IF NOT EXISTS knowledge.erasures (id text PRIMARY KEY, data jsonb NOT NULL CHECK (jsonb_typeof(data)='object'));
CREATE INDEX IF NOT EXISTS knowledge_jobs_status ON knowledge.jobs ((data->>'status'));
CREATE INDEX IF NOT EXISTS knowledge_events_customer ON knowledge.events ((data->>'customer_id'));
CREATE TABLE IF NOT EXISTS knowledge.backend_outbox (id text PRIMARY KEY, data jsonb NOT NULL);
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_worker') THEN CREATE ROLE knowledge_worker NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_reviewer') THEN CREATE ROLE knowledge_reviewer NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_ingest') THEN CREATE ROLE knowledge_ingest NOLOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='knowledge_backend') THEN CREATE ROLE knowledge_backend NOLOGIN; END IF;
 GRANT USAGE ON SCHEMA knowledge TO knowledge_worker, knowledge_reviewer, knowledge_ingest, knowledge_backend;
 GRANT SELECT,INSERT,UPDATE ON knowledge.backend_outbox TO knowledge_backend;
 GRANT SELECT ON knowledge.erasures TO knowledge_backend;
 GRANT SELECT ON ALL TABLES IN SCHEMA knowledge TO knowledge_worker, knowledge_reviewer;
 GRANT SELECT,INSERT,UPDATE ON knowledge.events,knowledge.jobs TO knowledge_ingest;
 GRANT SELECT ON knowledge.erasures TO knowledge_ingest;
 GRANT INSERT,UPDATE ON knowledge.events,knowledge.jobs,knowledge.gaps,knowledge.revisions,knowledge.regression_cases,knowledge.audit TO knowledge_worker;
 GRANT INSERT,UPDATE ON ALL TABLES IN SCHEMA knowledge TO knowledge_reviewer;
 GRANT USAGE ON SCHEMA btc_source TO knowledge_worker, knowledge_reviewer;
 GRANT SELECT ON btc_source.policy_chunks TO knowledge_worker, knowledge_reviewer;
END $$;

-- Public serving snapshots and live revocations.
CREATE TABLE IF NOT EXISTS knowledge.policy_sources (
    id text PRIMARY KEY,
    data jsonb NOT NULL CHECK (jsonb_typeof(data)='object')
);
CREATE TABLE IF NOT EXISTS knowledge.policy_revocations (
    id text PRIMARY KEY,
    data jsonb NOT NULL CHECK (jsonb_typeof(data)='object')
);
CREATE INDEX IF NOT EXISTS policy_sources_release ON knowledge.policy_sources ((data->>'release_id'));
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcp_knowledge') THEN
   CREATE ROLE mcp_knowledge NOLOGIN;
 END IF;
 GRANT USAGE ON SCHEMA knowledge TO mcp_knowledge;
 GRANT SELECT ON knowledge.policy_sources, knowledge.policy_revocations,
   knowledge.releases, knowledge.active TO mcp_knowledge;
 -- Reader cannot access raw BTC, customer evidence, decisions, permissions or mutate active.
 GRANT SELECT ON knowledge.policy_sources,knowledge.policy_revocations TO knowledge_reviewer,knowledge_worker;
 GRANT INSERT,UPDATE ON knowledge.policy_sources,knowledge.policy_revocations TO knowledge_reviewer;
END $$;

-- Different customers may extract concurrently; one customer's revisions stay ordered across channels.
CREATE INDEX IF NOT EXISTS langmem_customer_pending_job_idx
    ON runtime.langmem_distillation_jobs(customer_id, job_id)
    WHERE status IN ('pending', 'leased');
