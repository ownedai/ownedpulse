# Changelog

## 1.1.0 (2026-10)

### Fixed
- `scripts/registry/seed_registry.py` restored. It was missing from the repository while the API still called it at startup and on reset, so a fresh install did not register the base corpus.
- `seed_registry.py` no longer falls back to a built-in default database password; it refuses to run if `POSTGRES_PASSWORD` is not set.
- Host ports and container-internal ports are now separate settings. Changing a host port no longer breaks connections between services.
- PostgreSQL user and database defaults are consistent across `docker-compose.yml`, `install.sh` and `.env.example`.
- The UI no longer hard-codes an allowed hostname; set `VITE_ALLOWED_HOSTS` instead.
- Corrected the phi4:14b-q8_0 download size shown by `install.sh`.

### Added
- `DOCLING_VARIANT=cpu`: run Docling on the CPU instead of the GPU (`docker-compose.docling-cpu.yml`).
- Evaluation set, rubric, scoring scripts, result files and `eval/summarise.py`, which reproduces the README evaluation tables.
- Screenshots, CHANGELOG, SECURITY and CONTRIBUTING files, issue templates.

### Changed
- Container images pinned to tested versions: postgres 16.13, qdrant v1.19.1, ollama 0.35.1, docling-serve v1.35.0, langfuse 2.95.11.
- One-off maintenance scripts moved to `scripts/maintenance/`.
- Internal development notes removed from `docs/`.
- README rewritten: requirements, quick start, configuration, operations, troubleshooting, security and runtime model, evaluation method.
- Version set to 1.1.0 in the API and UI.

### Repository
- The repository history was rewritten and the repository recreated on 2026-10-02 to remove an accidentally committed credential, which had already been rotated. If you cloned before that date, delete your clone and clone again.

## 1.0.x (2026-05 to 2026-07)

Initial public releases.
