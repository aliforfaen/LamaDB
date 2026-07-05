-- Audiobookshelf integration: partial unique index for document upserts.
-- The collector stores one document per ABS library item, keyed by
-- (source_type='audiobookshelf', metadata->>'item_id'). This index lets the
-- ON CONFLICT clause in collector.py de-duplicate without locking the whole
-- documents table.

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_audiobookshelf_item_id
ON documents (source_type, (metadata ->> 'item_id'))
WHERE source_type = 'audiobookshelf';