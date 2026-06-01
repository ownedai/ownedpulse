# Regpulse — Traceability & Ingestion Rework: Overview Plan

**Status:** Approved for build
**Target repo location:** `/opt/projects/regpulse/docs/plans/`
**Supersedes:** original Phase G scope (UI build only). This rework re-scopes Phase G into a trace-infrastructure block (G-T*) followed by three UI surfaces (G1–G3).
**Authoritative references (do not duplicate, defer to these for existing names):**
`CLAUDE.md` v2 (field names, PostgreSQL schema, data quality rules), `design-spec.md` (CSS vars, component state, null display, data-testid, Annex 11 §8.1).

---

## 1. Why this rework exists

The differentiator for regpulse is **inspector-grade traceability** — a retrieved answer traceable back to the exact ingestion event that produced each chunk, regardless of how that chunk was ingested (RSS via n8n, manual CLI, or first-install bootstrap). No cloud RAG vendor can match this on the client's own infrastructure.

Three gaps block that claim today:
1. Langfuse traces wrap only the n8n RSS path; manual ingestions are untraced (TI-19).
2. `trace_id` is not stored per chunk, so a retrieved answer cannot be linked back to its ingestion run (TI-20).
3. The UI exposes provenance only via export, not as a primary, on-screen surface.

This rework closes all three and redesigns the three UI surfaces that present ingestion and query provenance.

---

## 2. Phase map & dependency chain

```
G-T1 Trace schema + canonical spec   (backend / data)   ── must precede ──┐
G-T2 Ingestion path unification      (backend)           ── must precede ──┤
G-T3 Full reingestion                (data migration)    ── must precede ──┤
G-T4 Post-reingestion quality gate   (scripted audit)     ── must precede ──┘
                                                                           │
        ┌──────────────────────────────────────────────────────────────────┘
        ▼
G1  Bootstrap / ingestion page       (UI + API)   ─┐
G2  Query page redesign              (UI + API)    ├─ independent of each other;
G3  Ingestion log pages redesign     (UI + API)   ─┘  all depend on G-T3 complete
```

**Hard rule:** No UI phase starts until G-T4 exits GREEN. G-T4 gates all three UI phases (G1/G2/G3), not just G1. Building the query split-screen against un-traced chunks produces a UI that demos broken provenance.

| Phase | Type | Depends on | Claude Code plan |
|---|---|---|---|
| G-T1 | Schema + spec | CLAUDE.md v2 + existing `run_log`/`run_id` reconciliation | `G-T1_Trace_Schema_and_Spec.md` |
| G-T2 | Backend | G-T1 | `G-T2_Ingestion_Path_Unification.md` |
| G-T3 | Data migration | G-T2 | `G-T3_Full_Reingestion.md` |
| G-T4 | Quality gate | G-T3 | `G-T4_Post_Reingestion_Quality_Gate.md` |
| G1 | UI + API | G-T4 GREEN + design gate | `G1_Bootstrap_Ingestion_Page.md` |
| G2 | UI + API | G-T3 + design gate | `G2_Query_Page_Redesign.md` |
| G3 | UI + API | G-T3 + design gate | `G3_Ingestion_Log_Redesign.md` |

---

## 3. Design-decision gates

Backend phases (G-T1/2/3) carry **one data-design decision** each, resolved in-plan — no visual design needed.

The three UI phases each require a **Claude Design gate before Claude Code build**, using the established workflow (Claude Design prototype → visual approval against ownedai brand → then build). Brand is locked: dark shell `#0F172A`, light content panel, Inter + JetBrains Mono, "owned" navy / "ai" accent blue.

| Gate | Phase | Decision to make at the gate | Resolved? |
|---|---|---|---|
| D-1 | G-T1 | ~~Lock canonical trace field names~~ **RESOLVED** — `ingestion_run` + `ingestion_doc` dedicated PostgreSQL tables; registry holds `trace_id` per chunk; Langfuse mirrors for observability, PostgreSQL is queryable truth. Field names locked in G-T1. No renames without full reingestion. | **Resolved** |
| D-2 | G-T3 | Confirm RSS archive default window (recommend 24 months) — fixed for v1, not a UI parameter yet | Decide before reingestion |
| D-3 | G1 | Bootstrap screen layout: scope-selection controls, progress display (SSE-driven), n8n-activation confirmation state, "already initialized" path | **Claude Design gate before build** |
| D-4 | G2 | Split-screen proportions (answer vs provenance), per-chunk provenance row layout, Langfuse trace_id link treatment, scroll/expand behaviour for 5–8 chunk answers | **Claude Design gate before build** |
| D-5 | G3 | Trace-centric log: run-level row design, drill-down to doc-level spans, status/error visual language | **Claude Design gate before build** |

