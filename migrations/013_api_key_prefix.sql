-- O(1) API key lookup via prefix hash.
-- Stores SHA-256 hash of the first 16 chars of each key (non-secret)
-- so authentication can look up exactly one row before doing the
-- single bcrypt verification. Replaces the previous O(N) full scan
-- over all active keys.
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS key_prefix TEXT;
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys (key_prefix) WHERE key_prefix IS NOT NULL AND active = true;
