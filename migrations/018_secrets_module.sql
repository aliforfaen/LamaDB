-- 018_secrets_module.sql
-- Encrypted secret storage. Depends on pgcrypto (enabled in migration 017).

-- The secret store — values are encrypted BYTEA columns
CREATE TABLE IF NOT EXISTS secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    description TEXT DEFAULT '',
    secret_type TEXT NOT NULL,
    -- Encrypted value columns
    encrypted_value BYTEA NOT NULL,
    encrypted_extra_1 BYTEA,
    encrypted_extra_2 BYTEA,
    -- Metadata
    priority TEXT NOT NULL DEFAULT 'primary',
    tags TEXT[] DEFAULT '{}',
    owner_user_id UUID REFERENCES users(id),
    owner_group_id UUID REFERENCES groups(id),
    -- Lifecycle
    expires_at TIMESTAMPTZ,
    last_revealed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secrets_service ON secrets(service);
CREATE INDEX IF NOT EXISTS idx_secrets_type ON secrets(secret_type);
CREATE INDEX IF NOT EXISTS idx_secrets_owner_user ON secrets(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_secrets_owner_group ON secrets(owner_group_id);
CREATE INDEX IF NOT EXISTS idx_secrets_tags ON secrets USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_secrets_expires ON secrets(expires_at) WHERE expires_at IS NOT NULL;

-- Explicit access grants (user or group)
CREATE TABLE IF NOT EXISTS secret_access (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    grantee_type TEXT NOT NULL,
    grantee_id UUID NOT NULL,
    access_level TEXT NOT NULL DEFAULT 'read',
    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (secret_id, grantee_type, grantee_id)
);
CREATE INDEX IF NOT EXISTS idx_secret_access_secret ON secret_access(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_access_grantee ON secret_access(grantee_type, grantee_id);

-- Access request workflow
CREATE TABLE IF NOT EXISTS secret_access_requests (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    requester_user_id UUID NOT NULL REFERENCES users(id),
    requested_level TEXT NOT NULL DEFAULT 'read',
    reason TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secret_requests_secret ON secret_access_requests(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_requests_status ON secret_access_requests(status);

-- Audit log
CREATE TABLE IF NOT EXISTS secret_audit_log (
    id BIGSERIAL PRIMARY KEY,
    secret_id UUID NOT NULL REFERENCES secrets(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    action TEXT NOT NULL,
    details TEXT DEFAULT '',
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_secret_audit_secret ON secret_audit_log(secret_id);
CREATE INDEX IF NOT EXISTS idx_secret_audit_user ON secret_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_secret_audit_created ON secret_audit_log(created_at DESC);

-- ─── Master encryption key (server-side, never leaves PostgreSQL) ──────

DO $$
DECLARE
    _key TEXT;
BEGIN
    _key := current_setting('secrets.encryption_key', true);
    IF _key IS NULL THEN
        _key := encode(gen_random_bytes(32), 'hex');
        EXECUTE format('ALTER SYSTEM SET secrets.encryption_key = %L', _key);
        PERFORM pg_reload_conf();
        -- Also set for the current session so reveal_secret_value() works immediately
        PERFORM set_config('secrets.encryption_key', _key, false);
    END IF;
END $$;

-- ─── SECURITY DEFINER function for decryption ──────────────────────────

CREATE OR REPLACE FUNCTION reveal_secret_value(
    p_secret_id UUID,
    p_requesting_user_id UUID
) RETURNS TEXT AS $$
DECLARE
    raw_value TEXT;
BEGIN
    SELECT pgp_sym_decrypt(encrypted_value, current_setting('secrets.encryption_key'))
    INTO raw_value FROM secrets WHERE id = p_secret_id;

    IF raw_value IS NULL THEN
        RAISE EXCEPTION 'Decryption failed for secret %', p_secret_id;
    END IF;

    INSERT INTO secret_audit_log (secret_id, user_id, action, details)
    VALUES (p_secret_id, p_requesting_user_id, 'reveal', 'decrypted via reveal_secret_value()');

    UPDATE secrets SET last_revealed_at = now() WHERE id = p_secret_id;

    RETURN raw_value;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ─── SSE NOTIFY triggers ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION notify_secret_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('secret_updated', json_build_object(
        'id', COALESCE(NEW.id, OLD.id),
        'action', TG_OP
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS secret_notify_trigger ON secrets;
CREATE TRIGGER secret_notify_trigger
    AFTER INSERT OR UPDATE OR DELETE ON secrets
    FOR EACH ROW EXECUTE FUNCTION notify_secret_change();

CREATE OR REPLACE FUNCTION notify_secret_request_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('secret_request_updated', json_build_object(
        'id', COALESCE(NEW.id, OLD.id),
        'action', TG_OP
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS secret_request_notify_trigger ON secret_access_requests;
CREATE TRIGGER secret_request_notify_trigger
    AFTER INSERT OR UPDATE ON secret_access_requests
    FOR EACH ROW EXECUTE FUNCTION notify_secret_request_change();
