import os
import uuid
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import psycopg2
import psycopg2.extras
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range, PointStruct
from qdrant_client.http.models import ScrollRequest

app = FastAPI(title="regpulse", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
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
OLLAMA_MODEL = "phi4:14b-q8_0"
EMBED_MODEL = "mxbai-embed-large"

# --- Clients ---
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def get_pg_conn():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
    )


def init_db():
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                query_id        UUID PRIMARY KEY,
                query_text      TEXT NOT NULL,
                routing_path    VARCHAR(20),
                answer          TEXT,
                citations       JSONB,
                filters_applied JSONB,
                timestamp       TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


init_db()

# --- Models ---
class QueryFilters(BaseModel):
    agency: Optional[str] = None
    doc_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class QueryRequest(BaseModel):
    query: str
    filters: Optional[QueryFilters] = None


class CitationModel(BaseModel):
    index: int
    chunk_id: str
    chunk_text: str
    title: str
    agency: str
    document_version: Optional[str] = None
    clause_id: Optional[str] = None
    publication_date: Optional[str] = None
    score: float
    superseded: bool = False
    superseded_by: Optional[str] = None
    local_file_path: Optional[str] = None
    source_url: Optional[str] = None
    page_number: Optional[int] = None


class QueryResponse(BaseModel):
    query_id: str
    timestamp: str
    routing_path: str
    answer: str
    citations: list[CitationModel]


# --- Ollama System Prompt ---
SYSTEM_PROMPT = """You are a regulatory intelligence assistant for the pharmaceutical and life sciences industry. You answer questions based exclusively on the provided regulatory source documents (FDA, EMA, ICH guidance).

Rules:
- Answer only from the provided context chunks. Do not use prior knowledge.
- Cite EVERY factual claim with a numeric citation marker like [1], [2], [3] exactly matching the chunk numbers provided. Never use descriptive citation markers — always use the numeric index shown in the context.
- If the context does not contain enough information, say so explicitly.
- Use precise regulatory language. Do not simplify or paraphrase regulatory requirements.
- If a cited document is marked as superseded, note this clearly in your answer.
- Do not give legal advice. State that queries requiring legal interpretation should be referred to a qualified regulatory professional.
- Format your answer for readability: use paragraphs separated by blank lines, and use numbered lists (1., 2., 3.) for enumerated requirements."""


# --- Routing ---
def is_metadata_query(text: str) -> bool:
    lower = text.lower().strip()
    metadata_patterns = [
        "how many", "count of", "number of", "list all", "list the",
        "when was", "what is the date", "what are the dates",
        "show me all", "give me a list", "enumerate",
    ]
    return any(lower.startswith(p) or p in lower for p in metadata_patterns)


# --- Helpers ---
def get_title(payload: dict) -> str:
    """Extract best available title from a Qdrant payload."""
    title = payload.get("document_title") or payload.get("title")
    if title:
        return title
    # Fallback: use section_path
    sp = payload.get("section_path")
    if sp and isinstance(sp, list) and len(sp) > 0:
        return sp[0]
    if sp and isinstance(sp, str):
        return sp
    # Last resort: format document_id
    doc_id = payload.get("document_id") or payload.get("doc_id") or ""
    return doc_id.replace("-", " ").replace("_", " ")


def parse_implicit_filters(query_text: str, existing: Optional[QueryFilters]) -> QueryFilters:
    """Extract agency and doc_type from natural language query text."""
    lower = query_text.lower()
    agency = existing.agency if existing else None
    doc_type = existing.doc_type if existing else None
    date_from = existing.date_from if existing else None
    date_to = existing.date_to if existing else None

    if not agency:
        if "fda" in lower:
            agency = "FDA"
        elif "ema" in lower:
            agency = "EMA"
        elif "ich" in lower:
            agency = "ICH"

    if not doc_type:
        if "press release" in lower or "press-release" in lower or "press_release" in lower:
            doc_type = "press_release"
        elif "guideline" in lower:
            doc_type = "guideline"

    # Extract keywords for content filtering (remove filter words)
    keywords = []
    stop_words = {"list", "all", "the", "how", "many", "what", "is", "are", "when", "was",
                  "show", "me", "give", "enumerate", "of", "in", "for", "to", "a", "and",
                  "fda", "ema", "ich", "press", "release", "releases", "guideline", "guidelines",
                  "related", "data", "published", "last", "days", "count", "number"}
    words = lower.replace(",", " ").replace(".", " ").replace("?", " ").split()
    for w in words:
        if w not in stop_words and len(w) > 2:
            keywords.append(w)

    return QueryFilters(agency=agency, doc_type=doc_type, date_from=date_from, date_to=date_to), keywords


