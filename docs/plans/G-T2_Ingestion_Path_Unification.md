# G-T2 — Ingestion Path Unification

**Type:** Backend · **Depends on:** G-T1 (two-mode trace contract + schema in place)
**Closes:** TI-19 (trace all ingestion paths), TI-20 (trace_id storage enforced)

---

## Objective

Route every ingestion trigger through one entry point that selects the correct trace mode (A or B) based on `ingestion_source`. No path may write chunks without an active trace. Per-document error isolation is mandatory — one document failure never aborts the run.

---

## Two modes recap

**Mode A (bulk — bootstrap_ui, manual_cli bulk):** No run envelope. Each document is its own top-level Langfuse trace. `ingestion_doc.run_id` = null.

**Mode B (batch — n8n_rss, manual_cli single):** One `ingestion_run` envelope. Each document is a span within it. `ingestion_doc.run_id` = FK to run.

---

## Prerequisites

- G-T1 merged: both mode contracts in `observability.py`, `ingestion_doc` table, `wipe_corpus.py` implemented.
- Read existing `ingestion/run_ingest.py`, `ingest.py`, `parsing.py`, `payload.py` to map current call paths.

---

## Tasks

1. **Single entry point** — `ingest_documents(docs, *, source, triggered_by, workflow_id=None, workflow_execution_id=None, bulk=False)`:

   - If `source=bootstrap_ui` or `bulk=True` → **Mode A loop:**
     ```
     for each doc:
       try:
         trace = start_document_trace(doc_id, source_url, source, triggered_by)
         parse → chunk → embed → upsert
         stamp trace_id + ingested_at + embedding_model on every chunk
         finalize_document_trace(trace, status=success, chunk_count=N)
         write ingestion_doc row (run_id=null)
       except Exception as e:
         finalize_document_trace(trace, status=failed, failure_reason=str(e))
         write ingestion_doc row (status=failed, failure_reason=str(e), run_id=null)
         log error, continue to next doc
     ```
     Returns: list of `{doc_id, status, trace_id, chunk_count, failure_reason}` per document.

   - If `source=n8n_rss` or single doc → **Mode B loop:**
     ```
     run = start_ingestion_run(source, triggered_by, workflow_id, workflow_execution_id)
     for each doc:
       try:
         span = start_document_span(run, doc_id, source_url)
         parse → chunk → embed → upsert
         stamp trace_id + ingested_at + embedding_model on every chunk
         finalize_document_span(span, status=success, chunk_count=N)
         write ingestion_doc row (run_id=run.trace_id)
       except Exception as e:
         finalize_document_span(span, status=failed, failure_reason=str(e))
         write ingestion_doc row (status=failed, run_id=run.trace_id)
         log error, continue
     finalize_ingestion_run(run, attempted, succeeded, failed)
     ```
     Returns: `{run_id, status, doc_count_succeeded, doc_count_failed}`.

2. **Per-document error isolation** — mandatory in both modes. The document loop MUST NOT abort on a single document failure. Run-level status for Mode B: `success` = all docs succeeded; `partial` = mixed; `failed` = all failed or run could not start. Never derived from estimates — always from actual `ingestion_doc` rows.

3. **Rewire n8n RSS path** — `run_ingest.py` passes `source="n8n_rss"`, `workflow_id` and `workflow_execution_id` from n8n execution context via CLI args or env.

4. **Rewire manual CLI path** — passes `source="manual_cli"`, `triggered_by=<username/host>`. Bulk flag (`--bulk`) triggers Mode A. Single doc triggers Mode B.

5. **Expose for bootstrap** — `source="bootstrap_ui"` always Mode A. Importable by FastAPI endpoint (G1).

6. **Supersede** — confirm `supersede_by_family_id()` runs inside the document processing block, within the try/except, so a supersede failure is captured per-document not run-level.

7. **Guard rail** — `payload.py` raises if `trace_id` missing on upsert. Structural, not best-effort.

---

## Acceptance criteria

- Mode A: 1000-doc synthetic batch → 1000 `ingestion_doc` rows (run_id=null), 1000 Langfuse top-level traces, zero run envelope rows.
- Mode B: 10-doc synthetic batch → 1 `ingestion_run` row, 10 `ingestion_doc` rows with run_id populated, nested Langfuse spans.
- **Error isolation test (Mode A):** 3-doc batch, doc 2 raises exception → doc 1 and doc 3 succeed, doc 2 has `status=failed` + `failure_reason`, function returns without raising, remaining docs processed.
- **Error isolation test (Mode B):** Same pattern → run completes with `status=partial`.
- n8n path: `workflow_execution_id` populated in `ingestion_run`.
- Manual CLI now appears in `ingestion_doc` with correct source.
- Upsert without `trace_id` raises.
- `tests/api` + `tests/integration` + `tests/compliance` pass.

## Out of scope

No reingestion (G-T3). No bootstrap UI (G1) — only the importable hook.

## Commit / corrections

`Phase G-T2 step N — description`. Record mode-selection deviations in `CORRECTIONS.md`.
