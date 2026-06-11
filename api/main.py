"""
regpulse API — FastAPI backend for regulatory intelligence queries.
Phase G: Query UI v2.
"""

import os
import re
import uuid
import json
import logging
import threading
import subprocess
from datetime import datetime, timezone, date as _date, timedelta as _timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from typing import Literal

from routers.corpus import router as corpus_router
from routers.admin import router as admin_router
from routers.bootstrap import router as bootstrap_router
from routers.ingestions import router as ingestions_router
from routers.sources import router as sources_router
from lib.scheduler import scheduler, setup_scheduler

# ── App init ──────────────────────────────────────────────────────────────────

APP_VERSION = "0.9.35"

app = FastAPI(title="regpulse API", version=APP_VERSION)

app.include_router(corpus_router, prefix="/api/corpus")
app.include_router(admin_router, prefix="/api/admin")
app.include_router(bootstrap_router, prefix="/api/bootstrap")
app.include_router(ingestions_router, prefix="/api/ingestions")
app.include_router(sources_router, prefix="/api/sources")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rp.ownedai.dev", "http://localhost:5173", "http://192.168.3.3:5173", "http://192.168.3.2:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("regpulse.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
OLLAMA_GEN_MODEL = os.getenv("OLLAMA_GEN_MODEL", "phi4:14b-q8_0")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")

# ── Active model cache (60s TTL, read from system_config) ─────────────────────

_model_cache = {"value": None, "fetched_at": 0.0}


def get_active_model() -> str:
    import time
    now = time.time()
    if _model_cache["value"] is not None and (now - _model_cache["fetched_at"]) < 60:
        return _model_cache["value"]
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM system_config WHERE key = 'active_llm_model'")
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                _model_cache["value"] = row[0]
                _model_cache["fetched_at"] = now
                return row[0]
        finally:
            conn.close()
    except Exception:
        pass
    return _model_cache["value"] or OLLAMA_GEN_MODEL

DATA_DIR = os.getenv("DATA_DIR", "/data")


# ── Database init ─────────────────────────────────────────────────────────────


def get_pg_conn():
    """Get a PostgreSQL connection. Raises on failure."""
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )


def init_db():
    """Initialise the query_history table. Raises on failure."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                query_id          UUID PRIMARY KEY,
                query_text        TEXT NOT NULL,
                routing_path      VARCHAR(20),
                answer            TEXT,
                citations         JSONB,
                sub_queries       JSONB,
                filters_applied   JSONB,
                retrieval_params  JSONB,
                langfuse_trace_id TEXT,
                timestamp         TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Migrate old schema — add missing columns if they don't exist
        migrations = [
            ("sub_queries", "JSONB"),
            ("retrieval_params", "JSONB"),
            ("langfuse_trace_id", "TEXT"),
            ("model_used", "TEXT"),
        ]
        for col_name, col_type in migrations:
            cur.execute(
                f"""DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'query_history' AND column_name = '{col_name}'
                    ) THEN
                        ALTER TABLE query_history ADD COLUMN {col_name} {col_type};
                    END IF;
                END $$;"""
            )
        conn.commit()
        cur.close()
        logger.info("query_history table ready")
    except Exception as e:
        logger.error("init_db failed: %s", e)
        raise
    finally:
        conn.close()


def persist_query(
    query_id: str,
    query_text: str,
    routing_path: str,
    answer: str,
    citations: list,
    sub_queries: list,
    filters_applied: dict,
    retrieval_params: dict,
    langfuse_trace_id: str = "",
    timestamp: str = "",
    model_used: str = "",
    classifier: str = "",
):
    """Persist a query result to query_history. Raises on failure."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO query_history
               (query_id, query_text, routing_path, answer, citations,
                sub_queries, filters_applied, retrieval_params, langfuse_trace_id, timestamp, model_used, classifier)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                query_id, query_text, routing_path, answer,
                json.dumps(citations), json.dumps(sub_queries),
                json.dumps(filters_applied), json.dumps(retrieval_params),
                langfuse_trace_id, timestamp, model_used, classifier,
            )
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error("persist_query failed: %s", e)
        raise
    finally:
        conn.close()


# ── Startup ──────────────────────────────────────────────────────────────────

def _cleanup_abandoned_state():
    """Mark documents and runs left in transient states by killed processes.

    'pending' docs and 'running' runs older than 1 hour have no live process
    behind them — the process was killed (OOM, container restart, n8n timeout).
    We mark them 'error' with an honest message so nothing hangs in limbo.
    Normal in-flight ingestion completes in under 5 minutes; 1 hour is safe.
    """
    try:
        conn = get_pg_conn()
        cur = conn.cursor()

        cur.execute(
            """UPDATE ingestion_state
               SET ingestion_status = 'error',
                   ingestion_error   = 'Process was killed before ingestion completed',
                   updated_at        = NOW()
               WHERE ingestion_status IN ('pending', 'parsing', 'chunking', 'embedding', 'uploading', 'running')
                 AND updated_at < NOW() - INTERVAL '10 minutes'"""
        )
        docs = cur.rowcount

        cur.execute(
            """UPDATE run_log
               SET status       = 'error',
                   completed_at = NOW(),
                   error_detail = 'Process was killed before run completed'
               WHERE status = 'running'
                 AND triggered_at < NOW() - INTERVAL '10 minutes'"""
        )
        runs = cur.rowcount

        conn.commit()
        cur.close()
        conn.close()

        if docs:
            logger.info("Startup: marked %d abandoned pending document(s) as error", docs)
        if runs:
            logger.info("Startup: marked %d abandoned running run(s) as error", runs)
    except Exception as e:
        logger.warning("Startup: abandoned-state cleanup failed: %s", e)

# ── Startup discovery ───────────────────────────────────────────────────────

