-- Consolidated ai-services memory schema. Apply after backend migrations.
-- Rerunnable for databases that already applied the former 0001-0013 files.

-- BEGIN 0001_memory
CREATE SCHEMA IF NOT EXISTS ai_memory;
CREATE TABLE IF NOT EXISTS ai_memory.turns (
    session_id uuid NOT NULL, turn_no integer NOT NULL, customer_id text,
    channel text NOT NULL, on_date date NOT NULL,
    customer_text text NOT NULL, agent_text text NOT NULL,
    PRIMARY KEY(session_id,turn_no)
);
CREATE INDEX IF NOT EXISTS memory_turns_customer_idx ON ai_memory.turns(customer_id,on_date DESC);
CREATE TABLE IF NOT EXISTS ai_memory.episodes (
    session_id uuid PRIMARY KEY, customer_id text NOT NULL, channel text NOT NULL,
    on_date date NOT NULL, summary text NOT NULL, outcome text NOT NULL DEFAULT 'khac',
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_episodes_customer_idx ON ai_memory.episodes(customer_id,on_date DESC);
CREATE TABLE IF NOT EXISTS ai_memory.facts (
    fact_id uuid PRIMARY KEY, customer_id text NOT NULL, key text NOT NULL,
    value jsonb, source text NOT NULL, source_session_id uuid NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL CHECK(status IN ('active','superseded','retracted')),
    supersedes_fact_id uuid
);
CREATE UNIQUE INDEX IF NOT EXISTS memory_facts_active_idx ON ai_memory.facts(customer_id,key) WHERE status='active';
CREATE TABLE IF NOT EXISTS ai_memory.order_links (
    customer_id text NOT NULL, order_id text NOT NULL, PRIMARY KEY(customer_id,order_id)
);
-- END 0001_memory

-- BEGIN 0002_operations
CREATE TABLE IF NOT EXISTS runtime.tool_operations (
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
-- END 0002_operations

-- BEGIN 0003_memory_provenance
ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS source_turn_id uuid,
    ADD COLUMN IF NOT EXISTS on_date date,
    ADD COLUMN IF NOT EXISTS source_kind text,
    ADD COLUMN IF NOT EXISTS source_tool text;

CREATE INDEX IF NOT EXISTS memory_facts_customer_date_idx
    ON ai_memory.facts(customer_id, on_date DESC);
-- END 0003_memory_provenance

-- BEGIN 0004_pending_facts
CREATE TABLE IF NOT EXISTS ai_memory.pending_facts (
    session_id uuid NOT NULL,
    source_turn_id uuid NOT NULL,
    turn_no integer NOT NULL,
    key text NOT NULL,
    value jsonb,
    op text NOT NULL CHECK (op IN ('set','delete')),
    source_kind text NOT NULL,
    source_tool text,
    on_date date NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),
    PRIMARY KEY (session_id,source_turn_id,key)
);
CREATE INDEX IF NOT EXISTS memory_pending_session_idx
    ON ai_memory.pending_facts(session_id,turn_no);
CREATE UNIQUE INDEX IF NOT EXISTS memory_facts_source_turn_key_idx
    ON ai_memory.facts(source_session_id,source_turn_id,key)
    WHERE source_turn_id IS NOT NULL;
-- END 0004_pending_facts

-- BEGIN 0005_memory_evidence_quote
ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS evidence_quote text;

ALTER TABLE ai_memory.pending_facts
    ADD COLUMN IF NOT EXISTS evidence_quote text;
-- END 0005_memory_evidence_quote

-- BEGIN 0006_episode_identity_boundary
-- A database that reached the former 0008 migration has already run this
-- one-time repair. Do not rewrite its episode summaries on reapplication.
DO $repair$ BEGIN
IF NOT EXISTS (
    SELECT 1 FROM pg_attribute
    WHERE attrelid = 'ai_memory.facts'::regclass
      AND attname = 'scope_type' AND NOT attisdropped
) THEN
-- Older claim_pending versions assigned the resolved customer to every earlier
-- anonymous turn in the session. Recover the boundary from the first claim and
-- the first commit after it, then restore earlier turns to anonymous ownership.
WITH first_claim AS (
    SELECT LEFT(operation_key, 36)::uuid AS session_id,
           MIN(created_at) AS claimed_at
    FROM ai_memory.write_operations
    WHERE operation_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:.*:claim_pending$'
      AND jsonb_typeof(result->'memory_writes') = 'array'
    GROUP BY LEFT(operation_key, 36)::uuid
), first_verified_turn AS (
    SELECT claim.session_id,
           MIN((operation.result->>'turn_no')::integer) AS turn_no
    FROM first_claim AS claim
    JOIN ai_memory.write_operations AS operation
      ON LEFT(operation.operation_key, 36) = claim.session_id::text
     AND operation.operation_key LIKE '%:commit_turn'
     AND operation.created_at >= claim.claimed_at
     AND operation.result->>'turn_no' ~ '^[0-9]+$'
    GROUP BY claim.session_id
)
UPDATE ai_memory.turns AS turn_row
SET customer_id = NULL
FROM first_claim AS claim
LEFT JOIN first_verified_turn AS verified ON verified.session_id = claim.session_id
WHERE turn_row.session_id = claim.session_id
  AND (verified.turn_no IS NULL OR turn_row.turn_no < verified.turn_no);

-- Rebuild legacy episodes that combined attributed and unattributed turns.
-- Only turns already attributed to the episode owner may enter its summary.
-- Earlier claim_pending versions could also promote anonymous facts. Retract
-- any such active fact before the customer profile is read by the new runtime.
-- The claim result records each inserted fact_id even when the original
-- anonymous commit had no operation key to connect its message to a turn.
UPDATE ai_memory.facts AS fact
SET status = 'retracted'
WHERE fact.status = 'active'
  AND EXISTS (
      SELECT 1 FROM ai_memory.write_operations AS operation
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(operation.result->'memory_writes') = 'array'
               THEN operation.result->'memory_writes' ELSE '[]'::jsonb END
      ) AS written(item)
      WHERE operation.operation_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:.*:claim_pending$'
        AND jsonb_typeof(operation.result->'memory_writes') = 'array'
        AND LEFT(operation.operation_key, 36) = fact.source_session_id::text
        AND written.item->>'fact_id' = fact.fact_id::text
  );

