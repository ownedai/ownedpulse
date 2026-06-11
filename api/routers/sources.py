"""Sources router — /api/sources/ bootstrap status, date estimate, and bootstrap trigger."""

import os
import uuid
import subprocess
import threading
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny
from lib import ingestion_lock

logger = logging.getLogger(__name__)

router = APIRouter()

QDRANT_HOST       = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT       = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_base")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")


def get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )


# Presentation metadata per feed_id — fixed set of known feeds.
FEED_METADATA: dict = {
    "ema_reg_guidance":   {"agency": "EMA", "label": "Regulatory Guidance",  "description": "Regulatory guidance and procedural documents"},
    "ema_sci_guidelines": {"agency": "EMA", "label": "Scientific Guidelines", "description": "Guidelines, reflection papers, scientific annexes"},
    "fda_press_releases": {"agency": "FDA", "label": "Press Releases",        "description": "News and announcements"},
    "ich_guidelines":     {"agency": "ICH", "label": "All ICH Guidelines",    "description": "Quality, safety, efficacy guidelines"},
}


# ── GET /sources/bootstrap-status ────────────────────────────────────────────

@router.get("/bootstrap-status")
async def bootstrap_status():
    """
    Returns current corpus state: base corpus documents and per-feed RSS stats.
    Base corpus = documents with corpus_doc = TRUE (seed/curated set).
    RSS feeds = entries in feed_config with aggregate stats from document_registry.
    """
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()

            # Base corpus documents
            cur.execute("""
                SELECT
                    document_id,
                    issuing_body,
                    doc_type,
                    ingestion_status,
                    COALESCE(chunk_count, 0) AS chunk_count,
                    last_indexed_at,
                    metadata_json->>'document_title' AS document_title,
                    publication_date
                FROM document_registry_ext
                WHERE corpus_doc = TRUE
                ORDER BY issuing_body, document_id
            """)
            base_rows = cur.fetchall()

            # RSS feeds: feed_config joined with aggregate stats from document_registry
            # Count all registered docs (including not-yet-indexed) for the
            # bootstrap modal's "available for ingestion" display.
            cur.execute("""
                SELECT
                    fc.feed_id,
                    fc.name,
                    fc.enabled,
                    fc.last_run_at,
                    COUNT(dr.document_id) AS doc_count,
                    MIN(dr.publication_date) AS date_min,
                    MAX(dr.publication_date) AS date_max,
                    MAX(dr.last_indexed_at) FILTER (
                        WHERE dr.ingestion_status IN ('indexed', 'success')
                    ) AS last_indexed_at
                FROM feed_config fc
                LEFT JOIN document_registry_ext dr ON dr.feed_id = fc.feed_id
                GROUP BY fc.feed_id, fc.name, fc.enabled, fc.last_run_at
                ORDER BY fc.feed_id
            """)
            feed_rows = cur.fetchall()
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    base_corpus = []
    for row in base_rows:
        doc_id, issuing_body, doc_type, ingestion_status, chunk_count, last_indexed_at, document_title, publication_date = row
        agency = "EMA" if issuing_body == "EU-Commission" else (issuing_body or "Unknown")
        base_corpus.append({
            "document_id": doc_id,
            "document_title": document_title or doc_id,
            "issuing_body": agency,
            "doc_type": doc_type,
            "ingestion_status": ingestion_status,
            "chunk_count": chunk_count,
            "last_indexed_at": last_indexed_at.isoformat() if last_indexed_at else None,
            "publication_date": publication_date.isoformat() if publication_date else None,
        })

    rss_feeds = []
    for row in feed_rows:
        feed_id, name, enabled, last_run_at, doc_count, date_min, date_max, last_indexed_at = row
        meta = FEED_METADATA.get(feed_id, {"agency": "Unknown", "label": name, "description": ""})
        rss_feeds.append({
            "feed_id": feed_id,
            "label": meta["label"],
            "agency": meta["agency"],
            "description": meta["description"],
            "enabled": enabled,
            "doc_count": int(doc_count) if doc_count else 0,
            "date_min": date_min.isoformat() if date_min else None,
            "date_max": date_max.isoformat() if date_max else None,
            "last_indexed_at": last_indexed_at.isoformat() if last_indexed_at else None,
            "last_run_at": last_run_at.isoformat() if last_run_at else None,
        })

    initialized = any(d["ingestion_status"] in ("indexed", "success") for d in base_corpus)

    return {
        "initialized": initialized,
        "base_corpus": base_corpus,
        "rss_feeds": rss_feeds,
    }


# ── GET /sources/date-estimate ────────────────────────────────────────────────

@router.get("/date-estimate")
async def date_estimate(
    feed_ids: str = Query(..., description="Comma-separated feed IDs"),
    date_from: Optional[str] = Query(None, description="Lower bound (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Upper bound (YYYY-MM-DD)"),
):
    """
    Estimate document and chunk count for a given feed + date selection.
    No ingestion is triggered. Returns estimated_docs: null if data is unreliable.
    """
    feed_id_list = [f.strip() for f in feed_ids.split(",") if f.strip()]
    if not feed_id_list:
        return {"estimated_docs": 0, "estimated_chunks": 0, "note": "No feeds selected."}

    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            conditions = ["feed_id = ANY(%s)",
                          "(ingestion_status IS NULL OR ingestion_status NOT IN ('excluded', 'unsupported', 'not_viable'))"]
            params: list = [feed_id_list]

            if date_from:
                conditions.append("publication_date >= %s::date")
                params.append(date_from)
            if date_to:
                conditions.append("publication_date <= %s::date")
                params.append(date_to)

            where = " AND ".join(conditions)
            cur.execute(
                f"SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM document_registry_ext WHERE {where}",
                params,
            )
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        return {
            "estimated_docs": None,
            "estimated_chunks": None,
            "note": f"Estimate unavailable — {str(e)[:100]}",
        }

    doc_count = int(row[0]) if row else 0
    chunk_count = int(row[1]) if row else 0
    return {
        "estimated_docs": doc_count,
        "estimated_chunks": chunk_count,
        "note": "Estimate based on currently indexed documents. Actual count may differ after re-download.",
    }


