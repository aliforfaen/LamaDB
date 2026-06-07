-- Migration 006: Smart Notification Routing tables
-- Notification rules
CREATE TABLE IF NOT EXISTS notification_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT true,
    -- Match conditions (AND logic — all must match)
    match_source TEXT,          -- exact match on events.source (NULL = any)
    match_type TEXT,            -- exact match on events.type
    match_severity TEXT,        -- exact match: info, warn, critical
    match_tags TEXT[] DEFAULT '{}',  -- event must have ALL these tags
    -- Delivery
    channel TEXT NOT NULL,      -- 'telegram', 'ntfy', 'webhook'
    channel_config JSONB DEFAULT '{}',  -- channel-specific config
    -- Priority override
    priority TEXT DEFAULT 'normal',  -- low, normal, high, critical
    -- Cooldown
    cooldown_seconds INT DEFAULT 0,  -- 0 = no cooldown, fire every time
    -- Tracking
    last_fired_at TIMESTAMPTZ,
    fire_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rules_enabled ON notification_rules (enabled);
CREATE INDEX IF NOT EXISTS idx_rules_source ON notification_rules (match_source);

-- Notification log (audit trail)
CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    rule_id UUID REFERENCES notification_rules(id) ON DELETE SET NULL,
    event_id BIGINT,             -- REFERENCES events(id) — nullable, events may be deleted
    channel TEXT NOT NULL,
    status TEXT NOT NULL,        -- 'sent', 'failed', 'cooldown', 'no_match'
    message TEXT,
    error TEXT,
    fired_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notif_log_fired ON notification_log (fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_log_rule ON notification_log (rule_id);
