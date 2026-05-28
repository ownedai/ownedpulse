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
    query text analysis.
    """
    query_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    filters = request.filters or QueryFilters()
    retrieval = request.retrieval_params or RetrievalParams()

    # Determine routing
    if is_metadata_query(request.query):
        return await _run_metadata_query(query_id, timestamp, request, filters, retrieval)

    return await _run_content_query(query_id, timestamp, request, filters, retrieval)


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
    """Execute a METADATA-path query. Returns structured results from Qdrant scroll."""
    # Will be fully implemented in step 5
    return {
        "query_id": query_id,
        "timestamp": timestamp,
        "routing_path": "METADATA",
        "sub_queries": [],
        "answer": "Metadata query processing is being implemented.",
        "citations": [],
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
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ── GET /api/query/{query_id}/export ──────────────────────────────────────────


@app.get("/api/query/{query_id}/export")
async def export_query(query_id: str, format: str = "json"):
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ── GET /api/query/history/export ─────────────────────────────────────────────


@app.get("/api/query/history/export")
async def export_history(format: str = "json"):
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ── GET /api/trace/{trace_id} ─────────────────────────────────────────────────


@app.get("/api/trace/{trace_id}")
async def get_trace(trace_id: str):
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ── GET /api/pdf/page ─────────────────────────────────────────────────────────


@app.get("/api/pdf/page")
async def pdf_page(file_path: str, page_no: int = 0):
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ── GET /api/corpus/stats ─────────────────────────────────────────────────────


@app.get("/api/corpus/stats")
async def corpus_stats():
    raise HTTPException(status_code=501, detail="Not implemented yet")


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
