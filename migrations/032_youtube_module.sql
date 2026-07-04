-- YouTube integration: add unique constraint on source_type + metadata for upserts
-- The YouTube collector uses source_type='youtube' and stores video_id inside
-- metadata as a natural key. We add a unique index so ON CONFLICT can de-duplicate.

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_youtube_video_id
ON documents (source_type, (metadata ->> 'video_id'))
WHERE source_type = 'youtube';
