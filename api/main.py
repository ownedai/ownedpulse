"""
regpulse API — FastAPI backend for regulatory intelligence queries.
Phase G: Query UI v2.
"""

import os
import re
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel, Field
from typing import Literal

from routers.corpus import router as corpus_router
from routers.admin import router as admin_router
from routers.bootstrap import router as bootstrap_router

# ── App init ──────────────────────────────────────────────────────────────────

app = FastAPI(title="regpulse API", version="0.8.0")

app.include_router(corpus_router, prefix="/api/corpus")
app.include_router(admin_router, prefix="/api/admin")
app.include_router(bootstrap_router, prefix="/api/bootstrap")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rp.ownedai.dev", "http://localhost:5173"],
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
):
    """Persist a query result to query_history. Raises on failure."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO query_history
               (query_id, query_text, routing_path, answer, citations,
                sub_queries, filters_applied, retrieval_params, langfuse_trace_id, timestamp, model_used)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                query_id, query_text, routing_path, answer,
                json.dumps(citations), json.dumps(sub_queries),
                json.dumps(filters_applied), json.dumps(retrieval_params),
                langfuse_trace_id, timestamp, model_used,
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
            """UPDATE document_registry
               SET ingestion_status = 'error',
                   ingestion_error   = 'Process was killed before ingestion completed',
                   updated_at        = NOW()
               WHERE ingestion_status = 'pending'
                 AND updated_at < NOW() - INTERVAL '1 hour'"""
        )
        docs = cur.rowcount

        cur.execute(
            """UPDATE run_log
               SET status       = 'error',
                   completed_at = NOW(),
                   error_detail = 'Process was killed before run completed'
               WHERE status = 'running'
                 AND triggered_at < NOW() - INTERVAL '1 hour'"""
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

@app.on_event("startup")
async def startup():
    init_db()
    _cleanup_abandoned_state()

from lib.observability import get_langfuse


# ── System prompt V6 ──────────────────────────────────────────────────────────

SYSTEM_PROMPT_V6 = (
    "You are a regulatory intelligence assistant for the pharmaceutical and "
    "life sciences industry. You answer questions based exclusively on the "
    "provided regulatory source documents (FDA, EMA, ICH guidance).\n\n"
    "IMPORTANT — Citation format:\n"
    "- You MUST cite EVERY factual claim with a numeric citation marker [N] "
    "that matches the source chunk numbers in the context.\n"
    "- Start with [1] for your first citation. Every sentence that states a "
    "regulatory requirement or fact MUST include at least one [N] marker.\n"
    "- Place citation markers [N] at the end of the complete sentence, after "
    "the final word but before the closing period. Never insert a citation "
    "mid-sentence. Never place a citation after a period. Maximum one "
    "citation per sentence.\n"
    "- Example: \"The FDA requires audit trails to be secure and tamper-evident [1].\"\n"
    "- Never use descriptive markers like \"(see source)\" or \"(FDA guidance)\" — "
    "only [N] with the chunk number.\n\n"
    "Rules:\n"
    "- Answer only from the provided context chunks. Do not use prior knowledge.\n"
    "- If the context does not contain enough information, say so explicitly.\n"
    "- Use precise regulatory language. Do not simplify or paraphrase requirements.\n"
    "- If a cited document is marked as SUPERSEDED, note this in your answer.\n"
    "- Format your answer as clean prose paragraphs separated by blank lines.\n"
    "- Do NOT use markdown bold headings. Do NOT use numbered lists unless the "
    "user explicitly asked for a list.\n"
    "- Do not give legal advice. State that queries requiring legal interpretation "
    "should be referred to a qualified regulatory professional."
)

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


# ── Metadata query detection ──────────────────────────────────────────────────

METADATA_PATTERNS = [
    re.compile(r'^how\s+many', re.IGNORECASE),
    re.compile(r'\bcount\s+(of|all|the)\b', re.IGNORECASE),
    re.compile(r'\blist\s+(all|the)\b', re.IGNORECASE),
    re.compile(r'\bwhen\s+was\b', re.IGNORECASE),
    re.compile(r'\bwhat\s+is\s+the\s+current\b', re.IGNORECASE),
    re.compile(r'\bwhat\s+version\b', re.IGNORECASE),
    re.compile(r'\bhow\s+much\b', re.IGNORECASE),
    re.compile(r'\bsearch\s+for\b', re.IGNORECASE),
]


def is_metadata_query(query: str) -> bool:
    """Detect if a query is asking for metadata, not semantic content."""
    return any(p.search(query) for p in METADATA_PATTERNS)


# ── Ollama helpers ────────────────────────────────────────────────────────────

import httpx

OLLAMA_BASE = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"


async def ollama_generate(
    prompt: str,
    system: str = "",
    model: str = None,
    temperature: float | None = None,
) -> str:
    """Call Ollama generate API and return the response text.

    temperature: None = model default (for answer generation).
                 0.0  = deterministic (for query expansion).
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
        return resp.json()["response"]


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
from qdrant_client.models import Filter, FieldCondition, IsEmptyCondition, PayloadField, MatchValue, MatchAny, Range
from qdrant_client.http.models import DatetimeRange


