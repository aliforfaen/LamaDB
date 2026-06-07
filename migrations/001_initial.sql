-- LamaDB Initial Migration
-- Core tables: documents, document_links, events, api_keys, feeds, monitor_status

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Universal document store
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    metadata JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_documents_tags ON documents USING GIN (tags);
CREATE INDEX idx_documents_source_type ON documents (source_type);
CREATE INDEX idx_documents_created ON documents (created_at DESC);

-- Typed relationships between documents
CREATE TABLE document_links (
    id BIGSERIAL PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    context TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_links_source ON document_links (source_id);
CREATE INDEX idx_links_target ON document_links (target_id);
CREATE INDEX idx_links_type ON document_links (link_type);

-- Event bus (replaces events.jsonl)
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ DEFAULT now(),
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    title TEXT NOT NULL,
    body TEXT,
    metadata JSONB DEFAULT '{}',
    processed BOOLEAN DEFAULT false
);
CREATE INDEX idx_events_ts ON events (ts DESC);
CREATE INDEX idx_events_source ON events (source);
CREATE INDEX idx_events_severity ON events (severity);
CREATE INDEX idx_events_processed ON events (processed) WHERE NOT processed;

-- Feeds (module: feeds)
CREATE TABLE feeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT,
    filter_tags TEXT[] DEFAULT '{}',
    filter_source_types TEXT[] DEFAULT '{}',
    max_items INT DEFAULT 50,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Monitor status (module: uptime)
CREATE TABLE monitor_status (
    id BIGSERIAL PRIMARY KEY,
    monitor_id TEXT NOT NULL,
    monitor_name TEXT NOT NULL,
    monitor_url TEXT,
    status INT NOT NULL,
    msg TEXT,
    duration_ms INT,
    received_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_monitor_received ON monitor_status (received_at DESC);
CREATE INDEX idx_monitor_id ON monitor_status (monitor_id);

-- API keys for authentication
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'read',
    scopes TEXT[] DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);
