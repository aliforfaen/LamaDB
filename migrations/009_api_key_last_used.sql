-- Add last_used_at column to api_keys for tracking key usage
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_api_keys_last_used ON api_keys (last_used_at DESC);
