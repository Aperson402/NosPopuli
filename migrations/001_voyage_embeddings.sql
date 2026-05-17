-- Switch bill_chunks embedding from OpenAI text-embedding-3-small (1536-dim)
-- to Voyage voyage-law-2 (1024-dim).
-- Run this AFTER truncating/re-ingesting bill_chunks.

ALTER TABLE bill_chunks
    ALTER COLUMN embedding TYPE vector(1024);

-- Drop old index if it exists, then recreate for the new dimensions.
DROP INDEX IF EXISTS bill_chunks_embedding_idx;

CREATE INDEX ON bill_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