def build_qdrant_filter(filters: Optional[QueryFilters]) -> Optional[Filter]:
    if not filters:
        return None
    must = []
    if filters.agency:
        must.append(FieldCondition(key="issuing_body", match=MatchValue(value=filters.agency)))
    if filters.doc_type:
        must.append(FieldCondition(key="doc_type", match=MatchValue(value=filters.doc_type)))
    if filters.date_from or filters.date_to:
        range_kwargs = {}
        if filters.date_from:
            range_kwargs["gte"] = filters.date_from
        if filters.date_to:
            range_kwargs["lte"] = filters.date_to
        must.append(FieldCondition(key="publication_date", range=Range(**range_kwargs)))
    return Filter(must=must) if must else None


def check_superseded(doc_family_id: Optional[str], doc_id: str) -> tuple[bool, Optional[str]]:
    if not doc_family_id:
        return False, None
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT title, publication_date FROM document_registry WHERE document_family_id = %s AND doc_id != %s ORDER BY publication_date DESC LIMIT 1",
            (doc_family_id, doc_id),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return True, row.get("title")
    except Exception:
        pass
    return False, None


def generate_embedding(text: str) -> list[float]:
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            if resp.status_code == 200:
                return resp.json().get("embedding", [])
    except Exception:
        pass
    return []


def format_answer_html(text: str) -> str:
    """Convert plain-text answer into basic HTML for display."""
    import re

    lines = text.split("\n")
    # Group consecutive non-blank lines into blocks
    blocks = []
    cur = []
    for line in lines:
        if line.strip():
            cur.append(line)
        else:
            if cur:
                blocks.append(cur)
                cur = []
    if cur:
        blocks.append(cur)

    out = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        # Check if this block and consecutive blocks form a numbered list
        if re.match(r"^\d+[.)]\s+", block[0]):
            ol_items = []
            while i < len(blocks) and re.match(r"^\d+[.)]\s+", blocks[i][0]):
                ol_items.append(blocks[i])
                i += 1
            out.append('<ol class="list-decimal ml-5 mb-3 space-y-1">')
            for item_block in ol_items:
                content = " ".join(item_block)
                content = re.sub(r"^\d+[.)]\s+", "", content)
                content = format_inline(content)
                out.append(f"<li>{content}</li>")
            out.append("</ol>")
            continue

        # Paragraph block
        para = " ".join(block)
        para = format_inline(para)
        out.append(f"<p>{para}</p>")
        i += 1

    return "\n".join(out)


def format_inline(text: str) -> str:
    """Apply inline formatting: bold, citation markers."""
    import re
    # **bold** → <strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # [N] → clickable citation marker
    text = re.sub(r"\[(\d+)\]", r'<cite class="citation-marker" data-cite="\1">[\1]</cite>', text)
    return text


def generate_rag_answer(query: str, chunks: list[dict]) -> str:
    context = "\n\n".join(
        f"[{i+1}] {get_title(c)} "
        f"({c.get('issuing_body','')}, {c.get('publication_date','')}) "
        f"Clause {c.get('clause_id','N/A')}\n{c.get('chunk_text','')}"
        for i, c in enumerate(chunks)
    )
    prompt = f"Context:\n\n{context}\n\nQuestion: {query}\n\nAnswer:"

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "system": SYSTEM_PROMPT,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
            return f"Error: Ollama returned status {resp.status_code}"
    except Exception as e:
        return f"Error generating answer: {str(e)}"


