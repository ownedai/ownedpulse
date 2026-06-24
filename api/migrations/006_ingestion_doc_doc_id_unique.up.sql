-- G-T1: Add UNIQUE constraint on ingestion_doc(doc_id)
-- trace_emitter.start_doc_trace() uses ON CONFLICT (doc_id) but the table
-- had only a regular index on doc_id, not a unique constraint. Every
-- ingestion attempt failed with "InvalidColumnReference" as a result.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ingestion_doc'::regclass
          AND conname = 'ingestion_doc_doc_id_unique'
    ) THEN
        -- Deduplicate in case any prior ingestion left duplicate doc_id rows
        DELETE FROM ingestion_doc a
        USING ingestion_doc b
        WHERE a.doc_id = b.doc_id
          AND a.created_at < b.created_at;

        ALTER TABLE ingestion_doc ADD CONSTRAINT ingestion_doc_doc_id_unique UNIQUE (doc_id);
    END IF;
END $$;
