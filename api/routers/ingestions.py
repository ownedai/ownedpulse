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
    """Unified ingestion list: session groups (bulk) + RSS runs."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()

        # ── Session groups: group manual_cli/bootstrap_ui by date ──────────
        sg_where = ["trigger_source = ANY(%s)"]
        sg_params: list = [list(SESSION_SOURCES)]
        if date_from:
            sg_where.append("triggered_at >= %s::timestamptz")
            sg_params.append(date_from)
        if date_to:
            sg_where.append("triggered_at <= %s::timestamptz + INTERVAL '1 day'")
            sg_params.append(date_to)

        cur.execute(
            f"""
            SELECT
                trigger_source,
                (triggered_at AT TIME ZONE 'UTC')::date::text AS grp_date,
                MIN(triggered_at) AS triggered_at,
                COUNT(*) AS run_count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status IN ('error','failed') THEN 1 ELSE 0 END) AS failed
            FROM run_log
            WHERE {' AND '.join(sg_where)}
            GROUP BY trigger_source, (triggered_at AT TIME ZONE 'UTC')::date
            ORDER BY MIN(triggered_at) DESC
            """,
            sg_params
        )
        session_groups = []
        for row in cur.fetchall():
            ts, grp_date, triggered_at, run_count, succeeded, failed = row
            run_token = f"{grp_date}_{ts}"
            total = succeeded + failed
            if failed == 0:
                grp_status = "success"
            elif succeeded == 0:
                grp_status = "error"
            else:
                grp_status = "partial"

            if status and grp_status != status:
                continue
            if source:
                allowed = SOURCE_CATEGORIES.get(source, (source,))
                if ts not in allowed:
                    continue

            session_groups.append({
                "type": "session_group",
                "run_token": run_token,
                "source": ts,
                "triggered_at": _fmt_dt(triggered_at),
                "status": grp_status,
                "doc_count": int(run_count),
                "doc_count_succeeded": int(succeeded),
                "doc_count_failed": int(failed),
            })

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
    """Documents ingested in a session group (bootstrap/manual bulk)."""
    # run_token = "YYYY-MM-DD_trigger_source"
    try:
        parts = run_token.split("_", 1)
        grp_date = parts[0]
        trigger_src = parts[1] if len(parts) > 1 else None
        if not trigger_src:
            raise HTTPException(status_code=422, detail="Invalid run_token format")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid run_token format")

    try:
        conn = get_pg_conn()
        cur = conn.cursor()

        # Get run_ids for this session group
        cur.execute(
            """
            SELECT run_id FROM run_log
            WHERE trigger_source = %s
              AND (triggered_at AT TIME ZONE 'UTC')::date::text = %s
            """,
            (trigger_src, grp_date)
        )
        run_ids = [str(row[0]) for row in cur.fetchall()]
        if not run_ids:
            cur.close()
            conn.close()
            return {"run_token": run_token, "items": [], "total": 0, "page": page, "page_size": page_size}

        # Count unique docs (not spans)
        cur.execute(
            "SELECT COUNT(DISTINCT doc_id) FROM ingestion_doc WHERE trace_id::text = ANY(%s)",
            (run_ids,)
        )
        total = cur.fetchone()[0]

        # Fetch page — latest span per doc_id with retry metadata
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
            ORDER BY ingested_at DESC
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

        cur.close()
        conn.close()
        return {"run_token": run_token, "items": items, "total": total, "page": page, "page_size": page_size}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


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
        total = cur.fetchone()[0]

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
            ORDER BY ingested_at DESC
            LIMIT %s OFFSET %s
            """,
            (run_id, page_size, (page - 1) * page_size)
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
