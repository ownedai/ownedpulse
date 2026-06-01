# G2 — Query Page Redesign (Split-Screen Traceability)

**Type:** UI + API · **Depends on:** G-T3 complete (chunks carry trace_id)
**Design gate D-4:** Claude Design prototype + visual approval BEFORE build.

---

## Objective

Redesign the query page so a retrieved answer and the full provenance of every chunk that produced it are visible together: answer in the upper region, per-chunk traceability in the lower region, including a live Langfuse `trace_id` link per chunk.

## Design gate D-4 (resolve before build)

Decide and approve in Claude Design:
- Split proportions: answer region vs provenance region (and whether the split is fixed, draggable, or collapsible).
- Per-chunk provenance row layout — fields to show: `chunk_id`, `doc_id`, `clause_id`, `source_url`, `publication_date`, `ingested_at`, `embedding_model`, `trace_id` (rendered as a link to the Langfuse trace).
- Scroll/expand behaviour for **5–8 chunk answers** (most answers): provenance panel is scrollable with expandable rows, not a flat list. Decide collapsed vs expanded default.
- Citation ↔ chunk linkage: clicking a citation in the answer highlights/scrolls to its provenance row.
- Inline PDF source view (PDF.js) — retain from prior spec; decide whether it opens in the provenance region or a side panel.

Brand + `ownedai-ui` reuse; `data-testid` per `design-spec.md`. Honour null-field display rules from `design-spec.md` (e.g. clause_id may be null for RSS chunks).

## API tasks

1. **Query response shape** — extend the query endpoint so each retrieved chunk in the response carries the full provenance set above, read from Qdrant payload + registry join. Use `client.query_points()` (TI-5).
2. **Langfuse link construction** — return a resolvable Langfuse trace URL per chunk from its `trace_id` (construct from the Langfuse base URL + trace_id; do not hardcode per-environment host — read from config).
3. **Citation post-processor** — retain/adjust the existing FastAPI citation post-processor so answer citations map to chunk identifiers the UI can link to provenance rows.
4. **Two-path routing** — preserve CONTENT (semantic RAG) vs METADATA (Qdrant scroll) routing from UI Spec v1.1; provenance panel applies to CONTENT answers.

## UI tasks

1. Build approved D-4 split layout.
2. Render answer with clickable citations.
3. Render provenance panel: one expandable row per chunk with the full field set; `trace_id` as a link opening the Langfuse trace in a new tab.
4. Wire citation→row highlight/scroll.
5. Integrate inline PDF view per D-4 decision.
6. Retain query session export/print (Annex 11 §8.1, TI-10) — export must include answer + all chunk provenance + trace_ids.

## Acceptance criteria

- For a CONTENT query, every retrieved chunk shows complete provenance including a working Langfuse trace link.
- 5–8 chunk answers render without layout breakage; provenance scrolls/expands per D-4.
- Clicking a citation locates its chunk row.
- Export contains answer + full per-chunk provenance + trace_ids.
- Null fields display per `design-spec.md` rules (no raw "None"/HTML leakage — a prior v1 failure mode).
- `tests/api` + `tests/integration` + `tests/e2e` + `tests/compliance` pass.

## Out of scope

Bootstrap (G1). Log pages (G3).

## Commit / corrections

`Phase G2 step N — description`. Log Langfuse URL/link issues in `CORRECTIONS.md`.
