"""Admin router — /api/admin/ routes for system management."""

import os
import uuid
import json
import asyncio
import logging
import subprocess
import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance
from lib import ingestion_lock

logger = logging.getLogger("ownedpulse.admin")

router = APIRouter()

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "ollama")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
# Handle both bare hostnames and full URLs (e.g. http://10.0.2.2:11434 for external Ollama)
_OLLAMA_PARSED = OLLAMA_HOST
if "://" in OLLAMA_HOST:
    from urllib.parse import urlparse as _up
    _pu = _up(OLLAMA_HOST)
    _OLLAMA_PARSED = _pu.hostname or OLLAMA_HOST
    if _pu.port:
        OLLAMA_PORT = _pu.port
OLLAMA_BASE = f"http://{_OLLAMA_PARSED}:{OLLAMA_PORT}"
# Must match OLLAMA_NUM_CTX in main.py — a different context size here would
# load a second runner for the same model and evict the query one.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "12288"))
DOCLING_HOST = os.getenv("DOCLING_HOST", "http://docling:5001")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")

from lib.db import get_pg_conn

# ── PATCH /admin/feeds/{feed_id} request model ────────────────────────────────

class FeedToggleRequest(BaseModel):
    enabled: bool


# ── PUT /admin/model request model ────────────────────────────────────────────

class ModelUpdateRequest(BaseModel):
    model: str


# ── PUT /admin/scheduler/config request model ─────────────────────────────────

class SchedulerConfigRequest(BaseModel):
    hour: int
    minute: int
    timezone: str


# ── GET /admin/health ─────────────────────────────────────────────────────────

@router.get("/health")
async def admin_health():
    result = {"qdrant": {}, "postgres": {}, "ollama": {}}

    # Qdrant
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        coll_info = client.get_collection(QDRANT_COLLECTION)
        result["qdrant"] = {
            "status": "ok",
            "points_count": coll_info.points_count,
            "indexed_vectors_count": coll_info.indexed_vectors_count,
            "collection_status": coll_info.status.name,
        }
    except Exception as e:
        result["qdrant"] = {"status": "error", "message": str(e)}

    # PostgreSQL
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM document_registry")
            document_count = cur.fetchone()[0]
            cur.execute("SELECT max(last_indexed_at) FROM document_registry_ext")
            last_ingestion = cur.fetchone()[0]
            cur.close()
            result["postgres"] = {
                "status": "ok",
                "document_count": document_count,
                "last_ingestion": last_ingestion.isoformat() if last_ingestion else None,
            }
        finally:
            conn.close()
    except Exception as e:
        result["postgres"] = {"status": "error", "message": str(e)}

    # Ollama
    try:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
            r.raise_for_status()
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            # Check active model from system_config
            conn = get_pg_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
                row = cur.fetchone()
                active_model = (row[0] if row else None) or os.getenv("OLLAMA_GEN_MODEL")
                cur.close()
            finally:
                conn.close()
            model_loaded = active_model in models if active_model else False
            result["ollama"] = {
                "status": "ok",
                "active_model": active_model,
                "model_loaded": model_loaded,
            }
    except Exception as e:
        result["ollama"] = {"status": "error", "message": str(e)}

    return result


# ── GET /admin/sources ────────────────────────────────────────────────────────

@router.get("/sources")
async def admin_feeds():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT feed_id, name, feed_url, feed_type, enabled, last_run_at, created_at, updated_at FROM feed_config ORDER BY feed_id")
        rows = cur.fetchall()
        cur.close()

        feeds = []
        for row in rows:
            feed_id, name, feed_url, feed_type, enabled, last_run_at, created_at, updated_at = row
            feeds.append({
                "feed_id": feed_id,
                "name": name,
                "url": feed_url,
                "feed_type": feed_type,
                "enabled": enabled,
                "last_run_at": last_run_at.isoformat() if hasattr(last_run_at, 'isoformat') and last_run_at else None,
                "created_at": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
                "updated_at": updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at),
            })

        return feeds
    finally:
        conn.close()


