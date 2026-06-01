# regpulse — Ingestion Trace Specification v1

**Status:** Canonical (G-T1 locked). All ingestion paths MUST conform.
**Last updated:** 2026-06-01

---

## 1. Architecture

Three-level trace: **run_log** (trace) → **ingestion_doc** (document span) → **Qdrant chunk payload** (per-chunk).

```
run_log (1 row per ingestion run)
  ├── ingestion_doc (1 row per document in that run)
  │     ├── Qdrant chunk (trace_id in payload)
  │     ├── Qdrant chunk
  │     └── ...
  └── ingestion_doc
        ├── Qdrant chunk
        └── ...
```

PostgreSQL is the queryable record of truth. Langfuse mirrors for observability (not required for trace integrity).

---

## 2. Trace level — `run_log` table

One row per ingestion run. PK = `id` (integer sequence). Logical identifier = `run_id` (UUID).

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-increment PK |
| `run_id` | UUID | Logical trace identifier. Unique. Stamped on every chunk as `trace_id`. |
| `triggered_at` | TIMESTAMPTZ | When the run started (DEFAULT NOW()) |
| `completed_at` | TIMESTAMPTZ | When the run finished (nullable until finalized) |
| `trigger_source` | VARCHAR(20) | Ingestion source enum (see §5) |
| `triggered_by` | TEXT | Human or system identifier (e.g. `n8n-scheduler`, `zoran`) |
| `workflow_id` | TEXT | n8n workflow ID (nullable) |
| `n8n_execution_id` | VARCHAR(100) | n8n execution ID (nullable) |
| `feed_source` | VARCHAR(50) | Feed identifier (nullable) |
| `status` | VARCHAR(20) | Run status enum (see §5) |
| `items_fetched` | INTEGER | Documents attempted in this run |
| `items_new` | INTEGER | Documents successfully ingested |
| `items_skipped` | INTEGER | Documents skipped (duplicates, no change) |
| `error_count` | INTEGER | Documents that failed |
| `duration_ms` | INTEGER | Wall-clock duration (nullable) |
| `error_detail` | TEXT | Error summary if status=error (nullable) |

### Constraints
- `PRIMARY KEY (id)`
- `UNIQUE (run_id)` — enables FK references from `ingestion_doc`
- Indexes on `triggered_at DESC`, `status`

---

## 3. Document-span level — `ingestion_doc` table

One row per document per ingestion run. FK → `run_log.run_id`.

| Column | Type | Description |
|---|---|---|
| `span_id` | UUID PK | Unique span identifier |
| `trace_id` | UUID FK | References `run_log(run_id)` |
| `doc_id` | TEXT | `document_registry.document_id` |
| `source_url` | TEXT | Original source URL (nullable) |
| `fetched_at` | TIMESTAMPTZ | When the source was fetched |
| `parsed_at` | TIMESTAMPTZ | When parsing/chunking completed |
| `chunk_count` | INTEGER | Number of chunks produced |
| `embedding_model` | TEXT | Embedding model used (e.g. `mxbai-embed-large`) |
| `status` | VARCHAR(20) | Document span status enum (see §5) |
| `failure_reason` | TEXT | Error detail if status=failed |
| `created_at` | TIMESTAMPTZ | Row creation time |

### Constraints
- `PRIMARY KEY (span_id)`
- `FOREIGN KEY (trace_id) REFERENCES run_log(run_id)`
- Indexes on `trace_id`, `doc_id`, `status`

---

## 4. Chunk level — Qdrant payload fields

Every chunk in the `knowledge_base` collection MUST carry these trace fields:

| Field | Type | Description |
|---|---|---|
| `trace_id` | string UUID | The `run_log.run_id` of the ingestion run that created this chunk |
| `chunked_at` | ISO8601 string | When this chunk was created (already present, serves as `ingested_at`) |
| `embedding_model` | string | Model used for the vector (already present, e.g. `mxbai-embed-large`) |
| `chunk_id` | UUID string | Deterministic chunk identifier (already present, unchanged) |
| `document_id` | string | Parent document identifier (already present) |

