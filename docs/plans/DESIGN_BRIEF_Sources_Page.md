# Sources Page — Claude Design Brief
**Version:** 1.0 · **Date:** 2026-06-01
**For:** Claude Design (visual prototype)
**Read first:** ui/design-handoff/design-spec.md, query-ui-v3.css, the existing Admin page screenshot

---

## Context

Sources is a new page added to ownedpulse. It owns corpus configuration and initial ingestion setup. It is opened rarely — during system setup or when the operator needs to add, reingest, or remove a source.

Feed Management moves from Admin to Sources. Admin slims to System Health, Pipeline Trigger, Model Selection only.

---

## Navigation Change

Add Sources to the left sidebar nav between Corpus and Run Log:

```
[ownedai logo]
─────────────
Query          ← route: /
Corpus         ← route: /corpus
Sources        ← route: /sources     ← NEW
Run Log        ← route: /corpus/runs
Admin          ← route: /admin
─────────────
[system info block]
```

Icon for Sources: lucide-react `Layers` or `FolderOpen`. Top bar title on /sources: "Sources".

---

## Page Layout

Three cards stacked vertically, full width, same card style as Admin page (dark card background on dark shell `#0F172A`, monospace small-caps section headers matching SYSTEM HEALTH / FEED MANAGEMENT style).

---

## Card 1 — Corpus Summary

**Purpose:** At-a-glance corpus health. Primary thing an operator sees on return visits.

Light visual treatment — not a raw number strip. A grouped stat display, one group per agency (FDA, EMA, ICH), each group showing doc counts broken down by doc_type class.

Layout: horizontal row of agency groups. Each group is a small card-within-card or a bordered cell:

```
┌─ FDA ──────────────────┐  ┌─ EMA ──────────────────┐  ┌─ ICH ──────┐
│ Guidance        847    │  │ Scientific GL   134     │  │ Guidelines │
│ Press Releases  167    │  │ Regulatory GU    77     │  │       157  │
│ Safety Comms      0    │  │                        │  │            │
│ Last ingested: 2026-05 │  │ Last ingested: 2026-05  │  │ Last: ...  │
└────────────────────────┘  └────────────────────────┘  └────────────┘
```

- Doc counts in a larger weight, class labels in muted smaller text
- "Last ingested" date below each agency group in muted text
- Zero counts shown in `--status-warn` amber, not hidden — a zero is meaningful
- ⚠️ **Taxonomy verification pending** — exact class labels and whether a doc_type maps to one or multiple agencies is unresolved. Design should accommodate 2–4 rows per agency group. Use placeholder labels for now; Claude Code will bind to live data.

---

## Card 2 — Base Corpus Documents

**Purpose:** The 7 managed regulatory documents (fixed set for v1). Version-aware with supersede chains.

Section header: `BASE CORPUS` (monospace small-caps, matching existing style)

Table columns: Document | Agency | Version | Published | Status | Last Ingested | Chunks | Actions

**Supersede chain:** Documents with multiple versions render as an expandable row. The active version is the primary row. Clicking a chevron expands superseded versions below it, indented, read-only, no action buttons. Use existing supersede chain pill styles from design-spec.md:
- Active: `background: var(--accent)`, text white, pill shape
- Superseded: `border: 1px solid var(--muted)`, transparent background, muted text
- Chain arrow: `→` or lucide ChevronRight, `var(--muted-foreground)`

Example ICH Q9 row:
```
▶ ICH Q9(R1)   ICH   R1 (2023)   2023-01   ● Active     2026-05-28   47    [Reingest] [Delete]
  └ ICH Q9     ICH   1.0 (2005)  2005-06   ○ Superseded 2026-05-28   31    —
```

**Action buttons per active row:**
- `Reingest` — secondary/outline style, small
- `Delete` — destructive/outline style, small, red border on hover

**Delete confirmation:** inline confirmation row below the row (not a modal), showing "This will remove N chunks from the corpus. This action is logged." with Confirm (red) and Cancel buttons. Two-step, not instant.

