-- 003_not_viable_recheck: add periodic recheck columns for not_viable documents
ALTER TABLE ingestion_state
    ADD COLUMN IF NOT EXISTS not_viable_retry_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE ingestion_state
    ADD COLUMN IF NOT EXISTS recheck_at TIMESTAMPTZ;

-- Partial index for efficient recheck polling
CREATE INDEX IF NOT EXISTS idx_ingestion_state_recheck
    ON ingestion_state (recheck_at, ingestion_status)
    WHERE ingestion_status = 'not_viable' AND recheck_at IS NOT NULL;
