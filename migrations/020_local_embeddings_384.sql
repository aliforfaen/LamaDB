-- Drop HNSW index before altering vector dimensions
DROP INDEX IF EXISTS idx_documents_embedding_hnsw;

-- Clear existing 1536-dim embeddings (invalid after this migration)
UPDATE documents SET embedding = NULL;

-- Alter vector column from 1536 to 384 dimensions
ALTER TABLE documents ALTER COLUMN embedding TYPE vector(384);

-- Recreate HNSW index with new dimensions
CREATE INDEX idx_documents_embedding_hnsw
ON documents USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
