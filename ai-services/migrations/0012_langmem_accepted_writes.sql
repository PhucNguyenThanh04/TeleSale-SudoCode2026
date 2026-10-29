-- Verified writes from a completed job for reproducible BTC trace attribution.
ALTER TABLE ai_memory.langmem_distillation_jobs
    ADD COLUMN IF NOT EXISTS accepted_writes jsonb NOT NULL DEFAULT '[]'::jsonb;
