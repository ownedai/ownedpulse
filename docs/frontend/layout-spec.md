# Frontend Layout Spec

## Layout Zones

### Top nav bar (full width, above all zones)
- ownedai logo + wordmark (left)
- Theme toggle button (right, sun/moon, localStorage persistent)
- 44px height

### Zone 1: Left Sidebar (fixed 240px, always dark)
- "+ New query" button (accent)
- "RECENT QUERIES" heading + "View all →" link (goes to /history)
- Last 5 query items: truncated text + relative time (only on / page)
- Clicking: loads cached result from `query_history`, URL → `/?q={query_id}`
- "SYSTEM" section at bottom: Pipeline last run, Docs indexed, Embed model, Build version

### Zone 2: Filter Bar (below query input on Query page only)

Standard filters (always visible):
- Agency: All / FDA / EMA / ICH (ⓘ tooltip)
- Document type: All / Guidance / Press Release / Reflection Paper (ⓘ tooltip) — maps to `document_type` (hyphenated)
- Date range: All / Last 30d / Last 90d / Custom (ⓘ tooltip) — custom via floating popover

Retrieval settings (gear icon popover, right side):
- Collapsed: gear icon, turns blue when non-default
- Expanded: Query depth (Low/Standard/Deep) / Top-K (5–20) / Min relevance (0.40–0.90)

### Zone 3: Main Content Panel

#### Landing state
- Heading "Query regulatory intelligence" (Inter 28px/500)
- Subtitle "Search FDA, EMA, and ICH guidance documents. All processing on your infrastructure."
- Query input (48px height), Submit button accent blue
- "Try these queries" label + three example chips (clickable, pill-shaped, outlined)
- Corpus stats bar at bottom

#### Active state
- Query input retains query text
- Thinking indicator: animated bar + "Searching N variations across X documents..."
- Answer: Inter 16px / 1.75 / plain prose / `[N]` markers as superscript clickable links
- Disclaimer below answer: italic / secondary / no card
- Query expansion (11px secondary, collapsible): "Query expansion · {N} variations generated ▾"
- "Sources ({N})" heading + Export button (JSON / PDF dropdown)
- Citation cards sorted by score desc:
  - Cited: full opacity, MATCHED green badge
  - Uncited (above threshold): 40% opacity, NOT CITED grey badge
  - Below threshold: not shown at all
  - Superseded: SUPERSEDED amber badge + "→ current version: {title}"
- Audit footer (sticky bottom): "Query ID: {short-uuid} ⓘ · {DD/MM/YYYY HH:MM:SS} · {Semantic search|Metadata lookup} · View trace →"

### Zone 4: Source Drawer (fixed overlay, slides from right)
- Triggered by clicking citation card or "View source →"
- `position: fixed`, 480px wide, dark backdrop via createPortal
- Main content does NOT shift

Drawer tabs: **Chunk | Provenance | Trace**

Header: document title (truncate >80 chars, hover tooltip) · Agency · Version · Status · Close button · "← Previous / Next →" navigation

**Chunk tab:**
- "RETRIEVED CHUNK" label + "chars {start}-{end}"
- Monospace (JetBrains Mono), distinct bg

**Provenance tab — all 9 fields required:**
| Source file | filename only, full path on hover |
| Document version | as-is |
| Clause ID | or "Not available" if null |
| Publication date | DD/MM/YYYY or "Not available" |
| Agency | EU-Commission normalised to EMA |
| Chunk index | position within document |
| Character offsets | "chars {start}-{end}" |
| Ingestion date | DD/MM/YYYY (from chunked_at) |
| Source URL | clickable external link |

PDF section: calls `GET /api/pdf/page`, shows "PDF not available" if source_local_path is null, page navigation arrows.

**Trace tab:**
- Fetched from `GET /api/trace/{trace_id}` (backend proxies Langfuse)
- Sections (collapsible): Header (trace ID, latency) · Query expansion (sub-queries + latency) · Per sub-query retrieval · Deduplication · LLM call (model, tokens, latency) · Retrieval params
- Opened when user clicks "View trace →" in audit footer

---

## New Pages

### /history

Table columns: # | Query | Date/Time | Routing | Agency | Sources | Actions
- Date: DD/MM/YYYY HH:MM
- Routing: "Semantic" / "Metadata"
- Actions: "Load" → loads result into main view
- Sortable by date, routing, source count
- Filterable by date range, routing, agency
- Pagination 50/page
- "Export all" button (JSON / CSV dropdown)

### /corpus

- Agency filter tabs (All / FDA / EMA / ICH) + Doc type filter
- Table: Document ID | Title | Version | Agency | Type | Published | Status | Chunks | Last Indexed
- Status: `● INDEXED` / `● ERROR` / `● PROCESSING` / `SUPERSEDED` badges
- Click row → /corpus/:docId

Document viewer overlay: sequential PDF pages via `/api/pdf/page`, page nav forward/back.

### /corpus/:docId — Document Detail

2-column layout (left 60% / right 40%):
- Left: key-value rows with dividers, hash comparison (PG vs Qdrant), version chain as pill chain
- Right: chunk table (3 cols) with expandable monospace text rows

### /corpus/runs — Run Log

Table: Run ID | Status | Source | N8N ID | Items | Errors | Duration | Triggered
- SOURCE: "SCHEDULED" outlined / "● MANUAL" filled blue
- STATUS: `● COMPLETE` / `● RUNNING` / `● ERROR` box badges
- Filter popovers + refresh button

### /admin

2×2 grid panels: System Health | Feed Management | Pipeline Trigger | Model Selection
- Health: inline dot + service name + metric text rows
- Feeds: Toggle switch, URL column (truncated)
- Trigger: full-width button → green on success + "● View in Run Log →"
- Model: green checkmark on success

---

## Tooltip Spec

- Trigger: hover, 300ms delay
- Visual: dark surface (#1E293B / #F8FAFC text), Inter 12px, max-width 280px, arrow

Required tooltips:

**Filter bar:**
- Agency: "Filter to documents from a specific regulatory agency"
- Document type: "Guidance is normative; press releases are informational"
- Date range: "Filter by document publication date, not ingestion date"
- Query depth: "More variations = better recall, slower response"
- Top-K: "Source chunks retrieved per search variation before filtering"
- Min relevance: "Below threshold = excluded from results"

**Citation card:**
- Score bar: "Semantic similarity. Minimum threshold: {value}."
- MATCHED: "This source was cited by the AI in its answer"
- NOT CITED: "Retrieved but not used by the AI in its answer"
- SUPERSEDED: "This document version has been superseded. Verify currency."
- Agency badges: "US Food and Drug Administration" / "European Medicines Agency" / "International Council for Harmonisation"

**Audit footer:**
- Query ID: "Unique identifier for this query session. Use for audit lookup."
- ⓘ: "Every query recorded for compliance traceability per Annex 11 §8.1."
- Timestamp: "Time this query was executed and recorded."
- Semantic search: "AI-generated answer from document content"
- Metadata lookup: "Direct lookup without AI generation"
- View trace: "View full pipeline trace — sub-queries, retrieval, LLM call"

**Corpus stats:**
- Agency counts: "Click to browse all documents from this agency"
- Last updated: "Last time new regulatory documents were ingested via RSS"

---

## Date Format Rule

All human-visible dates: **DD/MM/YYYY**. No exceptions.
Internal API payloads use ISO YYYY-MM-DD — convert at render layer only.
Export filenames may use ISO for system sortability.