# --- Routes ---
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    query_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    routing_path = "METADATA" if is_metadata_query(req.query) else "CONTENT"
    citations = []
    answer = ""

    qf = build_qdrant_filter(req.filters)

    if routing_path == "CONTENT":
        try:
            embedding = generate_embedding(req.query)
            if not embedding:
                answer = "Error: Could not generate query embedding."
            else:
                results = qdrant.query_points(
                    collection_name=QDRANT_COLLECTION,
                    query=embedding,
                    query_filter=qf,
                    limit=30,
                    with_payload=True,
                )
                # Keep best chunk per document for diversity
                best_per_doc = {}
                for r in results.points:
                    p = r.payload
                    if p is None:
                        continue
                    doc_id = p.get("document_id", "") or p.get("doc_id", "")
                    if not doc_id:
                        continue
                    score = float(r.score)
                    if doc_id not in best_per_doc or score > best_per_doc[doc_id]["score"]:
                        best_per_doc[doc_id] = {"point_id": str(r.id), "score": score, "payload": p}
                # Sort by score and take top 8 unique documents
                sorted_entries = sorted(best_per_doc.values(), key=lambda e: e["score"], reverse=True)[:8]
                chunk_entries = list(sorted_entries)

                chunks_for_context = [e["payload"] for e in chunk_entries]
                answer = format_answer_html(generate_rag_answer(req.query, chunks_for_context))

                for i, entry in enumerate(chunk_entries):
                    p = entry["payload"]
                    doc_family_id = p.get("document_family_id")
                    doc_id = p.get("document_id", "") or p.get("doc_id", "")
                    superseded, superseded_by = check_superseded(doc_family_id, doc_id)
                    page_number = p.get("page_no")
                    citations.append(CitationModel(
                        index=i + 1,
                        chunk_id=entry["point_id"],
                        chunk_text=p.get("chunk_text", ""),
                        title=get_title(p),
                        agency=p.get("issuing_body", ""),
                        document_version=p.get("document_version"),
                        clause_id=p.get("clause_id"),
                        publication_date=p.get("publication_date"),
                        score=entry["score"],
                        superseded=superseded,
                        superseded_by=superseded_by,
                        local_file_path=p.get("source_local_path") or p.get("local_file_path"),
                        source_url=p.get("source_url"),
                        page_number=page_number,
                    ))
        except Exception as e:
            answer = f"Error retrieving from knowledge base: {str(e)}"

    else:  # METADATA path
        try:
            implicit_filters, keywords = parse_implicit_filters(req.query, req.filters)
            mf = build_qdrant_filter(implicit_filters)

            all_points = []
            offset = None
            while True:
                scroll_resp = qdrant.scroll(
                    collection_name=QDRANT_COLLECTION,
                    scroll_filter=mf,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                )
                points, offset = scroll_resp[0], scroll_resp[1]
                all_points.extend(points)
                if offset is None or len(all_points) >= 500:
                    break

            # Filter by keywords in chunk_text if keywords extracted
            docs = {}
            for pt in all_points:
                p = pt.payload
                if p is None:
                    continue
                doc_id = p.get("document_id", "") or p.get("doc_id", "")
                if not doc_id:
                    continue
                if doc_id not in docs:
                    chunk_text = p.get("chunk_text", "").lower()
                    if keywords:
                        if not any(kw in chunk_text for kw in keywords):
                            continue
                    docs[doc_id] = {"point_id": str(pt.id), "payload": p}

            answer_parts = []
            summary_parts = []
            if implicit_filters.agency:
                summary_parts.append(implicit_filters.agency)
            if implicit_filters.doc_type:
                dt_label = "Press Releases" if "press_release" in implicit_filters.doc_type else implicit_filters.doc_type.replace("_", " ").title() + "s"
                summary_parts.append(dt_label)
            summary_prefix = " ".join(summary_parts) if summary_parts else "Documents"

            answer_parts.append(f'<p class="text-sm text-secondary mb-3">Found {len(docs)} {summary_prefix.lower()}{" matching your query" if keywords else ""}.</p>')

            if not docs:
                answer_parts.append('<p class="text-sm text-slate-500">No matching documents found.</p>')
            else:
                answer_parts.append('<ol class="space-y-2 ml-0 pl-0 list-none">')
                for i, (doc_id, entry) in enumerate(docs.items(), 1):
                    p = entry["payload"]
                    title = get_title(p)
                    agency = p.get("issuing_body", "")
                    pub_date = p.get("publication_date", "")
                    doc_type = p.get("doc_type", "")
                    source_url = p.get("source_url", "")
                    document_version = p.get("document_version", "")
                    version_str = f" v{document_version}" if document_version else ""
                    date_str = f" ({pub_date})" if pub_date else ""

                    if source_url:
                        title_html = f'<a href="{source_url}" target="_blank" rel="noopener noreferrer" class="text-accent-light hover:underline font-medium">[{i}] {title}</a>'
                    else:
                        title_html = f'<span class="font-medium">[{i}] {title}</span>'

                    meta = f"{agency}{version_str} · {doc_type.replace('_', ' ').title()}{date_str}"
                    answer_parts.append(
                        f'<li class="mb-2 pb-2 border-b border-slate-100 last:border-0">'
                        f'{title_html}<br>'
                        f'<span class="text-xs text-secondary">{meta}</span>'
                        f'</li>'
                    )

                    doc_family_id = p.get("document_family_id")
                    superseded, superseded_by = check_superseded(doc_family_id, doc_id)
                    page_number = p.get("page_no")
                    citations.append(CitationModel(
                        index=i,
                        chunk_id=entry["point_id"],
                        chunk_text=p.get("chunk_text", ""),
                        title=title,
                        agency=agency,
                        document_version=p.get("document_version"),
                        clause_id=p.get("clause_id"),
                        publication_date=pub_date,
                        score=0.0,
                        superseded=superseded,
                        superseded_by=superseded_by,
                        local_file_path=p.get("source_local_path") or p.get("local_file_path"),
                        source_url=source_url,
                        page_number=page_number,
                    ))

                answer_parts.append('</ol>')

            answer = "\n".join(answer_parts)
        except Exception as e:
            answer = f"Error during metadata query: {str(e)}"

    # Persist to query_history
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO query_history (query_id, query_text, routing_path, answer, citations, filters_applied) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                query_id,
                req.query,
                routing_path,
                answer,
                json.dumps([c.model_dump() for c in citations]),
                json.dumps(req.filters.model_dump() if req.filters else None),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass

    return QueryResponse(
        query_id=query_id,
        timestamp=timestamp,
        routing_path=routing_path,
        answer=answer,
        citations=citations,
    )


