-- Migration: 002_wiki_scratchpad_seed.sql
-- Seed a welcome scratchpad entry so the dashboard isn't empty

INSERT INTO documents (source_type, title, content, metadata, tags)
VALUES (
    'scratchpad',
    'Welcome',
    'Scratchpad entries appear here. Write quick notes on the dashboard and they get auto-ingested into the wiki.',
    '{"source": "seed"}',
    ARRAY ['scratchpad']
)
ON CONFLICT DO NOTHING;
