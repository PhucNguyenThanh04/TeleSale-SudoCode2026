ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS source_turn_id uuid,
    ADD COLUMN IF NOT EXISTS on_date date,
    ADD COLUMN IF NOT EXISTS source_kind text,
    ADD COLUMN IF NOT EXISTS source_tool text;

CREATE INDEX IF NOT EXISTS memory_facts_customer_date_idx
    ON ai_memory.facts(customer_id, on_date DESC);
