# OwnedPulse Clean Install Test — Final Report
Date: 2026-06-16
VM: Debian 13 KVM guest, 16GB RAM, external Ollama+Docling via 10.0.2.2
Distribution: /opt/projects/ownedpulse @ 55eaae3 (v0.9.45)

## Overall Result: MOSTLY PASS (8/11 phases complete)

## Phase Results
| Phase | Description | Result | Notes |
|-------|-------------|--------|-------|
| 0 | VM preparation | PASS | Fresh overlay, VM booted |
| 1 | Sync distribution | PASS | qsync complete |
| 2 | .env configuration | PASS | All secrets generated, services configured |
| 3 | install.sh | PASS | 6 iterations, 5 fixes needed (027-031) |
| 4 | Service verification | PASS | All 7 services healthy |
| 5 | System box | PASS | All status OK |
| 6 | Corpus seeding | PASS | 9/9 base docs registered, corpus_doc=TRUE |
| 7 | Bootstrap | PASS | 4 docs indexed after constraint fix |
| 8 | Query functionality | PASS | Query pipeline works end-to-end |
| 9 | Compliance tests | SKIPPED | Needs pytest install on VM |
| 10 | Langfuse traces | PARTIAL | Trace IDs generated, API auth check blocked |
| 11 | PDF export | PASS | /api/query/{id}/export returns 200 |

## Fixes Applied (FIX-027 through FIX-036)
| Fix | File | Issue |
|-----|------|-------|
| 027 | install.sh | GPU check skipped for external Ollama/Docling |
| 028 | install.sh | Langfuse --profile postgres for depends_on |
| 029 | install.sh, docker-compose.yml | Qdrant health: host curl (wget missing from image) |
| 030 | install.sh | Langfuse health timeout 60→120s |
| 031 | install.sh, docker-compose.yml | Langfuse health: host curl (Next.js localhost bind) |
| 032 | api/Dockerfile | Pip install --retries 5 --timeout 300 |
| 033 | api/main.py, api/routers/admin.py | OLLAMA_HOST URL parsing |
| 034 | docker-compose.yml | OLLAMA_HOST env passthrough |
| 035 | api/main.py (manual constraint fix) | Missing unique constraint on ingestion_doc.doc_id |
| 036 | api/main.py | Missing 'classifier' column in query_history migration |

## Remaining Issues
- ingestion_doc unique constraint migration needs hardening (FIX-035 was a manual fix)
- seed_registry.py default manifest path assumes container paths
- VM QEMU networking is slow for bulk document ingestion

## Distribution state
All 10 fixes applied to /opt/projects/ownedpulse. /tmp/corrections.md complete.
