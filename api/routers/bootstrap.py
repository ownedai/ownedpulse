"""Bootstrap router — /api/bootstrap/ routes for initial corpus load + Sources page."""

import os
import uuid
import json
import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# In-memory session state — single-worker container, survives per-process
_sessions: dict = {}

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_base")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

N8N_HOST = os.getenv("N8N_HOST", "n8n")
N8N_PORT = int(os.getenv("N8N_PORT", "5678"))
N8N_API_KEY = os.getenv("N8N_API_KEY", "")


def get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )


def normalise_agency(a: str) -> str:
    return "EMA" if a == "EU-Commission" else a


# ── Request/response models ───────────────────────────────────────────────────

class BootstrapScope(BaseModel):
    fda_guidance: bool = True
    fda_press: bool = True
    ema: bool = True
    ich: bool = True


class BootstrapRunRequest(BaseModel):
    scope: BootstrapScope
    force: bool = False
    redownload: str = "none"  # "none" | "check" | "force"


class ReingestDocRequest(BaseModel):
    doc_id: str


# ── GET /bootstrap/state ─────────────────────────────────────────────────────

@router.get("/state")
async def bootstrap_state():
    doc_count = 0
    n8n_active = False
    last_bootstrap = None

    bootstrap_doc_count = 0

    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM document_registry WHERE ingestion_status IN ('indexed', 'success')")
            doc_count = cur.fetchone()[0]
            # Last bootstrap session: bootstrap_ui or manual_cli, grouped by UTC date
            cur.execute(
                """
                SELECT last_at, session_doc_count FROM (
                    SELECT
                        MAX(triggered_at) AS last_at,
                        COUNT(*) AS session_doc_count,
                        (triggered_at AT TIME ZONE 'UTC')::date AS grp_date
                    FROM run_log
                    WHERE trigger_source IN ('bootstrap_ui', 'manual_cli')
                    GROUP BY (triggered_at AT TIME ZONE 'UTC')::date
                    ORDER BY grp_date DESC
                    LIMIT 1
                ) t
                """
            )
            row = cur.fetchone()
            if row and row[0]:
                last_bootstrap = row[0].isoformat()
                bootstrap_doc_count = int(row[1])
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass

    from lib.scheduler import get_scheduler
    sched = get_scheduler()
    scheduler_active = sched.running and sched.get_job("rss_daily_ingestion") is not None

    # Check for active in-memory session
    active_session = None
    for sid, sess in _sessions.items():
        if sess.get("status") in ("pending", "running"):
            active_session = sid
            break

    return {
        "state": "initialized" if doc_count > 0 else "fresh",
        "doc_count": doc_count,
        "bootstrap_doc_count": bootstrap_doc_count,
        "n8n_active": scheduler_active,
        "last_bootstrap": last_bootstrap,
        "active_session": active_session,
    }


# ── GET /bootstrap/corpus-summary ────────────────────────────────────────────

