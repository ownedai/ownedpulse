"""
regpulse API — FastAPI backend for regulatory intelligence queries.
Phase G: Query UI v2.
"""

import os
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── App init ──────────────────────────────────────────────────────────────────

app = FastAPI(title="regpulse API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rp.ownedai.dev", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("regpulse.api")

# ── Config ────────────────────────────────────────────────────────────────────

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

DATA_DIR = os.getenv("DATA_DIR", "/data")

# ── Request / Response models ─────────────────────────────────────────────────


class QueryFilters(BaseModel):
    agency: str | None = None
    document_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class RetrievalParams(BaseModel):
    query_depth: str = "standard"
    top_k: int = 10
    score_threshold: float = 0.60


class QueryRequest(BaseModel):
    query: str
    filters: QueryFilters | None = None
    retrieval_params: RetrievalParams | None = None


# ── Health endpoint ───────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    """Return health status of all backend dependencies."""
    components = {}

    # Qdrant
    try:
        from qdrant_client import QdrantClient
        qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
        qdrant.get_collection(QDRANT_COLLECTION)
        components["qdrant"] = "ok"
    except Exception as e:
        components["qdrant"] = f"error: {e}"

    # PostgreSQL
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            dbname=POSTGRES_DB, user=POSTGRES_USER,
            password=POSTGRES_PASSWORD, connect_timeout=5
        )
        conn.close()
        components["postgres"] = "ok"
    except Exception as e:
        components["postgres"] = f"error: {e}"

    # Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags")
            if resp.status_code == 200:
                components["ollama"] = "ok"
            else:
                components["ollama"] = f"error: status {resp.status_code}"
    except Exception as e:
        components["ollama"] = f"error: {e}"

    # Langfuse
    try:
        import langfuse
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "")
        if public_key and secret_key and host:
            lf = langfuse.Langfuse(
                public_key=public_key, secret_key=secret_key, host=host
            )
            lf.auth_check()
            components["langfuse"] = "ok"
        else:
            components["langfuse"] = "disabled (no credentials)"
    except Exception as e:
        components["langfuse"] = f"error: {e}"

    all_ok = all(
        v == "ok" or v.startswith("disabled")
        for v in components.values()
    )
    status_code = 200 if all_ok else 503

    return {"status": "ok" if all_ok else "degraded", **components}, status_code


# ── Placeholder endpoints (implemented in subsequent steps) ───────────────────


@app.post("/api/query")
async def submit_query(request: QueryRequest):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/query/history")
async def query_history(limit: int = 10, offset: int = 0):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/query/{query_id}/export")
async def export_query(query_id: str, format: str = "json"):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/query/history/export")
async def export_history(format: str = "json"):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/trace/{trace_id}")
async def get_trace(trace_id: str):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/pdf/page")
async def pdf_page(file_path: str, page_no: int = 0):
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/corpus/stats")
async def corpus_stats():
    raise HTTPException(status_code=501, detail="Not implemented yet")


@app.get("/api/corpus/documents")
async def corpus_documents(
    agency: str | None = None,
    document_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    raise HTTPException(status_code=501, detail="Not implemented yet")