**Reingest confirmation:** none needed — reingest is non-destructive. Button triggers directly, row shows inline progress indicator (spinner + "Reingesting...") until complete, then updates Last Ingested and Chunks.

---

## Card 3 — RSS Feeds

**Purpose:** Ongoing automated ingestion sources. Moved from Admin.

Section header: `RSS FEEDS`

Table columns: Feed Name | Source ID | URL (truncated) | Enabled | Last Fetch | Docs Ingested | Actions

Retain existing toggle style from Admin (36×20px, 150ms transition).

**Add per-row action:** `Reingest` button (secondary/outline, small) — triggers historical re-pull for that feed through the traced pipeline. Same inline progress behaviour as Card 2 reingest.

No Delete on RSS feeds for v1 — feeds are configured at setup, removal is an admin operation outside this UI for now.

---

## Card 4 — Initial Load

**Purpose:** First-time corpus population or deliberate full reset. Rare action.

Section header: `INITIAL LOAD`

Not a form — a single button that opens a modal:

**Button states:**
- Never run: `[Run Initial Load]` — primary blue, full card width
- Already populated: `[Re-run Initial Load]` — secondary/outline style. Below button: muted text "Corpus last populated: 2026-05-28 · 1,382 documents"

**Re-run wipe warning:** When corpus already populated, modal opens with a prominent amber warning block before scope selection: "This will permanently delete all corpus data, ingestion history, and Langfuse traces before reingesting. This cannot be undone." A checkbox "I understand this will wipe the corpus" must be checked before [Start Initial Load] enables.

**Modal — Initial Load Configuration:**

Title: "Configure Initial Load"

Body: Scope selection — checkboxes grouped by agency. Each checkbox row shows: class label, current doc count if already ingested ("847 documents" in muted text), "not ingested" if zero.

```
FDA
  ☑ Guidance                    847 documents
  ☑ Press Releases               167 documents
  ☐ Safety Communications        not ingested

EMA
  ☑ Scientific Guidelines        134 documents
  ☑ Regulatory Guidance           77 documents

ICH
  ☑ Guidelines                   157 documents
```

Below scope selection: informational note (muted, small):
"Selected classes will be fetched from their respective sources. Already-ingested documents will be superseded if newer versions exist. This action is logged in Run Log."

Footer: `[Cancel]` (ghost) + `[Start Initial Load]` (primary blue, disabled until at least one class selected)

**Progress state (modal stays open):** After trigger, scope selection is replaced by SSE progress display.

Counter bar at top (always visible during run):
```
Processing: 847 / 1,382   ████████████░░░░░░░  61%
Succeeded: 845   Failed: 2
```

Below counter: scrollable per-document rows arriving via SSE as each document completes. Each row: document title (truncated) + agency + doc_type + status pill (SUCCESS green / FAILED amber). FAILED rows show failure_reason in muted small text below.

Failed rows use `--status-warn` amber — partial completion at scale is expected, not a critical error.

Final state after run_complete: counter updates to final counts. All succeeded: green summary. Partial: amber "N succeeded · N failed — details in Run Log". RSS activation confirmation if n8n activated. Close button re-enables; modal does NOT auto-close — operator should review before closing.

Modal close button disabled during active run.

---

## Design Tokens

Reuse existing tokens from design-spec.md throughout. No new tokens required — all states covered by:
- `--status-ok` #22c55e
- `--status-error` #ef4444
- `--status-warn` #f59e0b
- `--status-running` #3b82f6 + pulse animation
- Supersede pill styles as defined in design-spec.md

---

## Responsive Behaviour

Below 1024px: Cards stack single column (same as Admin 1×4 collapse rule).
Base Corpus table below 1024px: hide "Published" and "Chunks" columns.
RSS Feeds table below 1024px: hide "URL" and "Last Fetch" columns.
Initial Load modal: full width on mobile, max-width 560px on desktop.

---

## What This Brief Does Not Cover

- Adding new base corpus documents (post-v1)
- Per-feed archive window configuration (post-v1)
- Feed deletion (post-v1)
- Taxonomy label mapping (pending verification — Claude Code binds to live doc_type values from registry)
