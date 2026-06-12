# Remove RSS Dead Code — Audit Report

## Category A — Dead functions (REMOVE entire function)

### `fetch_rss()` — fetch_feed.py:109-146
Dead RSS XML parser. Only called from `fetch_feed()` dispatcher at line 501
(fallback for unrecognized feed_type) and rss-only path at line 562.
Both callers are dead — no active feed_type uses this path.

### `rss_only` dispatch block — fetch_feed.py:552-567
The entire `if args.rss_only:` block in main(). Dead — scheduler no longer
passes `--rss-only`.

### `--rss-only` argparse — fetch_feed.py:514-515, run_pipeline.py:243-244
The argparse definitions. Dead CLI flags.

### `rss_only` parameter — run_pipeline.py:53,65-66,254
The `rss_only` parameter in `fetch_items()` and its forwarding to `fetch_feed.py`.

### `RSS_FEED_URLS` dict — fetch_feed.py:245-250
Feed URL mapping only used by rss-only path.

### `stop_active_rss()` — scheduler.py:77-86
Kills RSS subprocess. Functions `_active_proc` and `_active_run_id` only used here.

### `_active_proc` / `_active_run_id` globals — scheduler.py:73-74
Only used by `stop_active_rss()` and `run_rss_ingestion_job()`.

### `_write_run_log_error_or_insert()` — scheduler.py:31-60
Only called from `run_rss_ingestion_job()`.

### `run_rss_ingestion_job()` — scheduler.py:89-172
Entire async function. Launches `run_pipeline.py` as subprocess.
Replaced by bootstrap flow.

### `reschedule_rss_job()` — scheduler.py:174-181
Reschedules the cron job. Used by admin.py:616 but admin trigger is dead.

### `setup_scheduler()` / `_read_schedule_from_db()` — scheduler.py:183-220
Adds the daily cron job. Still needed for scheduled ingestion.

### `RSS_SOURCES` — ingestions.py:10
Constant list of RSS trigger_source values.

### `rss_runs` query block — ingestions.py:124-173
The RSS runs query section in the unified ingestion list.

### `rss_run_progress()` SSE endpoint — ingestions.py:515+
SSE endpoint for RSS run progress. Dead since RSS pipelines removed.

### Admin trigger endpoints calling `run_rss_ingestion_job` — admin.py:206-208, 220-221, 537-538
POST /feeds/{id}/trigger, POST /trigger-run calling scheduler functions.

### `admin_stop_ingestion()` — admin.py:226-233
Stop endpoint that calls `stop_active_rss()`.

### `RSS_SCHEDULE_*` duplicates — admin.py:514-516
Duplicate schedule env var reads in admin.py (also in scheduler.py).

### `bootstrap_activate_rss()` — bootstrap.py:602-615
POST /bootstrap/activate-rss endpoint. Dead n8n remnant.

### `activateRss()` — client.js:242
Client function calling `/api/bootstrap/activate-rss`.

### `openRssProgress()` — client.js
Client function for RSS SSE endpoint.

### All `_rss*` functions/variables — useBootstrapProgress.js:143-248
`_rssState`, `_rssListeners`, `_rssEsRef`, `rssNotify()`, `subscribeRssProgress()`,
`startRssTracking()`, `stopRssTracking()`, `useRssProgress()`.

### RssRunRow SSE logic — IngestionsPage.jsx:624-673
`rssState`, `useRssProgress()`, `liveStatus`, `displayNew`, `displayErrors`.

### `rssActivated` state — SourcesPage.jsx:702,736,937
"RSS automation: active" display.

### `n8n_rss` entry — QueryPage.jsx:23, IngestionsPage.jsx:37
Source label map entries.

## Category B — RSS branch in shared function (REMOVE branch)

### `fetch_feed()` fallback — fetch_feed.py:501
`return fetch_rss(feed, cutoff_date=cutoff)` — fallback for unrecognized feed_type.
Remove line, return empty result instead.

### `n8n_rss` value in argparse choices — fetch_feed.py:509
Remove `"n8n_rss"` from trigger_source choices.