**Locked decisions (from prior discussion):**
- **D-1 trace storage: dedicated PostgreSQL `ingestion_run` + `ingestion_doc` tables.** Langfuse mirrors for observability; PostgreSQL is the queryable record of truth. Registry holds `trace_id` per chunk as FK. No renames without full reingestion.
- **Two-mode trace architecture:** Mode A (bulk/initial ingestion 1000+ docs) — one Langfuse trace per document, no run envelope, `ingestion_doc.run_id=null`. Mode B (RSS/small batch) — one `ingestion_run` envelope, document spans within it. Mode A is mandatory for initial ingestion — a single envelope over 1000+ documents produces an unusable Run Log (observed in current state).
- **Corpus wipe is atomic:** `wipe_corpus.py --confirm` deletes in sequence: Langfuse traces (regpulse-tagged) → `ingestion_doc` → `ingestion_run` → `document_registry` → Qdrant points. Partial state is never acceptable.
- Progress monitoring transport: **SSE** (one-directional, survives Cloudflare tunnel; WebSocket rejected as fragile through tunnel).
- Idempotency: bootstrap does a **state check first** (registry rows + n8n workflow active state via API); if initialized, explicit "re-run will wipe and reingest" confirm path.
- `workflow_execution_id` stored in PostgreSQL registry per document (not Langfuse-only).
- `trace_id` stored in Qdrant payload **and** registry per chunk.

---

## 4. Canonical ingestion trace (the contract every path must satisfy)

This is the spec G-T1 implements and G-T2 enforces across all trigger types. Full field-level detail in `G-T1_Trace_Schema_and_Spec.md`.

- **Trace level** (one per ingestion run → one Langfuse trace): `trace_id`, `ingestion_source`, `triggered_by`, `workflow_id`, `workflow_execution_id`, `started_at`, `completed_at`, `status`, `doc_count_attempted/succeeded/failed`, `error_summary`.
- **Document level** (one Langfuse span per doc): `span_id`, `doc_id`, `source_url`, `fetched_at`, `parsed_at`, `chunk_count`, `embedding_model`, `status`, `failure_reason`.
- **Chunk level** (Qdrant payload + PostgreSQL, not Langfuse): `chunk_id`, `doc_id`, `trace_id`, `ingested_at`, `embedding_model` + version.

`ingestion_source` enum: `n8n_rss | manual_cli | bootstrap_ui` (extensible).

---

## 5. Effort & schedule impact (honest flag)

Original Phase G build estimate: 37–52h. This rework roughly doubles it (trace retrofit + full reingestion + two new UI surfaces + log redesign + three Claude Design gates).

This is **high-leverage, not scope creep** — traceability is the single capability no cloud vendor matches. But the M1f early-September target slips unless something else is cut. Decide the trade at the G-T3 → G1 boundary, not at the deadline.

Rough sub-estimates (conservative; actual pace tends faster):
- G-T1: 6–9h · G-T2: 5–8h · G-T3: 4–7h (plus reingestion runtime) · G1: 14–20h · G2: 16–22h · G3: 8–12h · Design gates D-3/4/5: 4–6h each.

---

## 6. Tracked-item reconciliation

⚠️ **Schema reconciliation required before G-T1 builds anything:** CLAUDE.md shows `run_log` table and `document_registry.run_id` FK were already implemented (2026-05-29). These may partially or fully cover the `ingestion_run`/`trace_id` concepts. G-T1 task 0 reconciles before any migration is written. Do not assume the plan tables are new — they may be extensions of existing ones.

This rework closes/touches: **TI-19** (trace all ingestion paths — G-T2), **TI-20** (trace_id storage — G-T1), and naturally resolves during reingestion: **TI-1** (document_family_id), **TI-2** (doc_type at ingest), **TI-3** (last_indexed_at), **TI-5** (query_points migration), **TI-6** (source_fetched_at). **TI-9** (backup restore test) should run immediately before G-T3 reingestion so there is a verified rollback point.

---

## 7. Conventions (all phases)

- Commit: `Phase <id> step N — description`. Maintain `CORRECTIONS.md` for every deviation from plan.
- Field names are authoritative in `CLAUDE.md` v2 — Claude Code reconciles new fields against it, never invents.
- Qdrant access: `client.query_points()`, never deprecated `client.search()` (TI-5).
- Embedding: `mxbai-embed-large` (1024-dim). Classification: `phi4:14b-q8_0`. Collection: `knowledge_base`. Chunk ID: deterministic `MD5(doc_id|version|chunk_idx) → UUID`.
- Run test suite per existing order (fast → integ → e2e → all) at each phase gate.
