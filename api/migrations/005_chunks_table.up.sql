-- 005: Create chunks table — Annex 11 §17 compliant chunk archive (dual-write with Qdrant)

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          UUID        PRIMARY KEY,
    document_id       TEXT        NOT NULL,
    chunk_index       INTEGER,
    clause_id         TEXT,
    content_type      TEXT,
    chunk_status      TEXT        NOT NULL DEFAULT 'active',
    chunk_text        TEXT,
    char_offset_start INTEGER,
    char_offset_end   INTEGER,
    page_no           INTEGER,
    bbox              JSONB,
    document_version  TEXT,
    split_from        TEXT,
    split_method      TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_status ON chunks(chunk_status);
