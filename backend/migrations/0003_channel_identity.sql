ALTER TABLE app_runtime.chat_sessions ADD COLUMN IF NOT EXISTS channel_identity text;
ALTER TABLE app_runtime.chat_sessions ALTER COLUMN caller_phone DROP NOT NULL;
UPDATE app_runtime.chat_sessions SET channel_identity=caller_phone
WHERE channel='hotline' AND channel_identity IS NULL;