def _register_feed_items(feed_id: str, items: list, defaults: dict) -> int:
    """Upsert item list into document_registry as identity rows only.
    No ingestion, no archiving, no ingestion_state writes.
    Returns count of rows upserted.
    """
    import hashlib
    import re
    from urllib.parse import urlparse

    def _make_doc_id(fid: str, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        path = urlparse(url).path.rstrip("/").split("/")[-1]
        path = re.sub(r"[^a-z0-9\-]", "-", path.lower())[:40].strip("-")
        return f"{fid}-{path}-{url_hash}" if path else f"{fid}-{url_hash}"

    if not items:
        return 0

    conn = None
    count = 0
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            for item in items:
                url = item.get('url', '')
                if not url:
                    continue
                doc_id = _make_doc_id(feed_id, url)
                title = item.get('title', '')
                pub_date = item.get('pub_date', '') or None
                if pub_date and isinstance(pub_date, str) and len(pub_date) >= 10:
                    pub_date = pub_date[:10]
                else:
                    pub_date = None

                issuing_body = defaults.get('issuing_body', '')
                archive_path = f"/mnt/data/regulatory_archive/{issuing_body.lower()}/{doc_id}"

                cur.execute("""
                    INSERT INTO document_registry (
                        document_id, source_url, issuing_body,
                        document_class, document_type, document_status,
                        feed_id, corpus_doc, archive_path,
                        publication_date, metadata_json, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, FALSE, %s,
                        %s, %s, NOW(), NOW()
                    )
                    ON CONFLICT (document_id) DO NOTHING
                """, (
                    doc_id, url, issuing_body,
                    defaults.get('document_class', 'regulatory-public'),
                    defaults.get('document_type', 'guidance'),
                    defaults.get('document_status', 'final'),
                    feed_id, archive_path,
                    pub_date,
                    json.dumps({'document_title': title, 'title': title,
                                'feed_id': feed_id, 'source_url': url}),
                ))
                count += cur.rowcount
        conn.commit()
    except Exception as e:
        logger.error("[startup] _register_feed_items failed for %s: %s", feed_id, e)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()
    return count


# Feed identity defaults for lightweight startup registration.
# Mirrors sources_manifest.json.
_FEED_DEFAULTS = {
    'ema_sci_guidelines': {
        'issuing_body': 'EMA', 'document_class': 'regulatory-public',
        'document_type': 'guidance', 'document_status': 'final',
    },
    'ema_reg_guidance': {
        'issuing_body': 'EMA', 'document_class': 'regulatory-public',
        'document_type': 'guidance', 'document_status': 'final',
    },
    'fda_press_releases': {
        'issuing_body': 'FDA', 'document_class': 'regulatory-public',
        'document_type': 'press-release', 'document_status': 'final',
    },
    'ich_guidelines': {
        'issuing_body': 'ICH', 'document_class': 'regulatory-public',
        'document_type': 'guidance', 'document_status': 'final',
    },
}


def _discover_feed(feed_id: str) -> None:
    """Lightweight feed discovery for startup registry population.
    Fetches item list from online source, registers identity rows in
    document_registry only. No downloading, no archiving, no ingestion.
    """
    import sys
    sys.path.insert(0, '/opt/scripts')

    logger.info("[startup] fetching item list for feed: %s", feed_id)

    try:
        from rss.fetch_feed import (
            fetch_ema_sci, fetch_ema_reg,
            fetch_fda_press, fetch_ich,
            _fetch_ema_json,
        )

        if feed_id == 'ema_sci_guidelines':
            items = _fetch_ema_json('ema_sci_guidelines', months_override=None)
        elif feed_id == 'ema_reg_guidance':
            items = _fetch_ema_json('ema_reg_guidance', months_override=None)
        elif feed_id == 'fda_press_releases':
            items, _ = fetch_fda_press(
                {'feed_id': 'fda_press_releases', 'backfill_months': 12},
                months_override=None,
            )
        elif feed_id == 'ich_guidelines':
            items, _ = fetch_ich(
                {'feed_id': 'ich_guidelines', 'feed_type': 'json_api'},
            )
        else:
            logger.warning("[startup] unknown feed_id: %s — skipping", feed_id)
            return

        logger.info("[startup] %s: %d items fetched from source", feed_id, len(items))

        defaults = _FEED_DEFAULTS.get(feed_id, {})
        registered = _register_feed_items(feed_id, items, defaults)

        logger.info("[startup] %s: %d items registered in document_registry",
                    feed_id, registered)

    except Exception as e:
        logger.error("[startup] discovery failed for %s: %s", feed_id, e)


def populate_registry_if_empty() -> None:
    """Check each enabled feed in feed_config. For any feed with zero
    registered documents, spawn a background discovery thread.

    Non-blocking — returns immediately, threads run independently.
    Called once at startup.
    """
    conn = None
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fc.feed_id
                FROM feed_config fc
                LEFT JOIN document_registry dr USING (feed_id)
                WHERE fc.enabled = TRUE AND dr.document_id IS NULL
                GROUP BY fc.feed_id
                ORDER BY fc.feed_id
            """)
            empty_feeds = [row[0] for row in cur.fetchall()]

        if not empty_feeds:
            logger.info("[startup] registry populated for all feeds — skipping discovery")
            return

        logger.info(
            "[startup] %d feed(s) have no registered documents: %s — starting background discovery",
            len(empty_feeds), empty_feeds,
        )

        for feed_id in empty_feeds:
            t = threading.Thread(
                target=_discover_feed,
                args=(feed_id,),
                daemon=True,
                name=f"discovery-{feed_id}",
            )
            t.start()
            logger.info("[startup] discovery thread started for %s", feed_id)

    except Exception as e:
        logger.error("[startup] populate_registry_if_empty failed: %s", e)
    finally:
        if conn:
            conn.close()

def _ensure_qdrant_collection():
    """Create the Qdrant collection if it doesn't exist (e.g. after a wipe)."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
        collections = [c.name for c in client.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            logger.info("Qdrant collection '%s' created", QDRANT_COLLECTION)
    except Exception as e:
        logger.error("Qdrant collection init failed: %s", e)


@app.on_event("startup")
async def startup():
    _ensure_qdrant_collection()
    init_db()
    _cleanup_abandoned_state()
    setup_scheduler()
    scheduler.start()
    logger.info("APScheduler started")
    populate_registry_if_empty()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")

from lib.observability import get_langfuse


# ── System prompt ─────────────────────────────────────────────────────────────
# Prompt text is stored in api/prompts/system_prompt_v9.txt so it can be edited
# without changing this file.  The version tag is derived from the filename.

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

def _load_system_prompt() -> tuple[str, str]:
    """Load the highest-versioned system prompt from the prompts directory.

    Returns (version, prompt_text).  Files must be named system_prompt_<version>.txt.
    """
    candidates = sorted(_PROMPTS_DIR.glob("system_prompt_*.txt"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No system prompt files found in {_PROMPTS_DIR}")
    path = candidates[0]
    version = path.stem.replace("system_prompt_", "")
    text = path.read_text(encoding="utf-8").strip()
    return version, text

SYSTEM_PROMPT_VERSION, SYSTEM_PROMPT_V9 = _load_system_prompt()

# ── Request / Response models ─────────────────────────────────────────────────


class QueryFilters(BaseModel):
    agency: str | None = None
    document_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class RetrievalParams(BaseModel):
    query_depth: Literal["low", "standard", "deep"] = "standard"
    top_k: int = Field(10, ge=5, le=20)
    score_threshold: float = Field(0.60, ge=0.40, le=0.90)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    filters: QueryFilters | None = None
    retrieval_params: RetrievalParams | None = None
    generation_model: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

TITLE_SUFFIX_PATTERNS = [
    re.compile(r'\s*\|\s*European\s+Medicines\s+Agency(\s*\(\s*EMA\s*\))?\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*EMA(\s*\(\s*European\s+Medicines\s+Agency\s*\))?\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*FDA\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*ICH\s*$', re.IGNORECASE),
]


def strip_title_suffix(title: str) -> str:
    """Remove known agency suffixes from document titles."""
    if not title:
        return title
    for pat in TITLE_SUFFIX_PATTERNS:
        title = pat.sub("", title)
    return title.strip()


def normalise_agency(agency: str) -> str:
    """Normalise EU-Commission to EMA for display."""
    if agency == "EU-Commission":
        return "EMA"
    return agency


def normalise_agency_for_filter(agency: str) -> list[str]:
    """Expand EMA filter to include EU-Commission in Qdrant queries."""
    if agency == "EMA":
        return ["EMA", "EU-Commission"]
    return [agency]


# ── LLM query classifier ───────────────────────────────────────────────────────

CLASSIFIER_SYSTEM_PROMPT = (
    "You are a query classifier for a regulatory document knowledge base. "
    "Classify the user query into exactly one category:\n"
    "CONTENT: requires reading document text to answer — explanations, requirements, procedures, what a regulation says\n"
    "METADATA: requires knowing what documents exist — counts, lists, dates, versions, publication status, which issuing bodies\n"
    "SUPERSEDE: asks about revision history, what replaced what, changes between versions, or compares document versions\n"
    "Respond with exactly one word. No punctuation, no explanation."
)


def classify_query(query: str) -> tuple[str, str]:
    """
    Classify query routing path using phi4 LLM.
    Returns (routing_path, classifier_label).
    Falls back to CONTENT on any error or unrecognised response.
    SUPERSEDE falls back to CONTENT — no dedicated handler yet.
    """
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": "phi4:14b-q8_0",
                "prompt": f"Classify this query: {query}",
                "system": CLASSIFIER_SYSTEM_PROMPT,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 5},
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json().get("response", "").strip().upper()

        if result in ("CONTENT", "METADATA"):
            logger.info(f"LLM classifier: '{query[:80]}' → {result}")
            return result, f"llm:phi4:14b-q8_0"
        elif result == "SUPERSEDE":
            logger.info(f"LLM classifier: '{query[:80]}' → SUPERSEDE (fallback to CONTENT — no handler yet)")
            return "CONTENT", f"llm:phi4:14b-q8_0"
        else:
            logger.warning(f"LLM classifier returned unexpected '{result}' — falling back to CONTENT")
            return "CONTENT", f"llm:phi4:14b-q8_0"

    except Exception as e:
        logger.error(f"LLM classifier failed: {e} — falling back to CONTENT")
        return "CONTENT", "fallback:error"


# ── Ollama helpers ────────────────────────────────────────────────────────────

import httpx

OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"


async def ollama_generate(
    prompt: str,
    system: str = "",
    model: str = None,
    temperature: float | None = None,
    return_usage: bool = False,
) -> str | tuple:
    """Call Ollama generate API and return the response text.

    temperature: None = model default (for answer generation).
                 0.0  = deterministic (for query expansion).
    return_usage: if True, returns (text, {"input": n, "output": n}) tuple.
    """
    if model is None:
        model = get_active_model()
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
    }
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        resp.raise_for_status()
        body = resp.json()
        text = body["response"]
        if not return_usage:
            return text
        usage = {
            "input": body.get("prompt_eval_count", 0),
            "output": body.get("eval_count", 0),
        }
        return text, usage


async def ollama_embed(text: str) -> list[float]:
    """Get embedding vector for a text via Ollama."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/embeddings",
            json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


# ── Query expansion ───────────────────────────────────────────────────────────

QUERY_EXPANSION_PROMPT = (
    "You are a search query rewriter for a regulatory intelligence system. "
    "Given a user question about pharmaceutical regulations (FDA, EMA, ICH), "
    "generate {N} alternative phrasings that would help retrieve relevant "
    "document chunks from a vector database.\n\n"
    "Each variation should:\n"
    "- Use different keywords and phrasings\n"
    "- Capture different facets or interpretations of the question\n"
    "- Use regulatory terminology where appropriate\n"
    "- Be 5-15 words long\n\n"
    "Return ONLY the variations, one per line. No numbering, no bullets, "
    "no prefixes. No blank lines.\n\n"
    "User question: {query}\n\n"
    "Variations:"
)


async def expand_query(query: str, depth: int) -> list[str]:
    """Generate N sub-queries via Ollama query expansion."""
    prompt = QUERY_EXPANSION_PROMPT.format(N=depth, query=query)
    response = await ollama_generate(prompt, temperature=0.0)
    lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
    # Remove any numbering/bullet prefixes
    cleaned = []
    for line in lines:
        line = re.sub(r'^[\d]+[\.\)]\s*', '', line)
        line = line.strip().strip('"').strip("'")
        if line:
            cleaned.append(line)
    # Ensure we have at least the original query
    if not cleaned:
        cleaned = [query]
    return cleaned[:depth]


# ── Qdrant query ──────────────────────────────────────────────────────────────

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny, Range
from qdrant_client.http.models import DatetimeRange


def build_qdrant_filter(filters: QueryFilters | None) -> Optional[Filter]:
    """Build a Qdrant Filter from the API filter request.

    Filters on:
    - issuing_body (for agency)
    - document_type (hyphenated, for document type)
    - publication_date (ISO string comparison for date range)
    """
    conditions: list = []

    if filters:
        if filters.agency:
            agency_values = normalise_agency_for_filter(filters.agency)
            if len(agency_values) == 1:
                conditions.append(
                    FieldCondition(key="issuing_body", match=MatchValue(value=agency_values[0]))
                )
            else:
                conditions.append(
                    FieldCondition(key="issuing_body", match=MatchAny(any=agency_values))
                )

        if filters.document_type:
            conditions.append(
                FieldCondition(key="document_type", match=MatchValue(value=filters.document_type))
            )

        # publication_date is stored as an ISO string in Qdrant — Range/DatetimeRange
        # don't work on keyword fields. Date filtering is applied post-retrieval
        # (CONTENT path) and via PostgreSQL (METADATA path).

    # Exclude training materials and concept papers from standard content queries.
    # These remain retrievable when the user applies an explicit document_type filter.
    # Also exclude superseded chunks — old chunker versions replaced by reingestion.
    must_not: list = [
        FieldCondition(key="chunk_status", match=MatchValue(value="superseded")),
    ]
    if not (filters and filters.document_type in ("training_material", "concept_paper")):
        must_not.append(
            FieldCondition(key="document_type", match=MatchAny(any=["training_material", "concept_paper"])),
        )

    return Filter(must=conditions, must_not=must_not)


async def retrieve_chunks(
    query_text: str,
    qdrant_filter: Optional[Filter],
    top_k: int = 10,
    score_threshold: float = 0.60,
) -> list[dict]:
    """Embed query text and retrieve top chunks from Qdrant."""
    vector = await ollama_embed(query_text)

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    results = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        query_filter=qdrant_filter,
        limit=top_k,
        with_payload=True,
    )

    chunks = []
    for point in results.points:
        score = point.score if point.score is not None else 0.0
        if score < score_threshold:
            continue
        payload = point.payload or {}
        chunks.append({
            "chunk_id": str(point.id),
            "score": score,
            **payload,
        })

    return chunks


def deduplicate_chunks(chunks: list[dict], top_n: int = 8) -> list[dict]:
    """Keep best-scoring chunk per document_id, then take top N by score.
    Also remove chunks with identical text (duplicate content from different doc_ids)."""
    seen = {}
    for chunk in chunks:
        doc_id = chunk.get("document_id", chunk.get("chunk_id"))
        if doc_id not in seen or chunk["score"] > seen[doc_id]["score"]:
            seen[doc_id] = chunk

    deduped = sorted(seen.values(), key=lambda c: c["score"], reverse=True)

    # Remove chunks with identical text — same content ingested under different doc_ids
    seen_text = {}
    result = []
    for chunk in deduped:
        text_key = (chunk.get("chunk_text", "") or "")[:200].strip()
        if text_key and text_key in seen_text:
            continue  # skip lower-scored duplicate (list is already score-sorted)
        seen_text[text_key] = True
        result.append(chunk)

    return result[:top_n]


# ── Force-include explicitly mentioned documents ────────────────────────────────

# Known document name patterns mapped to document_ids (case-insensitive).
# Prefixing "ich q9" (single match) before "ich q9(r1)" (specific) is intentional.
DOCUMENT_NAME_MAP = {
    "eu gmp annex 11": "EU-GMP-Annex11",
    "annex 11": "EU-GMP-Annex11",
    "eu gmp annex 15": "EU-GMP-Annex15",
    "annex 15": "EU-GMP-Annex15",
    "eu gmp annex 22": "EU-GMP-Annex22",
    "annex 22": "EU-GMP-Annex22",
    "21 cfr part 11": "21-CFR-Part-11",
    "21 cfr 11": "21-CFR-Part-11",
    "ich q9(r1)": "ICH-Q9-R1",
    "ich q9": "ICH-Q9-R1",  # point to current version
    "ich q9 (r1)": "ICH-Q9-R1",
    "ich q10": "ICH-Q10",
}


def extract_mentioned_documents(query_text: str) -> list[str]:
    """Return document_ids explicitly mentioned in the query."""
    query_lower = query_text.lower()
    mentioned = []
    for pattern, doc_id in DOCUMENT_NAME_MAP.items():
        if pattern in query_lower:
            mentioned.append(doc_id)
    return list(set(mentioned))  # dedup — two patterns may map to same doc_id


async def fetch_document_chunks(doc_id: str, query_text: str, limit: int = 3) -> list[dict]:
    """Fetch top chunks from a specific document via semantic search.

    Embedding is done fresh for the query — deterministic at temperature 0.
    """
    from qdrant_client.models import Filter as QFilter, FieldCondition, MatchValue

    vector = await ollama_embed(query_text)
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    results = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        query_filter=QFilter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
        ),
        limit=limit,
        with_payload=True,
    )

    chunks = []
    for point in results.points:
        payload = point.payload or {}
        chunks.append({
            "chunk_id": str(point.id),
            "score": point.score if point.score is not None else 0.0,
            **payload,
        })
    return chunks


# ── Supersede-pair detection ──────────────────────────────────────────────────

def detect_supersede_pair(chunks: list[dict], pg_conn) -> dict | None:
    """Check retrieved chunks for a document_family_id. If found, resolve the
    full family from PostgreSQL and return a supersede_context dict.

    Returns None when no supersede pair is detected — caller is unaffected.
    Only issues one PG query when a family is triggered; zero queries otherwise.
    """
    # Scan chunk payloads for a non-null document_family_id (already in Qdrant payload).
    family_id = None
    triggered_by = None
    for chunk in chunks:
        fid = chunk.get("document_family_id") or ""
        if fid:
            family_id = fid
            triggered_by = chunk.get("document_id", "")
            break

    if not family_id:
        return None

    try:
        cur = pg_conn.cursor()
        cur.execute(
            """SELECT document_id, document_family_id, document_status,
                      document_version,
                      metadata_json->>'document_title' AS document_title
               FROM document_registry
               WHERE document_family_id = %s
               ORDER BY CASE WHEN document_status = 'superseded' THEN 0 ELSE 1 END,
                        document_id""",
            (family_id,),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception:
        return None

    if len(rows) < 2:
        # Family exists but only one member in registry — not a true supersede pair.
        return None

    members = [
        {
            "document_id": r[0],
            "document_family_id": r[1],
            "status": r[2],
            "version": r[3] or "",
            "title": strip_title_suffix(r[4] or r[0]),
        }
        for r in rows
    ]

    return {
        "family_id": family_id,
        "members": members,
        "triggered_by": triggered_by,
    }


def fetch_family_supplement_chunks(missing_doc_id: str, limit: int = 5) -> list[dict]:
    """Fetch a representative sample of chunks from a family member that did not
    appear in the semantic results. Uses scroll (no query vector needed).
    Prefers chunks with a non-null clause_id.
    """
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    points, _ = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=missing_doc_id))]
        ),
        limit=50,
        with_payload=True,
    )
    if not points:
        return []

    # Prefer chunks that have a clause_id, then fall back to any.
    with_clause = [p for p in points if p.payload and p.payload.get("clause_id")]
    candidates = with_clause if with_clause else points
    selected = candidates[:limit]

    return [
        {"chunk_id": str(p.id), "score": 0.0, "supplemented": True, **p.payload}
        for p in selected
    ]


def build_supersede_framing(supersede_context: dict) -> str:
    """Return the framing block prepended to the generation prompt when a
    supersede pair is detected. Empty string when context is None."""
    if not supersede_context:
        return ""
    superseded = next((m for m in supersede_context["members"] if m["status"] == "superseded"), None)
    active = next((m for m in supersede_context["members"] if m["status"] != "superseded"), None)
    if not superseded or not active:
        return ""
    lines = [
        "NOTE: This query involves a superseded document pair.",
        f"[SUPERSEDED] {superseded['title']} ({superseded['version']}) — replaced by the document below.",
        f"[ACTIVE]     {active['title']} ({active['version']}) — current version.",
        "When answering, distinguish clearly between the two versions. "
        "If the question asks about changes, compare them explicitly.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ── LLM answer generation ─────────────────────────────────────────────────────


def build_context(chunks: list[dict]) -> str:
    """Build the context string from retrieved chunks for the LLM prompt."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title = strip_title_suffix(chunk.get("document_title", "Unknown"))
        agency = normalise_agency(chunk.get("issuing_body", "Unknown"))
        clause = chunk.get("clause_id")
        version = chunk.get("document_version")
        date = chunk.get("publication_date")
        superseded = chunk.get("superseded", False)
        doc_type = chunk.get("document_type", "")  # hyphenated: guidance, other, reflection_paper, etc.

        header = f"[{i}] {title} — {agency}"
        if doc_type:
            header += f", {doc_type}"
        if version:
            header += f", {version}"
        if clause:
            header += f", §{clause}"
        if date:
            header += f" ({date})"
        if superseded:
            header += " [SUPERSEDED]"

        parts.append(f"{header}\n{chunk.get('chunk_text', '')}")

    return "\n\n".join(parts)


def parse_citations(answer: str, num_chunks: int) -> set[int]:
    """Find which [N] markers appear in the answer text."""
    cited = set()
    for i in range(1, num_chunks + 1):
        if f"[{i}]" in answer:
            cited.add(i)
    return cited


def fetch_chunk_provenance_batch(pg_conn, doc_ids: list) -> dict:
    """Batch-fetch ingestion provenance for a list of doc_ids.
    Returns dict keyed by doc_id with trace/ingestion metadata."""
    if not doc_ids:
        return {}
    try:
        cur = pg_conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT ON (id.doc_id)
                id.doc_id,
                id.span_id::text,
                id.trace_id::text,
                id.embedding_model,
                id.created_at AS ingested_at,
                id.fetched_at,
                id.parsed_at,
                id.chunk_count,
                id.status AS ingestion_status,
                rl.trigger_source AS ingestion_source,
                rl.triggered_by
            FROM ingestion_doc id
            LEFT JOIN run_log rl ON id.trace_id = rl.run_id
            WHERE id.doc_id = ANY(%s)
            ORDER BY id.doc_id, id.created_at DESC
            """,
            (list(doc_ids),)
        )
        rows = cur.fetchall()
        cur.close()
        result = {}
        for (doc_id, span_id, trace_id, embedding_model, ingested_at,
             fetched_at, parsed_at, chunk_count, ingestion_status,
             ingestion_source, triggered_by) in rows:
            result[doc_id] = {
                "span_id": span_id,
                "trace_id": trace_id,
                "embedding_model": embedding_model,
                "ingested_at": ingested_at.isoformat() if ingested_at else None,
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "parsed_at": parsed_at.isoformat() if parsed_at else None,
                "chunk_count": chunk_count,
                "ingestion_status": ingestion_status,
                "ingestion_source": ingestion_source,
                "triggered_by": triggered_by,
            }
        return result
    except Exception:
        return {}


def build_citation(chunk: dict, index: int, cited_by_llm: bool, provenance: dict = None) -> dict:
    """Build a citation response object from a chunk."""
    title = chunk.get("document_title", "")
    if not title:
        section_path = chunk.get("section_path", [])
        if section_path:
            title = section_path[0]
    if not title:
        title = "Untitled"
    prov = provenance or {}
    return {
        "index": index,
        "chunk_id": chunk.get("chunk_id", ""),
        "document_id": chunk.get("document_id", ""),
        "chunk_text": chunk.get("chunk_text", ""),
        "document_title": strip_title_suffix(title),
        "issuing_body": normalise_agency(chunk.get("issuing_body", "")),
        "document_version": chunk.get("document_version"),
        "clause_id": chunk.get("clause_id"),
        "publication_date": chunk.get("publication_date"),
        "page_no": chunk.get("page_no"),
        "chunk_index": chunk.get("chunk_index"),
        "char_offset_start": chunk.get("char_offset_start"),
        "char_offset_end": chunk.get("char_offset_end"),
        "chunked_at": chunk.get("chunked_at"),
        "score": chunk.get("score", 0.0),
        "cited_by_llm": cited_by_llm,
        "superseded": chunk.get("superseded", False),
        "superseded_by": chunk.get("superseded_by"),
        "source_local_path": chunk.get("source_local_path"),
        "source_url": chunk.get("source_url", ""),
        # G2 provenance fields
        "span_id": prov.get("span_id"),
        "trace_id": prov.get("trace_id"),
        "ingestion_source": prov.get("ingestion_source"),
        "triggered_by": prov.get("triggered_by"),
        "ingested_at": prov.get("ingested_at"),
        "fetched_at": prov.get("fetched_at"),
        "parsed_at": prov.get("parsed_at"),
        "chunk_count": prov.get("chunk_count"),
        "ingestion_status": prov.get("ingestion_status"),
        "embedding_model": prov.get("embedding_model"),
        "relevance_rank": index,
        "collection": "knowledge_base",
    }


# ── GET /api/chunk/provenance ─────────────────────────────────────────────────


@app.get("/api/chunk/provenance")
async def get_chunk_provenance(document_id: str):
    """Return ingestion provenance for a document — used for lazy-load in ChunkCard."""
    try:
        conn = get_pg_conn()
        prov_map = fetch_chunk_provenance_batch(conn, [document_id])
        conn.close()
        prov = prov_map.get(document_id)
        if not prov:
            return {}
        return prov
    except Exception as e:
        logger.error("Provenance fetch failed: %s", e)
        return {}


# ── Health endpoint ───────────────────────────────────────────────────────────


@app.get("/api/version")
async def get_version():
    return {"version": APP_VERSION}


@app.get("/api/health")
async def health():
    """Return health status of all backend dependencies."""
    components = {}

    # Qdrant
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
        client.get_collection(QDRANT_COLLECTION)
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
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            if resp.status_code == 200:
                components["ollama"] = "ok"
            else:
                components["ollama"] = f"error: status {resp.status_code}"
    except Exception as e:
        components["ollama"] = f"error: {e}"

    # Langfuse
    try:
        lf = get_langfuse()
        if lf:
            try:
                lf.auth_check()
                components["langfuse"] = "ok"
            except Exception:
                # auth_check() may fail on version mismatch (SDK vs server),
                # so fall back to a direct HTTP health check
                host = os.getenv("LANGFUSE_HOST", "")
                base = host.rstrip("/")
                health_url = f"{base}/api/public/health"
                resp = httpx.get(health_url, timeout=5)
                if resp.status_code == 200 and resp.json().get("status") == "OK":
                    components["langfuse"] = "ok"
                else:
                    components["langfuse"] = f"error: health check returned {resp.status_code}"
        else:
            components["langfuse"] = "disabled (no credentials)"
    except Exception as e:
        components["langfuse"] = f"error: {e}"

    all_ok = all(
        v == "ok" or v.startswith("disabled")
        for v in components.values()
    )
    status = "ok" if all_ok else "degraded"
    http_status = 200 if all_ok else 503

    return JSONResponse(
        content={"status": status, **components},
        status_code=http_status,
    )


# ── GET /api/system/registry-status ───────────────────────────────────────────


@app.get("/api/system/registry-status")
async def registry_status():
    """Per-feed discovery status for the bootstrap modal.
    discovery_running: True if any discovery thread is alive.
    feeds: per-feed registered document count.
    """
    discovery_threads = [
        t.name for t in threading.enumerate()
        if t.name.startswith("discovery-")
    ]

    conn = get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fc.feed_id, fc.name, COUNT(dr.document_id) as doc_count
                FROM feed_config fc
                LEFT JOIN document_registry dr USING (feed_id)
                WHERE fc.enabled = TRUE
                GROUP BY fc.feed_id, fc.name
                ORDER BY fc.feed_id
            """)
            feeds = [
                {
                    "feed_id": row[0],
                    "name": row[1],
                    "doc_count": row[2],
                    "discovering": f"discovery-{row[0]}" in discovery_threads,
                }
                for row in cur.fetchall()
            ]
        return {
            "discovery_running": len(discovery_threads) > 0,
            "active_feeds": discovery_threads,
            "feeds": feeds,
        }
    finally:
        conn.close()


# ── POST /api/query ───────────────────────────────────────────────────────────


@app.post("/api/query")
async def submit_query(request: QueryRequest):
    """Execute a regulatory intelligence query.

    Routes to CONTENT path (semantic RAG) or METADATA path based on
    query text analysis. Every query is persisted to query_history.
    """
    query_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    filters = request.filters or QueryFilters()
    retrieval = request.retrieval_params or RetrievalParams()

    # LLM-based query classification
    routing_path, classifier = classify_query(request.query)
    if routing_path == "METADATA":
        result = await _run_metadata_query(query_id, timestamp, request, filters, retrieval, routing_path, classifier)
    else:
        result = await _run_content_query(query_id, timestamp, request, filters, retrieval, routing_path, classifier)

    # Persist to query_history
    filters_dict = filters.model_dump() if filters else {}
    retrieval_dict = retrieval.model_dump() if retrieval else {}
    try:
        persist_query(
            query_id=query_id,
            query_text=request.query,
            routing_path=result["routing_path"],
            answer=result["answer"],
            citations=result["citations"],
            sub_queries=result.get("sub_queries", []),
            filters_applied=filters_dict,
            retrieval_params=retrieval_dict,
            langfuse_trace_id=result.get("langfuse_trace_id", ""),
            timestamp=timestamp,
            model_used=get_active_model(),
            classifier=classifier,
        )
    except Exception as e:
        logger.error("Failed to persist query %s: %s", query_id, e)
        # Query still returns to user even if persistence fails

    return result


async def _run_content_query(
    query_id: str,
    timestamp: str,
    request: QueryRequest,
    filters: QueryFilters,
    retrieval: RetrievalParams,
    routing_path: str = "CONTENT",
    classifier: str = "",
) -> dict:
    """Execute a CONTENT-path (semantic RAG) query."""
    import time as _time

    depth_map = {"low": 2, "standard": 3, "deep": 5}
    n_sub_queries = depth_map.get(retrieval.query_depth, 3)

    # Langfuse tracing
    lf = get_langfuse()
    lf_trace = None
    try:
        if lf:
            lf_trace = lf.trace(
                id=query_id,
                name="query",
                input={"query": request.query, "filters": filters.model_dump() if filters else {}},
                metadata={"routing_path": routing_path, "classifier": classifier, "query_depth": retrieval.query_depth},
            )
    except Exception:
        lf = None
        lf_trace = None

    try:
        # Step 1: Query expansion
        t_retrieval = _time.monotonic()
        sub_queries = await expand_query(request.query, n_sub_queries)

        # Include original query too
        all_queries = [request.query] + sub_queries

        # Step 2: Build Qdrant filter
        qdrant_filter = build_qdrant_filter(filters)

        # Step 3: Retrieve chunks per sub-query
        all_chunks = []
        for sq in all_queries:
            chunks = await retrieve_chunks(sq, qdrant_filter, retrieval.top_k, retrieval.score_threshold)
            all_chunks.extend(chunks)

        # Step 3b: Post-retrieval date filtering (Qdrant stores dates as strings,
        # so date range must be applied here rather than in the Qdrant query)
        if filters.date_from or filters.date_to:
            def _in_date_range(chunk):
                d = chunk.get("publication_date") or ""
                if filters.date_from and d and d < filters.date_from:
                    return False
                if filters.date_to and d and d > filters.date_to:
                    return False
                return True
            all_chunks = [c for c in all_chunks if _in_date_range(c)]

        # Step 4: Deduplicate — best score per document_id, top 8
        deduped_chunks = deduplicate_chunks(all_chunks, top_n=8)

        # Step 4a: Force-include chunks from explicitly mentioned documents.
        # When a query names a specific document (e.g. "Annex 11", "21 CFR Part 11"),
        # fetch chunks from that document regardless of semantic ranking. This ensures
        # GxP queries that name regulatory documents always get content from them.
        mentioned_docs = extract_mentioned_documents(request.query)
        if mentioned_docs:
            for doc_id in mentioned_docs:
                already_present = any(
                    c.get("document_id") == doc_id for c in deduped_chunks
                )
                if not already_present:
                    forced = await fetch_document_chunks(doc_id, request.query, limit=3)
                    if forced:
                        logger.info(
                            "Force-included %d chunks from %s (explicitly mentioned in query)",
                            len(forced), doc_id,
                        )
                        deduped_chunks = deduped_chunks + forced
            # Re-sort after merging
            deduped_chunks = sorted(deduped_chunks, key=lambda c: c["score"], reverse=True)

        # Step 4b: Supersede-pair detection — zero overhead when no family present
        supersede_context = None
        try:
            _pg_sup = get_pg_conn()
            supersede_context = detect_supersede_pair(deduped_chunks, _pg_sup)
            if supersede_context:
                # Determine which family member is absent from semantic results
                retrieved_doc_ids = {c.get("document_id") for c in deduped_chunks}
                for member in supersede_context["members"]:
                    if member["document_id"] not in retrieved_doc_ids:
                        supplement = fetch_family_supplement_chunks(member["document_id"])
                        deduped_chunks = deduped_chunks + supplement
                        break
            _pg_sup.close()
        except Exception:
            supersede_context = None

        t_retrieval2 = _time.monotonic()

        if lf and lf_trace:
            lf_trace.span(
                name="retrieval",
                input={
                    "query": request.query,
                    "sub_queries": sub_queries,
                    "top_k": retrieval.top_k,
                    "score_threshold": retrieval.score_threshold,
                },
                output={
                    "chunks_retrieved": len(all_chunks),
                    "chunks_after_dedup": len(deduped_chunks),
                },
                metadata={"latency_ms": round((t_retrieval2 - t_retrieval) * 1000)},
            )

        # Step 5: Build context and generate answer
        if not deduped_chunks:
            result = {
                "query_id": query_id,
                "timestamp": timestamp,
                "routing_path": "CONTENT",
                "sub_queries": sub_queries,
                "answer": "No sources above the relevance threshold were found for this query.",
                "citations": [],
                "retrieval_params_applied": {
                    "query_depth": retrieval.query_depth,
                    "top_k": retrieval.top_k,
                    "score_threshold": retrieval.score_threshold,
                    "sub_query_count": n_sub_queries,
                },
            }
            trace_id = lf_trace.id if lf_trace else ""
            try:
                if lf and lf_trace:
                    lf_trace.update(output={"answer": "No sources above the relevance threshold were found for this query."})
                    lf.flush()
            except Exception:
                pass
            result["langfuse_trace_id"] = trace_id
            return result

        context = build_context(deduped_chunks)
        framing = build_supersede_framing(supersede_context)
        prompt = f"{framing}Context:\n\n{context}\n\nQuestion: {request.query}\n\nAnswer:"
        t_llm = _time.monotonic()
        answer, llm_usage = await ollama_generate(prompt, system=SYSTEM_PROMPT_V9, return_usage=True, model=request.generation_model or None)
        t_llm2 = _time.monotonic()
        llm_latency_ms = round((t_llm2 - t_llm) * 1000)

        if lf and lf_trace:
            lf_trace.generation(
                name="llm_answer",
                model=get_active_model(),
                input={"prompt": prompt, "system": SYSTEM_PROMPT_V9},
                output={"answer": answer},
                usage=llm_usage,
                metadata={"latency_ms": llm_latency_ms, "system_prompt_version": SYSTEM_PROMPT_VERSION},
            )

        # Step 6: Determine which chunks were cited
        cited_indices = parse_citations(answer, len(deduped_chunks))

        # Fallback: if LLM didn't use any [N] markers, treat top 3 as cited
        if not cited_indices and deduped_chunks:
            cited_indices = set(range(1, min(4, len(deduped_chunks) + 1)))

        # Step 7: Build citations array (with provenance batch)
        doc_ids = [c.get("document_id", "") for c in deduped_chunks if c.get("document_id")]
        try:
            pg_conn_prov = get_pg_conn()
            prov_map = fetch_chunk_provenance_batch(pg_conn_prov, doc_ids)
            pg_conn_prov.close()
        except Exception:
            prov_map = {}

        cited_chunks = []
        uncited_chunks = []
        for i, chunk in enumerate(deduped_chunks, 1):
            doc_id = chunk.get("document_id", "")
            citation = build_citation(chunk, i, i in cited_indices, prov_map.get(doc_id))
            if i in cited_indices:
                cited_chunks.append(citation)
            else:
                uncited_chunks.append(citation)

        # Sort: MATCHED first, NOT CITED after; score descending within each group
        all_citations = sorted(cited_chunks + uncited_chunks, key=lambda c: (not c["cited_by_llm"], -c["score"]))

        trace_id = lf_trace.id if lf_trace else ""

        try:
            if lf and lf_trace:
                lf_trace.update(output={"answer": answer})
                lf.flush()
        except Exception:
            pass

        result = {
            "query_id": query_id,
            "timestamp": timestamp,
            "routing_path": "CONTENT",
            "sub_queries": sub_queries,
            "answer": answer.strip(),
            "citations": all_citations,
            "supersede_context": supersede_context,
            "retrieval_params_applied": {
                "query_depth": retrieval.query_depth,
                "top_k": retrieval.top_k,
                "score_threshold": retrieval.score_threshold,
                "sub_query_count": n_sub_queries,
            },
        }
        result["langfuse_trace_id"] = trace_id
        return result
    except Exception:
        # If instrumentation fails, still try to flush
        try:
            if lf:
                lf.flush()
        except Exception:
            pass
        raise


def _infer_date_range(query_lower: str, existing_from=None, existing_to=None):
    """Parse natural-language date expressions and return (date_from_iso, date_to_iso).
    Returns the existing values unchanged if they are already set."""
    if existing_from or existing_to:
        return existing_from, existing_to
    today = _date.today()
    m = re.search(r'last\s+(\d+)\s+days?', query_lower)
    if m:
        return (today - _timedelta(days=int(m.group(1)))).isoformat(), None
    m = re.search(r'last\s+(\d+)\s+weeks?', query_lower)
    if m:
        return (today - _timedelta(weeks=int(m.group(1)))).isoformat(), None
    m = re.search(r'last\s+(\d+)\s+months?', query_lower)
    if m:
        try:
            from dateutil.relativedelta import relativedelta as _rd
            return (today - _rd(months=int(m.group(1)))).isoformat(), None
        except ImportError:
            return (today - _timedelta(days=int(m.group(1)) * 30)).isoformat(), None
    m = re.search(r'(last|past)\s+year', query_lower)
    if m:
        try:
            from dateutil.relativedelta import relativedelta as _rd
            return (today - _rd(years=1)).isoformat(), None
        except ImportError:
            return (today - _timedelta(days=365)).isoformat(), None
    if 'this year' in query_lower:
        return _date(today.year, 1, 1).isoformat(), None
    m = re.search(r'\bin\s+(20\d{2})\b', query_lower)
    if m:
        yr = int(m.group(1))
        return _date(yr, 1, 1).isoformat(), _date(yr, 12, 31).isoformat()
    return existing_from, existing_to


async def _run_metadata_query(
    query_id: str,
    timestamp: str,
    request: QueryRequest,
    filters: QueryFilters,
    retrieval: RetrievalParams,
    routing_path: str = "METADATA",
    classifier: str = "",
) -> dict:
    """Execute a METADATA-path query using Qdrant scroll/count and PostgreSQL."""
    import time as _time

    query_lower = request.query.lower()
    qdrant_filter = build_qdrant_filter(filters)

    # Langfuse tracing
    lf = get_langfuse()
    lf_trace = None
    t0 = _time.monotonic()
    try:
        if lf:
            lf_trace = lf.trace(
                id=query_id,
                name="query",
                input={"query": request.query, "filters": filters.model_dump() if filters else {}},
                metadata={"routing_path": routing_path, "classifier": classifier},
            )
    except Exception:
        lf = None
        lf_trace = None

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Determine what kind of metadata query this is
    is_count = any(w in query_lower for w in ["how many", "how much", "count of", "number of"])
    is_list = any(w in query_lower for w in ["list", "show", "find all", "what are", "available", "which documents", "what documents", "what guidelines", "which guidelines"])
    is_current_version = any(w in query_lower for w in ["current version", "what is the current", "latest version", "which version", "what version"])
    is_publication_date = re.search(r'\bwhen\s+was\b|\bpublish(ed|ed\s+in)?\b.*\bwhen\b|\bpublication\s+date\b|\brelease\s+date\b', query_lower) is not None

    # Infer agency and document_type from query text if not set by request filters.
    # This lets "How many FDA guidance documents" work without the filter bar being set.
    inferred_agency = filters.agency
    if not inferred_agency:
        if "fda" in query_lower:
            inferred_agency = "FDA"
        elif "ema" in query_lower or "european medicines" in query_lower:
            inferred_agency = "EMA"
        elif "ich" in query_lower:
            inferred_agency = "ICH"

    inferred_doc_type = filters.document_type
    if not inferred_doc_type:
        if any(w in query_lower for w in ["guidance document", "guidance documents", "guideline", "guidelines"]):
            inferred_doc_type = "guidance"
        elif any(w in query_lower for w in ["press release", "press releases"]):
            inferred_doc_type = "press-release"
        elif any(w in query_lower for w in ["reflection paper", "reflection papers"]):
            inferred_doc_type = "reflection-paper"

    # Infer date range from query text when not set by filter bar
    inferred_date_from, inferred_date_to = _infer_date_range(
        query_lower, filters.date_from, filters.date_to
    )

    # Rebuild filter using inferred values when query text contains agency/type/date hints
    if (inferred_agency != filters.agency or inferred_doc_type != filters.document_type
            or inferred_date_from != filters.date_from or inferred_date_to != filters.date_to):
        inferred_filters = QueryFilters(
            agency=inferred_agency,
            document_type=inferred_doc_type,
            date_from=inferred_date_from,
            date_to=inferred_date_to,
        )
        qdrant_filter = build_qdrant_filter(inferred_filters)
    else:
        inferred_filters = filters

    citations = []
    answer = ""

    if is_count:
        # Count distinct documents from PostgreSQL document_registry
        import psycopg2 as _psycopg2
        total = 0
        pg_rows = []
        try:
            _conn = _psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                dbname=POSTGRES_DB, user=POSTGRES_USER,
                password=POSTGRES_PASSWORD, connect_timeout=5
            )
            _cur = _conn.cursor()
            where_clauses = ["ingestion_status = 'indexed'"]
            params = []
            if inferred_filters.agency:
                where_clauses.append("issuing_body = ANY(%s)")
                # Include EU-Commission when filtering for EMA
                if inferred_filters.agency == "EMA":
                    params.append(["EMA", "EU-Commission"])
                else:
                    params.append([inferred_filters.agency])
            if inferred_filters.document_type:
                # Map hyphenated UI values to the actual doc_type values in document_registry.
                # "guidance" covers both old guidance_pdf and new guidance ingestion paths.
                doc_type_map = {
                    "guidance": ["guidance", "guidance_pdf"],
                    "press-release": ["press_release"],
                    "reflection-paper": ["reflection_paper"],
                }
                pg_doc_types = doc_type_map.get(
                    inferred_filters.document_type,
                    [inferred_filters.document_type.replace("-", "_")]
                )
                where_clauses.append("doc_type = ANY(%s)")
                params.append(pg_doc_types)
            if inferred_filters.date_from:
                where_clauses.append("publication_date >= %s::date")
                params.append(inferred_filters.date_from)
            if inferred_filters.date_to:
                where_clauses.append("publication_date <= %s::date")
                params.append(inferred_filters.date_to)
            where_sql = "WHERE " + " AND ".join(where_clauses)
            _cur.execute(
                f"SELECT COUNT(*) FROM document_registry {where_sql}", params
            )
            total = _cur.fetchone()[0] or 0

            # Fetch a few representative documents for citations
            _cur.execute(
                f"""SELECT document_id,
                           metadata_json->>'document_title' as title,
                           issuing_body, document_version,
                           metadata_json->>'publication_date' as pub_date,
                           archive_path
                    FROM document_registry {where_sql}
                    ORDER BY metadata_json->>'publication_date' DESC NULLS LAST
                    LIMIT 5""",
                params
            )
            pg_rows = _cur.fetchall()
            _cur.close()
            _conn.close()
        except Exception as _e:
            logger.warning(f"Metadata count PG query failed, falling back to Qdrant: {_e}")
            # Fallback: count distinct document_ids via Qdrant scroll
            _seen = set()
            _offset = None
            while True:
                _res, _offset = client.scroll(
                    collection_name=QDRANT_COLLECTION,
                    scroll_filter=qdrant_filter,
                    limit=100,
                    offset=_offset,
                    with_payload=["document_id"],
                )
                for _p in _res:
                    _seen.add(_p.payload.get("document_id", str(_p.id)))
                if _offset is None:
                    break
            total = len(_seen)

        for i, row in enumerate(pg_rows, 1):
            doc_id, title, agency, version, pub_date, archive_path = row
            citations.append({
                "index": i,
                "chunk_id": "",
                "document_id": doc_id,
                "chunk_text": "",
                "document_title": strip_title_suffix(title or "") or "Untitled",
                "issuing_body": normalise_agency(agency or ""),
                "document_version": version,
                "clause_id": None,
                "publication_date": pub_date,
                "page_no": None,
                "chunk_index": None,
                "char_offset_start": None,
                "char_offset_end": None,
                "chunked_at": None,
                "score": 1.0,
                "cited_by_llm": True,
                "superseded": False,
                "superseded_by": None,
                "source_local_path": None,
                "source_url": "",
            })

        agency_str = f"from {inferred_filters.agency}" if inferred_filters.agency else "across all agencies"
        type_str = f" {inferred_filters.document_type} " if inferred_filters.document_type else " "
        if inferred_filters.date_from and inferred_filters.date_to:
            date_str = f" published between {inferred_filters.date_from} and {inferred_filters.date_to}"
        elif inferred_filters.date_from:
            date_str = f" published since {inferred_filters.date_from}"
        else:
            date_str = ""

        answer = f"There are {total}{type_str}documents {agency_str}{date_str} in the indexed corpus."

    elif is_current_version:
        # Look up document version from PostgreSQL document_registry
        import psycopg2
        answer_parts = []
        try:
            conn = psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                dbname=POSTGRES_DB, user=POSTGRES_USER,
                password=POSTGRES_PASSWORD, connect_timeout=5
            )
            cur = conn.cursor()
            where_clauses = ["ingestion_status = 'indexed'"]
            params = []
            if inferred_filters.agency:
                if inferred_filters.agency == "EMA":
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append(["EMA", "EU-Commission"])
                else:
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append([inferred_filters.agency])
            # Extract title keywords — strip version/meta stop words
            _ver_stop = {"which", "what", "version", "is", "the", "in", "knowledge", "base",
                         "current", "latest", "of", "a", "an", "are", "available"}
            _ver_words = [w for w in re.sub(r'[^\w\s]', ' ', query_lower).split()
                          if w not in _ver_stop and len(w) > 1]
            for kw in _ver_words[:5]:
                where_clauses.append("LOWER(metadata_json->>'document_title') LIKE %s")
                params.append(f"%{kw}%")
            where = "WHERE " + " AND ".join(where_clauses)
            cur.execute(
                f"""SELECT document_id, metadata_json->>'document_title' as title,
                          document_version, metadata_json->>'publication_date' as pub_date,
                          issuing_body, document_status, document_family_id
                   FROM document_registry
                   {where}
                   ORDER BY metadata_json->>'document_title'"""
                , params
            )
            rows = cur.fetchall()

            # Build family map for supersede detection
            families = {}
            for row in rows:
                doc_id, title, version, pub_date, agency, status, family_id = row
                if family_id:
                    if family_id not in families:
                        families[family_id] = []
                    families[family_id].append(row)

            for row in rows:
                doc_id, title, version, pub_date, agency, status, family_id = row
                agency_norm = normalise_agency(agency or "")
                title_clean = strip_title_suffix(title or "")

                superseded = False
                superseded_by = None
                if family_id and family_id in families:
                    # Check if a newer version exists in same family
                    for other in families[family_id]:
                        if other[0] != doc_id and other[3] and pub_date and other[3] > pub_date:
                            superseded = True
                            superseded_by = strip_title_suffix(other[1] or other[0])
                            break

                if is_current_version and superseded:
                    continue

                answer_parts.append(
                    f"{title_clean} ({agency_norm}): version {version or 'unknown'}"
                    f"{', published ' + pub_date if pub_date else ''}"
                    f"{' [SUPERSEDED by ' + superseded_by + ']' if superseded else ''}"
                )

                citations.append({
                    "index": len(citations) + 1,
                    "chunk_id": "",
                    "document_id": doc_id,
                    "chunk_text": "",
                    "document_title": title_clean or "Untitled",
                    "issuing_body": agency_norm,
                    "document_version": version,
                    "clause_id": None,
                    "publication_date": pub_date,
                    "page_no": None,
                    "chunk_index": None,
                    "char_offset_start": None,
                    "char_offset_end": None,
                    "chunked_at": None,
                    "score": 1.0,
                    "cited_by_llm": True,
                    "superseded": superseded,
                    "superseded_by": superseded_by,
                    "source_local_path": None,
                    "source_url": "",
                })

            cur.close()
            conn.close()

            if not answer_parts:
                answer = "No matching documents found in the document registry."
            else:
                answer = "\n".join(answer_parts)
        except Exception as e:
            logger.exception("Metadata version query failed")
            answer = f"Unable to look up document versions: {e}"

    elif is_list:
        # List documents from PostgreSQL with all inferred filters applied
        import psycopg2 as _psycopg2
        pg_rows = []
        try:
            _conn = _psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                dbname=POSTGRES_DB, user=POSTGRES_USER,
                password=POSTGRES_PASSWORD, connect_timeout=5
            )
            _cur = _conn.cursor()
            where_clauses = ["ingestion_status = 'indexed'"]
            params = []
            if inferred_filters.agency:
                if inferred_filters.agency == "EMA":
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append(["EMA", "EU-Commission"])
                else:
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append([inferred_filters.agency])
            if inferred_filters.document_type:
                doc_type_map = {
                    "guidance": ["guidance", "guidance_pdf"],
                    "press-release": ["press_release"],
                    "reflection-paper": ["reflection_paper"],
                }
                pg_doc_types = doc_type_map.get(
                    inferred_filters.document_type,
                    [inferred_filters.document_type.replace("-", "_")]
                )
                where_clauses.append("doc_type = ANY(%s)")
                params.append(pg_doc_types)
            if inferred_filters.date_from:
                where_clauses.append("publication_date >= %s::date")
                params.append(inferred_filters.date_from)
            if inferred_filters.date_to:
                where_clauses.append("publication_date <= %s::date")
                params.append(inferred_filters.date_to)
            where_sql = "WHERE " + " AND ".join(where_clauses)
            _cur.execute(
                f"""SELECT document_id,
                           metadata_json->>'document_title' as title,
                           issuing_body, document_version,
                           publication_date, source_url
                    FROM document_registry {where_sql}
                    ORDER BY publication_date DESC NULLS LAST
                    LIMIT 50""",
                params
            )
            pg_rows = _cur.fetchall()
            _cur.close()
            _conn.close()
        except Exception as _e:
            logger.warning(f"Metadata list PG query failed: {_e}")

        def _fmt_date(d):
            if not d:
                return ""
            s = str(d)[:10]
            try:
                from datetime import date as _d
                parts = s.split("-")
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
            except Exception:
                return s

        items = []
        for i, row in enumerate(pg_rows, 1):
            doc_id, title, agency, version, pub_date, src_url = row
            title_clean = strip_title_suffix(title or "") or "Untitled"
            agency_norm = normalise_agency(agency or "")
            date_part = f" · {_fmt_date(pub_date)}" if pub_date else ""
            version_part = f" · {version}" if version else ""
            items.append(
                f"{i}. [{title_clean}](/corpus/{doc_id}){version_part}{date_part}"
            )
            citations.append({
                "index": i,
                "chunk_id": "",
                "document_id": doc_id,
                "chunk_text": "",
                "document_title": title_clean,
                "issuing_body": agency_norm,
                "document_version": version,
                "clause_id": None,
                "publication_date": str(pub_date)[:10] if pub_date else None,
                "page_no": None,
                "chunk_index": None,
                "char_offset_start": None,
                "char_offset_end": None,
                "chunked_at": None,
                "score": 1.0,
                "cited_by_llm": True,
                "superseded": False,
                "superseded_by": None,
                "source_local_path": None,
                "source_url": src_url or "",
            })

        if items:
            agency_str = f"{inferred_filters.agency} " if inferred_filters.agency else ""
            type_str = f"{inferred_filters.document_type} " if inferred_filters.document_type else ""
            if inferred_filters.date_from:
                date_str = f" published since {_fmt_date(inferred_filters.date_from)}"
            else:
                date_str = ""
            header = f"{len(items)} {agency_str}{type_str}document{'s' if len(items) != 1 else ''}{date_str}:"
            answer = header + "\n\n" + "\n".join(items)
        else:
            answer = "No documents found matching your criteria."
    elif is_publication_date:
        # Publication date lookup: find the best-matching document and return its date
        import psycopg2 as _psycopg2
        # Extract meaningful keywords from query for document title search
        stop_words = {"when", "was", "is", "the", "published", "released", "publication",
                      "date", "of", "what", "year", "a", "an", "in", "for", "and", "or"}
        query_words = [w for w in re.sub(r'[^\w\s]', ' ', query_lower).split()
                       if w not in stop_words and len(w) > 1]

        pg_rows = []
        try:
            _conn = _psycopg2.connect(
                host=POSTGRES_HOST, port=POSTGRES_PORT,
                dbname=POSTGRES_DB, user=POSTGRES_USER,
                password=POSTGRES_PASSWORD, connect_timeout=5
            )
            _cur = _conn.cursor()
            where_clauses = ["ingestion_status = 'indexed'"]
            params = []
            if inferred_filters.agency:
                if inferred_filters.agency == "EMA":
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append(["EMA", "EU-Commission"])
                else:
                    where_clauses.append("issuing_body = ANY(%s)")
                    params.append([inferred_filters.agency])
            if query_words:
                # Each keyword must appear somewhere in the title (AND logic for precision)
                for kw in query_words[:5]:
                    where_clauses.append("LOWER(metadata_json->>'document_title') LIKE %s")
                    params.append(f"%{kw}%")
            where_sql = "WHERE " + " AND ".join(where_clauses)
            _cur.execute(
                f"""SELECT document_id,
                           metadata_json->>'document_title' as title,
                           issuing_body, publication_date, source_url
                    FROM document_registry {where_sql}
                    ORDER BY publication_date DESC NULLS LAST
                    LIMIT 5""",
                params
            )
            pg_rows = _cur.fetchall()
            _cur.close()
            _conn.close()
        except Exception as _e:
            logger.warning(f"Publication date PG query failed: {_e}")

        if pg_rows:
            parts = []
            for row in pg_rows:
                doc_id, title, agency, pub_date, src_url = row
                title_clean = strip_title_suffix(title or "") or "Untitled"
                agency_norm = normalise_agency(agency or "")
                if pub_date:
                    year = str(pub_date)[:4]
                    date_full = str(pub_date)[:10]
                    parts.append(
                        f"**{title_clean}** ({agency_norm}) was published on {date_full} (year: {year})."
                    )
                    citations.append({
                        "index": len(citations) + 1,
                        "chunk_id": "",
                        "document_id": doc_id,
                        "chunk_text": "",
                        "document_title": title_clean,
                        "issuing_body": agency_norm,
                        "document_version": None,
                        "clause_id": None,
                        "publication_date": date_full,
                        "page_no": None,
                        "chunk_index": None,
                        "char_offset_start": None,
                        "char_offset_end": None,
                        "chunked_at": None,
                        "score": 1.0,
                        "cited_by_llm": True,
                        "superseded": False,
                        "superseded_by": None,
                        "source_local_path": None,
                        "source_url": src_url or "",
                    })
                else:
                    parts.append(
                        f"**{title_clean}** ({agency_norm}): publication date not available in the corpus."
                    )
            answer = "\n\n".join(parts)
        else:
            answer = f"No document matching that description was found in the indexed corpus."

    else:
        # General metadata: count and overview
        count_result = client.count(
            collection_name=QDRANT_COLLECTION,
            count_filter=qdrant_filter,
            exact=True,
        )
        total = count_result.count if count_result else 0
        agency_str = f"from {inferred_filters.agency}" if inferred_filters.agency else "across all agencies"
        answer = f"Found {total} document chunks {agency_str} in the indexed corpus."

    trace_id = lf_trace.id if lf_trace else ""

    if lf and lf_trace:
        try:
            t1 = _time.monotonic()
            lf_trace.span(
                name="retrieval",
                input={"query": request.query},
                output={"answer": answer, "citation_count": len(citations)},
                metadata={"latency_ms": round((t1 - t0) * 1000)},
            )
            lf_trace.update(output={"answer": answer})
            lf.flush()
        except Exception:
            pass

    return {
        "query_id": query_id,
        "timestamp": timestamp,
        "routing_path": "METADATA",
        "sub_queries": [],
        "answer": answer.strip(),
        "citations": citations,
        "retrieval_params_applied": {
            "query_depth": retrieval.query_depth,
            "top_k": retrieval.top_k,
            "score_threshold": retrieval.score_threshold,
            "sub_query_count": 0,
        },
        "langfuse_trace_id": trace_id,
    }


