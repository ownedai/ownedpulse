# Changelog

## 1.1.0 (2026-10)

### Fixed
- `scripts/registry/seed_registry.py` restored. It was missing from the repository while the API still called it at startup and on reset, so a fresh install did not register the base corpus.
- `seed_registry.py` no longer falls back to a built-in default database password; it refuses to run if `POSTGRES_PASSWORD` is not set.
- Host ports and container-internal ports are now separate settings. Changing a host port no longer breaks connections between services.
- PostgreSQL user and database defaults are consistent across `docker-compose.yml`, `install.sh` and `.env.example`.
- The UI no longer hard-codes an allowed hostname; set `VITE_ALLOWED_HOSTS` instead.
- Corrected the phi4:14b-q8_0 download size shown by `install.sh`.
- A failed query is now visible. Previously the UI aborted at 60s and discarded the abort, showing a blank pane with no answer, no error and no spinner, while the API's own failure arrived later to a connection nobody was reading. The abort budget is 210s and an abort now reports a timeout.
- The API returns 504 with a message when the generation model does not respond within `OLLAMA_TIMEOUT`, instead of a bare 500.
- Failed queries are recorded. `persist_query` runs only after generation returns, so a query that timed out left no trace anywhere.
- One context size for every generation-model call. The classifier sent no `num_ctx` and so loaded the model's 16384 default while generation used 12288; Ollama keeps one runner per (model, context size), so each query evicted and reloaded a 17 GB model. Set `OLLAMA_NUM_CTX` to match every other client of a shared Ollama.
- `fda_drugs` ingests. Its configured `feed_type` was `rss`, which `fetch_feed()` did not handle, so it returned `None` and every run failed with "cannot unpack non-iterable NoneType object".
- `fda_guidance_catalogue` runs on the scheduler and manual paths. It returned an errors list where the caller expected a stats dict, failing every run with "list indices must be integers or slices, not str". Unknown feed types now raise with the type named rather than returning `None`.
- The generation model is loaded in the background at API startup, and `install.sh` waits for it, so the first query after starting no longer pays a multi-minute model load. Measured at 218s before, when another model had taken the GPU.
- Successful subprocess feed runs are recorded as `success` with their duration. They were written as `running` with `duration_ms = 0`, and the startup cleanup then rewrote every one of them to `error` with "Process was killed before run completed" — so the Run Log reported completed runs as failures.
- The UI query timeout is 300s, above the model-load path and the API's own `OLLAMA_TIMEOUT`.
- EMA publication dates are no longer stored with the month and day swapped. The feed publishes ISO 8601 and the date was parsed day-first, which reads `2026-09-10` as 10 September's *month* — 34.7% of EMA records were affected, and four landed in the future. Documents ingested by an earlier version keep their wrong dates until the corpus is reset.
- Citation counts include grouped markers. An answer citing `[3, 9]` had only its lone-style markers counted, so cited chunks were reported as not cited in the traceability panel, the citation payload and the PDF export.
- Base-corpus documents keep their manifest classification in chunk payloads. 21 CFR Part 11 and the EU GMP annexes were ingested as "guidance" because the payload type was derived from the canonical `doc_type`, which maps `regulation` and `annex` to `guidance`.
- Document classifications display and filter correctly across the UI. The query page, Corpus and Ingestions tables showed the canonical `doc_type`, which maps `regulation` and `annex` to `guidance`, so 21 CFR Part 11 and the EU GMP annexes read "Guidance"; they now prefer `document_type`. One shared label map replaces three per-page copies, the Corpus and query type filters gained Regulation, Annex and Q&A Guidance, and ingestion rows carry `document_type` so the Ingestions table can show it. The type filter previously offered only Guidance, Press Release and Reflection Paper.
- `OLLAMA_NUM_CTX` and `OLLAMA_TIMEOUT` are passed through to the API container; both were documented in `.env.example` but never forwarded, so setting either had no effect.

### Added
- `DOCLING_VARIANT=cpu`: run Docling on the CPU instead of the GPU (`docker-compose.docling-cpu.yml`).
- `query_history.status` and `query_history.error` columns, so a query that never produced an answer is recorded as `timeout` or `error` with its detail. Applied automatically on API start.
- `OLLAMA_NUM_CTX` and `OLLAMA_TIMEOUT` settings.
- Evaluation set, rubric, scoring scripts, result files and `eval/summarise.py`, which reproduces the README evaluation tables.
- Screenshots, CHANGELOG, SECURITY and CONTRIBUTING files, issue templates.

### Changed
- Container images pinned to tested versions: postgres 16.13, qdrant v1.19.1, ollama 0.35.1, docling-serve v1.35.0, langfuse 2.95.11.
- One-off maintenance scripts moved to `scripts/maintenance/`.
- Internal development notes removed from `docs/`.
- README rewritten: requirements, quick start, configuration, operations, troubleshooting, security and runtime model, evaluation method.
- Version set to 1.1.0 in the API and UI.

### Upgrading from 1.0.x
- The UI no longer allows `rp.*` hostnames by default. Set `VITE_ALLOWED_HOSTS` to the hostnames you use, or the UI answers `Blocked request. This host is not allowed` for anything but localhost and IP addresses. Add it to the `ownedpulse-ui` service environment.
- `OLLAMA_NUM_CTX` defaults to 12288. If the Ollama you point at is shared, every other client must request the same context size for the same model, or each will evict the other's loaded model.
- **Stored EMA publication dates and chunk document types written by earlier versions are wrong.** The date fix and the type fix apply at ingestion, so a corpus ingested by 1.0.x keeps the swapped dates and the collapsed `guidance` type. To repair it, reset the corpus and run Initial Load again:

  ```bash
  curl -X POST http://localhost:8001/api/admin/reset-corpus \
       -H 'Content-Type: application/json' -d '{"confirm": true}'
  # then Initial Load from the UI, or:
  curl -X POST http://localhost:8001/api/bootstrap/run \
       -H 'Content-Type: application/json' -d '{}'
  ```

  The reset empties the vector store and run history and re-registers the base corpus; downloaded documents are kept, and the next Initial Load re-ingests everything because an empty Qdrant collection is never treated as already ingested. See **Resetting the corpus** in the README.

### Repository
- The repository history was rewritten and the repository recreated on 2026-10-02 to remove an accidentally committed credential, which had already been rotated. If you cloned before that date, delete your clone and clone again.

## 1.0.x (2026-05 to 2026-07)

Initial public releases.