def build_qdrant_filter(filters: QueryFilters | None) -> Optional[Filter]:
    """Build a Qdrant Filter from the API filter request.

    Filters on:
    - issuing_body (for agency)
    - document_type (hyphenated, for document type)
    - publication_date (ISO string comparison for date range)

    Always excludes RSS-ingested chunks (those with feed_id set).
    """
    # Default: exclude RSS/HTML noise — chunks with feed_id payload set
    conditions = [IsEmptyCondition(is_empty=PayloadField(key="feed_id"))]

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

        if filters.date_from or filters.date_to:
            date_range = {}
            if filters.date_from:
                date_range["gte"] = filters.date_from
            if filters.date_to:
                date_range["lte"] = filters.date_to
            conditions.append(
                FieldCondition(key="publication_date", range=Range(**date_range))
            )

    return Filter(must=conditions)


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
    """Keep best-scoring chunk per document_id, then take top N by score."""
    seen = {}
    for chunk in chunks:
        doc_id = chunk.get("document_id", chunk.get("chunk_id"))
        if doc_id not in seen or chunk["score"] > seen[doc_id]["score"]:
            seen[doc_id] = chunk

    deduped = sorted(seen.values(), key=lambda c: c["score"], reverse=True)
    return deduped[:top_n]


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

        header = f"[{i}] {title} — {agency}"
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


def build_citation(chunk: dict, index: int, cited_by_llm: bool) -> dict:
    """Build a citation response object from a chunk."""
    title = chunk.get("document_title", "")
    if not title:
        section_path = chunk.get("section_path", [])
        if section_path:
            title = section_path[0]
    if not title:
        title = "Untitled"
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
    }


# ── Health endpoint ───────────────────────────────────────────────────────────


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

    # Determine routing
    if is_metadata_query(request.query):
        result = await _run_metadata_query(query_id, timestamp, request, filters, retrieval)
    else:
        result = await _run_content_query(query_id, timestamp, request, filters, retrieval)

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
                metadata={"routing_path": "CONTENT", "query_depth": retrieval.query_depth},
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

        # Step 4: Deduplicate — best score per document_id, top 8
        deduped_chunks = deduplicate_chunks(all_chunks, top_n=8)
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
        prompt = f"Context:\n\n{context}\n\nQuestion: {request.query}\n\nAnswer:"
        t_llm = _time.monotonic()
        answer = await ollama_generate(prompt, system=SYSTEM_PROMPT_V6)
        t_llm2 = _time.monotonic()

        if lf and lf_trace:
            lf_trace.generation(
                name="llm_answer",
                model=os.getenv("OLLAMA_MODEL", "phi4:14b-q8_0"),
                input={"prompt": prompt, "system": SYSTEM_PROMPT_V6},
                output={"answer": answer},
                metadata={"latency_ms": round((t_llm2 - t_llm) * 1000)},
            )

        # Step 6: Determine which chunks were cited
        cited_indices = parse_citations(answer, len(deduped_chunks))

        # Fallback: if LLM didn't use any [N] markers, treat top 3 as cited
        if not cited_indices and deduped_chunks:
            cited_indices = set(range(1, min(4, len(deduped_chunks) + 1)))

        # Step 7: Build citations array
        cited_chunks = []
        uncited_chunks = []
        for i, chunk in enumerate(deduped_chunks, 1):
            citation = build_citation(chunk, i, i in cited_indices)
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


