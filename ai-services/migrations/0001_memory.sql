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
