
## FIX-027: Skip GPU check when OLLAMA_MODE=external and DOCLING_MODE=external

**File:** /opt/projects/ownedpulse/install.sh
**Phase:** 3
**Problem:** install.sh failed with "No NVIDIA GPU detected" on test VM which has no GPU.
The VM uses ai-node's external Ollama and Docling via 10.0.2.2.
**Root cause:** GPU check was unconditional — didn't account for external service mode.
**Fix:** Wrapped GPU check in conditional: skip nvidia-smi and nvidia-container-toolkit
checks when both OLLAMA_MODE and DOCLING_MODE are "external".
**Verified:** pending re-run

## FIX-028: Langfuse start fails with "depends on undefined service postgres"

**File:** /opt/projects/ownedpulse/install.sh
**Phase:** 3
**Problem:** `docker compose --profile langfuse up -d langfuse` failed:
"service 'langfuse' depends on undefined service 'postgres': invalid compose project"
**Root cause:** langfuse has `depends_on: postgres` in docker-compose.yml, but only
the langfuse profile was activated. Postgres was running but its profile wasn't enabled
in the compose command, so docker compose couldn't see it.
**Fix:** Changed to `--profile postgres --profile langfuse` — includes postgres
profile to satisfy the dependency chain.
**Verified:** pending re-run

## FIX-029: Qdrant health check fails — wget not in qdrant image

**File:** /opt/projects/ownedpulse/install.sh, /opt/projects/ownedpulse/docker-compose.yml
**Phase:** 3, 5
**Problem:** Qdrant health check in both install.sh and docker-compose.yml used `wget`
inside the container. qdrant/qdrant:latest has no wget, curl, or busybox.
**Root cause:** The earlier "fix" that changed host curl → docker exec wget was based
on a different Qdrant image version or was never tested on a truly clean install.
**Fix:**
- install.sh: changed back to `curl -sf http://localhost:${QDRANT_PORT:-6333}/healthz` (host-side)
- docker-compose.yml: removed health check entirely (host verifies Qdrant via mapped port)
**Verified:** pending re-run

## FIX-030: Langfuse health check timeout at 60s — too short for first-start migrations

**File:** /opt/projects/ownedpulse/install.sh
**Phase:** 3, 5
**Problem:** Langfuse health check timed out at 60s. Container was still running database
migrations on first start (Next.js app bootstrapping with ~30 migrations).
**Root cause:** First-start migrations take ~90s. Timeout was set to 60s.
**Fix:** Increased timeout from 60 to 120 seconds.
**Verified:** pending re-run

## FIX-031: Langfuse health check fails — Next.js binds to Docker network IP, not localhost

**File:** /opt/projects/ownedpulse/install.sh, /opt/projects/ownedpulse/docker-compose.yml
**Phase:** 3, 5
**Problem:** Langfuse internal health checks using `wget http://localhost:3000` failed
with "Connection refused". Host curl to port 3001 worked fine.
**Root cause:** Next.js inside the langfuse container binds to the Docker network
interface (172.x.x.x) but NOT to 127.0.0.1. wget to localhost from inside the
container gets connection refused.
**Fix:**
- install.sh: changed to host-side `curl -sf http://localhost:${LANGFUSE_PORT:-3001}/api/public/health`
- docker-compose.yml: removed health check entirely (same as qdrant fix)
**Verified:** pending re-run

## FIX-032: Pip install times out during Docker build — QEMU network flaky

**File:** /opt/projects/ownedpulse/api/Dockerfile
**Phase:** 3, Step 8
**Problem:** `pip install --no-cache-dir -r requirements.txt` failed with
"ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org', port=443):
Read timed out." QEMU user-mode networking can drop connections during large downloads.
**Root cause:** No retries on pip install. Single transient failure kills the entire build.
**Fix:** Added `--retries 5 --timeout 120` to pip install command.
**Verified:** pending re-run

## FIX-033: OLLAMA_HOST URL parsing — handle both bare hostnames and full URLs

**File:** /opt/projects/ownedpulse/api/main.py, /opt/projects/ownedpulse/api/routers/admin.py
**Phase:** 4
**Problem:** API reported Ollama status "error" — "[Errno -2] Name or service not known".
docker-compose hardcoded `OLLAMA_HOST: ownedpulse-ollama`, but the VM uses external Ollama
at `http://10.0.2.2:11434`. The API code constructed `http://{OLLAMA_HOST}:{OLLAMA_PORT}`
which breaks if OLLAMA_HOST is already a full URL (`http://http://10.0.2.2:11434:11434`).
**Root cause:** API code didn't parse OLLAMA_HOST for existing scheme/port.
**Fix:** Added urlparse-based parsing at module level: if OLLAMA_HOST contains "://",
extract hostname and port; otherwise use as bare hostname. Removed duplicate OLLAMA_BASE
definitions inside functions.
**Verified:** pending restart

## FIX-034: docker-compose OLLAMA_HOST must allow .env override for external mode

**File:** /opt/projects/ownedpulse/docker-compose.yml
**Phase:** 4
**Problem:** docker-compose hardcoded `OLLAMA_HOST: ownedpulse-ollama`, which works
only for bundled mode. When OLLAMA_MODE=external and OLLAMA_HOST is set in .env to
the external URL, the hardcoded value overrode it.
**Root cause:** During the test-machine sync, we changed the OLLAMA_HOST from an
env-var-pass-through to a hardcoded value, assuming bundled mode only.
**Fix:** Changed to `${OLLAMA_HOST:-ownedpulse-ollama}` — passes through .env value
when set, defaults to bundled service name otherwise.
**Verified:** pending restart
**Additional fix for FIX-033:** Three occurrences in admin.py still used
`f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"` directly instead of OLLAMA_BASE.
Replaced with `f"{OLLAMA_BASE}/api/tags"`.

## FIX-035: Missing unique constraint on ingestion_doc.doc_id — ingestion upserts fail

**File:** Migration 001_ingestion_trace.up.sql — unique constraint was in the SQL file
but not applied during install.sh because the migration runs via psql and the DO block
may not have been executed correctly.
**Phase:** 7
**Problem:** All 31+ ingestion attempts failed with "InvalidColumnReference: there is no
unique or exclusion constraint matching the ON CONFLICT specification."
**Root cause:** The `ingestion_doc_doc_id_unique` UNIQUE constraint on
`ingestion_doc(doc_id)` was missing. The trace_emitter.py uses ON CONFLICT (doc_id)
which requires this constraint. The 001 migration DO block didn't apply it.
**Fix:** Added the constraint manually: `ALTER TABLE ingestion_doc ADD CONSTRAINT
ingestion_doc_doc_id_unique UNIQUE (doc_id);`. Also cleared error entries from
ingestion_state and restarted bootstrap.
**Verified:** Yes — ingestion now succeeds, 4 docs indexed

## FIX-036: query_history.persistence fails — missing 'classifier' column migration

**File:** /opt/projects/ownedpulse/api/main.py
**Phase:** 8
**Problem:** Error: "persist_query failed: column 'classifier' of relation 'query_history'
does not exist". Query results were not being saved to query_history.
**Root cause:** The 'classifier' column was used in INSERT statements but was never
added to the migrations list in init_db(). The schema wasn't migrated.
**Fix:** Added ("classifier", "TEXT") to the migrations list in init_db().
**Verified:** pending restart + re-query