async def _run_metadata_query(
    query_id: str,
    timestamp: str,
    request: QueryRequest,
    filters: QueryFilters,
    retrieval: RetrievalParams,
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
                metadata={"routing_path": "METADATA"},
            )
    except Exception:
        lf = None
        lf_trace = None

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Determine what kind of metadata query this is
    is_count = any(w in query_lower for w in ["how many", "how much", "count of", "number of"])
    is_list = any(w in query_lower for w in ["list", "show", "find all", "what are"])
    is_current_version = any(w in query_lower for w in ["current version", "what is the current", "latest version"])

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

    # Rebuild filter using inferred values when query text contains agency/type hints
    if inferred_agency != filters.agency or inferred_doc_type != filters.document_type:
        inferred_filters = QueryFilters(
            agency=inferred_agency,
            document_type=inferred_doc_type,
            date_from=filters.date_from,
            date_to=filters.date_to,
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
                # document_registry stores underscored doc_type; map hyphenated → underscored
                doc_type_map = {
                    "guidance": "guidance_pdf",
                    "press-release": "press_release",
                    "reflection-paper": "reflection_paper",
                }
                pg_doc_type = doc_type_map.get(inferred_filters.document_type, inferred_filters.document_type.replace("-", "_"))
                where_clauses.append("doc_type = %s")
                params.append(pg_doc_type)
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

        answer = f"There are {total}{type_str}documents {agency_str} in the indexed corpus."

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
            where = ""
            params = []
            if filters.agency:
                params.append(filters.agency)
                where = f"WHERE issuing_body = %s"
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
        # Scroll through Qdrant to list matching documents
        scroll_result = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=qdrant_filter,
            limit=20,
            with_payload=True,
        )
        points, _ = scroll_result
        seen_docs = {}
        for point in points:
            payload = point.payload or {}
            doc_id = payload.get("document_id", "")
            if doc_id and doc_id not in seen_docs:
                seen_docs[doc_id] = payload

        items = []
        for i, (doc_id, payload) in enumerate(seen_docs.items(), 1):
            title = strip_title_suffix(payload.get("document_title", "Unknown"))
            agency = normalise_agency(payload.get("issuing_body", "Unknown"))
            version = payload.get("document_version", "")
            pub_date = payload.get("publication_date", "")
            doc_type = payload.get("document_type", "")

            items.append(f"{i}. {title} — {agency}{', ' + version if version else ''}{' (' + pub_date + ')' if pub_date else ''}")

            citations.append({
                "index": i,
                "chunk_id": str(point.id),
                "document_id": doc_id,
                "chunk_text": "",
                "document_title": title or "Untitled",
                "issuing_body": agency,
                "document_version": version,
                "clause_id": payload.get("clause_id"),
                "publication_date": pub_date,
                "page_no": payload.get("page_no"),
                "chunk_index": payload.get("chunk_index"),
                "char_offset_start": payload.get("char_offset_start"),
                "char_offset_end": payload.get("char_offset_end"),
                "chunked_at": payload.get("chunked_at"),
                "score": 1.0,
                "cited_by_llm": True,
                "superseded": False,
                "superseded_by": None,
                "source_local_path": payload.get("source_local_path"),
                "source_url": payload.get("source_url", ""),
            })

        if items:
            answer = "Documents matching your query:\n\n" + "\n".join(items)
        else:
            answer = "No documents found matching your criteria."
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
async def query_history(limit: int = 10, offset: int = 0):
    """Return paginated query history from PostgreSQL."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT query_id, query_text, timestamp, routing_path,
                      citations, filters_applied
               FROM query_history
               ORDER BY timestamp DESC
               LIMIT %s OFFSET %s""",
            (limit, offset)
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
        return items
    finally:
        conn.close()


# ── GET /api/query/history/export ─────────────────────────────────────────────