# ── PATCH /admin/sources/{feed_id} ────────────────────────────────────────────

@router.patch("/sources/{feed_id}")
async def admin_toggle_feed(feed_id: str, body: FeedToggleRequest):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE feed_config SET enabled = %s, updated_at = NOW() WHERE feed_id = %s RETURNING feed_id, name, feed_url, feed_type, enabled, last_run_at, created_at, updated_at",
            (body.enabled, feed_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Feed not found")

        (fid, name, feed_url, feed_type, enabled, last_run_at, created_at, updated_at) = row

        cur.close()
        conn.commit()
        return {
            "feed_id": fid,
            "name": name,
            "url": feed_url,
            "feed_type": feed_type,
            "enabled": enabled,
            "last_run_at": last_run_at.isoformat() if hasattr(last_run_at, 'isoformat') and last_run_at else None,
            "created_at": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
            "updated_at": updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at),
        }
    finally:
        conn.close()


# ── POST /admin/sources/{feed_id}/trigger ────────────────────────────────────

@router.post("/sources/{feed_id}/trigger")
async def admin_trigger_feed(feed_id: str, background_tasks: BackgroundTasks, mode: str = "full"):
    """Trigger a single feed run via APScheduler background task.

    All modes use the same bulk scrapers. Scope is controlled by
    --max-age-days (default 30) in run_pipeline.py.
    """
    lock_st = ingestion_lock.state()
    if lock_st["active"]:
        raise HTTPException(status_code=409, detail=ingestion_lock.conflict_detail())

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT feed_id, enabled FROM feed_config WHERE feed_id = %s", (feed_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")
    if not row[1]:
        raise HTTPException(status_code=422, detail=f"Feed '{feed_id}' is disabled")

    from lib.scheduler import run_ingestion_job
    background_tasks.add_task(run_ingestion_job, feed_id=feed_id, triggered_by="admin-ui")
    return {"feed_id": feed_id, "status": "triggered"}


# ── POST /admin/trigger-run ──────────────────────────────────────────────────

@router.post("/trigger-run")
async def admin_trigger_run(background_tasks: BackgroundTasks):
    """Trigger a full ingestion run via APScheduler background task."""
    lock_st = ingestion_lock.state()
    if lock_st["active"]:
        raise HTTPException(status_code=409, detail=ingestion_lock.conflict_detail())

    from lib.scheduler import run_ingestion_job
    background_tasks.add_task(run_ingestion_job, triggered_by="admin-ui")
    return {"status": "triggered"}


# ── POST /admin/stop-ingestion ────────────────────────────────────────────────

@router.post("/stop-ingestion")
async def admin_stop_ingestion():
    """Stop the currently running ingestion subprocess."""
    from lib.scheduler import stop_ingestion
    killed = stop_ingestion()
    if killed:
        ingestion_lock.release()
        return {"status": "stopped"}
    return {"status": "nothing_to_stop"}


# ── GET /admin/models ─────────────────────────────────────────────────────────

@router.get("/models")
async def admin_models():
    # Get active model from system_config
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    active_model = (row[0] if row else None) or os.getenv("OLLAMA_GEN_MODEL")

    # Get available models from Ollama
    try:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
            r.raise_for_status()
            data = r.json()
            available_models = [m["name"] for m in data.get("models", [])]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unavailable: {str(e)}")

    return {
        "active_model": active_model,
        "available_models": available_models,
    }


# ── PUT /admin/model ─────────────────────────────────────────────────────────────

