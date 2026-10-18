ALTER TABLE ai_memory.facts
    ADD COLUMN IF NOT EXISTS evidence_quote text;

ALTER TABLE ai_memory.pending_facts
    ADD COLUMN IF NOT EXISTS evidence_quote text;
