-- 000_base_schema.sql — base tables required by ownedpulse
-- Run first before incremental migrations 001 through 004.
-- Idempotent — safe to re-run on an existing database.

BEGIN;

-- ── document_registry ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS document_registry (
    document_id          text NOT NULL,
    document_class       text NOT NULL,
    document_type        text NOT NULL,
    document_status      text NOT NULL,
    document_version     text,
    archive_path         text NOT NULL,
    source_url           text,
    source_hash          text,
    source_fetched_at    timestamptz,
    issuing_body         text,
    company_id           text,
    gxp_relevance        text,
    gxp_impact           text,
    metadata_json        jsonb NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    doc_type             text,
    classifier_confidence double precision,
    classified_by        text,
    doc_type_classified_at timestamptz,
    document_family_id   text,
    feed_id              text,
    last_check_status    text,
    corpus_doc           boolean NOT NULL DEFAULT false,
    publication_date     date,
    CONSTRAINT document_registry_doc_type_check CHECK (
        doc_type IS NULL OR doc_type = ANY (ARRAY[
            'guidance','reflection_paper','press_release','safety_alert',
            'drug_approval','news_item','other','training_material','concept_paper'
        ])
    )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'document_registry'::regclass
          AND conname = 'document_registry_pkey'
    ) THEN
        ALTER TABLE document_registry ADD CONSTRAINT document_registry_pkey
            PRIMARY KEY (document_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_doc_class
    ON document_registry (document_class);
CREATE INDEX IF NOT EXISTS idx_doc_status
    ON document_registry (document_status);
CREATE INDEX IF NOT EXISTS idx_document_registry_publication_date
    ON document_registry (publication_date DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_metadata_gin
    ON document_registry USING gin (metadata_json);


-- ── feed_config ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS feed_config (
    feed_id         varchar(50) NOT NULL,
    name            varchar(200) NOT NULL,
    feed_url        text NOT NULL,
    feed_type       varchar(20) NOT NULL DEFAULT 'rss',
    enabled         boolean NOT NULL DEFAULT true,
    last_run_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    authority       text,
    default_doc_type text,
    backfill_months integer NOT NULL DEFAULT 12,
    priority        integer NOT NULL DEFAULT 10,
    ingest_to_rag   boolean NOT NULL DEFAULT true,
    last_success_ts timestamptz,
    last_error      text,
    ich_page_hashes jsonb,
    scraper_config  jsonb,
    CONSTRAINT feed_config_feed_type_check CHECK (
        feed_type = ANY (ARRAY['rss','json_api','json_bulk','html_pagination'])
    )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'feed_config'::regclass
          AND conname = 'feed_config_pkey'
    ) THEN
        ALTER TABLE feed_config ADD CONSTRAINT feed_config_pkey
            PRIMARY KEY (feed_id);
    END IF;
END $$;


-- ── run_log ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS run_log (
    run_id           uuid NOT NULL DEFAULT gen_random_uuid(),
    triggered_at     timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz,
    trigger_source   varchar(20) NOT NULL DEFAULT 'scheduled',
    n8n_execution_id varchar(100),
    feed_source      varchar(50),
    status           varchar(20) NOT NULL DEFAULT 'running',
    items_fetched    integer NOT NULL DEFAULT 0,
    items_new        integer NOT NULL DEFAULT 0,
    items_skipped    integer NOT NULL DEFAULT 0,
    error_count      integer NOT NULL DEFAULT 0,
    duration_ms      integer,
    error_detail     text,
    triggered_by     text,
    workflow_id      text,
    doc_id           text,
    session_id       uuid,
    CONSTRAINT run_log_status_check CHECK (
        status = ANY (ARRAY[
            'success','partial','failed','running','pending','error','skipped'
        ])
    )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'run_log'::regclass
          AND conname = 'run_log_pkey'
    ) THEN
        ALTER TABLE run_log ADD CONSTRAINT run_log_pkey
            PRIMARY KEY (run_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_run_log_status
    ON run_log (status);
CREATE INDEX IF NOT EXISTS idx_run_log_triggered_at
    ON run_log (triggered_at DESC);


-- ── ingestion_state ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingestion_state (
    document_id             text NOT NULL,
    ingestion_status        text NOT NULL,
    ingestion_error         text,
    chunker_version         text,
    chunk_count             integer DEFAULT 0,
    last_indexed_at         timestamptz,
    run_id                  uuid,
    updated_at              timestamptz DEFAULT now(),
    not_viable_retry_count  integer NOT NULL DEFAULT 0,
    recheck_at              timestamptz
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ingestion_state'::regclass
          AND conname = 'ingestion_state_pkey'
    ) THEN
        ALTER TABLE ingestion_state ADD CONSTRAINT ingestion_state_pkey
            PRIMARY KEY (document_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ingestion_state'::regclass
          AND conname = 'ingestion_state_document_id_fkey'
    ) THEN
        ALTER TABLE ingestion_state
            ADD CONSTRAINT ingestion_state_document_id_fkey
            FOREIGN KEY (document_id)
            REFERENCES document_registry(document_id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ingestion_state_status
    ON ingestion_state (ingestion_status);


-- ── system_config ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS system_config (
    key         varchar(100) NOT NULL,
    value       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'system_config'::regclass
          AND conname = 'system_config_pkey'
    ) THEN
        ALTER TABLE system_config ADD CONSTRAINT system_config_pkey
            PRIMARY KEY (key);
    END IF;
END $$;


-- ── document_registry_ext (view) ─────────────────────────────────────

CREATE OR REPLACE VIEW document_registry_ext AS
SELECT
    dr.document_id,
    dr.document_class,
    dr.document_type,
    dr.document_status,
    dr.document_version,
    dr.archive_path,
    dr.source_url,
    dr.source_hash,
    dr.source_fetched_at,
    dr.last_check_status,
    dr.issuing_body,
    dr.company_id,
    dr.gxp_relevance,
    dr.gxp_impact,
    dr.metadata_json,
    dr.doc_type,
    dr.classifier_confidence,
    dr.classified_by,
    dr.doc_type_classified_at,
    dr.document_family_id,
    dr.feed_id,
    dr.corpus_doc,
    dr.publication_date,
    dr.created_at,
    ist.ingestion_status,
    ist.ingestion_error,
    ist.chunker_version,
    ist.chunk_count,
    ist.last_indexed_at,
    ist.run_id,
    ist.updated_at
FROM document_registry dr
LEFT JOIN ingestion_state ist USING (document_id);


COMMIT;
