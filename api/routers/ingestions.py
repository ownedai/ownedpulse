"""Ingestions router — /api/ingestions/ routes for G3 ingestion log page."""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_base")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
SESSION_SOURCES = ("bootstrap_ui", "manual_cli")
RSS_SOURCES = ("n8n_rss", "scheduled", "manual")

# UI category → internal trigger_source values
SOURCE_CATEGORIES = {
    "scheduled": ("n8n_rss", "scheduled"),
    "manual": ("manual_cli", "bootstrap_ui", "manual"),
}


def get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )


def _fmt_dt(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


# ── GET /ingestions ───────────────────────────────────────────────────────────


@router.get("")
async def list_ingestions(
    status: str | None = Query(None),
    source: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Unified ingestion list: session groups (bulk) + RSS runs.

    Grouped by session_id — all docs in one bootstrap/share the same session UUID.
    RSS runs and manual CLI use their run_id as the implicit session key.
    """
    try:
        conn = get_pg_conn()
        cur = conn.cursor()

        # ── Session groups: grouped by COALESCE(session_id, run_id) ─────────
        sg_where = ["trigger_source = ANY(%s)"]
        sg_params: list = [list(SESSION_SOURCES)]
        if status:
            # Pre-filter: sessions are a mix — filter post-group
            pass
        if source:
            allowed = SOURCE_CATEGORIES.get(source, (source,))
            sg_where.append("trigger_source = ANY(%s)")
            sg_params.append(list(allowed))
        if date_from:
            sg_where.append("triggered_at >= %s::timestamptz")
            sg_params.append(date_from)
        if date_to:
            sg_where.append("triggered_at <= %s::timestamptz + INTERVAL '1 day'")
            sg_params.append(date_to)

        cur.execute(
            f"""
            SELECT
                COALESCE(session_id, run_id)::text AS group_id,
                MIN(trigger_source) AS trigger_source,
                MIN(triggered_at) AS triggered_at,
                COUNT(*) AS doc_count,
                COUNT(*) FILTER (WHERE status = 'success') AS doc_count_succeeded,
                COUNT(*) FILTER (WHERE status IN ('error', 'failed')) AS doc_count_failed
            FROM run_log
            WHERE {' AND '.join(sg_where)}
            GROUP BY COALESCE(session_id, run_id)
            ORDER BY MIN(triggered_at) DESC
            """,
            sg_params
        )
        session_groups = []
        for row in cur.fetchall():
            gid, ts, triggered_at, cnt, succeeded, failed = row
            if failed == 0:
                grp_status = "success"
            elif succeeded == 0:
                grp_status = "error"
            else:
                grp_status = "partial"
            session_groups.append({
                "type": "session_group",
                "run_token": gid,
                "source": ts,
                "triggered_at": _fmt_dt(triggered_at),
                "status": grp_status,
                "doc_count": cnt,
                "doc_count_succeeded": succeeded,
                "doc_count_failed": failed,
            })

        # Apply status filter post-grouping
        if status:
            session_groups = [sg for sg in session_groups if sg["status"] == status]

        # ── RSS runs: each run_log row for rss/scheduled sources ───────────
        rss_where = ["trigger_source = ANY(%s)"]
        rss_params: list = [list(RSS_SOURCES)]
        if date_from:
            rss_where.append("triggered_at >= %s::timestamptz")
            rss_params.append(date_from)
        if date_to:
            rss_where.append("triggered_at <= %s::timestamptz + INTERVAL '1 day'")
            rss_params.append(date_to)
        if status:
            rss_where.append("status = %s")
            rss_params.append(status)
        if source:
            allowed = SOURCE_CATEGORIES.get(source, (source,))
            rss_where.append("trigger_source = ANY(%s)")
            rss_params.append(list(allowed))

        cur.execute(
            f"""
            SELECT run_id, trigger_source, triggered_at, feed_source,
                   status, items_new, items_skipped, error_count, duration_ms, error_detail
            FROM run_log
            WHERE {' AND '.join(rss_where)}
            ORDER BY triggered_at DESC
            """,
            rss_params
        )
        rss_runs = []
        for row in cur.fetchall():
            run_id, ts, triggered_at, feed_source, run_status, items_new, items_skipped, error_count, duration_ms, error_detail = row
            rss_runs.append({
                "type": "rss_run",
                "run_id": str(run_id),
                "source": ts,
                "triggered_at": _fmt_dt(triggered_at),
                "feed_name": feed_source or "—",
                "status": run_status,
                "doc_count_new": items_new or 0,
                "doc_count_skipped": items_skipped or 0,
                "doc_count_errors": error_count or 0,
                "duration_seconds": round(duration_ms / 1000, 1) if duration_ms else None,
                "error_detail": error_detail or None,
            })

        cur.close()
        conn.close()

        # Merge and sort by triggered_at desc
        all_items = session_groups + rss_runs
        all_items.sort(key=lambda x: x["triggered_at"] or "", reverse=True)

        total = len(all_items)
        offset = (page - 1) * page_size
        page_items = all_items[offset: offset + page_size]

        return {"items": page_items, "total": total, "page": page, "page_size": page_size}

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# ── GET /ingestions/sessions/{run_token}/documents ────────────────────────────

@router.get("/sessions/{run_token}/documents")
async def session_documents(
    run_token: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """Documents ingested in a session group (bootstrap/manual bulk).

    run_token is the session_id (UUID) or run_id that groups the ingestion run.
    """
    conn = get_pg_conn()
    cur = conn.cursor()

    # Find all run_log rows sharing this session_id or matching this run_id
    cur.execute(
        """
        SELECT run_id FROM run_log
        WHERE session_id = %s::uuid OR run_id = %s::uuid
        """,
        (run_token, run_token)
    )
    run_ids = [str(row[0]) for row in cur.fetchall()]
    if not run_ids:
        cur.close()
        conn.close()
        return {"run_token": run_token, "items": [], "total": 0, "page": page, "page_size": page_size}

    # Count unique docs from ingestion_doc (normal path)
    cur.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM ingestion_doc WHERE trace_id::text = ANY(%s)",
        (run_ids,)
    )
    traced_count = cur.fetchone()[0]

    if traced_count > 0:
        # Normal path — ingestion_doc has rows
        cur.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (id.doc_id)
                    id.doc_id,
                    COALESCE(dr.metadata_json->>'document_title', dr.metadata_json->>'title', id.doc_id) AS document_title,
                    COALESCE(dr.issuing_body, '') AS agency,
                    COALESCE(dr.doc_type, '') AS doc_type,
                    id.status AS ingestion_status,
                    id.chunk_count,
                    id.failure_reason,
                    id.trace_id::text,
                    id.source_url,
                    id.fetched_at,
                    id.parsed_at,
                    id.created_at AS ingested_at,
                    id.embedding_model,
                    COUNT(*) OVER (PARTITION BY id.doc_id) AS retry_count,
                    FIRST_VALUE(id.status) OVER (PARTITION BY id.doc_id ORDER BY id.created_at ASC) AS first_attempt_status
                FROM ingestion_doc id
                LEFT JOIN document_registry dr ON dr.document_id = id.doc_id
                WHERE id.trace_id::text = ANY(%s)
                ORDER BY id.doc_id, id.created_at DESC
            ) sub
            ORDER BY CASE WHEN ingestion_status IN ('error', 'failed') THEN 0 ELSE 1 END ASC, ingested_at DESC
            LIMIT %s OFFSET %s
            """,
            (run_ids, page_size, (page - 1) * page_size)
        )
        items = []
        for row in cur.fetchall():
            (doc_id, document_title, agency, doc_type, ingestion_status,
             chunk_count, failure_reason, trace_id, source_url,
             fetched_at, parsed_at, ingested_at, embedding_model,
             retry_count, first_attempt_status) = row
            items.append({
                "doc_id": doc_id,
                "document_title": document_title or doc_id,
                "agency": agency,
                "doc_type": doc_type,
                "ingestion_status": ingestion_status,
                "chunk_count": chunk_count or 0,
                "failure_reason": failure_reason,
                "trace_id": trace_id,
                "source_url": source_url,
                "fetched_at": _fmt_dt(fetched_at),
                "parsed_at": _fmt_dt(parsed_at),
                "ingested_at": _fmt_dt(ingested_at),
                "embedding_model": embedding_model,
                "retry_count": int(retry_count),
                "has_retries": int(retry_count) > 1,
                "first_attempt_status": first_attempt_status,
            })
        total = traced_count
    else:
        # Fallback — ingestion_doc has no rows (subprocess crashed before
        # creating document spans). Synthesize entries from run_log rows.
        cur.execute(
            """
            SELECT rl.run_id, rl.doc_id, rl.status, rl.error_detail,
                   COALESCE(dr.metadata_json->>'document_title', dr.metadata_json->>'title') AS document_title,
                   COALESCE(dr.issuing_body, '') AS agency,
                   COALESCE(dr.doc_type, '') AS doc_type
            FROM run_log rl
            LEFT JOIN document_registry dr ON dr.document_id = rl.doc_id
            WHERE rl.run_id::text = ANY(%s)
            ORDER BY CASE WHEN rl.status IN ('error', 'failed') THEN 0 ELSE 1 END ASC,
                     rl.triggered_at DESC
            LIMIT %s OFFSET %s
            """,
            (run_ids, page_size, (page - 1) * page_size)
        )
        items = []
        for row in cur.fetchall():
            rid, doc_id, status, error_detail, title, agency, doc_type = row
            display_id = doc_id or str(rid)
            items.append({
                "doc_id": display_id,
                "document_title": title or display_id,
                "agency": agency or "",
                "doc_type": doc_type or "",
                "ingestion_status": status,
                "chunk_count": 0,
                "failure_reason": error_detail,
                "trace_id": str(rid),
                "source_url": None,
                "fetched_at": None,
                "parsed_at": None,
                "ingested_at": None,
                "embedding_model": None,
                "retry_count": 1,
                "has_retries": False,
                "first_attempt_status": None,
            })

        cur.execute(
            "SELECT COUNT(*) FROM run_log WHERE run_id::text = ANY(%s)",
            (run_ids,)
        )
        total = cur.fetchone()[0]

    cur.close()
    conn.close()
    return {"run_token": run_token, "items": items, "total": total, "page": page, "page_size": page_size}


# ── GET /ingestions/runs/{run_id} ────────────────────────────────────────────

@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Single run_log row — used by inline trace viewer."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT run_id, trigger_source, feed_source, status,
                   triggered_at, completed_at, items_fetched,
                   items_new, items_skipped, error_count, duration_ms, error_detail
            FROM run_log WHERE run_id = %s::uuid
            """,
            (run_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        (rid, trigger_source, feed_source, status,
         triggered_at, completed_at, items_fetched,
         items_new, items_skipped, error_count, duration_ms, error_detail) = row
        return {
            "run_id": str(rid),
            "trigger_source": trigger_source,
            "feed_source": feed_source,
            "status": status,
            "triggered_at": _fmt_dt(triggered_at),
            "completed_at": _fmt_dt(completed_at),
            "items_fetched": items_fetched or 0,
            "items_new": items_new or 0,
            "items_skipped": items_skipped or 0,
            "error_count": error_count or 0,
            "duration_ms": duration_ms,
            "error_detail": error_detail,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# ── GET /ingestions/runs/{run_id}/documents ───────────────────────────────────

@router.get("/runs/{run_id}/documents")
async def run_documents(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """Documents ingested in a specific RSS run."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(DISTINCT doc_id) FROM ingestion_doc WHERE trace_id::text = %s",
            (run_id,)
        )
        traced_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (id.doc_id)
                    id.doc_id,
                    COALESCE(dr.metadata_json->>'document_title', dr.metadata_json->>'title', id.doc_id) AS document_title,
                    COALESCE(dr.issuing_body, '') AS agency,
                    COALESCE(dr.doc_type, '') AS doc_type,
                    id.status AS ingestion_status,
                    id.chunk_count,
                    id.failure_reason,
                    id.trace_id::text,
                    id.source_url,
                    id.fetched_at,
                    id.parsed_at,
                    id.created_at AS ingested_at,
                    id.embedding_model,
                    COUNT(*) OVER (PARTITION BY id.doc_id) AS retry_count,
                    FIRST_VALUE(id.status) OVER (PARTITION BY id.doc_id ORDER BY id.created_at ASC) AS first_attempt_status
                FROM ingestion_doc id
                LEFT JOIN document_registry dr ON dr.document_id = id.doc_id
                WHERE id.trace_id::text = %s
                ORDER BY id.doc_id, id.created_at DESC
            ) sub
            ORDER BY CASE WHEN ingestion_status IN ('error', 'failed') THEN 0 ELSE 1 END ASC, ingested_at DESC
            LIMIT %s OFFSET %s
            """,
            (run_id, page_size, (page - 1) * page_size)
        )
        items = []
        traced_doc_ids = set()
        for row in cur.fetchall():
            (doc_id, document_title, agency, doc_type, ingestion_status,
             chunk_count, failure_reason, trace_id, source_url,
             fetched_at, parsed_at, ingested_at, embedding_model,
             retry_count, first_attempt_status) = row
            traced_doc_ids.add(doc_id)
            items.append({
                "doc_id": doc_id,
                "document_title": document_title or doc_id,
                "agency": agency,
                "doc_type": doc_type,
                "ingestion_status": ingestion_status,
                "chunk_count": chunk_count or 0,
                "failure_reason": failure_reason,
                "trace_id": trace_id,
                "source_url": source_url,
                "fetched_at": _fmt_dt(fetched_at),
                "parsed_at": _fmt_dt(parsed_at),
                "ingested_at": _fmt_dt(ingested_at),
                "embedding_model": embedding_model,
                "retry_count": int(retry_count),
                "has_retries": int(retry_count) > 1,
                "first_attempt_status": first_attempt_status,
            })

        # Fallback: supplement with document_registry when ingestion_doc has no entries
        # or fewer than expected. RSS runs created by fetch_feed.py don't write to
        # ingestion_doc — those entries only exist after run_ingest.py traces them.
        # Look up the run's feed_source and time window to find the relevant docs.
        cur.execute(
            """SELECT feed_source, triggered_at, completed_at, items_new
               FROM run_log WHERE run_id = %s::uuid""",
            (run_id,)
        )
        run_row = cur.fetchone()
        if run_row:
            feed_source, triggered_at, completed_at, items_new = run_row
            items_new = items_new or 0
            if feed_source and triggered_at and traced_count < items_new:
                end_ts = completed_at or triggered_at
                cur.execute(
                    """SELECT document_id,
                              COALESCE(metadata_json->>'document_title', metadata_json->>'title', document_id) AS title,
                              issuing_body,
                              COALESCE(doc_type, '') AS doc_type,
                              ingestion_status,
                              chunk_count,
                              ingestion_error,
                              source_url,
                              created_at
                       FROM document_registry_ext
                       WHERE feed_id = %s
                         AND created_at >= %s::timestamptz - INTERVAL '24 hours'
                         AND created_at <= %s::timestamptz + INTERVAL '24 hours'
                       ORDER BY created_at DESC""",
                    (feed_source, triggered_at, end_ts)
                )
                for row in cur.fetchall():
                    doc_id, title, agency, doc_type, status, chunks, err, url, created_at = row
                    if doc_id not in traced_doc_ids:
                        items.append({
                            "doc_id": doc_id,
                            "document_title": title or doc_id,
                            "agency": agency or "",
                            "doc_type": doc_type or "",
                            "ingestion_status": status,
                            "chunk_count": chunks or 0,
                            "failure_reason": err,
                            "trace_id": None,
                            "source_url": url,
                            "fetched_at": None,
                            "parsed_at": None,
                            "ingested_at": _fmt_dt(created_at),
                            "embedding_model": None,
                            "retry_count": 1,
                            "has_retries": False,
                            "first_attempt_status": None,
                        })

        total = len(items)
        cur.close()
        conn.close()
        return {"run_id": run_id, "items": items, "total": total, "page": page, "page_size": page_size}

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# ── GET /ingestions/spans/{doc_id} ───────────────────────────────────────────

@router.get("/spans/{doc_id:path}")
async def doc_spans(doc_id: str):
    """All ingestion spans for a specific doc_id, oldest-first. Used for retry history."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT span_id, status, failure_reason, created_at, chunk_count
            FROM ingestion_doc
            WHERE doc_id = %s
            ORDER BY created_at ASC
            """,
            (doc_id,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            raise HTTPException(status_code=404, detail="No spans found for doc_id")
        items = []
        for i, row in enumerate(rows, start=1):
            span_id, status, failure_reason, created_at, chunk_count = row
            items.append({
                "attempt": i,
                "span_id": str(span_id),
                "status": status,
                "failure_reason": failure_reason,
                "created_at": _fmt_dt(created_at),
                "chunk_count": chunk_count or 0,
            })
        return {"doc_id": doc_id, "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
