# G-T4 — Post-Reingestion Quality Gate

**Type:** Verification / scripted audit · **Depends on:** G-T3 complete
**Gates:** G1, G2, G3 — none of the UI phases start until G-T4 exits green.
**Output:** Dated quality report stored at `docs/quality/corpus-quality-YYYY-MM-DD.md` — portfolio evidence and operational record.

---

## Objective

Verify the reingested corpus is complete, structurally sound, and trace-consistent before any UI is built on top of it. A UI demo built on a corrupt or incomplete corpus is a liability, not an asset.

---

## Script

Implement as `scripts/corpus_quality_check.py`. Runs standalone against the live PostgreSQL + Qdrant stack. Exits 0 on all-pass, non-zero on any mandatory failure.

Usage:
```
python scripts/corpus_quality_check.py --report docs/quality/corpus-quality-$(date +%F).md
```

---

## Checks

### 1. Corpus completeness
- Doc count per source (`ingestion_source` + agency) matches expected baseline (record expected counts at G-T3 close; compare here).
- Every document in `document_registry` has at least one corresponding chunk in Qdrant. Zero-chunk documents = fail.
- Every Qdrant chunk has a corresponding `doc_id` in the registry. Orphaned chunks = fail.

### 2. Chunk quality
- `clause_id` coverage rate per document — report % null per doc; flag any corpus document below 80% coverage (known issue: Annex 11 §4.1–4.8, Annex 15 chunks 7–12 from Task E).
- Chunk character length distribution: report mean, min, max, p5. Flag chunks under 50 chars as suspect.
- Scan chunk text for residual HTML/XML artefacts (`<`, `>`, `href=`, `xmlns`) — report count and sample.

### 3. Metadata completeness
Null-rate report across `document_registry` for every mandatory field. Mandatory = must be 0% null:
- `trace_id`, `ingestion_source`, `doc_type`, `document_family_id` (corpus docs only), `ingested_at`, `embedding_model`.

Advisory (report null rate, do not fail):
- `clause_id` (chunk level), `source_fetched_at`, `publication_date`.

### 4. Supersede chain integrity
- Every document with `document_family_id` set resolves to exactly one active version in the registry. Multiple active versions for same family = fail.
- No orphaned supersede references (document_family_id pointing to a non-existent doc_id).

### 5. Trace coverage
- Every chunk in Qdrant carries a `trace_id` in its payload. Null `trace_id` on any chunk = fail.
- Every `trace_id` on a chunk resolves to a row in `ingestion_doc`. Dangling reference = fail.
- **Mode A (bulk):** `ingestion_doc.run_id` is null for all bulk-ingested documents — this is correct, not an error. Do not flag null `run_id` as a problem for Mode A rows.
- **Mode B (RSS):** `ingestion_doc.run_id` must resolve to an `ingestion_run` row. Dangling FK = fail.
- **Failed document spans:** Query `ingestion_doc WHERE status = 'failed'` — report count and list all `doc_id` + `failure_reason`. Any failed spans = WARN (not fail — transient failures at scale are expected). Zero = PASS. Report must surface these so operator can decide whether to retry. Silent ignoring of failed spans is not acceptable.
- **Wipe completeness:** Confirm `ingestion_run` and `ingestion_doc` were empty before reingestion started (i.e. wipe_corpus.py ran cleanly). Check by comparing earliest `ingested_at` in `ingestion_doc` against the wipe timestamp logged by `wipe_corpus.py`.

### 6. Embedding sanity
- Spot-check: retrieve top-5 nearest neighbours for 3 known chunks (one Annex 11, one ICH Q9(R1), one FDA guidance). All top-5 should be same-document or closely related — flag if unrelated documents dominate.
- Flag any chunk with vector norm below 0.01 (near-zero embedding = likely embedding failure).

---

## Report format

The output `.md` file records:

- Run date + operator
- Ingestion run trace_ids covered
- Per-check result: PASS / WARN / FAIL with counts and sample rows for failures
- Summary table: N checks, N passed, N warned, N failed
- Overall verdict: GREEN (all mandatory pass) / RED (any mandatory fail)

GREEN verdict = G1 unblocked. RED = fix root cause, re-run G-T3 or targeted re-ingest, re-run G-T4.

---

## Acceptance criteria

- Script runs to completion without exception against live stack.
- Report file written to `docs/quality/` with correct date stamp.
- All mandatory checks PASS (GREEN verdict).
- Known issues (Annex 11 clause_id gaps from Task E) appear as WARN, not FAIL — they are tracked, not blocking.
- Script committed to repo; runnable by a fresh clone with standard dependencies.

---

## Portfolio note

This report is a direct answer to the QA director question: "How do you know the corpus is complete and accurate?" Keep every dated report — they form a corpus governance audit trail consistent with Annex 11 §4.8 (data quality) and §17 (archiving).

---

## Out of scope

No UI. No reingestion (G-T3). No fixes — if checks fail, root cause is addressed in G-T3 context, then G-T4 is re-run.

## Commit / corrections

`Phase G-T4 step N — description`. Attach report filename to commit message.
