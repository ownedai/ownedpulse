# Doc-type and Status Standardisation — 2026-06-02

## Summary

Full standardisation of `doc_type` and `ingestion_status` values across PostgreSQL,
Qdrant payloads, pipeline scripts, and frontend status rendering.

## Registry state after cleanup

### doc_type distribution (document_registry)

| doc_type         | count |
|------------------|-------|
| drug_approval    |   837 |
| guidance         |   387 |
| press_release    |   106 |
| safety_alert     |    21 |
| other            |    16 |
| news_item        |    13 |
| reflection_paper |     9 |
| **Total**        | **1389** |

`guidance_pdf` fully retired — 0 rows.

### ingestion_status distribution (document_registry)

| ingestion_status | count |
|------------------|-------|
| indexed          |  1388 |
| superseded       |     1 |

Zero pending, zero error, zero running rows. Registry clean.

### run_log status distribution

| status  | count |
|---------|-------|
| success |  1387 |

`complete` fully retired — 0 rows.

## Changes made

### DB (PostgreSQL)
- Renamed all `guidance_pdf` → `guidance` in `document_registry.doc_type`
- Renamed all `complete` → `success` in `run_log.status`
- Reclassified 2 misclassified FDA docs:
  - GLP-1 concerns doc (`fda_guidance-concerns-use-glucagon-like-...`) → `safety_alert`
  - NAMs FDA page (`fda_guidance-new-approach-methodologies-nams`) → `other`
- Added check constraint on `document_registry.doc_type` enforcing canonical values
- Added check constraint on `run_log.status` enforcing canonical values

### Canonical doc_type values (enforced by constraint)
`guidance`, `reflection_paper`, `press_release`, `safety_alert`, `drug_approval`, `news_item`, `other`

### Canonical run_log status values (enforced by constraint)
`running`, `success`, `partial`, `failed`, `error`

### Pipeline scripts
- `fetch_feed.py`: `status = 'complete'` → `status = 'success'` in run_log UPDATE
- `run_ingest.py`: `CANONICAL_DOC_TYPES` replaces `DOC_TYPES_ALLOWED` (guidance not guidance_pdf);
  `validate_doc_type()` guard falls back to `other` for non-canonical values;
  `REGULATORY_DOMAIN_MAP` and `DOC_TYPE_TO_DOCUMENT_TYPE` updated to use `guidance`
- `bootstrap.py`: `final_status = "complete"` → `final_status = "success"`

### Classifier prompt
- `classifier_prompt_v1.txt` updated to v2: `guidance_pdf` → `guidance` in allowed
  categories; explicit rule 5 forbidding `guidance_pdf`; note that `reflection_paper`
  is primarily EMA terminology

### Frontend
- `ui/src/utils/status.js` — new shared status utility (`STATUS_CONFIG`, `getStatusConfig`)
- `RunLogPage.jsx`, `DocumentDetailPage.jsx`, `CorpusPage.jsx`, `SourcesPage.jsx` —
  all inline `StatusBadge` implementations replaced with shared `getStatusConfig()`
- RunLogPage filter dropdown: `{ label: 'Complete', value: 'complete' }` → `{ label: 'Success', value: 'success' }`