UPDATE ai_memory.facts AS fact
SET status = 'retracted'
WHERE fact.status = 'active'
  AND fact.source_turn_id IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM ai_memory.write_operations AS operation
      JOIN ai_memory.turns AS turn_row
        ON turn_row.session_id = fact.source_session_id
       AND turn_row.turn_no = (operation.result->>'turn_no')::integer
      WHERE operation.operation_key =
            fact.source_session_id::text || ':' || fact.source_turn_id::text || ':commit_turn'
        AND turn_row.customer_id IS NULL
  );

WITH mixed AS (
    SELECT episode.session_id, episode.customer_id
    FROM ai_memory.episodes AS episode
    WHERE EXISTS (
        SELECT 1 FROM ai_memory.turns AS turn_row
        WHERE turn_row.session_id = episode.session_id
          AND turn_row.customer_id IS DISTINCT FROM episode.customer_id
    )
), rebuilt AS (
    SELECT mixed.session_id,
           LEFT(STRING_AGG(
               'Khách: ' || owned.customer_text || ' Trợ lý: ' || owned.agent_text,
               ' | ' ORDER BY owned.turn_no
           ), 800) AS summary
    FROM mixed
    JOIN LATERAL (
        SELECT turn_no, customer_text, agent_text
        FROM ai_memory.turns
        WHERE session_id = mixed.session_id AND customer_id = mixed.customer_id
        ORDER BY turn_no DESC
        LIMIT 3
    ) AS owned ON TRUE
    GROUP BY mixed.session_id
)
UPDATE ai_memory.episodes AS episode
SET summary = rebuilt.summary, updated_at = now()
FROM rebuilt
WHERE episode.session_id = rebuilt.session_id;

