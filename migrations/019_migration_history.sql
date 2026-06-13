-- Migration tracking: each file runs exactly once
CREATE TABLE IF NOT EXISTS migration_history (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now(),
    checksum TEXT,
    execution_ms INT
);
