-- Keep anonymous-turn evidence until trusted identity can queue enrichment.
BEGIN;
ALTER TABLE runtime.turns
    ADD COLUMN IF NOT EXISTS tool_observations jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS verified_outcome text NOT NULL DEFAULT 'khac';
COMMIT;