-- An episode with no attributed turns has no verified source to summarize.
DELETE FROM ai_memory.episodes AS episode
WHERE EXISTS (
    SELECT 1 FROM ai_memory.turns AS turn_row
    WHERE turn_row.session_id = episode.session_id
      AND turn_row.customer_id IS DISTINCT FROM episode.customer_id
)
AND NOT EXISTS (
    SELECT 1 FROM ai_memory.turns AS turn_row
    WHERE turn_row.session_id = episode.session_id
      AND turn_row.customer_id = episode.customer_id
);
END IF;
END $repair$;
-- END 0006_episode_identity_boundary

-- BEGIN 0007_erasure_requests
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
-- END 0007_erasure_requests

-- BEGIN 0008_scoped_facts
ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS scope_type text NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS scope_id text NOT NULL DEFAULT '';

ALTER TABLE ai_memory.facts DROP CONSTRAINT IF EXISTS memory_fact_scope_valid;

ALTER TABLE ai_memory.facts
    ADD CONSTRAINT memory_fact_scope_valid CHECK (
        (scope_type = 'global' AND scope_id = '') OR
        (scope_type IN ('product', 'room') AND scope_id <> '')
    );

DROP INDEX IF EXISTS ai_memory.memory_facts_active_idx;
CREATE UNIQUE INDEX IF NOT EXISTS memory_facts_scoped_active_idx
    ON ai_memory.facts(customer_id, scope_type, scope_id, key) WHERE status='active';

DROP INDEX IF EXISTS ai_memory.memory_facts_source_turn_key_idx;
CREATE UNIQUE INDEX IF NOT EXISTS memory_facts_source_turn_scope_key_idx
    ON ai_memory.facts(source_session_id, source_turn_id, scope_type, scope_id, key)
    WHERE source_turn_id IS NOT NULL;
-- END 0008_scoped_facts

-- BEGIN 0009_structured_episodes
ALTER TABLE ai_memory.episodes
    ADD COLUMN IF NOT EXISTS topics jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS resolved_prior_items jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed')),
    ADD COLUMN IF NOT EXISTS schema_version integer NOT NULL DEFAULT 1;
-- END 0009_structured_episodes

-- BEGIN 0010_langmem_distillation_jobs
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
-- END 0010_langmem_distillation_jobs

-- BEGIN 0011_langmem_store
CREATE SCHEMA IF NOT EXISTS langmem_store;
REVOKE ALL ON SCHEMA langmem_store FROM PUBLIC;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcp_memory') THEN
        GRANT USAGE ON SCHEMA langmem_store TO mcp_memory;
    END IF;
END $$;
-- END 0011_langmem_store

-- BEGIN 0012_langmem_accepted_writes
-- Verified writes from a completed job for reproducible BTC trace attribution.
ALTER TABLE ai_memory.langmem_distillation_jobs
    ADD COLUMN IF NOT EXISTS accepted_writes jsonb NOT NULL DEFAULT '[]'::jsonb;
-- END 0012_langmem_accepted_writes

-- BEGIN 0013_langmem_job_proposals
-- Persist admitted proposals before multi-step store writes so retries are stable.
ALTER TABLE ai_memory.langmem_distillation_jobs
    ADD COLUMN IF NOT EXISTS accepted_proposals jsonb,
    ADD COLUMN IF NOT EXISTS verified_outcome text NOT NULL DEFAULT 'khac'
        CHECK (verified_outcome IN ('khac', 'hen_goi_lai', 'chot_don', 'tu_choi', 'chuyen_may'));
-- END 0013_langmem_job_proposals
