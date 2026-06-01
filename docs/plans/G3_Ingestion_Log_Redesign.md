# G3 — Ingestion Log Pages Redesign (Trace-Centric)

**Type:** UI + API · **Depends on:** G-T3 complete (trace tables populated)
**Design gate D-5:** Claude Design prototype + visual approval BEFORE build.

---

## Objective

Redesign all ingestion log pages around the canonical trace: one row per ingestion run, drill-down to document-level spans, surfacing source, status, counts, and the Langfuse trace — so a QA director can audit "what was ingested, when, by which trigger, and with what result" from the app.

## Design gate D-5 (resolve before build)

Decide and approve in Claude Design:
- Run-level list row: `started_at`, `ingestion_source`, `triggered_by`, `workflow_id`/`workflow_execution_id` (when present), `status`, `doc_count_succeeded/attempted`, link to Langfuse trace.
- Filtering/sorting: by `ingestion_source`, `status`, date range.
- Drill-down to document-level span view: per-doc `source_url`, `fetched_at`, `parsed_at`, `chunk_count`, `status`, `failure_reason`.
- Status/error visual language (success/partial/failed) consistent with G1/G2.
- Whether failed-doc detail links to a retry action (note: retry uses the existing `reingest_pending.py` path — surface only if cheap; otherwise read-only for v1).

Brand + `ownedai-ui`; `data-testid` per `design-spec.md`.

## API tasks

1. **Runs list** `GET /ingestion/runs` — paginated, reads `ingestion_run`; supports filter by source/status/date.
2. **Run detail** `GET /ingestion/runs/{trace_id}` — run header + its `ingestion_doc` spans.
3. **Langfuse link** — per-run resolvable Langfuse trace URL from `trace_id` (config-driven base URL, shared helper with G2).
4. Ensure all three `ingestion_source` values render correctly (n8n_rss, manual_cli, bootstrap_ui) — the unification (G-T2) is what makes manual + bootstrap runs appear here at all.

## UI tasks

1. Build approved D-5 run-level list with filters.
2. Drill-down to span-level detail.
3. Per-run Langfuse trace link.
4. Consistent status/error styling with G1/G2.
5. Replace any legacy n8n-only log view so all ingestion sources appear in one place.

## Acceptance criteria

- All ingestion runs (RSS, manual, bootstrap) appear in one log, distinguishable by `ingestion_source`.
- Run drill-down shows accurate per-doc spans with counts and failure reasons.
- Langfuse trace link resolves per run.
- Filters work; failed/partial runs are clearly distinguished.
- `tests/api` + `tests/integration` + `tests/e2e` pass.

## Out of scope

Bootstrap (G1). Query page (G2). Building a new retry engine (reuse existing `reingest_pending.py` if retry is surfaced at all).

## Commit / corrections

`Phase G3 step N — description`. Log any span/run join issues in `CORRECTIONS.md`.
