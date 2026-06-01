-- G-T1: Ingestion trace schema — reverse migration

DROP TABLE IF EXISTS ingestion_doc;

ALTER TABLE run_log
    DROP CONSTRAINT IF EXISTS run_log_run_id_unique,
    DROP COLUMN IF EXISTS triggered_by,
    DROP COLUMN IF EXISTS workflow_id;