### `trigger_source` filter in ingestions.py:138-139
The branch that filters by `RSS_SOURCES`.

## Category C — Dead constants (REMOVE)

### `RSS_SCHEDULE_HOUR/MINUTE/TIMEZONE` — scheduler.py:18-20
Keep — they're the defaults for `_read_schedule_from_db()`. Still used.

### `PIPELINE_SCRIPT` — scheduler.py:22
Only used by `run_rss_ingestion_job()`. Remove after removing that function.

### `n8n_rss` trace_emitter references — trace_emitter.py:10,88
Docstring examples. Update to remove.

### `n8n_rss` ingest_documents references — ingest_documents.py:12,15,26,360,443
Docstring examples and mode comments. Update to remove.

## Category D — Dead imports (REMOVE after functions)

### `import feedparser` — fetch_feed.py:15
Only used by `fetch_rss()`.

### `import feedparser` — fetch_feed.py top
Same line.

## Category E — Comments/docstrings (REMOVE/UPDATE)

### All docstrings mentioning "RSS" — various files
Update terminology throughout.

## Category F — Schema/db (DO NOT TOUCH)

### `feed_type` column values
Leaving permissive. No migration needed.

### `trigger_source` column values
`n8n_rss`, `scheduled`, `manual` remain in run_log table. No migration.

## Category G — UI strings (REMOVE)

### `n8n_rss` in source pill — IngestionsPage.jsx:37
### CSS `.g3-row.rss` — index.css
### `activate-rss` route in client.js
### Comments mentioning "RSS" in useBootstrapProgress.js

## Files to modify

| File | Categories |
|------|-----------|
| `api/lib/scheduler.py` | A (run_rss_ingestion_job, stop_active_rss, reschedule_rss_job, _active_proc/run_id, _write_run_log_error_or_insert), C (PIPELINE_SCRIPT) |
| `api/routers/admin.py` | A (trigger endpoints referencing scheduler, stop-ingestion, RSS_SCHEDULE_* duplicates), B (schedule config still needed) |
| `api/routers/ingestions.py` | A (RSS_SOURCES, rss_runs block, rss_run_progress SSE), B (trigger_source filter) |
| `api/routers/bootstrap.py` | A (activate-rss endpoint) |
| `api/routers/sources.py` | E (docstrings only) |
| `scripts/rss/fetch_feed.py` | A (fetch_rss, rss_only block, RSS_FEED_URLS), B (fetch_feed fallback, argparse), D (feedparser import) |
| `scripts/rss/run_pipeline.py` | A (rss_only param, --rss-only argparse) |
| `api/lib/trace_emitter.py` | E (docstrings) |
| `api/lib/ingest_documents.py` | E (docstrings) |
| `api/lib/ingestion_lock.py` | E (docstring) |
| `ui/src/hooks/useBootstrapProgress.js` | A (all _rss* code) |
| `ui/src/api/client.js` | A (activateRss, openRssProgress) |
| `ui/src/components/pages/IngestionsPage.jsx` | A (rssState/useRssProgress), G (n8n_rss label) |
| `ui/src/components/pages/QueryPage.jsx` | G (n8n_rss label) |
| `ui/src/components/pages/SourcesPage.jsx` | A (rssActivated), G (comment) |

## What STAYS

- `rss` lock kind in ingestion_lock.py — used by bootstrap too
- `rss_feeds` parameter name in BootstrapRequest — it's the payload key, not RSS-specific. Rename to `sources` in a separate PR.
- `rss` CSS classes — `.g3-row.rss` used by existing HTML
- `rss_schedule_*` system_config keys — still used by scheduler
- `RSS_SCHEDULE_*` env vars — still used as defaults
- All of `scripts/rss/` directory — fetch_feed.py, run_pipeline.py, archive.py, resolve_landing.py still used by the scheduler's daily run (which calls run_pipeline.py)
- `run_pipeline.py` and its subprocess chain — still used by daily scheduler
- `admin.py` scheduler config endpoints — still used for schedule management
- `ingestion_lock.py` — still used by bootstrap
