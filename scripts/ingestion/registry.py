# /opt/scripts/ingestion/registry.py
#
# ingestion_status taxonomy:
#   pending    — awaiting ingestion
#   running    — ingestion in progress
#   success    — ingested successfully
#   indexed    — legacy alias for success (pre-v0.8)
#   partial    — ingested with warnings (some chunks failed)
#   failed     — technical failure (will retry automatically)
#   not_viable — content insufficient for ingestion (will NOT retry automatically)
#                e.g. thin navigation pages, JS-only pages, boilerplate-only content
#                To retry: manually set ingestion_status = 'pending' after source changes
#   superseded — document version superseded by a newer version
import os
from contextlib import contextmanager
from pathlib import Path
import psycopg2
import psycopg2.extras
from .config import PG_DSN

_HOST_ARCHIVE_ROOT = "/mnt/data/regulatory_archive"
_ARCHIVE_ROOT = str(Path(os.environ.get("ARCHIVE_ROOT", _HOST_ARCHIVE_ROOT)))


def _rewrite_path(p: str) -> str:
    """Rewrite host-side archive path to container mount path."""
    if p and p.startswith(_HOST_ARCHIVE_ROOT) and _ARCHIVE_ROOT != _HOST_ARCHIVE_ROOT:
        return _ARCHIVE_ROOT + p[len(_HOST_ARCHIVE_ROOT):]
    return p


@contextmanager
def pg_conn():
    """PostgreSQL connection context manager. Auto-commit/rollback/close."""
    conn = psycopg2.connect(PG_DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_metadata(doc_id: str) -> dict:
    """Load document metadata from registry. Returns metadata_json + archive_path."""
    with pg_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                'SELECT metadata_json, archive_path FROM document_registry WHERE document_id = %s',
                (doc_id,)
            )
            row = cur.fetchone()
    if not row:
        raise ValueError(f'Document not in registry: {doc_id}')
    meta = dict(row['metadata_json'])
    meta['archive_path'] = _rewrite_path(row['archive_path'] or '')
    # source_local_path in metadata_json also stores the host path
    if meta.get('source_local_path'):
        meta['source_local_path'] = _rewrite_path(meta['source_local_path'])
    if meta.get('source_pdf_path'):
        meta['source_pdf_path'] = _rewrite_path(meta['source_pdf_path'])
    return meta


def mark_document_not_viable(doc_id: str, reason: str) -> None:
    """Mark a document as not_viable in the registry.

    not_viable means the document was fetched and parsed successfully but did
    not contain sufficient substantive content for ingestion (e.g. a thin
    navigation page, a JS-rendered page with no static text, or a document
    where HTML cleaning left insufficient text).

    not_viable documents:
    - Are NOT retried on the next scheduled run
    - Are NOT ingested into Qdrant
    - Remain in document_registry for audit purposes
    - Can be manually reset to 'pending' for retry after source content changes
    """
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE document_registry
                   SET ingestion_status = 'not_viable',
                       ingestion_error = %s,
                       updated_at = NOW()
                   WHERE document_id = %s""",
                (f"Not viable: {reason}", doc_id),
            )


def update_ingestion_status(doc_id: str, status: str, **fields) -> None:
    """Update ingestion_status and optional fields in ingestion_state."""
    # GATE3b: write to ingestion_state instead of document_registry
    insert_cols = ['document_id', 'ingestion_status', 'updated_at']
    insert_vals = ['%s', '%s', 'NOW()']
    update_clauses = ['ingestion_status = EXCLUDED.ingestion_status', 'updated_at = NOW()']
    params = [doc_id, status]
    for k, v in fields.items():
        insert_cols.append(k)
        insert_vals.append('%s')
        update_clauses.append(f'{k} = EXCLUDED.{k}')
        params.append(v)
    sql = (
        f"INSERT INTO ingestion_state ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(insert_vals)}) "
        f"ON CONFLICT (document_id) DO UPDATE SET {', '.join(update_clauses)}"
    )
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