# ── GET /api/query/history ────────────────────────────────────────────────────


@app.get("/api/query/history")
async def query_history(
    limit: int = 10,
    offset: int = 0,
    search: str = "",
    routing_path: str = "",
    date_from: str = "",
    date_to: str = "",
):
    """Return paginated, filtered query history from PostgreSQL."""
    conditions = []
    params: list = []

    if search:
        conditions.append("query_text ILIKE %s")
        params.append(f"%{search}%")
    if routing_path:
        conditions.append("routing_path = %s")
        params.append(routing_path)
    if date_from:
        conditions.append("timestamp::date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp::date <= %s")
        params.append(date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM query_history {where}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"""SELECT query_id, query_text, timestamp, routing_path,
                      citations, filters_applied
               FROM query_history
               {where}
               ORDER BY timestamp DESC
               LIMIT %s OFFSET %s""",
            params + [limit, offset]
        )
        rows = cur.fetchall()
        items = []
        for row in rows:
            qid, qtext, ts, routing, citations, filters_json = row
            cits = citations if isinstance(citations, list) else json.loads(citations or "[]")
            filts = filters_json if isinstance(filters_json, dict) else json.loads(filters_json or "{}")
            items.append({
                "query_id": qid,
                "query_text": qtext,
                "timestamp": ts.isoformat() if ts else "",
                "routing_path": routing or "",
                "citation_count": len(cits),
                "filters_applied": filts,
                "agency_filter": filts.get("agency", "All"),
            })
        cur.close()
        return {"items": items, "total": total}
    finally:
        conn.close()


