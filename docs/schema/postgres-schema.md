# PostgreSQL Schema

Database: `knowledge_base`, User: `postgres`.

## document_registry

| Column | Type | Notes |
|---|---|---|
| `document_id` | text | Primary identifier |
| `issuing_body` | text | Same as Qdrant `issuing_body` |
| `doc_type` | text | Underscored values |
| `last_indexed_at` | timestamptz | Last ingestion (NOT `ingested_at`) |
| `archive_path` | text | Full host path to PDF archive |
| `metadata_json` | jsonb | Contains `publication_date`, `document_title`, etc. |
| `run_id` | UUID | FK → run_log(run_id) |

### Path rewriting for PDF rendering

`archive_path` on host: `/mnt/data/regulatory_archive/...`.
Container mount: `/archive`. Rewrite at endpoint level:
`/mnt/data/regulatory_archive` → `/archive`.

Migration:
```sql
ALTER TABLE document_registry
ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES run_log(run_id);
CREATE INDEX IF NOT EXISTS idx_document_registry_run_id ON document_registry(run_id);
```

## query_history

```sql
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
);
```

`init_db()` MUST raise on failure — do NOT silently swallow exceptions.

## feed_config — enabled column

```sql
ALTER TABLE feed_config
ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
```

`fetch_feed.py` must query `WHERE enabled=TRUE` at runtime (not cached at startup).

## run_log

```sql
CREATE TABLE IF NOT EXISTS run_log (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    trigger_source  VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    n8n_execution_id VARCHAR(100),
    feed_source     VARCHAR(50),
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    items_fetched   INTEGER NOT NULL DEFAULT 0,
    items_new       INTEGER NOT NULL DEFAULT 0,
    items_skipped   INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    error_detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_log_triggered_at ON run_log(triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_log_status ON run_log(status);
```

## system_config

```sql
CREATE TABLE IF NOT EXISTS system_config (
    key     VARCHAR(100) PRIMARY KEY,
    value   TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO system_config (key, value) VALUES
    ('active_llm_model', 'phi4:14b-q8_0'),
    ('n8n_trigger_webhook', '')
ON CONFLICT (key) DO NOTHING;
```

After n8n webhook is confirmed:
```sql
UPDATE system_config SET value = 'http://n8n:5678/webhook/regpulse-ingest-trigger'
WHERE key = 'n8n_trigger_webhook';
```

Active LLM model is read from `system_config` on each request (60s cache), NOT from a static constant.
