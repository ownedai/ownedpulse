-- G-T1: Ingestion trace schema — forward migration
-- Extends run_log (existing trace-level table) + creates ingestion_doc (document-span table)

-- 1. Extend run_log with missing trace-level fields + unique constraint on run_id
ALTER TABLE run_log
    ADD COLUMN IF NOT EXISTS triggered_by TEXT,
    ADD COLUMN IF NOT EXISTS workflow_id  TEXT;

-- run_id must be unique for FK references (its values are UUIDs, unique in practice)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'run_log'::regclass
          AND conname = 'run_log_run_id_unique'
    ) THEN
        ALTER TABLE run_log ADD CONSTRAINT run_log_run_id_unique UNIQUE (run_id);
    END IF;
END $$;

-- 2. Create ingestion_doc — one row per document per ingestion run
CREATE TABLE IF NOT EXISTS ingestion_doc (
    span_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id         UUID NOT NULL REFERENCES run_log(run_id),
    doc_id           TEXT NOT NULL,
    source_url       TEXT,
    fetched_at       TIMESTAMPTZ,
    parsed_at        TIMESTAMPTZ,
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    embedding_model  TEXT,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    failure_reason   TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_doc_trace_id ON ingestion_doc(trace_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_doc_doc_id   ON ingestion_doc(doc_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_doc_status    ON ingestion_doc(status);