@router.get("/corpus-summary")
async def corpus_summary():
    """Per-agency-per-doctype breakdown for Sources page summary cards."""
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT issuing_body, doc_type, count(*)
                FROM document_registry
                WHERE ingestion_status IN ('indexed', 'success')
                GROUP BY issuing_body, doc_type
                ORDER BY issuing_body, count(*) DESC
                """
            )
            rows = cur.fetchall()
            # Per-agency last indexed from ingestion_doc.created_at (last_indexed_at is unpopulated)
            cur.execute(
                """
                SELECT dr.issuing_body, max(id.created_at)
                FROM ingestion_doc id
                JOIN document_registry dr ON dr.document_id = id.doc_id
                WHERE id.status = 'success'
                GROUP BY dr.issuing_body
                """
            )
            agency_last = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT issuing_body,
                       min((metadata_json->>'publication_date')::text),
                       max((metadata_json->>'publication_date')::text)
                FROM document_registry
                WHERE ingestion_status IN ('indexed', 'success')
                  AND metadata_json->>'publication_date' IS NOT NULL
                  AND metadata_json->>'publication_date' != ''
                GROUP BY issuing_body
                """
            )
            agency_pub_range = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    # Aggregate per normalised agency
    by_agency: dict = {}
    for issuing_body, doc_type, count in rows:
        agency = normalise_agency(issuing_body or "Unknown")
        if agency not in by_agency:
            by_agency[agency] = {
                "agency": agency, "total": 0, "by_type": {},
                "last_indexed": None, "pub_date_min": None, "pub_date_max": None,
            }
        by_agency[agency]["total"] += count
        by_agency[agency]["by_type"][doc_type or "other"] = (
            by_agency[agency]["by_type"].get(doc_type or "other", 0) + count
        )

    # Attach per-agency last indexed; merge EU-Commission into EMA
    for raw_agency, ts in agency_last.items():
        normalised = normalise_agency(raw_agency or "Unknown")
        if normalised in by_agency:
            existing = by_agency[normalised]["last_indexed"]
            candidate = ts.isoformat() if ts else None
            if candidate and (existing is None or candidate > existing):
                by_agency[normalised]["last_indexed"] = candidate

    # Attach per-agency publication date range; merge EU-Commission into EMA
    for raw_agency, (pub_min, pub_max) in agency_pub_range.items():
        normalised = normalise_agency(raw_agency or "Unknown")
        if normalised in by_agency:
            ag = by_agency[normalised]
            if pub_min and (ag["pub_date_min"] is None or pub_min < ag["pub_date_min"]):
                ag["pub_date_min"] = pub_min
            if pub_max and (ag["pub_date_max"] is None or pub_max > ag["pub_date_max"]):
                ag["pub_date_max"] = pub_max

    all_dates = [ag["last_indexed"] for ag in by_agency.values() if ag["last_indexed"]]
    global_last = max(all_dates) if all_dates else None

    return {
        "agencies": list(by_agency.values()),
        "last_indexed": global_last,
    }


# ── POST /bootstrap/run ──────────────────────────────────────────────────────

@router.post("/run")
async def bootstrap_run(body: BootstrapRunRequest):
    # Block if another session is already running
    for sid, sess in _sessions.items():
        if sess.get("status") in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Bootstrap already running (session {sid}). Wait for it to complete."
            )

    # Check initialized state
    doc_count = 0
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM document_registry")
            doc_count = cur.fetchone()[0]
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    if doc_count > 0 and not body.force:
        raise HTTPException(
            status_code=422,
            detail="Corpus is already initialized. Set force=true to wipe and reingest."
        )

    # Build doc list from scope
    docs = _build_doc_list(body.scope)
    if not docs:
        raise HTTPException(status_code=422, detail="No documents match the selected scope")

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "status": "pending",
        "total": len(docs),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "docs": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    redownload = body.redownload if body.redownload in ("none", "check", "force") else "none"

    t = threading.Thread(
        target=_bootstrap_worker,
        args=(session_id, docs, redownload),
        daemon=True,
    )
    t.start()

    return {
        "session_id": session_id,
        "total_docs": len(docs),
        "state": "running",
    }


def _build_doc_list(scope: BootstrapScope) -> list:
    conditions = []
    if scope.fda_guidance:
        conditions.append("(issuing_body = 'FDA' AND doc_type NOT IN ('press_release', 'news_item'))")
    if scope.fda_press:
        conditions.append("(issuing_body = 'FDA' AND doc_type IN ('press_release', 'news_item'))")
    if scope.ema:
        conditions.append("issuing_body IN ('EMA', 'EU-Commission')")
    if scope.ich:
        conditions.append("issuing_body = 'ICH'")

    if not conditions:
        return []

    where = " OR ".join(f"({c})" for c in conditions)
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT document_id FROM document_registry WHERE {where} ORDER BY document_id"
            )
            rows = cur.fetchall()
            cur.close()
        finally:
            conn.close()
        return [{"doc_id": row[0], "phase": "live"} for row in rows]
    except Exception:
        return []


