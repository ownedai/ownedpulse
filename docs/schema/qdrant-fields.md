# Qdrant Chunk Payload — Authoritative Field Names

Collection: `knowledge_base`. These are ACTUAL field names verified against the live system.

| Field | Type | Notes |
|---|---|---|
| `document_id` | string | Document identifier (NOT `doc_id`) |
| `chunk_id` | UUID string | Unique chunk identifier |
| `document_title` | string | Title (NOT `title`). Falls back to `section_path[0]` if missing |
| `issuing_body` | string | Agency: FDA / EMA / ICH / EU-Commission (NOT `agency`) |
| `doc_type` | string | UNDERSCORED: `press_release`, `guidance_pdf`, `reflection_paper`, etc. |
| `document_type` | string | HYPHENATED: `press-release`, `guidance`, `reflection-paper`, etc. |
| `document_version` | string | E.g. `"1.0"`, `"Rev. 1"` |
| `regulatory_domain` | list of strings | E.g. `['GMP', 'CSV']` |
| `clause_id` | string \| null | E.g. `"4.8"` |
| `clause_id_prefix` | string | Not currently used |
| `chunk_index` | int | Position within document (NOT `chunk_idx`) |
| `chunk_text` | string | The actual text content |
| `char_offset_start` | int | Start char offset |
| `char_offset_end` | int | End char offset |
| `page_no` | int | Page number in source PDF (NOT `page_number`) |
| `publication_date` | string | ISO date |
| `chunked_at` | string | ISO datetime — ingestion timestamp |
| `chunk_status` | string | E.g. `indexed` (NOT `ingestion_status`) |
| `source_url` | string | URL to source document |
| `source_local_path` | string \| null | Path to local PDF (NOT `local_file_path`) |
| `document_family_id` | string \| null | Links document versions for supersede |
| `section_path` | list of strings | Heading hierarchy, title fallback |

## Filtering Rules — CRITICAL

Filter on `document_type` (hyphenated). Do NOT filter on `doc_type` (underscored).

UI filter values map to Qdrant fields:
- Agency: filters on `issuing_body`
- Document type: filters on `document_type` (hyphenated values)
- Date range: filters on `publication_date` (string ISO comparison)