# ── POST /sources/bootstrap ───────────────────────────────────────────────────

class FeedSelection(BaseModel):
    feed_id: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class BootstrapRequest(BaseModel):
    mode: str = "wipe_and_reload"          # "wipe_and_reload" | "reload_changed_only"
    base_corpus: List[str] = []            # doc_ids to include
    rss_feeds: List[FeedSelection] = []
    redownload: str = "check"              # "none" | "check" | "force"


def _build_doc_list_from_scope(base_corpus: List[str], rss_feeds: List[FeedSelection]) -> list:
    """Build the flat doc list for the bootstrap worker from new-style scope selection."""
    docs = []

    # Base corpus: specific doc_ids selected by user
    for doc_id in base_corpus:
        docs.append({"doc_id": doc_id, "issuing_body": "", "phase": "live"})

    # RSS feeds: query document_registry filtered by feed_id + optional date range
    if rss_feeds:
        feed_id_list = [f.feed_id for f in rss_feeds]
        # All selected feeds share the same date window in the current UI
        date_from = rss_feeds[0].date_from if rss_feeds else None
        date_to   = rss_feeds[0].date_to   if rss_feeds else None

        try:
            conn = get_pg_conn()
            try:
                cur = conn.cursor()
                conditions: list = ["feed_id = ANY(%s)"]
                params: list = [feed_id_list]
                if date_from:
                    conditions.append("publication_date >= %s::date")
                    params.append(date_from)
                if date_to:
                    conditions.append("publication_date <= %s::date")
                    params.append(date_to)
                where = " AND ".join(conditions)
                cur.execute(
                    f"SELECT document_id, issuing_body FROM document_registry WHERE {where} ORDER BY document_id",
                    params,
                )
                for row in cur.fetchall():
                    docs.append({"doc_id": row[0], "issuing_body": row[1] or "", "phase": "live"})
                cur.close()
            finally:
                conn.close()
        except Exception:
            pass

    # Interleave by issuing body so same-host downloads are spaced apart
    from routers.bootstrap import _interleave_docs
    return _interleave_docs(docs)


@router.post("/bootstrap")
async def sources_bootstrap(body: BootstrapRequest):
    """
    Trigger a corpus bootstrap/reload run. Returns immediately with session_id for
    SSE progress tracking via GET /api/bootstrap/progress/{session_id}.
    """
    if body.mode not in ("wipe_and_reload", "reload_changed_only"):
        raise HTTPException(status_code=422, detail="Invalid mode.")

    # Import session state and worker from bootstrap router (shared in-process dict)
    from routers.bootstrap import _sessions, _bootstrap_worker

    # Block if any ingestion is already running (bootstrap or RSS)
    lock_st = ingestion_lock.state()
    if lock_st["active"]:
        raise HTTPException(status_code=409, detail=ingestion_lock.conflict_detail())
    for sid, sess in _sessions.items():
        if sess.get("status") in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Bootstrap already running (session {sid}). Wait for it to complete.",
            )

    # Docs are already registered by startup discovery (populate_registry_if_empty).
    # _build_doc_list_from_scope reads document_registry directly.
    docs = _build_doc_list_from_scope(body.base_corpus, body.rss_feeds)
    if not docs:
        raise HTTPException(status_code=422, detail="No documents match the selected scope.")

    # Map UI mode to redownload strategy (controls source file fetch, not the wipe)
    # wipe_and_reload always forces full redownload; reload_changed_only respects the selection
    redownload = "force" if body.mode == "wipe_and_reload" else body.redownload

    # When wipe_and_reload: delete archive directories for selected docs
    # so source files are re-downloaded from scratch, not overwritten in place.
    if body.mode == "wipe_and_reload":
        import shutil
        from pathlib import Path
        ARCHIVE = Path("/archive")
        wiped = 0
        for doc in docs:
            doc_id = doc.get("doc_id", "")
            if not doc_id:
                continue
            for agency_dir in ARCHIVE.iterdir():
                if not agency_dir.is_dir():
                    continue
                candidate = agency_dir / doc_id
                if candidate.exists() and candidate.is_dir():
                    try:
                        shutil.rmtree(candidate)
                        wiped += 1
                    except Exception as e:
                        logger.warning("Could not wipe archive dir %s: %s", candidate, e)
                    break
        logger.info("wipe_and_reload: deleted %d archive directories", wiped)

    # Always wipe Qdrant chunks and reset registry for selected documents.
    # This is a deliberate reload — the download mode only controls whether
    # source files are re-fetched, not whether existing chunks are cleared.
    doc_ids = [d["doc_id"] for d in docs]
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchAny(any=doc_ids))]
            ),
        )
    except Exception:
        pass  # Qdrant wipe is best-effort; ingestion will overwrite anyway
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            # GATE3c: delete ingestion_state rows — absence = not indexed
            cur.execute(
                "DELETE FROM ingestion_state WHERE document_id = ANY(%s)",
                (doc_ids,),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass  # Non-fatal — ingestion will update status on completion

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

    t = threading.Thread(
        target=_bootstrap_worker,
        args=(session_id, docs, redownload),
        daemon=True,
    )
    t.start()

    return {
        "session_id": session_id,
        "total_docs": len(docs),
        "status": "running",
        "message": "Bootstrap run started.",
    }
