# G-T1 — Trace Schema + Canonical Ingestion Spec

**Type:** Backend / data schema · **Depends on:** `CLAUDE.md` v2 (authoritative existing field names)
**D-1 status: RESOLVED** — dedicated PostgreSQL tables, field names locked below. No design gate remaining; build directly.

---

## Objective

Define and implement the canonical ingestion trace with two distinct modes depending on ingestion type. Schema must support both modes cleanly.

---

## Two-mode trace architecture (core design decision)

**Mode A — Bulk / initial ingestion (1000+ documents):**
No run envelope. Each document is its own top-level Langfuse trace and its own `ingestion_doc` row. `ingestion_run` is NOT created. Run Log shows individual document rows. This is the only viable model at scale — a single envelope over 1000+ documents produces unusable Run Log output (as observed in current state: one PARTIAL row with 1382 errors).

**Mode B — Batch / RSS ingestion (5–20 documents per n8n run):**
One `ingestion_run` envelope wrapping all documents in the batch. Each document gets an `ingestion_doc` span within the run. Run Log shows one row per RSS run with drill-down to document spans. This is the correct model for small scheduled batches.

The `ingestion_source` field determines which mode applies:
- `bootstrap_ui` → Mode A (bulk)
- `manual_cli` (bulk flag set) → Mode A
- `n8n_rss` → Mode B
- `manual_cli` (single doc) → Mode B

---

## Prerequisites

- Read `CLAUDE.md` in order per START HERE protocol.
- **Existing schema to reconcile against:** `run_log` table and `document_registry.run_id` FK (added 2026-05-29). Task 0 governs reconciliation — do it before any migration code.
- Read existing authoritative field names from `CLAUDE.md` v2. Do not invent or rename existing fields.
- Confirm current Qdrant payload schema and PostgreSQL `document_registry` columns before altering.

---

## Tasks

0. **Reconcile with existing schema before writing anything** — read live PostgreSQL schema and existing migration files:
   - Check whether `run_log` already covers `ingestion_run` fields. If yes, extend rather than duplicate.
   - Check whether `document_registry.run_id` maps to `trace_id` concept. Confirm FK target.
   - Document findings in `CORRECTIONS.md` before proceeding.
   - If `run_log` + `run_id` fully cover Mode B, skip to task 2 and add only `ingestion_doc` as new.

1. **PostgreSQL registry migration** — add columns to `document_registry`:
   - `trace_id` (UUID) — for Mode A: this IS the document's own trace_id. For Mode B: FK to `ingestion_run.trace_id`.
   - `workflow_id` (text, nullable)
   - `workflow_execution_id` (text, nullable)
   - `ingestion_source` (text, enum-checked: `n8n_rss|manual_cli|bootstrap_ui`)
   - Confirm `last_indexed_at`, `source_fetched_at`, `doc_type`, `document_family_id` exist and are writable.
   - Provide reversible SQL migration with up/down.

2. **Trace tables** — implement as decided (D-1 resolved):
   - `ingestion_run` — one row per Mode B batch run. Fields: trace-level spec below.
   - `ingestion_doc` — one row per document for BOTH modes. For Mode A: `run_id` is null. For Mode B: `run_id` FK to `ingestion_run`. This table is the unified document ingestion record regardless of mode.

3. **Qdrant payload schema** — add to every chunk payload:
   - `trace_id` (string UUID), `ingested_at` (ISO8601), `embedding_model` + version.
   - Update `payload.py`. Keep deterministic `chunk_id` unchanged.

4. **`lib/observability.py`** — implement two-mode trace emitter:

   Mode A (per-document trace):
   - `start_document_trace(doc_id, source_url, source, triggered_by) -> trace handle` — opens a top-level Langfuse trace per document
   - `finalize_document_trace(handle, status, chunk_count, failure_reason=None)`

   Mode B (batch run):
   - `start_ingestion_run(source, triggered_by, workflow_id=None, workflow_execution_id=None) -> run handle`
   - `start_document_span(run_handle, doc_id, source_url) -> span handle`
   - `finalize_document_span(span_handle, status, chunk_count, failure_reason=None)`
   - `finalize_ingestion_run(run_handle, doc_count_attempted, doc_count_succeeded, doc_count_failed, error_summary=None)`

5. **Wipe procedure** — implement `scripts/wipe_corpus.py`. Atomic wipe in this exact sequence:
   1. Delete Langfuse traces tagged with project `regpulse` via Langfuse API
   2. Truncate `ingestion_doc`
   3. Truncate `ingestion_run` (Mode B runs)
   4. Truncate `document_registry` (or delete where applicable)
   5. Delete all points from Qdrant `knowledge_base` collection (do NOT drop collection — preserve index config)
   
   Script requires explicit `--confirm` flag. Prints count of records to be deleted before executing. Exits non-zero if any step fails. Partial wipe (some steps succeeded, others failed) is logged and reported — never silently incomplete.
   
   This script is used by: G-T3 (full reingestion), Sources Initial Load `force=true` path (G1).

6. **Schema doc** — write/update `docs/trace-spec.md` with locked field names, two-mode architecture, wipe procedure. Update `CLAUDE.md` v2 to mark new fields authoritative.

---

## Canonical trace fields

**`ingestion_run` table (Mode B only):**
`trace_id` · `ingestion_source` · `triggered_by` · `workflow_id` · `workflow_execution_id` · `started_at` · `completed_at` · `status` (`success|partial|failed`) · `doc_count_attempted` · `doc_count_succeeded` · `doc_count_failed` · `error_summary` (nullable)

**`ingestion_doc` table (both modes):**
`id` (PK) · `trace_id` (Langfuse trace ID — for Mode A: top-level trace; for Mode B: span ID) · `run_id` (FK to `ingestion_run.trace_id`, nullable — null for Mode A) · `doc_id` · `source_url` · `fetched_at` · `parsed_at` · `chunk_count` · `embedding_model` · `status` (`success|failed`) · `failure_reason` (nullable) · `ingestion_source` · `triggered_by` · `ingested_at`

**Chunk level** (Qdrant payload + registry, NOT Langfuse):
`chunk_id` · `doc_id` · `trace_id` · `ingested_at` · `embedding_model` (+ version)

---

## Acceptance criteria

- Migration applies and reverses cleanly.
- `observability.py` exposes both mode contracts; unit-tested with synthetic docs for each mode.
- `wipe_corpus.py` requires `--confirm`, prints pre-wipe counts, executes atomically, reports any partial failure.
- `docs/trace-spec.md` documents two-mode architecture. `CLAUDE.md` v2 updated.
- `tests/api` + `tests/compliance` pass.

## Out of scope

No reingestion (G-T3). No path wiring (G-T2). No UI.

## Commit / corrections

`Phase G-T1 step N — description`. Log schema reconciliation findings in `CORRECTIONS.md`.
