-- Migration: 002_wiki_scratchpad_seed.sql
-- Seed a welcome scratchpad entry so the dashboard isn't empty
-- Uses WHERE NOT EXISTS so migration is idempotent (migration runner
-- re-runs all files on every container restart).

INSERT INTO documents (source_type, title, content, metadata, tags)
SELECT
    'scratchpad',
    'Welcome',
    'Scratchpad entries appear here. Write quick notes on the dashboard and they get auto-ingested into the wiki.',
    '{"source": "seed"}',
    ARRAY ['scratchpad']
WHERE NOT EXISTS (
    SELECT 1 FROM documents WHERE source_type = 'scratchpad'
);
