# Phase H Completion Criteria

What "done" means for Phase G → H handoff:

- All 6 verification queries pass with correct routing
- query_history persists to PostgreSQL — verified via direct DB query
- Export endpoint returns full provenance (JSON + PDF) — both formats verified
- Theme toggle works and persists across browser sessions
- /history page lists queries with working Load action
- Cited vs uncited chunks visually distinguished
- Superseded ICH Q9 (2005) shows amber badge with link to Q9(R1) (2023)
- Langfuse trace shown in SourceDrawer Trace tab (not separate panel)
- Audit footer visible on every query result
- doc_type filter works — `document_type` field used, hyphenated values
- All tooltips present per spec
- UI v3 redesign complete — no duplicate logo, no push-layout, nav items present
- /corpus page (Corpus Registry) — table loads, rows clickable
- /corpus/:docId (Document Detail) — metadata, hash comparison, chunk list, supersede chain
- /corpus/runs (Run Log) — runs list, expandable rows show ingested docs
- /admin page — all 4 panels functional (health, feeds toggle, trigger, model)
- DB migrations all applied — confirmed via verification SQL in extension_brief §8
- fetch_feed.py writes run_log lifecycle — manual trigger creates run_log row
- active_llm_model read from system_config per query (not static constant)
- `docker-compose up` brings both containers from clean state on a fresh ai-node clone
- Test suite passes — `bash tests/run_tests.sh all` zero failures
- CORRECTIONS.md documents every divergence with reasons
- README documents setup and demo procedure
- Repository ready for GitHub release (private → public on Phase H release)

---

## Verification Queries

These six must all return correct results before Phase G is done:

**CONTENT path (must route CONTENT):**
1. "What are the Annex 11 requirements for audit trails?"
2. "Summarise ICH Q9(R1) changes from the 2005 version."
3. "What FDA guidance applies to computerised system validation?"

**METADATA path (must route METADATA):**
4. "How many EMA guidelines were published in the last 90 days?"
5. "What is the current ICH Q9 version?"
6. "List all FDA press releases related to data integrity."

All six must return non-empty answer + citations + correct routing.