@app.get("/api/query/history")
def query_history():
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT query_id, query_text, timestamp, routing_path, jsonb_array_length(citations) as citation_count "
            "FROM query_history ORDER BY timestamp DESC LIMIT 50"
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for row in rows:
            if row.get("timestamp"):
                row["timestamp"] = row["timestamp"].isoformat()
        return rows
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/api/query/{query_id}/export")
def query_export(query_id: str):
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT query_id, query_text, timestamp, routing_path, answer, citations, filters_applied "
            "FROM query_history WHERE query_id = %s", (query_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Query not found")
        result = dict(row)
        if result.get("timestamp"):
            result["timestamp"] = result["timestamp"].isoformat()
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/api/pdf/page")
def pdf_page(file_path: str = Query(...), page_number: int = Query(...)):
    import fitz

    # Map host path /mnt/data/regulatory_archive → container path /archive
    file_path = file_path.replace("/mnt/data/regulatory_archive", "/archive", 1)
    full_path = file_path
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="PDF file not available")

    try:
        doc = fitz.open(full_path)
        if page_number < 0 or page_number >= len(doc):
            doc.close()
            raise HTTPException(status_code=400, detail="Page number out of range")
        page = doc[page_number]
        pix = page.get_pixmap(dpi=150)
        doc.close()
        from fastapi.responses import Response
        return Response(content=pix.tobytes("png"), media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF rendering error: {str(e)}")


@app.get("/api/corpus/stats")
def corpus_stats():
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COUNT(*) as total FROM document_registry")
        total = cur.fetchone()["total"]

        cur.execute("SELECT issuing_body, COUNT(*) as count FROM document_registry GROUP BY issuing_body")
        per_agency = {r["issuing_body"]: r["count"] for r in cur.fetchall()}

        cur.execute("SELECT MAX(last_indexed_at) as last_run FROM document_registry")
        last_run_row = cur.fetchone()
        last_run = last_run_row["last_run"].isoformat() if last_run_row and last_run_row["last_run"] else None

        cur.close()
        conn.close()
        return {"total_documents": total, "per_agency": per_agency, "last_pipeline_run": last_run}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
