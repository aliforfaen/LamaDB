-- Migration 002: Add ticker support to events table
-- Adds ticker flag and tags array for dashboard marquee support

ALTER TABLE events ADD COLUMN IF NOT EXISTS ticker BOOLEAN DEFAULT false;
ALTER TABLE events ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events (ts DESC) WHERE ticker = true;
CREATE INDEX IF NOT EXISTS idx_events_tags ON events USING GIN (tags);