@router.put("/model")
async def admin_update_model(body: ModelUpdateRequest):
    model = body.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required")

    # Validate model exists in Ollama
    try:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
            r.raise_for_status()
            data = r.json()
            available_models = [m["name"] for m in data.get("models", [])]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unavailable: {str(e)}")

    if model not in available_models:
        raise HTTPException(status_code=400, detail=f"Model '{model}' not found in Ollama. Available: {', '.join(available_models)}")

    # Update system_config
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES ('active_llm_model', %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (model,)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return {"active_model": model}


# ── GET /admin/model-status ───────────────────────────────────────────────────

@router.get("/model-status")
async def admin_model_status():
    """Check Ollama, Qdrant, and PostgreSQL status for the System box."""

    # Get active model name from system_config
    active_model = None
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
            row = cur.fetchone()
            active_model = (row[0] if row else None) or os.getenv("OLLAMA_GEN_MODEL")
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass

    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")

    response = {
        "model": active_model,
        "loaded": False,
        "embed_model": embed_model,
        "embed_loaded": False,
        "qdrant": {"status": "unknown"},
        "postgres": {"status": "unknown"},
    }

    # ── Ollama probe ──────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/ps")
            resp.raise_for_status()
            running = [m["name"] for m in resp.json().get("models", [])]
            response["loaded"] = any(
                r == active_model or r.split(":")[0] == (active_model or "").split(":")[0]
                for r in running
            )
            response["embed_loaded"] = any(
                r == embed_model or r.split(":")[0] == embed_model.split(":")[0]
                for r in running
            )
            response["running_models"] = running
    except Exception as e:
        response["error"] = str(e)

    # ── Qdrant probe ──────────────────────────────────────────────────────────
    try:
        qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3)
        coll_info = qdrant_client.get_collection(QDRANT_COLLECTION)
        response["qdrant"] = {
            "status": "ok",
            "points": coll_info.points_count,
            "collection_status": coll_info.status.name.lower(),
        }
    except Exception as e:
        response["qdrant"] = {"status": "error", "detail": str(e)}

    # ── PostgreSQL probe ──────────────────────────────────────────────────────
    try:
        pg_conn = get_pg_conn()
        try:
            cur = pg_conn.cursor()
            cur.execute("SELECT count(*) FROM document_registry_ext WHERE ingestion_status = 'indexed'")
            response["postgres"] = {
                "status": "ok",
                "document_count": cur.fetchone()[0],
            }
            cur.close()
        finally:
            pg_conn.close()
    except Exception as e:
        response["postgres"] = {"status": "error", "detail": str(e)}

    # ── Docling probe ─────────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{DOCLING_HOST}/health")
            resp.raise_for_status()
            if resp.json().get("status") == "ok":
                response["docling"] = {"status": "ok"}
            else:
                response["docling"] = {"status": "error", "detail": "unexpected response"}
    except Exception as e:
        response["docling"] = {"status": "error", "detail": str(e)}

    # ── Langfuse probe ───────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{LANGFUSE_HOST}/api/public/health")
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK":
                response["langfuse"] = {
                    "status": "ok",
                    "version": data.get("version", "unknown"),
                }
            else:
                response["langfuse"] = {"status": "error", "detail": "unexpected response"}
    except Exception as e:
        response["langfuse"] = {"status": "error", "detail": str(e)}

    return response


# ── POST /admin/warmup ────────────────────────────────────────────────────────

