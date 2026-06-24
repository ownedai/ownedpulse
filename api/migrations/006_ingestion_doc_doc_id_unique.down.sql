-- G-T1: Remove UNIQUE constraint on ingestion_doc(doc_id)
ALTER TABLE ingestion_doc DROP CONSTRAINT IF EXISTS ingestion_doc_doc_id_unique;