def _bootstrap_worker(session_id: str, docs: list, redownload: str = "none"):
    """Runs in a background thread. Updates _sessions[session_id] per doc."""
    from lib.ingest_documents import ingest_documents  # noqa: PLC0415

    session = _sessions[session_id]
    session["status"] = "running"

    for i, doc in enumerate(docs):
        # Check for cancellation before each document
        if session.get("cancelled"):
            break

        doc_id = doc["doc_id"]
        try:
            result = ingest_documents(
                [doc],
                source="bootstrap_ui",
                triggered_by="bootstrap_ui",
                redownload=redownload,
            )
            doc_results = result.get("results", [])
            dr = doc_results[0] if doc_results else {}

            if dr.get("status") == "ok":
                session["succeeded"] += 1
                session["docs"].append({
                    "doc_id": doc_id,
                    "status": "ok",
                    "chunks": dr.get("chunk_count", 0),
                })
            elif dr.get("status") == "skipped":
                session["skipped"] += 1
                session["docs"].append({
                    "doc_id": doc_id,
                    "status": "skipped",
                    "reason": (dr.get("detail") or "Unsupported format")[:200],
                })
            else:
                session["failed"] += 1
                session["docs"].append({
                    "doc_id": doc_id,
                    "status": "failed",
                    "reason": (dr.get("detail") or "Unknown error")[:200],
                })
        except Exception as e:
            session["failed"] += 1
            session["docs"].append({
                "doc_id": doc_id,
                "status": "failed",
                "reason": str(e)[:200],
            })

        session["processed"] = i + 1

    if session.get("cancelled"):
        session["status"] = "failed"
    else:
        succeeded = session["succeeded"]
        failed = session["failed"]
        if failed == 0:
            final_status = "success"
        elif succeeded > 0 or session.get("skipped", 0) > 0:
            final_status = "partial"
        else:
            final_status = "failed"
        session["status"] = final_status

    session["completed_at"] = datetime.now(timezone.utc).isoformat()


# ── GET /bootstrap/progress/{session_id} (SSE) ───────────────────────────────

@router.get("/progress/{session_id}")
async def bootstrap_progress(session_id: str):
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Bootstrap session not found")

    async def event_stream():
        sent_doc_idx = 0
        try:
            while True:
                session = _sessions.get(session_id)
                if not session:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'session not found'})}\n\n"
                    break

                # Flush new per-doc events
                new_docs = session["docs"][sent_doc_idx:]
                for doc_event in new_docs:
                    yield f"data: {json.dumps({'type': 'doc', **doc_event})}\n\n"
                sent_doc_idx = len(session["docs"])

                # Overall progress event
                yield f"data: {json.dumps({'type': 'progress', 'total': session['total'], 'processed': session['processed'], 'succeeded': session['succeeded'], 'failed': session['failed'], 'skipped': session.get('skipped', 0), 'status': session['status']})}\n\n"

                if session["status"] not in ("pending", "running"):
                    break

                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── POST /bootstrap/reingest-doc ─────────────────────────────────────────────

@router.post("/reingest-doc")
async def reingest_doc(body: ReingestDocRequest):
    """Reingest a single document by doc_id. Returns immediately; runs in background."""
    doc_id = body.doc_id.strip()
    if not doc_id:
        raise HTTPException(status_code=422, detail="doc_id required")

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "session_id": session_id,
        "status": "pending",
        "total": 1,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "docs": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    t = threading.Thread(
        target=_bootstrap_worker,
        args=(session_id, [{"doc_id": doc_id, "phase": "live"}]),
        daemon=True,
    )
    t.start()

    return {"session_id": session_id, "doc_id": doc_id, "state": "running"}


# ── POST /bootstrap/sessions/{session_id}/stop ───────────────────────────────

@router.post("/sessions/{session_id}/stop")
async def stop_bootstrap_session(session_id: str):
    """Signal a running bootstrap session to stop after the current document."""
    if session_id not in _sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = _sessions[session_id]
    if session.get("status") not in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"Session is not running (status: {session['status']})")
    session["cancelled"] = True
    return {"session_id": session_id, "message": "Cancellation requested — will stop after current document."}


# ── POST /bootstrap/activate-rss ─────────────────────────────────────────────

@router.post("/activate-rss")
async def bootstrap_activate_rss():
    """Returns scheduler status — APScheduler is always active when the API is running."""
    from lib.scheduler import get_scheduler
    sched = get_scheduler()
    job = sched.get_job("rss_daily_ingestion")
    running = sched.running and job is not None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "activated": running,
        "already_active": running,
        "note": f"RSS automation active via APScheduler. Next run: {next_run}." if running else "Scheduler not running.",
    }
