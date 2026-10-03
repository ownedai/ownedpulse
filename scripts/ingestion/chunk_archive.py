"""
chunk_archive.py
PostgreSQL chunk archive — dual-write companion to Qdrant.
Provides Annex 11 §17 compliant chunk storage and query provenance foundation.
"""

import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)

INSERT_SQL = """
INSERT INTO chunks (
    chunk_id, document_id, chunk_index, clause_id, content_type,
    chunk_status, chunk_text, char_offset_start, char_offset_end,
    page_no, bbox, document_version, split_from, split_method
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET
    chunk_status      = EXCLUDED.chunk_status,
    char_offset_start = EXCLUDED.char_offset_start,
    char_offset_end   = EXCLUDED.char_offset_end,
    document_version  = EXCLUDED.document_version,
    updated_at        = NOW()
"""

DELETE_SQL = "DELETE FROM chunks WHERE chunk_id = ANY(%s::uuid[])"


def _get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "knowledge_base"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


def upsert_chunks_pg(points) -> None:
    """
    Write or update chunk records in PostgreSQL.
    Raises on failure — callers must handle and treat as ingestion error.
    Both Qdrant and PostgreSQL must succeed for ingestion to be marked indexed.
    """
    conn = _get_conn()
    cur = conn.cursor()
    rows = []
    for point in points:
        p = point.payload
        bbox = p.get("bbox")
        rows.append((
            str(point.id),
            p.get("document_id", ""),
            p.get("chunk_index"),
            p.get("clause_id"),
            p.get("content_type"),
            p.get("chunk_status", "active"),
            p.get("chunk_text", ""),
            p.get("char_offset_start"),
            p.get("char_offset_end"),
            p.get("page_no"),
            json.dumps(bbox) if bbox else None,
            p.get("document_version"),
            p.get("split_from"),
            p.get("split_method"),
        ))
    cur.executemany(INSERT_SQL, rows)
    conn.commit()
    cur.close()
    conn.close()


def delete_chunks_pg(chunk_ids: List[str]) -> None:
    """Delete chunk records from PostgreSQL by chunk_id. Never raises."""
    if not chunk_ids:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(DELETE_SQL, (chunk_ids,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        logger.warning("chunk_archive: delete failed — PG write skipped", exc_info=True)


SUPERSEDE_SQL = """
UPDATE chunks
SET chunk_status = 'superseded',
    updated_at   = NOW()
WHERE chunk_id = ANY(%s::uuid[]);
"""


def supersede_chunks_pg(chunk_ids: list) -> None:
    """Mark chunk records as superseded in PostgreSQL. Never raises — logs on failure."""
    if not chunk_ids:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(SUPERSEDE_SQL, (chunk_ids,))
        affected = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        logger.debug(f"chunk_archive: marked {affected} chunks as superseded in PostgreSQL")
    except Exception as e:
        logger.error(f"chunk_archive: supersede failed: {e}")
