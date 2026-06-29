# Phase H Readiness Report
**Date:** 2026-06-03  
**Auditor:** Claude Code (automated)  
**Plan ref:** CLAUDE.md § Phase H Completion Criteria

---

## Overall Verdict

**NOT READY** — 5 blockers across two categories: GitHub release blockers (4) and demo video blockers (1).

---

## Checklist

| Item | Status | Notes |
|---|---|---|
| README.md present | **FAIL** | Absent — `/opt/projects/ownedpulse/README.md` does not exist |
| GAMP 5 statement present | **FAIL** | Not found in any docs file |
| Intended Use Boundary referenced | **FAIL** | Not found in any docs file |
| .gitignore present and correct | PASS | Excludes `.env`, `__pycache__`, `node_modules`, `ui/design-handoff/` |
| No hardcoded credentials/paths | **FAIL** | `api/lib/ingest_documents.py` lines 54–60: hardcoded PG password `b4e74f2...`, hardcoded `localhost` fallbacks, hardcoded `/opt/scripts` path. Also: `docker-compose.yml` has Langfuse keys in plaintext |
| docker-compose one-command startup | PARTIAL | Two separate compose files (`/opt/docker-compose/ownedpulse-api/` and `ownedpulse-ui/`). No single top-level `docker-compose.yml` in repo root. Also: compose files reference `context: /opt/projects/ownedpulse/api` (absolute host path — breaks on fresh clone) |
| .env.example present | **FAIL** | Absent — no `.env.example` or `.env.template` in repo |
| bootstrap_corpus.sh present | **FAIL** | Absent — no `bootstrap_corpus.sh` or equivalent |
| bootstrap_corpus.sh handles clean slate | **FAIL** | N/A (file absent) |
| Task E complete (Annex 11 §4.1–4.8) | **FAIL** | 21 chunks, clause_id covers only top-level sections (`1`–`17`). §4.x sub-clauses 4.1–4.8 are absent — all content is aggregated in clause_id=`4`. No sub-clause promotion script found. |
| Task E complete (Annex 15 sub-headings) | WARN | 34 chunks, 30 with clause_id, 4 null. Top-level sections only (1–4, 6–12). No section 5 present. Preamble chunks lack clause_id. Acceptable for demo. |
| chunk_status verified | WARN | 3 values in corpus: `active` (majority), `superseded` (88 ICH-Q9 chunks — correct), `final` (65 FDA drugs docs — `other` doc_type, not harmful but inconsistent with expected `active`) |
| All 6 demo queries pass | PASS | All 6 return non-empty answers with correct routing. See detail below. |
| Supersede demo (D-1) working | PASS | Query 2 ("Summarise ICH Q9(R1) changes") returns `supersede_context=True` |
| UI accessible | PASS | `http://localhost:5173` → HTTP 200 |
| API accessible | PASS | `http://localhost:8001/api/health` → `{"status":"ok","qdrant":"ok","postgres":"ok","ollama":"ok","langfuse":"ok"}` |

---

## Demo Query Results (Check 7)

| # | Query | Path | Citations | Answer | supersede_context | Status |
|---|---|---|---|---|---|---|
| D-1 | What are the Annex 11 requirements for audit trails? | CONTENT | 8 | yes | no | PASS |
| D-2 | Summarise ICH Q9(R1) changes from the 2005 version. | CONTENT | 8 | yes | **yes** | PASS |
| D-3 | What FDA guidance applies to computerised system validation? | CONTENT | 8 | yes | no | PASS |
| D-4 | How many EMA guidelines were published in the last 90 days? | METADATA | 0 | yes | no | PASS (0 is correct) |
| D-5 | What is the current ICH Q9 version? | METADATA | 567 | yes | no | PASS (full registry scroll) |
| D-6 | List all FDA press releases related to data integrity. | METADATA | 16 | yes | no | PASS |

All 6 queries routed correctly. No errors.

---

## Blockers for Demo Video

