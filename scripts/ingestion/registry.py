# /opt/scripts/ingestion/registry.py
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


def update_ingestion_status(doc_id: str, status: str, **fields) -> None:
    """Update ingestion_status and optional fields in registry."""
    clauses = ['ingestion_status = %s', 'updated_at = NOW()']
    params = [status]
    for k, v in fields.items():
        clauses.append(f'{k} = %s')
        params.append(v)
    params.append(doc_id)
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE document_registry SET {", ".join(clauses)} WHERE document_id = %s',
                params
            )
