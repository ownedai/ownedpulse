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
from fastapi.responses import Response
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
):
    """Persist a query result to query_history. Raises on failure."""
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO query_history
               (query_id, query_text, routing_path, answer, citations,
                sub_queries, filters_applied, retrieval_params, langfuse_trace_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                query_id, query_text, routing_path, answer,
                json.dumps(citations), json.dumps(sub_queries),
                json.dumps(filters_applied), json.dumps(retrieval_params),
                langfuse_trace_id,
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

@app.on_event("startup")
async def startup():
    init_db()

# ── System prompt V6 ──────────────────────────────────────────────────────────

SYSTEM_PROMPT_V6 = (
    "You are a regulatory intelligence assistant for the pharmaceutical and "
    "life sciences industry. You answer questions based exclusively on the "
    "provided regulatory source documents (FDA, EMA, ICH guidance).\n\n"
    "Rules:\n"
    "- Answer only from the provided context chunks. Do not use prior knowledge.\n"
    "- Cite EVERY factual claim with a numeric citation marker [N] corresponding "
    "to the source chunks.\n"
    "- Never use descriptive citation markers like \"(see source)\" — only [N].\n"
    "- If the context does not contain enough information, say so explicitly.\n"
    "- Use precise regulatory language. Do not simplify or paraphrase requirements.\n"
    "- If a cited document is marked as superseded, note this in your answer.\n"
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
    query_depth: str = "standard"
    top_k: int = 10
    score_threshold: float = 0.60


class QueryRequest(BaseModel):
    query: str
    filters: QueryFilters | None = None
    retrieval_params: RetrievalParams | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

TITLE_SUFFIX_PATTERNS = [
    re.compile(r'\s*\|\s*European\s+Medicines\s+Agency\s*$', re.IGNORECASE),
    re.compile(r'\s*\|\s*EMA\s*$', re.IGNORECASE),
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


async def ollama_generate(prompt: str, system: str = "", model: str = None) -> str:
    """Call Ollama generate API and return the response text."""
    if model is None:
        model = OLLAMA_GEN_MODEL
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
            },
        )
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
    response = await ollama_generate(prompt)
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
    if not filters:
        return None

    conditions = []

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

    if not conditions:
        return None

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
    depth_map = {"low": 2, "standard": 3, "deep": 5}
    n_sub_queries = depth_map.get(retrieval.query_depth, 3)

    # Step 1: Query expansion
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

    # Step 5: Build context and generate answer
    if not deduped_chunks:
        return {
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
            "langfuse_trace_id": "",
        }

    context = build_context(deduped_chunks)
    prompt = f"Context:\n\n{context}\n\nQuestion: {request.query}\n\nAnswer:"
    answer = await ollama_generate(prompt, system=SYSTEM_PROMPT_V6)

    # Step 6: Determine which chunks were cited
    cited_indices = parse_citations(answer, len(deduped_chunks))

    # Step 7: Build citations array — cited first (by score), then uncited (by score)
    cited_chunks = []
    uncited_chunks = []
    for i, chunk in enumerate(deduped_chunks, 1):
        citation = build_citation(chunk, i, i in cited_indices)
        if i in cited_indices:
            cited_chunks.append(citation)
        else:
            uncited_chunks.append(citation)

    return {
        "query_id": query_id,
        "timestamp": timestamp,
        "routing_path": "CONTENT",
        "sub_queries": sub_queries,
        "answer": answer.strip(),
        "citations": cited_chunks + uncited_chunks,
        "retrieval_params_applied": {
            "query_depth": retrieval.query_depth,
            "top_k": retrieval.top_k,
            "score_threshold": retrieval.score_threshold,
            "sub_query_count": n_sub_queries,
        },
        "langfuse_trace_id": "",
    }


async def _run_metadata_query(
    query_id: str,
    timestamp: str,
    request: QueryRequest,
    filters: QueryFilters,
    retrieval: RetrievalParams,
) -> dict:
    """Execute a METADATA-path query using Qdrant scroll/count and PostgreSQL."""
    query_lower = request.query.lower()
    qdrant_filter = build_qdrant_filter(filters)

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Determine what kind of metadata query this is
    is_count = any(w in query_lower for w in ["how many", "how much", "count of", "number of"])
    is_list = any(w in query_lower for w in ["list", "show", "find all", "what are"])
    is_current_version = any(w in query_lower for w in ["current version", "what is the current", "latest version"])

    citations = []
    answer = ""

    if is_count:
        # Count document chunks matching filter in Qdrant
        count_result = client.count(
            collection_name=QDRANT_COLLECTION,
            count_filter=qdrant_filter,
            exact=True,
        )
        total = count_result.count if count_result else 0

        agency_str = f"from {filters.agency}" if filters.agency else "across all agencies"
        type_str = f" of type {filters.document_type}" if filters.document_type else ""

        answer = f"There are {total} document chunks{type_str} {agency_str} in the indexed corpus."

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
                    "document_title": title_clean,
                    "issuing_body": agency_norm,
                    "document_version": version,
                    "clause_id": None,
                    "publication_date": pub_date,
                    "page_no": None,
                    "chunk_index": None,
                    "char_offset_start": None,
                    "char_offset_end": None,
                    "chunked_at": None,
                    "score": 0.0,
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
                "document_title": title,
                "issuing_body": agency,
                "document_version": version,
                "clause_id": payload.get("clause_id"),
                "publication_date": pub_date,
                "page_no": payload.get("page_no"),
                "chunk_index": payload.get("chunk_index"),
                "char_offset_start": payload.get("char_offset_start"),
                "char_offset_end": payload.get("char_offset_end"),
                "chunked_at": payload.get("chunked_at"),
                "score": 0.0,
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
        agency_str = f"from {filters.agency}" if filters.agency else "across all agencies"
        answer = f"Found {total} document chunks {agency_str} in the indexed corpus."

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
        "langfuse_trace_id": "",
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
async def export_history(format: str = "json"):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT query_id, query_text, routing_path, timestamp, citations, "
            "filters_applied FROM query_history ORDER BY timestamp DESC LIMIT 1000"
        )
        rows = cur.fetchall()
        cur.close()

        if format == "json":
            results = []
            for row in rows:
                qid, qtext, routing, ts, citations, filters_applied = row
                citations_list = json.loads(citations) if isinstance(citations, str) else (citations or [])
                results.append({
                    "query_id": qid,
                    "query_text": qtext,
                    "routing_path": routing,
                    "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    "citation_count": len(citations_list),
                    "filters_applied": json.loads(filters_applied) if isinstance(filters_applied, str) else (filters_applied or {}),
                })
            return results

        elif format == "csv":
            import csv
            from io import StringIO

            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(["query_id", "query_text", "routing_path", "timestamp", "citation_count", "agency_filter"])
            for row in rows:
                qid, qtext, routing, ts, citations, filters_applied = row
                citations_list = json.loads(citations) if isinstance(citations, str) else (citations or [])
                filters_dict = json.loads(filters_applied) if isinstance(filters_applied, str) else (filters_applied or {})
                agency = filters_dict.get("agency") or "All"
                writer.writerow([
                    qid, qtext, routing,
                    ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
                    len(citations_list), agency,
                ])

            filename = f"regpulse-history-export-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
            return Response(
                content=buf.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

        else:
            raise HTTPException(status_code=400, detail="Format must be json or csv")

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
        ts_iso = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)

        if format == "json":
            export = {
                "export_timestamp": datetime.now(timezone.utc).isoformat(),
                "regpulse_version": "0.7.0",
                "query": {
                    "query_id": query_id,
                    "query_text": query_text,
                    "timestamp": ts_iso,
                    "routing_path": routing_label,
                    "retrieval_params_applied": retrieval_dict,
                    "sub_queries": sub_queries_list,
                    "filters_applied": filters_dict,
                },
                "answer": answer,
                "citations": {
                    "cited": [c for c in citations_list if c.get("cited_by_llm")],
                    "retrieved_but_not_cited": [c for c in citations_list if not c.get("cited_by_llm")],
                },
                "langfuse_trace_id": langfuse_trace_id,
            }
            return export

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
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Trace fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to fetch trace from Langfuse")


