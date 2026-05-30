"""Admin router — /api/admin/ routes for system management."""

import os
import uuid
import json
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from qdrant_client import QdrantClient

router = APIRouter()

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_base")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "ollama")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))


def get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )


# ── PATCH /admin/feeds/{feed_id} request model ────────────────────────────────

class FeedToggleRequest(BaseModel):
    enabled: bool


# ── PUT /admin/model request model ────────────────────────────────────────────

class ModelUpdateRequest(BaseModel):
    model: str


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
            cur.execute("SELECT max(last_indexed_at) FROM document_registry")
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
            r = await http.get(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=10)
            r.raise_for_status()
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            # Check active model from system_config
            conn = get_pg_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
                row = cur.fetchone()
                active_model = row[0] if row else None
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


# ── GET /admin/feeds ──────────────────────────────────────────────────────────

@router.get("/feeds")
async def admin_feeds():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT feed_id, name, url, feed_type, enabled, last_run_at, created_at, updated_at FROM feed_config ORDER BY feed_id")
        rows = cur.fetchall()
        cur.close()

        feeds = []
        for row in rows:
            feed_id, name, url, feed_type, enabled, last_run_at, created_at, updated_at = row
            feeds.append({
                "feed_id": feed_id,
                "name": name,
                "url": url,
                "feed_type": feed_type,
                "enabled": enabled,
                "last_run_at": last_run_at.isoformat() if hasattr(last_run_at, 'isoformat') and last_run_at else None,
                "created_at": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
                "updated_at": updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at),
            })

        return feeds
    finally:
        conn.close()


# ── PATCH /admin/feeds/{feed_id} ──────────────────────────────────────────────

@router.patch("/feeds/{feed_id}")
async def admin_toggle_feed(feed_id: str, body: FeedToggleRequest):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE feed_config SET enabled = %s, updated_at = NOW() WHERE feed_id = %s RETURNING feed_id, name, url, feed_type, enabled, last_run_at, created_at, updated_at",
            (body.enabled, feed_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Feed not found")

        (fid, name, url, feed_type, enabled, last_run_at, created_at, updated_at) = row

        cur.close()
        conn.commit()
        return {
            "feed_id": fid,
            "name": name,
            "url": url,
            "feed_type": feed_type,
            "enabled": enabled,
            "last_run_at": last_run_at.isoformat() if hasattr(last_run_at, 'isoformat') and last_run_at else None,
            "created_at": created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
            "updated_at": updated_at.isoformat() if hasattr(updated_at, 'isoformat') else str(updated_at),
        }
    finally:
        conn.close()


# ── POST /admin/trigger-run ──────────────────────────────────────────────────

@router.post("/trigger-run")
async def admin_trigger_run():
    # Read webhook URL from system_config
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_config WHERE key = 'n8n_trigger_webhook'")
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    webhook_url = (row[0] if row else "").strip()
    if not webhook_url:
        raise HTTPException(status_code=503, detail="Webhook URL not configured")

    run_id = str(uuid.uuid4())

    # Create run_log row
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO run_log (run_id, trigger_source, status)
               VALUES (%s, 'manual', 'running')""",
            (run_id,)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()

    # Call n8n webhook
    n8n_called = False
    n8n_status = None
    try:
        async with httpx.AsyncClient() as http:
            r = await http.get(
                webhook_url,
                params={"run_id": run_id, "trigger_source": "manual"},
                timeout=15
            )
            n8n_called = True
            n8n_status = r.status_code
    except Exception as e:
        # Webhook call failed — update run_log to error
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE run_log SET status = 'error', error_detail = %s, completed_at = NOW() WHERE run_id = %s",
                (f"Webhook call failed: {str(e)}", run_id)
            )
            cur.close()
        finally:
            conn.close()
        raise HTTPException(status_code=502, detail=f"n8n webhook call failed: {str(e)}")

    return {
        "run_id": run_id,
        "status": "triggered",
        "n8n_webhook_called": n8n_called,
        "n8n_response_status": n8n_status,
    }


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

    active_model = row[0] if row else None

    # Get available models from Ollama
    try:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=10)
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
            r = await http.get(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=10)
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
    """Check whether the active LLM model is currently loaded in Ollama (/api/ps)."""
    OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

    # Get active model name from system_config
    active_model = None
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
            row = cur.fetchone()
            active_model = row[0] if row else None
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass

    # Query Ollama /api/ps for currently loaded models
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/ps")
            resp.raise_for_status()
            running = [m["name"] for m in resp.json().get("models", [])]
            loaded = any(
                r == active_model or r.split(":")[0] == (active_model or "").split(":")[0]
                for r in running
            )
            return {"model": active_model, "loaded": loaded, "running_models": running}
    except Exception as e:
        return {"model": active_model, "loaded": False, "error": str(e)}


# ── POST /admin/warmup ────────────────────────────────────────────────────────

@router.post("/warmup")
async def admin_warmup():
    """Fire a minimal generate request to trigger Ollama model load. Returns immediately."""
    OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

    active_model = None
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
            row = cur.fetchone()
            active_model = row[0] if row else None
            cur.close()
        finally:
            conn.close()
    except Exception:
        pass

    if not active_model:
        return {"status": "no model configured"}

    # Fire-and-forget: send a minimal prompt with keep_alive to load the model.
    # We don't await the generation result — just triggering the load.
    import asyncio

    async def _load():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                await client.post(f"{OLLAMA_BASE}/api/generate", json={
                    "model": active_model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": "10m",
                })
        except Exception:
            pass

    asyncio.create_task(_load())
    return {"status": "warmup initiated", "model": active_model}
