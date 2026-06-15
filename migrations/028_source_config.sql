-- Migration 028: Per-source event noise configuration
-- Per-source caps to suppress noisy event sources (e.g. dozzle flooding the
-- event stream). 0 = unlimited / never auto-dismiss.
CREATE TABLE IF NOT EXISTS source_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL UNIQUE,
    max_events_per_hour INT DEFAULT 0,       -- 0 = unlimited
    auto_dismiss_after_minutes INT DEFAULT 0, -- 0 = never auto-dismiss
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_source_config_name ON source_config (source_name);