# ── GET /api/pdf/page ─────────────────────────────────────────────────────────


@app.get("/api/pdf/page")
async def pdf_page(file_path: str, page_no: int = 0):
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


# ── GET /api/corpus/stats ─────────────────────────────────────────────────────


@app.get("/api/corpus/stats")
async def corpus_stats():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM document_registry")
        total = cur.fetchone()[0]

        cur.execute("SELECT issuing_body, count(*) FROM document_registry GROUP BY issuing_body")
        raw_agency = dict(cur.fetchall())

        # Normalise EU-Commission → EMA
        per_agency = {}
        for agency, count in raw_agency.items():
            key = normalise_agency(agency)
            per_agency[key] = per_agency.get(key, 0) + count

        cur.execute(
            "SELECT metadata_json->>'document_type', count(*) FROM document_registry GROUP BY metadata_json->>'document_type'"
        )
        per_doc_type = dict(cur.fetchall())

        cur.execute("SELECT max(last_indexed_at) FROM document_registry")
        last_run = cur.fetchone()[0]
        last_run_iso = last_run.isoformat() if last_run else None

        cur.close()
        return {
            "total_documents": total,
            "per_agency": per_agency,
            "per_document_type": per_doc_type,
            "last_pipeline_run": last_run_iso,
        }
    finally:
        conn.close()


# ── GET /api/corpus/documents ─────────────────────────────────────────────────


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
