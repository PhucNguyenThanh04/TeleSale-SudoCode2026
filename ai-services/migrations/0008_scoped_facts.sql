ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS scope_type text NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS scope_id text NOT NULL DEFAULT '';

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