async def warm_models(active_model: str, embed_model: str = "mxbai-embed-large") -> None:
    """Load the generation and embedding models into Ollama.

    The requests exist only to trigger the load; their responses are discarded.
    A cold model is a latency problem, not a failure, so problems are logged and
    never raised — callers may run this from startup.

    num_ctx must match what queries request, or the query pays for a second load
    of the same model at a different context size.
    """
    async def _post(path: str, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                await client.post(f"{OLLAMA_BASE}{path}", json=payload)
            logger.info("[warmup] %s loaded", payload.get("model"))
        except Exception as e:
            logger.warning("[warmup] %s failed to load: %s", payload.get("model"), e)

    await asyncio.gather(
        _post("/api/generate", {
            "model": active_model,
            "prompt": "",
            "stream": False,
            "keep_alive": "10m",
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        }),
        _post("/api/embeddings", {
            "model": embed_model,
            "prompt": "warmup",
            "keep_alive": "10m",
        }),
    )


@router.post("/warmup")
async def admin_warmup():
    """Fire a minimal generate request to trigger Ollama model load. Returns immediately."""

    active_model = None
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
            row = cur.fetchone()
            active_model = (row[0] if row else None) or os.getenv("OLLAMA_GEN_MODEL")
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass

    if not active_model:
        return {"status": "no model configured"}

    # Fire-and-forget: we don't await the load, just start it.
    asyncio.create_task(warm_models(active_model))
    return {"status": "warmup initiated", "model": active_model, "embed_model": "mxbai-embed-large"}


# ── POST /admin/reset-corpus ──────────────────────────────────────────────────

class ResetCorpusRequest(BaseModel):
    confirm: bool = False


@router.post("/reset-corpus")
async def admin_reset_corpus(body: ResetCorpusRequest):
    """
    Destructive reset: wipes the Qdrant collection, truncates run_log,
    ingestion_doc and ingestion_state, then re-runs seed_registry against the
    archive. document_registry is NOT cleared — seed_registry upserts the
    corpus manifest's documents onto whatever rows are already there, so
    downloaded documents keep their rows and their repaired dates.
    Requires confirm=true. Blocks if ingestion is running.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to proceed. This will wipe all Qdrant chunks, "
                   "run_log, and ingestion_doc tables."
        )

    lock_st = ingestion_lock.state()
    if lock_st["active"]:
        raise HTTPException(status_code=409, detail=ingestion_lock.conflict_detail())

    result: dict = {
        "qdrant_wiped": False,
        "tables_truncated": [],
        "registry_rows_kept": 0,
        "base_corpus_seeded": 0,
        "seed_registry_ok": False,
    }

    # 1. Truncate trace tables and ingestion_state — PG first so Qdrant is not orphaned on failure
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE ingestion_doc, ingestion_state, run_log CASCADE")
        result["tables_truncated"] = ["ingestion_doc", "ingestion_state", "run_log"]
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Table truncate failed: {e}")
    finally:
        if not conn.closed:
            conn.close()

    # 2. Wipe Qdrant collection and immediately recreate it empty
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        client.delete_collection(QDRANT_COLLECTION)
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        result["qdrant_wiped"] = True
        logger.info("Qdrant collection '%s' deleted and recreated empty", QDRANT_COLLECTION)
    except Exception as e:
        logger.error("Qdrant wipe failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Qdrant wipe failed: {e}")

    # 3. Upsert the base corpus onto document_registry (it is not cleared first)
    try:
        seed_result = subprocess.run(
            ["python3", "/opt/scripts/registry/seed_registry.py"],
            capture_output=True, text=True, timeout=60,
        )
        if seed_result.returncode != 0:
            logger.error("seed_registry.py failed after reset: %s", seed_result.stderr)
        else:
            result["seed_registry_ok"] = True
            logger.info("seed_registry.py completed after reset")
    except subprocess.TimeoutExpired:
        logger.error("seed_registry.py timed out after reset")
    except Exception as e:
        logger.error("seed_registry.py failed after reset: %s", e)

    # 4. Report what the registry actually holds. Read from the table rather
    #    than parsing seed_registry's stdout: the table is the result, and the
    #    registry keeps every row it had, so the row count is not the seed count.
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE corpus_doc) "
                "FROM document_registry"
            )
            kept, seeded = cur.fetchone()
            result["registry_rows_kept"] = kept
            result["base_corpus_seeded"] = seeded
            cur.close()
        finally:
            conn.close()
    except Exception as e:
        logger.error("Post-reset count query failed: %s", e)

    return result


# ── GET /admin/scheduler/status ───────────────────────────────────────────────

RSS_SCHEDULE_HOUR = int(os.environ.get("RSS_SCHEDULE_HOUR", "9"))
RSS_SCHEDULE_MINUTE = int(os.environ.get("RSS_SCHEDULE_MINUTE", "0"))
RSS_SCHEDULE_TIMEZONE = os.environ.get("RSS_SCHEDULE_TIMEZONE", "Europe/Berlin")


@router.get("/scheduler/status")
async def get_scheduler_status():
    from lib.scheduler import get_scheduler
    sched = get_scheduler()
    job = sched.get_job("daily_ingestion")
    return {
        "scheduler_running": sched.running,
        "job_id": "daily_ingestion",
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "schedule": f"{RSS_SCHEDULE_HOUR:02d}:{RSS_SCHEDULE_MINUTE:02d} {RSS_SCHEDULE_TIMEZONE}",
    }


# ── POST /admin/scheduler/trigger ────────────────────────────────────────────

@router.post("/scheduler/trigger")
async def trigger_scheduler_now(background_tasks: BackgroundTasks):
    """Manual trigger — fires ingestion for all enabled feeds as a background task."""
    from lib.scheduler import run_ingestion_job
    background_tasks.add_task(run_ingestion_job, triggered_by="admin-ui")
    return {"status": "triggered", "message": "Source ingestion started in background"}


# ── POST /admin/scheduler/pause ──────────────────────────────────────────────

@router.post("/scheduler/pause")
async def pause_scheduler():
    from lib.scheduler import get_scheduler
    get_scheduler().pause_job("daily_ingestion")
    return {"status": "paused"}


# ── POST /admin/scheduler/resume ─────────────────────────────────────────────

@router.post("/scheduler/resume")
async def resume_scheduler():
    from lib.scheduler import get_scheduler
    get_scheduler().resume_job("daily_ingestion")
    return {"status": "resumed"}


# ── POST /admin/scheduler/clear ──────────────────────────────────────────────

@router.post("/scheduler/clear")
async def clear_scheduler():
    """Remove the daily ingestion job entirely. No scheduled runs until reconfigured."""
    from lib.scheduler import get_scheduler
    try:
        get_scheduler().remove_job("daily_ingestion")
    except Exception:
        pass  # job may not exist
    return {"status": "cleared"}


# ── GET /admin/scheduler/config ───────────────────────────────────────────────

@router.get("/scheduler/config")
async def get_scheduler_config():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value FROM system_config WHERE key IN "
            "('rss_schedule_hour', 'rss_schedule_minute', 'rss_schedule_timezone')"
        )
        rows = dict(cur.fetchall())
        cur.close()
    finally:
        conn.close()
    return {
        "hour": int(rows.get("rss_schedule_hour", RSS_SCHEDULE_HOUR)),
        "minute": int(rows.get("rss_schedule_minute", RSS_SCHEDULE_MINUTE)),
        "timezone": rows.get("rss_schedule_timezone", RSS_SCHEDULE_TIMEZONE),
    }


# ── PUT /admin/scheduler/config ───────────────────────────────────────────────

@router.put("/scheduler/config")
async def update_scheduler_config(body: SchedulerConfigRequest):
    if not (0 <= body.hour <= 23):
        raise HTTPException(status_code=400, detail="Hour must be 0–23")
    if not (0 <= body.minute <= 59):
        raise HTTPException(status_code=400, detail="Minute must be 0–59")

    try:
        import zoneinfo
        zoneinfo.ZoneInfo(body.timezone)
    except (ImportError, KeyError, Exception):
        raise HTTPException(status_code=400, detail=f"Invalid timezone: {body.timezone}")

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        for key, value in [
            ("rss_schedule_hour", str(body.hour)),
            ("rss_schedule_minute", str(body.minute)),
            ("rss_schedule_timezone", body.timezone),
        ]:
            cur.execute(
                "INSERT INTO system_config (key, value, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (key, value),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    from lib.scheduler import reschedule_ingestion_job
    reschedule_ingestion_job(body.hour, body.minute, body.timezone)

    return {"hour": body.hour, "minute": body.minute, "timezone": body.timezone}