### Payload construction

`trace_id` is passed through `build_payload()` in `payload.py`:

```python
build_payload(chunk, idx, meta, clause_id, cross_refs, offsets, prov,
              chunker_version, trace_id="<run_log.run_id>")
```

---

## 5. Enums

### `trigger_source` (run_log) — ingestion source

| Value | Description |
|---|---|
| `n8n_rss` | RSS feed ingestion triggered via n8n webhook |
| `manual_cli` | Manual CLI ingestion (`python run_ingest.py`) |
| `bootstrap_ui` | First-install bootstrap triggered from Admin UI |

Note: Existing rows use `scheduled`/`manual` from pre-G-T1 schema. These are backward-compatible. New rows use the canonical values above.

### `status` (run_log) — run status

| Value | Description |
|---|---|
| `running` | Run is in progress |
| `success` | All documents ingested without errors |
| `partial` | Some documents failed, some succeeded |
| `error` | Run-level failure (e.g. DB connection lost) |

Note: Existing rows use `complete` for success. New finalize calls should use the canonical values above. Readers should treat `complete` as equivalent to `success`.

### `status` (ingestion_doc) — document span status

| Value | Description |
|---|---|
| `pending` | Span created, ingestion not yet started |
| `success` | Document ingested successfully |
| `failed` | Document ingestion failed |

---

## 6. Trace emitter contract

All ingestion paths MUST use `api.lib.trace_emitter` as the single entry point.

### Functions

```python
start_ingestion_trace(*, source, triggered_by,
                      workflow_id=None, workflow_execution_id=None) -> IngestionTrace
```
Creates a `run_log` row with status=`running`. Returns an `IngestionTrace` handle with `.trace_id`.

```python
start_document_span(trace_id, *, doc_id, source_url="") -> DocumentSpan
```
Creates an `ingestion_doc` row with status=`pending`. Returns a `DocumentSpan` handle with `.span_id`.

### Finalize methods

```python
trace.finalize(*, status, doc_count_attempted=0, doc_count_succeeded=0,
               doc_count_failed=0, error_summary=None)
```
Updates `run_log` with final status, counts, and `completed_at`.

```python
span.finalize(*, status, chunk_count=0, embedding_model="", failure_reason=None)
```
Updates `ingestion_doc` with final status, chunk count, and `parsed_at`.

### trace_id stamping

`trace.trace_id` (a UUID string) MUST be passed to `build_payload()` as the `trace_id` parameter for every chunk in that run. This is the link that enables query-time provenance: a retrieved chunk can be traced back to its exact ingestion run.

---

## 7. Migration

Migration files at `api/migrations/001_ingestion_trace.{up,down}.sql`.

Apply: `api/migrations/001_ingestion_trace.up.sql`
Reverse: `api/migrations/001_ingestion_trace.down.sql`

Changes from pre-G-T1 schema:
- `run_log`: added `triggered_by TEXT`, `workflow_id TEXT`, UNIQUE constraint on `run_id`
- New table: `ingestion_doc`

---

## 8. Acceptance criteria (G-T1 gate)

- [x] Migration applies and reverses cleanly
- [x] `trace_emitter.py` exposes three-level contract: `start_ingestion_trace()` → `start_document_span()` → `.finalize()`
- [x] Smoke test produces complete run→doc→chunk trace (run_log + ingestion_doc rows)
- [x] `payload.py` emits `trace_id` on every chunk
- [x] This spec documents locked field names; CLAUDE.md updated

---

## 9. Related

- `docs/plans/G-T1_Trace_Schema_and_Spec.md` — implementation plan (this spec is the output)
- `docs/plans/G-T2_Ingestion_Path_Unification.md` — enforces this contract across all paths
- `docs/plans/G-T3_Full_Reingestion.md` — verifies 100% trace_id coverage
- `CORRECTIONS.md` — Field-name divergences from plan spec