| # | Item | Detail |
|---|---|---|
| B-DV1 | **Task E: Annex 11 §4.1–4.8 sub-clause promotion incomplete** | The Annex 11 demo query ("What are the Annex 11 requirements for audit trails?") will retrieve chunks with clause_id=`4` (all of Section 4), not individual clause_id=`4.1`, `4.2`, etc. This means the Provenance drawer cannot show specific clause-level citations. The demo video is intended to demonstrate audit trail traceability — citing §4.8 specifically is essential for the pharma QA director audience. |

---

## Blockers for GitHub Release

| # | Item | Detail |
|---|---|---|
| B-GH1 | **README.md absent** | Repo has no README. GitHub release requires: project description, prerequisites, quick-start, intended use, GAMP 5 categorisation statement, architecture overview. |
| B-GH2 | **GAMP 5 categorisation statement missing** | No GAMP 5 / Category 5 / intended use declaration exists in any doc. Required for pharma portfolio credibility. |
| B-GH3 | **Hardcoded credentials in source** | `api/lib/ingest_documents.py` line 54 contains the production PG password in plaintext as a default fallback. `docker-compose.yml` contains Langfuse API keys in plaintext. Must be removed before public repo. |
| B-GH4 | **No .env.example and no top-level docker-compose** | A fresh clone has no working startup path. The compose files are outside the repo (`/opt/docker-compose/`), reference absolute host paths, and contain hardcoded keys. A self-contained `docker-compose.yml` + `.env.example` in the repo root is required for public release. |

---

## Recommended Next Actions

Priority order:

1. **Task E — Annex 11 sub-clause promotion** *(demo video blocker)*  
   Implement sub-clause splitting in the ingestion path for EU-GMP-Annex11 so §4.1–§4.8 each get distinct chunk_id and clause_id. Re-ingest EU-GMP-Annex11 only (no full corpus wipe needed). This unblocks the demo video.

2. **Remove hardcoded credentials** *(GitHub blocker, security)*  
   In `api/lib/ingest_documents.py`, remove the default fallback PG password (lines 54, 59). All credentials must come from env vars only. Move Langfuse keys out of docker-compose into `.env` (gitignored).

3. **Write README.md** *(GitHub blocker)*  
   Sections: project description, intended use, GAMP 5 Category 5 statement, prerequisites, quick-start (docker-compose), architecture diagram reference, demo queries, license.

4. **Write .env.example** *(GitHub blocker)*  
   All required env vars with placeholder values: `POSTGRES_PASSWORD`, `HF_TOKEN`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `QDRANT_HOST`, `OLLAMA_HOST`.

5. **Create top-level docker-compose.yml** *(GitHub blocker)*  
   A single `docker-compose.yml` at repo root that brings up `ownedpulse-api` + `ownedpulse-ui`. Use relative build contexts. Join `ai-stack` network. Load credentials from `.env`.

6. **Write bootstrap_corpus.sh** *(recommended for demo)*  
   Script to initialise Qdrant collection + PostgreSQL tables + ingest seed corpus from a clean slate. Idempotent. Documents that the bootstrap UI page (G1) already handles this interactively — the script is a CLI fallback for headless setup.

7. **Investigate chunk_status=`final`** *(low priority)*  
   65 FDA drug chunks have `chunk_status=final` instead of `active`. These are `doc_type=other` docs and do not surface in filtered queries. Investigate whether this is a valid terminal state or a stale value from a pre-G-T3 ingestion path. No user-visible impact confirmed.

---

## Summary

- **Demo video:** 1 blocker (Task E Annex 11 sub-clauses). All 6 queries pass. Supersede demo works. UI and API are up.
- **GitHub release:** 4 blockers (README, GAMP 5 statement, credentials, docker-compose/env.example). No blocker is technically complex — all are documentation and configuration work.
- **Estimated effort:** Task E (half day). README + docs (half day). Credentials + docker-compose + .env.example (2 hours). Total: ~1.5 days.
