-- 003_not_viable_recheck rollback
DROP INDEX IF EXISTS idx_ingestion_state_recheck;
ALTER TABLE ingestion_state DROP COLUMN IF EXISTS recheck_at;
ALTER TABLE ingestion_state DROP COLUMN IF EXISTS not_viable_retry_count;