# ── GET /api/query/history/export ─────────────────────────────────────────────


def build_audit_query(
    date_from=None,
    date_to=None,
    search=None,
        routing_path=None,
    limit=500,
) -> tuple[str, list]:
    """Build filtered query_history SELECT with parameterised filters."""
    conditions = []
    params = []

    if date_from:
        conditions.append("timestamp::date >= %s")
        params.append(date_from)

    if date_to:
        conditions.append("timestamp::date <= %s")
        params.append(date_to)

    if search:
        conditions.append("(query_text ILIKE %s OR answer ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    if routing_path:
        conditions.append("routing_path = %s")
        params.append(routing_path)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT
            query_id, query_text, routing_path, timestamp,
            answer, citations, sub_queries,
            filters_applied, retrieval_params,
            langfuse_trace_id, model_used
        FROM query_history
        {where}
        ORDER BY timestamp DESC
        LIMIT %s
    """
    params.append(limit)

    return sql, params


@app.get("/api/query/history/export")
async def export_history(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    date_from: Optional[_date] = Query(None),
    date_to: Optional[_date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    routing_path: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
):
    import csv
    from io import StringIO, BytesIO

    sql, params = build_audit_query(
        date_from=date_from,
        date_to=date_to,
        search=search,
        routing_path=routing_path,
        limit=limit,
    )

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if format == "csv":
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "query_id", "timestamp", "query_text", "answer_excerpt", "routing",
            "model_used", "agency_filter", "document_type_filter",
            "date_from", "date_to", "query_depth", "top_k", "score_threshold",
            "sub_queries", "citation_count", "cited_document_ids", "cited_document_titles",
            "langfuse_trace_id",
        ])

        for row in rows:
            (qid, qtext, routing, ts, answer, citations_raw,
             sub_queries_raw, filters_raw, retrieval_raw,
             trace_id, model_used) = row

            citations = citations_raw if isinstance(citations_raw, list) else (json.loads(citations_raw) if citations_raw else [])
            sub_queries = sub_queries_raw if isinstance(sub_queries_raw, list) else (json.loads(sub_queries_raw) if sub_queries_raw else [])
            filters = filters_raw if isinstance(filters_raw, dict) else (json.loads(filters_raw) if filters_raw else {})
            retrieval = retrieval_raw if isinstance(retrieval_raw, dict) else (json.loads(retrieval_raw) if retrieval_raw else {})

            cited = [c for c in citations if c.get("cited_by_llm")]
            cited_ids = " | ".join(c.get("document_id", "") for c in cited)
            cited_titles = " | ".join(c.get("document_title", "") for c in cited)

            routing_label = "Metadata lookup" if routing == "METADATA" else "Semantic search"

            answer_text = answer or ""
            answer_excerpt = (answer_text[:300] + "… [full answer: load query_id in regpulse]") if len(answer_text) > 300 else answer_text

            writer.writerow([
                qid, ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                qtext, answer_excerpt, routing_label, model_used or "",
                filters.get("agency") or "All", filters.get("document_type") or "All",
                filters.get("date_from") or "", filters.get("date_to") or "",
                retrieval.get("query_depth") or "", retrieval.get("top_k") or "",
                retrieval.get("score_threshold") or "", " | ".join(sub_queries),
                len(citations), cited_ids, cited_titles, trace_id or "",
            ])

        date_suffix = ""
        if date_from and date_to:
            date_suffix = f"_{date_from}_{date_to}"
        elif date_from:
            date_suffix = f"_from_{date_from}"
        filename = f"regpulse_audit{date_suffix}.csv"

        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif format == "pdf":
        if not rows:
            raise HTTPException(status_code=404, detail="No queries match the filters")

        import io as _io

        # Build query list for audit log
        queries = []
        for row in rows:
            (qid, qtext, routing, ts, answer, citations_raw,
             sub_queries_raw, filters_raw, retrieval_raw,
             trace_id, model_used) = row

            citations = citations_raw if isinstance(citations_raw, list) else (json.loads(citations_raw) if citations_raw else [])
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

            queries.append({
                "query_id": str(qid),
                "query_text": qtext or "",
                "timestamp": ts_iso,
                "routing_path": routing or "",
                "prompt_version": (retrieval_raw or {}).get("prompt_version", "") if isinstance(retrieval_raw, dict) else "",
                "answer": answer or "",
                "citations": citations,
                "langfuse_trace_id": str(trace_id) if trace_id else "",
            })

        filters_for_cover = {
            "date_from": datetime.strptime(str(date_from), "%Y-%m-%d").strftime("%d.%m.%Y") if date_from else None,
            "date_to": datetime.strptime(str(date_to), "%Y-%m-%d").strftime("%d.%m.%Y") if date_to else None,
            "search": search,
            "routing_path": routing_path,
        }

        # Get corpus date from most recent successful ingestion run
        corpus_date = "—"
        try:
            cfg_conn = get_pg_conn()
            with cfg_conn.cursor() as c:
                c.execute(
                    "SELECT completed_at FROM run_log"
                    " WHERE status = 'success' AND items_new > 0"
                    " ORDER BY completed_at DESC LIMIT 1"
                )
                row = c.fetchone()
            cfg_conn.close()
            if row and row[0]:
                corpus_date = row[0].strftime("%d.%m.%Y")
        except Exception:
            pass

        from lib.pdf_export import generate_audit_log_pdf
        pdf_bytes = generate_audit_log_pdf(
            queries=queries,
            filters_applied=filters_for_cover,
            corpus_date=corpus_date,
            system_version=APP_VERSION,
        )

        date_suffix = ""
        if date_from and date_to:
            date_suffix = f"_{date_from}_{date_to}"
        filename = f"regpulse_audit_log{date_suffix}_{len(queries)}queries.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


# ── GET /api/audit/count ──────────────────────────────────────────────────────


@app.get("/api/audit/count")
async def audit_count(
    date_from: Optional[_date] = Query(None),
    date_to: Optional[_date] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    routing_path: Optional[str] = Query(None),
):
    sql, params = build_audit_query(
        date_from=date_from,
        date_to=date_to,
        search=search,
        routing_path=routing_path,
        limit=99999,
    )
    # Wrap in COUNT(*) — remove the LIMIT param for count
    count_sql = f"SELECT COUNT(*) FROM ({sql.rstrip()}) sub"
    count_params = params

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(count_sql, count_params)
        row = cur.fetchone()
        cur.close()
        count = row[0] if row else 0
    finally:
        conn.close()

    return {"count": count}


# ── GET /api/query/{query_id} ──────────────────────────────────────────────────


@app.get("/api/query/{query_id}")
async def get_query(query_id: str):
    """Return a cached query result from query_history."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT query_text, routing_path, answer, citations, sub_queries, "
            "filters_applied, retrieval_params, langfuse_trace_id, timestamp "
            "FROM query_history WHERE query_id = %s",
            (query_id,)
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Query not found")

        (query_text, routing_path, answer, citations, sub_queries,
         filters_applied, retrieval_params, langfuse_trace_id, timestamp) = row

        citations_list = json.loads(citations) if isinstance(citations, str) else (citations or [])
        retrieval_dict = json.loads(retrieval_params) if isinstance(retrieval_params, str) else (retrieval_params or {})
        sub_queries_list = json.loads(sub_queries) if isinstance(sub_queries, str) else (sub_queries or [])

        if hasattr(timestamp, 'isoformat'):
            ts = timestamp
            if ts.tzinfo is not None:
                from datetime import timezone as _tz
                ts = ts.astimezone(_tz.utc)
            ts_iso = ts.isoformat()
        else:
            ts_iso = str(timestamp)

        return JSONResponse(content={
            "query_id": query_id,
            "query_text": query_text,
            "timestamp": ts_iso,
            "routing_path": routing_path,
            "sub_queries": sub_queries_list,
            "answer": answer,
            "citations": citations_list,
            "retrieval_params_applied": retrieval_dict,
            "langfuse_trace_id": langfuse_trace_id,
        })
    finally:
        conn.close()


# ── GET /api/query/{query_id}/export ──────────────────────────────────────────


@app.get("/api/query/{query_id}/export")
async def export_query(query_id: str, format: str = "json"):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT query_text, routing_path, answer, citations, sub_queries, "
            "filters_applied, retrieval_params, langfuse_trace_id, timestamp, classifier "
            "FROM query_history WHERE query_id = %s",
            (query_id,)
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Query not found")

        (query_text, routing_path, answer, citations, sub_queries,
         filters_applied, retrieval_params, langfuse_trace_id, timestamp, classifier) = row

        citations_list = json.loads(citations) if isinstance(citations, str) else (citations or [])
        filters_dict = json.loads(filters_applied) if isinstance(filters_applied, str) else (filters_applied or {})
        retrieval_dict = json.loads(retrieval_params) if isinstance(retrieval_params, str) else (retrieval_params or {})
        sub_queries_list = json.loads(sub_queries) if isinstance(sub_queries, str) else (sub_queries or [])

        routing_label = "Metadata lookup" if routing_path == "METADATA" else "Semantic search"
        # Normalise to UTC for consistency with query response timestamp
        if hasattr(timestamp, 'isoformat'):
            ts = timestamp
            if ts.tzinfo is not None:
                from datetime import timezone as tz
                ts = ts.astimezone(tz.utc)
            ts_iso = ts.isoformat()
        else:
            ts_iso = str(timestamp)

        if format == "json":
            export = {
                "query_id": query_id,
                "query_text": query_text,
                "timestamp": ts_iso,
                "routing_path": routing_label,
                "answer": answer,
                "citations": citations_list,
                "sub_queries": sub_queries_list,
                "filters_applied": filters_dict,
                "retrieval_params_applied": retrieval_dict,
                "uncited_chunks": [c for c in citations_list if not c.get("cited_by_llm")],
                "langfuse_trace_id": langfuse_trace_id,
                "classifier": classifier or "",
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "regpulse_version": APP_VERSION,
            }
            return JSONResponse(
                content=export,
                headers={"Content-Disposition": f'attachment; filename="regpulse-export-{query_id}.json"'},
            )

        elif format == "pdf":
            from lib.pdf_export import generate_query_export_pdf

            payload = {
                "query_id":               query_id,
                "query_text":             query_text,
                "timestamp":              ts_iso,
                "routing_path":           routing_path,
                "answer":                 answer,
                "citations":              citations_list,
                "sub_queries":            sub_queries_list,
                "filters_applied":        filters_dict,
                "retrieval_params_applied": retrieval_dict,
                "langfuse_trace_id":      langfuse_trace_id,
                "classifier":             classifier or "",
            }
            pdf_bytes = generate_query_export_pdf(payload)
            filename = f"regpulse-export-{query_id[:8]}.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

        else:
            raise HTTPException(status_code=400, detail="Format must be json or pdf")

    finally:
        conn.close()


# ── GET /api/trace/{trace_id} ─────────────────────────────────────────────────


@app.get("/api/trace/{trace_id}")
async def get_trace(trace_id: str):
    # Validate trace_id looks like a UUID before even checking config
    try:
        uuid.UUID(trace_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Trace not found")

    lf_public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    lf_secret = os.getenv("LANGFUSE_SECRET_KEY", "")
    lf_host = os.getenv("LANGFUSE_HOST", "")

    if not lf_public or not lf_secret:
        raise HTTPException(status_code=503, detail="Langfuse not configured — set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")

    import httpx
    import base64

    auth = base64.b64encode(f"{lf_public}:{lf_secret}".encode()).decode()
    url = f"{lf_host}/api/public/traces/{trace_id}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Basic {auth}"})
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Trace not found")
            if resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"Langfuse returned {resp.status_code}")
            data = resp.json()

            # Transform for frontend: convert latency s→ms, compute per-observation latency
            def _obs_latency(obs):
                # Prefer explicit latency from metadata (SDK v2 doesn't set endTime)
                meta = obs.get("metadata") or {}
                if "latency_ms" in meta:
                    return meta["latency_ms"]
                if obs.get("endTime") and obs.get("startTime"):
                    try:
                        from datetime import datetime as _dt

                        start = _dt.fromisoformat(obs["startTime"].replace("Z", "+00:00"))
                        end = _dt.fromisoformat(obs["endTime"].replace("Z", "+00:00"))
                        return round((end - start).total_seconds() * 1000)
                    except Exception:
                        pass
                return None

            def _stringify(v):
                if v is None:
                    return None
                if isinstance(v, str):
                    return v
                try:
                    return json.dumps(v)
                except Exception:
                    return str(v)

            data["latency"] = round(data.get("latency", 0) * 1000) if data.get("latency") else None
            for obs in data.get("observations", []):
                obs["latency"] = _obs_latency(obs)
                obs["input"] = _stringify(obs.get("input"))
                obs["output"] = _stringify(obs.get("output"))

            return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Trace fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to fetch trace from Langfuse")