@app.get("/api/query/history/export")
async def export_history():
    import csv
    from io import StringIO

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT query_id, query_text, routing_path, timestamp,
                      answer, citations, sub_queries,
                      filters_applied, retrieval_params,
                      langfuse_trace_id, model_used
               FROM query_history
               ORDER BY timestamp DESC
               LIMIT 1000"""
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "query_id",
        "timestamp",
        "query_text",
        "answer_excerpt",
        "routing",
        "model_used",
        "agency_filter",
        "document_type_filter",
        "date_from",
        "date_to",
        "query_depth",
        "top_k",
        "score_threshold",
        "sub_queries",
        "citation_count",
        "cited_document_ids",
        "cited_document_titles",
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

        # Truncate answer to 300 chars for CSV readability; full answer retrievable via query_id
        answer_text = answer or ""
        answer_excerpt = (answer_text[:300] + "… [full answer: load query_id in regpulse]") if len(answer_text) > 300 else answer_text

        writer.writerow([
            qid,
            ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            qtext,
            answer_excerpt,
            routing_label,
            model_used or "",
            filters.get("agency") or "All",
            filters.get("document_type") or "All",
            filters.get("date_from") or "",
            filters.get("date_to") or "",
            retrieval.get("query_depth") or "",
            retrieval.get("top_k") or "",
            retrieval.get("score_threshold") or "",
            " | ".join(sub_queries),
            len(citations),
            cited_ids,
            cited_titles,
            trace_id or "",
        ])

    filename = f"regpulse-audit-export-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "regpulse_version": "0.7.0",
            }
            return JSONResponse(
                content=export,
                headers={"Content-Disposition": f'attachment; filename="regpulse-export-{query_id}.json"'},
            )

        elif format == "pdf":
            from io import BytesIO
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
            )
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_LEFT

            buf = BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=A4,
                                    leftMargin=20*mm, rightMargin=20*mm,
                                    topMargin=20*mm, bottomMargin=20*mm)
            styles = getSampleStyleSheet()
            story = []

            # Title
            story.append(Paragraph("regpulse — Query Export", styles['Title']))
            story.append(Spacer(1, 6*mm))

            # Query details
            detail_style = ParagraphStyle('Detail', parent=styles['Normal'], fontSize=9, fontName='Courier')
            story.append(Paragraph(f"Query ID: {query_id}", detail_style))
            story.append(Paragraph(f"Timestamp: {ts_iso}", detail_style))
            story.append(Paragraph(f"Routing: {routing_label}", detail_style))
            story.append(Paragraph(f"Export date: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')}", detail_style))
            story.append(Spacer(1, 4*mm))

            # Query text
            story.append(Paragraph("<b>Query</b>", styles['Heading2']))
            story.append(Paragraph(query_text, styles['Normal']))
            story.append(Spacer(1, 4*mm))

            # Answer
            story.append(Paragraph("<b>Answer</b>", styles['Heading2']))
            for para in (answer or '').split('\n\n'):
                if para.strip():
                    story.append(Paragraph(para.strip().replace('\n', '<br/>'), styles['Normal']))
                    story.append(Spacer(1, 2*mm))
            story.append(Spacer(1, 4*mm))

            # Filter/retrieval info
            story.append(Paragraph("<b>Retrieval Parameters</b>", styles['Heading2']))
            story.append(Paragraph(f"Filters: {json.dumps(filters_dict)}", detail_style))
            story.append(Paragraph(f"Params: {json.dumps(retrieval_dict)}", detail_style))
            if sub_queries_list:
                story.append(Paragraph(f"Sub-queries: {', '.join(sub_queries_list)}", detail_style))
            story.append(Spacer(1, 4*mm))

            # Citations — cited
            cited = [c for c in citations_list if c.get("cited_by_llm")]
            if cited:
                story.append(Paragraph(f"<b>Cited Sources ({len(cited)})</b>", styles['Heading2']))
                for c in cited:
                    title = c.get('document_title', 'Unknown')
                    story.append(Paragraph(f"[{c.get('index', '?')}] {title}", styles['Normal']))
                    story.append(Paragraph(
                        f"Agency: {c.get('issuing_body', '—')} · "
                        f"Version: {c.get('document_version', '—')} · "
                        f"Clause: {c.get('clause_id') or 'Not available'} · "
                        f"Score: {c.get('score', 0):.2f} · "
                        f"Published: {c.get('publication_date') or 'Not available'}",
                        detail_style
                    ))
                    if c.get('chunk_text'):
                        story.append(Paragraph(c['chunk_text'][:300] + ('...' if len(c['chunk_text']) > 300 else ''), detail_style))
                    story.append(Spacer(1, 3*mm))

            # Citations — uncited
            uncited = [c for c in citations_list if not c.get("cited_by_llm")]
            if uncited:
                story.append(Paragraph(f"<b>Retrieved but Not Cited ({len(uncited)})</b>", styles['Heading2']))
                for c in uncited:
                    title = c.get('document_title', 'Unknown')
                    story.append(Paragraph(f"[{c.get('index', '?')}] {title} (score: {c.get('score', 0):.2f})", detail_style))
                    story.append(Spacer(1, 1*mm))

            # Trace ID
            if langfuse_trace_id:
                story.append(Spacer(1, 4*mm))
                story.append(Paragraph(f"Langfuse Trace ID: {langfuse_trace_id}", detail_style))

            doc.build(story)
            buf.seek(0)

            filename = f"regpulse-export-{query_id[:8]}.pdf"
            return Response(
                content=buf.getvalue(),
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
        pix = page.get_pixmap(dpi=150)
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
