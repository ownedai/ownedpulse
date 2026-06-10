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
    - Are scheduled for periodic recheck (7d, 14d, 28d, 56d, 112d backoff)
    - After 5 failed rechecks, are permanently abandoned
    - Remain in document_registry for audit purposes
    - Can be manually reset to 'pending' for immediate retry
    """
    with pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT not_viable_retry_count FROM ingestion_state WHERE document_id = %s",
                (doc_id,)
            )
            row = cur.fetchone()
            current_retry = row[0] if row else 0

            if current_retry == 0:
                days = 7
                new_retry_count = 1
            else:
                days = min(7 * (2 ** current_retry), 112)
                new_retry_count = current_retry + 1

            cur.execute(
                """INSERT INTO ingestion_state
                   (document_id, ingestion_status, ingestion_error, updated_at,
                    not_viable_retry_count, recheck_at)
                   VALUES (%s, 'not_viable', %s, NOW(), %s, NOW() + (%s || ' days')::INTERVAL)
                   ON CONFLICT (document_id) DO UPDATE SET
                       ingestion_status = 'not_viable',
                       ingestion_error  = EXCLUDED.ingestion_error,
                       not_viable_retry_count = EXCLUDED.not_viable_retry_count,
                       recheck_at = EXCLUDED.recheck_at,
                       updated_at = NOW()""",
                (doc_id, f"Not viable: {reason}", new_retry_count, str(days)),
            )


def get_docs_due_for_not_viable_recheck(feed_id: str = None, limit: int = 20) -> list:
    """Return document_ids of not_viable docs due for periodic recheck.

    Excludes docs that have exceeded max retries (not_viable_retry_count >= 5).
    """
    with pg_conn() as conn:
        with conn.cursor() as cur:
            if feed_id:
                cur.execute(
                    """SELECT s.document_id
                       FROM ingestion_state s
                       JOIN document_registry d USING (document_id)
                       WHERE s.ingestion_status = 'not_viable'
                         AND s.recheck_at <= NOW()
                         AND s.not_viable_retry_count < 5
                         AND d.feed_id = %s
                       ORDER BY s.recheck_at ASC
                       LIMIT %s""",
                    (feed_id, limit),
                )
            else:
                cur.execute(
                    """SELECT document_id
                       FROM ingestion_state
                       WHERE ingestion_status = 'not_viable'
                         AND recheck_at <= NOW()
                         AND not_viable_retry_count < 5
                       ORDER BY recheck_at ASC
                       LIMIT %s""",
                    (limit,),
                )
            return [r[0] for r in cur.fetchall()]


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
