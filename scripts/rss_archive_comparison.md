Task: RSS vs Archive Pipeline Dry-Run Comparison
Goal: Determine whether archive scrapers cover the same document universe as RSS feeds. No DB reads. No file downloads. No data modification. Live HTTP only — read metadata/URLs from endpoints.
Step 1 — Read existing code first
Read these files before writing anything:

Find and read fetch_feed.py — extract exact RSS feed URLs and item parsing logic (how it extracts title, link, guid, pubDate per item)
Find and read the EMA JSON scraper — extract exact endpoint URL, pagination params, field names
Find and read the FDA scraper — extract exact base URL and pagination pattern
Find and read the ICH scraper — extract exact endpoint URL and field names
Find and read sources_manifest.json — confirm all feed URLs

Report back: paste the exact URLs for all 3 archive endpoints and all RSS feed URLs. Confirm field names used for title and URL in each scraper. Do not proceed until done.
Step 2 — Write comparison script
Write /opt/projects/ownedpulse/scripts/rss_archive_comparison.py.
Requirements:

requests with 15s timeout on all calls
All fetches in try/except — one endpoint failing must not abort the rest
No writes to DB, no file downloads, no Qdrant calls
Respect existing pagination logic from the scrapers you read in Step 1

RSS collection function — for each RSS feed URL:

Fetch and parse XML (use feedparser or xml.etree.ElementTree — check which is already installed)
Extract per item: title (strip/normalize whitespace), link URL (normalized: lowercase, strip trailing slash, strip query params except essential ones), pubDate if present, guid
Return list of dicts: {title, url, guid, pub_date, feed_name}
Collect from all feeds defined in sources_manifest.json

Archive collection functions — one per source:
EMA JSON:

Replicate the pagination logic from the existing EMA scraper exactly
Fetch all pages (stop condition: same as existing scraper)
Extract per item: title (normalized), url (normalized same way as RSS)
Apply the same title-based classifier logic if it exists in the scraper — flag ema_sci vs ema_reg per item
Return list of dicts: {title, url, source='ema_archive'}
Cap at 50 pages max as safety limit — print warning if hit

FDA:

Replicate pagination from existing FDA scraper
Extract: title (normalized), url (normalized)
Cap at 30 pages max
Return list of dicts: {title, url, source='fda_archive'}

ICH:

Replicate from existing ICH scraper
Extract: title (normalized), url (normalized)
Return list of dicts: {title, url, source='ich_archive'}

Matching logic:
Primary match: exact normalized URL match between RSS item link and archive item URL.
Fallback match (for items with no URL match): normalized title similarity. Normalize = lowercase, remove punctuation, collapse whitespace. If normalized titles share >80% of words (simple token overlap), treat as probable match. Flag these as FUZZY_MATCH not EXACT_MATCH.
Per RSS feed, compute:

EXACT_MATCH count
FUZZY_MATCH count
NO_MATCH count — items in RSS with no archive equivalent

For NO_MATCH items: print title, url, pub_date — these are the loss candidates.
Also compute per archive source:

How many archive items have no RSS equivalent (informational only — these are archive-only docs, not a loss risk)

Step 3 — Output
Print structured report:
=== RSS vs ARCHIVE DRY-RUN COMPARISON ===
Run date/time: ...
Timeouts: 15s per request

[RSS FEEDS COLLECTED]
Feed: <name>  Items: N  Date range: earliest–latest pubDate

[ARCHIVE ENDPOINTS COLLECTED]
EMA JSON:  N items  Pages fetched: N
FDA:       N items  Pages fetched: N
ICH:       N items

[OVERLAP ANALYSIS BY RSS FEED]
Feed: ema_sci_guidelines
  Total RSS items:   N
  Exact matches:     N  (N%)
  Fuzzy matches:     N  (N%)
  No match (AT RISK): N  (N%)

Feed: ema_reg_guidance
  ...

Feed: fda_press_releases
  ...

Feed: ich_guidelines
  ...

[NO-MATCH ITEMS — POTENTIAL INFORMATION LOSS]
Feed: <name>
  - <title> | <url> | <pub_date>
  ...

[ARCHIVE-ONLY ITEMS — NOT A LOSS RISK]
EMA archive items not in any RSS feed: N
FDA archive items not in any RSS feed: N
ICH archive items not in any RSS feed: N

[VERDICT]
RSS feeds safe to drop: YES / NO / CONDITIONAL
At-risk item count: N
Notes: ...
Step 4 — Report back before running
Show me Step 1 findings (exact URLs, field names from actual files) and the complete script. Wait for explicit go-ahead before executing.
