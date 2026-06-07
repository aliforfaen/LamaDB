-- Migration 003: FreshRSS RSS module indexes
-- Index for efficient URL lookups when deduplicating RSS articles

CREATE INDEX IF NOT EXISTS idx_documents_url
    ON documents ((metadata->>'url'))
    WHERE source_type = 'rss_article';
