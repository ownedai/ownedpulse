# Sources Page — Claude Code Implementation Brief
**Version:** 1.0 · **Date:** 2026-06-01
**For:** Claude Code (implementation)
**Read first (in order):** CLAUDE.md → DEBRIEF.md → design-spec.md → query-ui-v3.css → DESIGN_BRIEF_Sources_Page.md (approved visual) → this file

---

## Prerequisites

- G-T1 complete: `ingestion_run`, `ingestion_doc` tables exist, `trace_id` on registry
- G-T2 complete: unified traced `ingest_documents()` callable from API
- G-T3 + G-T4 complete: corpus populated, quality gate green
- Approved Claude Design output for Sources page reviewed and placed in `ui/design-handoff/`
- Feed Management currently lives in Admin router — it moves to Sources router in this phase

---

## Scope

1. New `/sources` route + Sources page component
2. New FastAPI router `api/routers/sources.py`
3. Nav update: add Sources item between Corpus and Run Log
4. Admin page: remove Feed Management section (now in Sources)
5. Initial Load modal with SSE progress stream

---

## Backend — `api/routers/sources.py`

### Corpus summary endpoint
`GET /sources/summary`

Returns doc counts grouped by agency + doc_type from `document_registry`. Query:
```sql
SELECT agency, doc_type, COUNT(*) as doc_count, MAX(ingested_at) as last_ingested
FROM document_registry
WHERE status = 'active'
GROUP BY agency, doc_type
ORDER BY agency, doc_type
```
Response shape:
```json
{
  "groups": [
    {
      "agency": "FDA",
      "doc_type": "guidance",
      "doc_count": 847,
      "last_ingested": "2026-05-28T09:00:00Z"
    }
  ],
  "total": 1382,
  "last_updated": "2026-05-28T09:00:00Z"
}
```

### Base corpus documents
`GET /sources/corpus-docs`
Returns the managed base documents with supersede chains. Query `document_registry` where `corpus_doc = true` (add this boolean flag if not present — corpus docs are the 7 fixed regulatory documents, distinguished from RSS-ingested docs).

Response includes `document_family_id` to group supersede chains. Sort: active version first per family, superseded versions below ordered by `published_date` desc.

`POST /sources/corpus-docs/{doc_id}/reingest`
Triggers reingest for a single corpus document. Calls unified `ingest_documents()` with `source="manual_cli"`, `triggered_by="sources_ui"`. Returns `trace_id` for client polling.

`DELETE /sources/corpus-docs/{doc_id}`
Soft-delete: set `status = 'deleted'` in registry, remove chunks from Qdrant by `doc_id` filter. Record deletion in an audit log row (or `ingestion_run` with `ingestion_source = 'delete_ui'`). Two-step: first call returns deletion summary (chunk count), second call with `?confirm=true` executes. Never hard-delete without confirm.

### RSS feeds
`GET /sources/feeds`
Returns all feeds with operational stats. Extend existing feed query to include `doc_count` and `last_ingested` per feed from `document_registry`.

`PUT /sources/feeds/{feed_id}` — update enabled state (moved from Admin)

`POST /sources/feeds/{feed_id}/reingest`
Triggers historical re-pull for one feed. Same traced path as above.

### Initial Load
`GET /sources/initial-load/state`
Returns:
```json
{
  "status": "populated",  // "fresh" | "populated"
  "total_docs": 1382,
  "last_run": "2026-05-28T09:00:00Z",
  "scope_summary": [
    { "agency": "FDA", "doc_type": "guidance", "doc_count": 847 }
  ]
}
```
"fresh" = registry has zero active rows. "populated" = at least one active row.

`POST /sources/initial-load/run`
Body: `{ "scope": [{"agency": "FDA", "doc_type": "guidance"}, ...], "force": false }`
If `force=false` and status=populated, return 409 with message "Corpus already populated. Send force=true to wipe and reingest."
If `force=true`, call `wipe_corpus.py` logic (or equivalent internal function) before reingesting. Wipe is atomic and sequential: Langfuse traces (regpulse-tagged) → `ingestion_doc` → `ingestion_run` → `document_registry` → Qdrant points. Do NOT drop Qdrant collection.
Launches as FastAPI background task using **Mode A** (bulk, per-document traces, no run envelope — mandatory for 1000+ doc initial load). Returns `{ "run_token": "uuid" }` — this is not a `trace_id` (there is no run envelope in Mode A), it is a session token used to track the SSE stream. Store it server-side mapped to the background task.

`GET /sources/initial-load/progress/{run_token}`
**SSE endpoint.** Mode A: each document emits its own event as it completes. No run envelope. The background task never aborts on a single document failure.

```
event: run_started
data: {"run_token": "...", "doc_count_attempted": 1382}

event: doc_complete
data: {"doc_id": "...", "document_title": "...", "doc_type": "guidance", "agency": "FDA", "status": "success", "chunk_count": 47, "succeeded_so_far": 1, "failed_so_far": 0}

event: doc_failed
data: {"doc_id": "...", "document_title": "...", "doc_type": "guidance", "agency": "FDA", "status": "failed", "failure_reason": "fetch timeout", "succeeded_so_far": 845, "failed_so_far": 2}

event: run_complete
data: {"doc_count_attempted": 1382, "doc_count_succeeded": 1380, "doc_count_failed": 2, "rss_activated": true}
```

- `succeeded_so_far` and `failed_so_far` on every event drives the counter bar in the UI without client-side counting
- `doc_failed` renders as amber row — non-blocking, expected at scale
- Keep connection open until `run_complete` or `run_failed`
- Heartbeat comment (`: ping`) every 15 seconds — prevents Cloudflare tunnel timeout
- `run_complete` with `doc_count_failed > 0`: UI shows amber "N succeeded · N failed — details in Run Log" 

