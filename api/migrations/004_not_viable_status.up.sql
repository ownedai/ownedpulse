-- H4: Add not_viable to ingestion_doc status check constraint
-- Allows ingest.py to record the actual disposition instead of masking as 'skipped'.

ALTER TABLE ingestion_doc DROP CONSTRAINT IF EXISTS ingestion_doc_status_check;

ALTER TABLE ingestion_doc ADD CONSTRAINT ingestion_doc_status_check CHECK (
    status IN ('success', 'partial', 'failed', 'running', 'pending', 'error', 'skipped', 'not_viable')
);