# ── GET /api/query/{query_id}/trace  (G2 traceability panel) ─────────────────


@app.get("/api/query/{query_id}/trace")
async def get_query_trace(query_id: str):
    """Return structured LLM call data for the G2 traceability panel.

    Fetches the Langfuse trace for this query and extracts the llm_answer
    generation span into a flat structure the UI can display directly.
    """
    try:
        uuid.UUID(query_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Query not found")

    # Look up langfuse_trace_id from query_history
    try:
        conn = get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT langfuse_trace_id FROM query_history WHERE query_id = %s",
                (query_id,),
            )
            row = cur.fetchone()
        conn.close()
    except Exception:
        return {"error": "trace_unavailable"}

    if not row or not row[0]:
        return {"error": "trace_unavailable"}

    trace_id = row[0]
    lf_public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    lf_secret = os.getenv("LANGFUSE_SECRET_KEY", "")
    lf_host = os.getenv("LANGFUSE_HOST", "")

    if not lf_public or not lf_secret:
        return {"error": "trace_unavailable"}

    import base64
    auth = base64.b64encode(f"{lf_public}:{lf_secret}".encode()).decode()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{lf_host}/api/public/traces/{trace_id}",
                headers={"Authorization": f"Basic {auth}"},
            )
            if resp.status_code != 200:
                return {"error": "trace_unavailable"}
            data = resp.json()

        # Find spans we care about
        llm_obs = None
        retrieval_obs = None
        for obs in data.get("observations", []):
            if obs.get("type") == "GENERATION" and obs.get("name") == "llm_answer":
                llm_obs = obs
            elif obs.get("name") == "retrieval":
                retrieval_obs = obs

        # Pull chunk counts from retrieval span output
        chunks_retrieved = None
        chunks_sent = None
        if retrieval_obs:
            out = retrieval_obs.get("output") or {}
            if isinstance(out, str):
                try:
                    out = json.loads(out)
                except Exception:
                    out = {}
            chunks_retrieved = out.get("chunks_retrieved")
            chunks_sent = out.get("chunks_after_dedup")

        # Extract latency: prefer metadata, then computed from start/end
        def _latency_ms(obs):
            meta = obs.get("metadata") or {}
            if "latency_ms" in meta:
                return meta["latency_ms"]
            if obs.get("endTime") and obs.get("startTime"):
                try:
                    from datetime import datetime as _dt
                    start = _dt.fromisoformat(obs["startTime"].replace("Z", "+00:00"))
                    end = _dt.fromisoformat(obs["endTime"].replace("Z", "+00:00"))
                    return round((end - start).total_seconds() * 1000)
                except Exception:
                    pass
            # Fall back to trace-level latency (ms — already converted from s in trace data)
            lat = data.get("latency")
            if lat:
                # trace latency comes in seconds from Langfuse
                return round(lat * 1000) if lat < 10000 else lat
            return None

        if llm_obs:
            usage = llm_obs.get("usage") or {}
            latency = _latency_ms(llm_obs)
            # Timestamp from observation startTime
            ts = llm_obs.get("startTime") or data.get("timestamp")
            return {
                "model": llm_obs.get("model"),
                "timestamp": ts,
                "input_tokens": usage.get("input") or usage.get("promptTokens") or 0,
                "output_tokens": usage.get("output") or usage.get("completionTokens") or 0,
                "latency_ms": latency,
                "system_prompt_version": (llm_obs.get("metadata") or {}).get("system_prompt_version") or SYSTEM_PROMPT_VERSION,
                "chunks_sent_to_context": chunks_sent,
                "chunks_retrieved": chunks_retrieved,
            }
        else:
            # No LLM span — return trace-level data as fallback
            return {
                "model": None,
                "timestamp": data.get("timestamp"),
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": round(data.get("latency", 0) * 1000) if data.get("latency") else None,
                "system_prompt_version": SYSTEM_PROMPT_VERSION,
                "chunks_sent_to_context": chunks_sent,
                "chunks_retrieved": chunks_retrieved,
            }
    except Exception as e:
        logger.error("Query trace fetch failed: %s", e)
        return {"error": "trace_unavailable"}


