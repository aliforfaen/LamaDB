-- Add HNSW index on documents.embedding for fast cosine similarity search.
-- pgvector supports HNSW (Hierarchical Navigable Small World) indexes.
-- The vector(1536) column already exists from 001_initial.sql.

CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
ON documents USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
