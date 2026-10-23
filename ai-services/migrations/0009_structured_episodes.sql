ALTER TABLE ai_memory.episodes
    ADD COLUMN IF NOT EXISTS topics jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS resolved_prior_items jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed')),
    ADD COLUMN IF NOT EXISTS schema_version integer NOT NULL DEFAULT 1;