### n8n activation
Reuse existing webhook/API activation logic from G1 (bootstrap). `POST /sources/initial-load/activate-rss` — idempotent, checks active state before calling n8n API.

---

## Frontend — `ui/src/pages/Sources.jsx`

### Component structure
```
Sources
├── CorpusSummaryCard         ← Card 1
├── BaseCorpusCard            ← Card 2
│   ├── CorpusDocRow (active)
│   │   └── SupersedeChainRow (expandable, per superseded version)
│   └── DeleteConfirmRow (inline, conditional)
├── RssFeedsCard              ← Card 3
│   └── FeedRow
└── InitialLoadCard           ← Card 4
    └── InitialLoadModal
        ├── ScopeSelector (pre-run state)
        └── ProgressDisplay (SSE-driven, run state)
```

### data-testid attributes (required, per design-spec.md convention)
- `sources-summary-card`
- `sources-corpus-card`
- `sources-feeds-card`
- `sources-initial-load-card`
- `corpus-doc-row-{doc_id}`
- `supersede-expand-{doc_id}`
- `corpus-doc-reingest-{doc_id}`
- `corpus-doc-delete-{doc_id}`
- `delete-confirm-{doc_id}`
- `feed-row-{feed_id}`
- `feed-reingest-{feed_id}`
- `initial-load-btn`
- `initial-load-modal`
- `scope-checkbox-{agency}-{doc_type}`
- `initial-load-start-btn`
- `progress-display`
- `progress-row-{doc_id}`

### SSE handling
Use `EventSource` API. Open on modal trigger after receiving `run_token`. Handle:
- `run_started` → replace scope selection with progress panel; show counter bar initialised to "0 / N"
- `doc_complete` → append SUCCESS row to scrollable list; update counter bar using `succeeded_so_far` + `failed_so_far` from event data; update progress bar width
- `doc_failed` → append FAILED amber row with `failure_reason` below; update counter bar
- `run_complete` → finalise counter bar; show summary line (green if all succeeded, amber if partial); show RSS activation confirmation if `rss_activated=true`; re-enable close button
- `error` event or connection drop → show error state with retry option; re-enable close button

Counter bar drives from server-sent cumulative counts — do not count client-side.
Close EventSource on modal close or run completion.

### Null field display
Follow design-spec.md rules. Specifically:
- `last_ingested` null → display "Never" in muted text
- `doc_count` zero → display "0" in `--status-warn` amber, not hidden
- `doc_type` null → display "—"

### Supersede chain expand/collapse
Default: collapsed (chevron right). Click row or chevron to expand (chevron down). Superseded rows are indented 24px, use muted text, no action buttons. Use existing pill styles from design-spec.md.

---

## Nav update

Add to sidebar nav array (between Corpus and Run Log):
```jsx
{ label: 'Sources', path: '/sources', icon: Layers }  // lucide-react Layers icon
```

---

## Admin page cleanup

Remove from Admin:
- Feed Management card (`FEED MANAGEMENT` section) — it is now in Sources
- The `PUT /admin/feeds/{id}` route moves to `PUT /sources/feeds/{feed_id}`

Retain in Admin: System Health, Pipeline Trigger, Model Selection.

Update Admin responsive note: 3 cards (was 4), 2×2 grid collapses to 1×3 below 1024px.

---

## Taxonomy verification gap

`GET /sources/summary` groups by `agency` + `doc_type` from live registry data. Do NOT hardcode agency or doc_type label mappings — render whatever the registry returns. Display labels: convert `doc_type` snake_case to Title Case for display (`scientific_guideline` → "Scientific Guideline"). Agency values render as-is (already uppercase: FDA, EMA, ICH).

If the same `doc_type` value appears under multiple agencies, it will appear as separate rows per agency — this is correct behaviour. Do not merge.

---

## Migration

No new schema changes required if G-T1/T2/T3 are complete. One addition: if `corpus_doc` boolean column is not present on `document_registry`, add migration `registry/007_add_corpus_doc_flag.sql`:
```sql
ALTER TABLE document_registry ADD COLUMN IF NOT EXISTS corpus_doc BOOLEAN DEFAULT FALSE;
-- Backfill: mark the 7 known corpus documents
UPDATE document_registry SET corpus_doc = TRUE WHERE doc_id IN (
  -- list the 7 doc_ids here; Claude Code must read the live registry to populate this list
);
```

---

## Acceptance criteria

- `/sources` route renders all four cards with live data
- Corpus summary shows counts by agency + doc_type with correct last_ingested dates
- Supersede chain (ICH Q9 / Q9R1) expands and collapses correctly
- Reingest on a corpus doc creates a Run Log entry with `source=manual_cli`
- Delete two-step confirm works; deletion appears in Run Log
- RSS feed enabled toggle and reingest work (moved from Admin, same behaviour)
- Initial Load modal: scope selection → trigger → SSE progress → completion state
- SSE heartbeat keeps connection alive through Cloudflare tunnel (15s ping)
- Force=true path wipes selected scope and reingests
- Admin page no longer shows Feed Management
- Nav shows Sources between Corpus and Run Log
- All data-testid attributes present
- Null fields display per design-spec.md rules
- `tests/api` + `tests/integration` + `tests/e2e` pass

---

## Out of scope

- Adding new corpus documents (post-v1)
- Feed deletion (post-v1)
- Per-feed archive window configuration (post-v1)
- Query page redesign (G2)
- Run Log redesign (G3)

## Commit / corrections

`Phase G1 step N — description`. Log taxonomy display deviations in `CORRECTIONS.md`.
