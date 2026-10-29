-- Persist admitted proposals before multi-step store writes so retries are stable.
ALTER TABLE ai_memory.langmem_distillation_jobs
    ADD COLUMN IF NOT EXISTS accepted_proposals jsonb,
    ADD COLUMN IF NOT EXISTS verified_outcome text NOT NULL DEFAULT 'khac'
        CHECK (verified_outcome IN ('khac', 'hen_goi_lai', 'chot_don', 'tu_choi', 'chuyen_may'));
