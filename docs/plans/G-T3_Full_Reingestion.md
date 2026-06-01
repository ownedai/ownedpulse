# G-T3 — Full Reingestion Under New Schema

**Type:** Data migration · **Depends on:** G-T1 + G-T2 merged and tested
**Design gate:** D-2 — confirm RSS archive default window before running (recommend 24 months, fixed for v1).
**Run TI-9 first:** backup restore test (Qdrant + PostgreSQL) so there is a verified rollback point before wiping.

---

## Objective

Wipe `knowledge_base` (Qdrant) and the registry, then reingest the full archive + corpus through the unified traced path so every chunk carries `trace_id` and the schema gaps resolved by reingestion are closed.

## Prerequisites

- G-T1 + G-T2 green.
- TI-9 backup restore test passed and documented with date — this is the rollback point.
- D-2 decided: archive window = 24 months (or override).

## Tasks

1. **Pre-flight** — run `regpulse-preflight.sh` (dirs, Docker, Qdrant, PostgreSQL, Ollama model, ports, ai-stack network). Abort if any check fails.

2. **Backup + verify** — confirm TI-9 restore test is current. Snapshot current Qdrant collection + registry to the restic chain before destructive steps.

3. **Atomic wipe** — run `scripts/wipe_corpus.py --confirm`. This executes in sequence:
   1. Delete Langfuse traces tagged `regpulse` via Langfuse API
   2. Truncate `ingestion_doc`
   3. Truncate `ingestion_run`
   4. Truncate `document_registry`
   5. Delete all points from Qdrant `knowledge_base` (preserve collection + index config)
   
   Do NOT drop/recreate the collection — preserve the 1024-dim Cosine config and HNSW settings. Only wipe points. If `wipe_corpus.py` reports any partial failure, resolve before proceeding.

4. **Reingest corpus** — the 7 target regulatory docs through the unified path, `source="manual_cli"`, `bulk=False` → **Mode B** (small batch, run envelope appropriate). Verify clause_id quality preserved.

5. **Reingest RSS archive** — via the historical backfill path (Phase_F0: openFDA records + FDA HTML + EMA + ICH), bounded to the D-2 window. All through the traced entry point with `source="manual_cli"`, `bulk=True` → **Mode A** (per-document traces, no run envelope). At 1000+ documents, Mode B would produce an unusable single PARTIAL row in Run Log.

6. **Fix HNSW build** — the prior load left `indexed_vectors_count=0` at 12,197 points. Set `indexing_threshold` appropriately and/or trigger optimizer; verify `indexed_vectors_count > 0` and status green after load. Document the resolution.

7. **Resolve-on-reingest verification** — confirm these are now populated (no longer None): `document_family_id` (TI-1), `doc_type` at ingest (TI-2), `last_indexed_at` (TI-3), `source_fetched_at` (TI-6). Confirm all retrieval code uses `client.query_points()` (TI-5).

8. **Trace integrity audit** — query: count chunks where `trace_id IS NULL` → must be 0. Every chunk resolves to an `ingestion_run` row. Spot-check 5 chunks end-to-end: chunk → trace_id → run → Langfuse trace.

## Decision D-2

RSS archive window for v1: **24 months fixed** (recommended). Not yet a UI parameter — the bootstrap page (G1) will offer agency selection but a fixed lookback for v1. Override here if different.

## Acceptance criteria

- 0 chunks with null `trace_id`.
- `indexed_vectors_count > 0`, collection status green.
- TI-1/2/3/5/6 verified resolved (documented).
- Re-run of corpus ingestion is idempotent (supersede works, no duplicate active chunks).
- All 6 canonical verification queries still PASS/PASS-PARTIAL post-reingestion.
- Reingestion run itself appears as a complete trace in Langfuse + registry.

## Out of scope

No UI. No bootstrap endpoint (G1 builds it; reingestion here is operator-run via the unified function).

## Commit / corrections

`Phase G-T3 step N — description`. Document HNSW resolution and the reingestion run trace_id in `CORRECTIONS.md` / run log.
