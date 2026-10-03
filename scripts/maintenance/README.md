# Maintenance scripts

One-off and diagnostic tools. None of these run as part of ingestion or
serving — run them by hand when repairing or auditing an existing corpus.

`./scripts` is mounted into the api container at `/opt/scripts`, so every
script below can be run with `docker exec` while the stack is up. All of them
read the same PostgreSQL, Qdrant and Ollama connection settings as the api
service, which are already present in the container environment.

| Script | Purpose | Run |
|---|---|---|
| `data_quality_gate.py` | Runs 15 corpus integrity checks (Qdrant/PostgreSQL consistency, chunk vocabulary, supersede links, Annex 11 clauses). Exits 1 if any check fails. | `docker exec ownedpulse-api python3 /opt/scripts/maintenance/data_quality_gate.py [--verbose]` |
| `check_chunk_consistency.py` | Compares the Qdrant collection against the PostgreSQL `chunks` table and reports missing points, status mismatches and per-document count deltas. Exits 1 on any inconsistency. | `docker exec ownedpulse-api python3 /opt/scripts/maintenance/check_chunk_consistency.py` |
| `patch_qdrant_payloads.py` | Backfills document-level metadata (`document_title`, `issuing_body`, `document_version`, `publication_date`, …) into chunk payloads for the seed documents that predate the current payload schema. | `docker exec ownedpulse-api python3 /opt/scripts/maintenance/patch_qdrant_payloads.py` |
| `backfill_issuing_body.py` | Fills in empty `issuing_body` values on RSS-ingested chunks, deriving the value from the `feed_id` prefix when the document registry has none. | `docker exec ownedpulse-api python3 /opt/scripts/maintenance/backfill_issuing_body.py [--dry-run]` |
| `backfill_ti7_version.py` | Re-extracts `document_version` from landing pages with the structured extractor and writes it to both PostgreSQL and Qdrant. Does not re-run Docling, chunking or embedding. | `docker exec ownedpulse-api python3 /opt/scripts/maintenance/backfill_ti7_version.py` |

`backfill_issuing_body.py` imports `lib.db` from the api package, so it also
needs the repository checkout on `sys.path` — the script resolves that itself
relative to its own location.
