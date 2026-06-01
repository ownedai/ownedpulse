# G1 — Bootstrap / Ingestion Page

**Type:** UI + API · **Depends on:** G-T3 complete (chunks carry trace_id)
**Design gate D-3:** Claude Design prototype + visual approval against ownedai brand BEFORE Claude Code build.

---

## Objective

First-install entry point: user selects ingestion scope, triggers the process, monitors progress live in-app, and ends with RSS automation activated. Same screen handles the "already initialized" re-run case.

## Design gate D-3 (resolve before build)

Produce in Claude Design, approve visually, then build:
- Scope-selection controls: corpus (on/off), FDA / ICH / EMA archives (each on/off). Months-back is **fixed at 24 for v1** (display as read-only info, not an input — per D-2).
- Live progress display driven by **SSE**: overall run status + per-document rows as they complete (doc_id, status, chunk_count).
- Terminal states: success summary, partial (with failed-doc list), failed.
- **n8n activation confirmation** as an explicit final state: "RSS automation: activated" — so the user sees ongoing ingestion is configured.
- "Already initialized" path: state-check result + explicit "re-run will wipe and reingest" confirmation control.

Brand: dark shell `#0F172A`, light content panel, Inter + JetBrains Mono. Reuse `ownedai-ui` components. Define `data-testid` attributes per `design-spec.md`.

## API tasks (FastAPI, port 8001)

1. **State-check endpoint** `GET /bootstrap/state` — returns `fresh` vs `initialized` by checking: registry row count > 0 AND n8n workflow active state via n8n REST API. This is the idempotency guard.

2. **Bootstrap trigger** `POST /bootstrap/run` — body: scope selection + `force` flag (required when state=initialized). Launches ingestion as a **FastAPI background task** calling the unified `ingest_documents(..., source="bootstrap_ui", triggered_by="bootstrap")` from G-T2. On `force`, performs wipe + reingest (reuse G-T3 logic, not a parallel implementation).

3. **Progress stream** `GET /bootstrap/progress/{trace_id}` — **SSE** endpoint emitting run + per-doc events from the live `ingestion_run`/`ingestion_doc` rows. (SSE chosen: one-directional, survives Cloudflare tunnel; WebSocket rejected.)

4. **n8n activation** `POST /bootstrap/activate-rss` — calls n8n REST API to activate the RSS workflow by ID. Idempotent: check active state first; if already active, return success without duplicate activation. Emit a first Langfuse trace on activation so observability is verifiable day one.

5. **Sequencing** — the run executes: (1) ingest selected archives + corpus, (2) activate RSS workflow, (3) return preflight/verification summary. Activation is step 2, surfaced as the final confirmation state in the UI.

## UI tasks (React + Tailwind, port 5173)

1. On load, call `/bootstrap/state`; branch fresh vs initialized.
2. Render approved D-3 layout; bind scope controls.
3. On submit, POST `/bootstrap/run`, then open SSE to `/bootstrap/progress/{trace_id}`; render per-doc rows live.
4. Render terminal state + n8n activation confirmation.
5. Initialized path: show confirm-to-wipe control; only sends `force=true` after explicit confirm.

## Acceptance criteria

- Fresh install: scope selection → traced ingestion → RSS activated, all visible in-app.
- SSE progress updates render per-doc in near-real-time through the Cloudflare tunnel.
- Re-run without `force` is refused; with `force` performs wipe + reingest exactly once (no duplicate active workflow).
- Activation is idempotent; a Langfuse trace exists post-activation.
- The bootstrap ingestion appears as a complete run→doc→chunk trace.
- `tests/api` + `tests/integration` + `tests/e2e` pass.

## Out of scope

Query UI (G2). Log pages (G3). Months-back as a user input (deferred post-v1).

## Commit / corrections

`Phase G1 step N — description`. Log any n8n REST API quirk in `CORRECTIONS.md`.
