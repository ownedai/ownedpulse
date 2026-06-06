-- ============================================================================
-- document_registry table
-- Schema v0.2 — KnowledgeBase pipeline
-- 
-- The registry is the queryable index of every document the pipeline knows
-- about. It replaces the flat REGISTRY dict from the v0.1 design.
--
-- Flat columns for fields used in NocoDB UI filters/sorts/groupings.
-- metadata_json (JSONB) holds the full metadata — source of truth.
-- Flat columns are caches populated from metadata_json on insert/update.
--
-- Per spec $7.2 (KnowledgeBase_Architecture_Schema_Implementation_v1.0.docx)
-- ============================================================================

CREATE TABLE document_registry (
    document_id           TEXT        PRIMARY KEY,
    document_class        TEXT        NOT NULL,
    document_type         TEXT        NOT NULL,
    document_status       TEXT        NOT NULL,    -- final | draft | superseded | retired
    document_version      TEXT,

    archive_path          TEXT        NOT NULL,    -- absolute path to document directory
    source_url            TEXT,
    source_hash           TEXT,
    source_fetched_at     TIMESTAMPTZ,

    -- denormalised flags for fast filtering / listing in NocoDB UI
    issuing_body          TEXT,
    company_id            TEXT,
    gxp_relevance         TEXT,
    gxp_impact            TEXT,

    -- ingestion state
    ingestion_status      TEXT        NOT NULL DEFAULT 'pending',
                                                  -- pending | parsed | chunked | embedded | indexed | failed
    ingestion_error       TEXT,
    chunker_version       TEXT,
    chunk_count           INTEGER,
    last_indexed_at       TIMESTAMPTZ,

    -- full metadata as queryable JSONB
    metadata_json         JSONB       NOT NULL,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_doc_class       ON document_registry(document_class);
CREATE INDEX idx_doc_status      ON document_registry(document_status);
CREATE INDEX idx_ingestion_state ON document_registry(ingestion_status);
CREATE INDEX idx_metadata_gin    ON document_registry USING GIN (metadata_json);
