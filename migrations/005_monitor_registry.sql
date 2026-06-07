-- Monitor Registry: polled data from Uptime Kuma API
-- Stores monitor list + tags fetched periodically to catch new monitors
-- before they send any heartbeats

CREATE TABLE IF NOT EXISTS monitor_registry (
    monitor_id TEXT PRIMARY KEY,
    monitor_name TEXT NOT NULL,
    monitor_url TEXT,
    monitor_type TEXT,
    tags TEXT[] DEFAULT '{}',
    parent_id TEXT,
    active BOOLEAN DEFAULT true,
    last_seen TIMESTAMPTZ DEFAULT now(),
    raw_data JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_registry_tags ON monitor_registry USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_registry_active ON monitor_registry (active);