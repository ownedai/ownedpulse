# Phase G — Completed Work

## G-T3 Reingestion + Ingestion Fixes (2026-06-01)

- **G-T3 full reingestion** — All 1,382 documents re-ingested through the three-level trace system. 22,066 Qdrant chunks, 23,039 vectors indexed, 0 null trace_ids, 1,408 ingestion_doc spans, run_log finalized as success.

- **run_ingest.py — three failure-mode fixes** (commit `d089ebd`):
  - `run_ingest_v2()` line 354: uses `source_file_format` over `content_type` for HTML vs Docling routing
  - `ingest_html_document()`: falls back to `source.pdf` when `source.html` missing but contains HTML (FDA labeling pages)
  - `run_ingest_v2()`: cleans stale `extracted/` and `chunks/` dirs before ingestion to avoid PermissionError from Docker root-owned files
  - `build_rss_meta()`: respects `source_local_path` and `source_file_format` from disk metadata instead of reconstructing from `content_type`
  - New helpers: `_resolve_source_path()`, `_is_structured_xml()`

- **21-CFR-Part-11 XML routing fix** (commit `656deb0`):
  - `_is_structured_xml()` detects eCFR XML and routes through Docling for proper heading extraction
  - Result: 23 chunks, 100% clause_id coverage, all §11.1–§11.300 present (previously 15 chunks of Federal Register bot-block HTML, 0% clause_id)

- **Host execution support** — `config.py` uses `os.environ.setdefault()` for PG_DSN and DOCLING_HOST. `embedding.py` guards empty text. `resolve_landing.py` extracts publication dates from PDF filenames.

- **g3_reingest.py orchestrator** — Full wipe-and-reingest at `/opt/scripts/g3_reingest.py`. Checkpointed to `/tmp/g3_reingest_checkpoint.json` per doc. Supports `--dry-run` and `--resume`.

## Core fixes (2026-05-29)

- **Langfuse truncation** — Removed `[:500]` and `[:200]` slices from generation input/output in `api/main.py`. Full prompt and answer sent.
- **Sticky audit footer** — `.rp-audit` has `position: sticky; bottom: 0` in `ui/src/index.css`.
- **ICH feed metadata backfill** — Fixed `_extract_ich_items()`. Deleted 151 old ICH junk entries, re-ingested 147 docs (6,053 Qdrant chunks). Date normalisation applied: 5,467 chunks across 113 docs updated to ISO dates.
- **DB migrations** — All 4 migrations applied: `run_log`, `system_config`, `feed_config.enabled`, `document_registry.run_id`.
- **fetch_feed.py run_log lifecycle** — `--trigger-source`, `--run-id`, `--n8n-execution-id` args added. INSERT at start, UPDATE at end/error.
- **/corpus + /admin API routers** (commit 2896c32) — Both routers in `api/routers/corpus.py` and `api/routers/admin.py`. All 12 endpoints implemented. `get_active_model()` reads from `system_config` with 60s cache.
- **Frontend pages** (commit 2896c32) — CorpusPage, DocumentDetailPage, RunLogPage, AdminPage added. Sidebar extended.

## UI v3 Redesign (2026-05-29, commit 37cb6d0)

All P1–P8 fixes implemented:

- **P1+P2**: TopNav 44px, page title left + theme toggle right. Logo removed from TopNav.
- **P3**: Sidebar has primary nav (Query/Corpus/Run Log/Admin) with inline SVG icons, `useLocation`-based active state.
- **P4**: FilterBar below QueryInput. Type → dropdown. Date → dropdown + floating popover. Retrieval → gear icon popover.
- **P5**: EmptyState stripped of logo/h1/subtitle. "Ask a regulatory question" label.
- **P6**: SourcePanel as `position: fixed` overlay drawer (480px, createPortal). Main content never shifts.
- **P7**: LangfuseDrawer merged into SourcePanel as Trace tab. Three tabs: Chunk | Provenance | Trace.
- **P8**: Recent queries capped at 5 (`useHistory(5)`). "View all →" present.

## FilterBar + stats bar polish (2026-05-29)

- FilterBar vertical alignment fixed — all controls inline with shared baseline
- Retrieval gear button matches dropdown style, blue when non-default
- CorpusStatsBar moved from EmptyState to App.jsx (always at bottom of main-column)
- System info block: `margin-top: auto` in CSS

## Screenshot-match visual redesign (2026-05-29)

- Sidebar active state: filled solid blue pill
- FilterBar group labels removed
- CorpusPage: text search + FilterDropdown popovers, reordered table columns
- RunLogPage: FilterDropdown popovers, N8N ID column, SCHEDULED/MANUAL/status badges
- DocumentDetailPage: 2-column layout, SectionLabel components, version chain as pills
- AdminPage: small-caps section labels, inline health rows, Toggle switch, full-width trigger button
