BEGIN;
ALTER TABLE runtime.turns ADD COLUMN IF NOT EXISTS private_delivery jsonb;
COMMIT;
