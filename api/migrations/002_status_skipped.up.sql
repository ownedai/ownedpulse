-- Add 'skipped' to status check constraints on run_log and ingestion_doc.
-- Required for binary/unsupported-format documents (e.g. XLSX) that are
-- intentionally skipped during ingestion rather than failing.

ALTER TABLE run_log DROP CONSTRAINT IF EXISTS run_log_status_check;
ALTER TABLE run_log ADD CONSTRAINT run_log_status_check
    CHECK (status IN ('success','partial','failed','running','pending','error','skipped'));

ALTER TABLE ingestion_doc DROP CONSTRAINT IF EXISTS ingestion_doc_status_check;
ALTER TABLE ingestion_doc ADD CONSTRAINT ingestion_doc_status_check
    CHECK (status IN ('success','partial','failed','running','pending','error','skipped'));