# ── GET /api/system-prompt ────────────────────────────────────────────────────


@app.get("/api/system-prompt")
async def get_system_prompt():
    """Return the active system prompt text and version for the UI prompt viewer."""
    return {
        "version": SYSTEM_PROMPT_VERSION,
        "text": SYSTEM_PROMPT_V9,
    }


# ── GET /api/pdf/page ─────────────────────────────────────────────────────────


@app.get("/api/pdf/page")
async def pdf_page(file_path: str, page_no: int):
    # Rewrite host archive path to container mount
    local_path = file_path.replace("/mnt/data/regulatory_archive", "/archive")
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    import fitz

    doc = None
    try:
        doc = fitz.open(local_path)
        if page_no < 0 or page_no >= doc.page_count:
            raise HTTPException(status_code=404, detail=f"Page {page_no} out of range (0-{doc.page_count - 1})")

        page = doc.load_page(page_no)
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        return Response(content=img_bytes, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF render failed: %s", e)
        raise HTTPException(status_code=500, detail="PDF render failed")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


# ── GET /api/pdf/info ──────────────────────────────────────────────────────────


@app.get("/api/pdf/info")
async def pdf_info(file_path: str):
    local_path = file_path.replace("/mnt/data/regulatory_archive", "/archive")
    if not os.path.isfile(local_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    import fitz

    doc = None
    try:
        doc = fitz.open(local_path)
        return JSONResponse(content={"page_count": doc.page_count, "file_path": file_path})
    except Exception as e:
        logger.error("PDF info failed: %s", e)
        raise HTTPException(status_code=500, detail="PDF info failed")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
