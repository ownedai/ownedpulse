# API Contracts

## POST /api/query

Request:
```json
{
  "query": "string",
  "filters": {
    "agency": "FDA|EMA|ICH|null",
    "document_type": "guidance|press-release|reflection-paper|null",
    "date_from": "ISO date|null",
    "date_to": "ISO date|null"
  },
  "retrieval_params": {
    "query_depth": "low|standard|deep",
    "top_k": 10,
    "score_threshold": 0.60
  }
}
```

Retrieval parameters:
- `query_depth`: `low` (N=2 sub-queries), `standard` (N=3, default), `deep` (N=5)
- `top_k`: per sub-query, range 5–20, default 10
- `score_threshold`: minimum score, range 0.40–0.90, default 0.60

### Routing

- METADATA path: `is_metadata_query()` detects "how many", "count of", "list all", "when was". Returns structured list from Qdrant scroll, no LLM generation.
- CONTENT path: semantic RAG with query expansion.

### CONTENT path pipeline

1. Generate N sub-queries from user query via Ollama (query expansion)
2. For each sub-query: embed → `query_points()` → retrieve `top_k` chunks
3. Combine all results, deduplicate to best chunk per `document_id`, take top 8 by score
4. Apply `score_threshold` — drop any chunk below threshold
5. If all chunks dropped: return empty citations + "No sources above the relevance threshold were found for this query."
6. Send remaining chunks to Ollama with V6 system prompt
7. Return plain-text answer with `[N]` markers + citation array

### System prompt V6

```
You are a regulatory intelligence assistant for the pharmaceutical and
life sciences industry. You answer questions based exclusively on the
provided regulatory source documents (FDA, EMA, ICH guidance).

Rules:
- Answer only from the provided context chunks. Do not use prior knowledge.
- Cite EVERY factual claim with a numeric citation marker [N] corresponding
  to the source chunks.
- Never use descriptive citation markers like "(see source)" — only [N].
- If the context does not contain enough information, say so explicitly.
- Use precise regulatory language. Do not simplify or paraphrase requirements.
- If a cited document is marked as superseded, note this in your answer.
- Format your answer as clean prose paragraphs separated by blank lines.
- Do NOT use markdown bold headings. Do NOT use numbered lists unless the
  user explicitly asked for a list.
- Do not give legal advice. State that queries requiring legal interpretation
  should be referred to a qualified regulatory professional.
```

### Response

```json
{
  "query_id": "uuid",
  "timestamp": "ISO datetime",
  "routing_path": "CONTENT|METADATA",
  "sub_queries": ["string", ...],
  "answer": "string (plain text with [N] markers)",
  "citations": [
    {
      "index": 1,
      "chunk_id": "uuid",
      "document_id": "string",
      "chunk_text": "string",
      "document_title": "string (suffix stripped)",
      "issuing_body": "FDA|EMA|ICH",
      "document_version": "string",
      "clause_id": "string|null",
      "publication_date": "string|null",
      "page_no": "int|null",
      "chunk_index": "int",
      "char_offset_start": "int",
      "char_offset_end": "int",
      "chunked_at": "string",
      "score": 0.94,
      "cited_by_llm": true,
      "superseded": false,
      "superseded_by": null,
      "source_local_path": "string|null",
      "source_url": "string"
    }
  ],
  "retrieval_params_applied": {
    "query_depth": "standard",
    "top_k": 10,
    "score_threshold": 0.60,
    "sub_query_count": 3
  },
  "langfuse_trace_id": "string"
}
```

Critical: `answer` is PLAIN TEXT with `[N]` markers — do NOT pre-render to HTML on server.

---

## GET /api/query/history

Returns last 10 queries for sidebar (paginated with `?limit=10&offset=0`).

Fields per item: `query_id`, `query_text`, `timestamp`, `routing_path`, `citation_count`, `filters_applied`, `agency_filter`.

---

## GET /api/query/{query_id}/export?format=json|pdf

Export content: query text + id + timestamp, routing path (human-readable), retrieval params, sub-queries, filters, answer, cited citations (full provenance), uncited retrieved chunks (labelled "Retrieved but not cited"), Langfuse trace ID, export timestamp and version.

Filename: `ownedpulse-export-{query_id}.{json|pdf}`

---

## GET /api/query/history/export?format=json|csv

Full history export for /history page.

---

## GET /api/trace/{trace_id}

Proxies Langfuse API for UI drawer. Avoids CORS.

---

## GET /api/pdf/page?file_path={path}&page_no={n}

Returns PNG of rendered PDF page. Path rewriting applied internally.
Returns 404 if file does not exist — UI handles gracefully.
DPI 150, 0-indexed page numbers.

---

## GET /api/corpus/stats

```json
{
  "total_documents": 1324,
  "per_agency": { "FDA": 964, "EMA": 209, "ICH": 154 },
  "per_document_type": { ... },
  "last_pipeline_run": "ISO datetime|null"
}
```

EU-Commission counts normalised into EMA.

---

## GET /api/corpus/documents

Paginated document list for /corpus browser.
Params: `agency`, `document_type`, `date_from`, `date_to`, `limit`, `offset`.

---

## GET /api/health

Returns `{ "status": "ok", "qdrant": "ok", "postgres": "ok", "ollama": "ok", "langfuse": "ok" }`.
Returns 503 if any component is down (specific component marked).

---

## /corpus router

| Endpoint | Notes |
|---|---|
| `GET /corpus/documents` | Paginated doc list from document_registry. Params: page, page_size, issuing_body, doc_type, ingestion_status |
| `GET /corpus/documents/{doc_id}` | Single doc + Qdrant hash comparison (qdrant_source_hash, pg_source_hash, hash_match) |
| `GET /corpus/documents/{doc_id}/chunks` | Paginated chunks via Qdrant scroll() — NOT search |
| `GET /corpus/feed-runs` | Paginated run_log list, most recent first |
| `GET /corpus/feed-runs/{run_id}` | Run row + documents ingested in that run |
| `GET /corpus/supersede/{document_family_id}` | All docs in family ordered by publication_date ASC |

---

## /admin router

| Endpoint | Notes |
|---|---|
| `GET /admin/health` | Qdrant + PostgreSQL + Ollama status with key metrics. Never fail entire endpoint for one service |
| `GET /admin/feeds` | All feed_config rows including enabled column |
| `PATCH /admin/feeds/{feed_id}` | Toggle enabled. Body: `{"enabled": true}` |
| `POST /admin/trigger-run` | Read n8n_trigger_webhook from system_config → create run_log row → call n8n webhook → return run_id. 503 if webhook URL empty |
| `GET /admin/models` | active_model from system_config + available_models from Ollama /api/tags |
| `PUT /admin/model` | Update active_llm_model in system_config. Validate model exists in Ollama first |
