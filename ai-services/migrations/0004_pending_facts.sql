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
