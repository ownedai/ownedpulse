#!/usr/bin/env python3
"""
fetch_feed.py — F3: Fetch and normalise feed items
Location: /opt/scripts/rss/fetch_feed.py

Input:  --feed-id <id>  --mode live|backfill  [--months-override N]
Output: JSON array on stdout. Each item:
        {url, title, pub_date, authority, feed_id, rss_body, feed_item_guid}
        Items already in document_registry with ingestion_status=success are excluded.
        ICH: returns [] if page hashes unchanged and items already ingested.
Exit:   0 on success, 1 on error
"""

import os, sys, json, time, hashlib, argparse, uuid, logging
import psycopg2, requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from dateutil.relativedelta import relativedelta
from dateutil import parser as dateparser
from dateutil.tz import tzoffset
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "ownedai-regulatory-pipeline/1.0"}

# EMA CloudFront CDN requires browser-like headers with a Referer pointing to
# the EMA search page. Without this, requests get 404 HTML error pages.
# See: https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format
EMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,application/pdf,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.ema.europa.eu/en/search",
}


def _ema_proxies():
    """Return SOCKS5 proxy dict for EMA requests if EMA_PROXY is set.
    Returns None otherwise (use default outbound connection)."""
    proxy = os.environ.get("EMA_PROXY")
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}

# US timezone abbreviations not understood by dateutil by default
TZINFOS = {
    "EDT": tzoffset("EDT", -4*3600), "EST": tzoffset("EST", -5*3600),
    "CDT": tzoffset("CDT", -5*3600), "CST": tzoffset("CST", -6*3600),
    "MDT": tzoffset("MDT", -6*3600), "MST": tzoffset("MST", -7*3600),
    "PDT": tzoffset("PDT", -7*3600), "PST": tzoffset("PST", -8*3600),
}

ICH_API_BASE = "https://admin.ich.org/api/v1/nodes?loadEntities%5B%5D=paragraph&alias="
ICH_SUBDIVISIONS = [
    "/page/quality-guidelines", "/page/safety-guidelines",
    "/page/efficacy-guidelines", "/page/multidisciplinary-guidelines",
]

import sys
sys.path.insert(0, '/opt/scripts')
from ingestion.config import PG_DSN

def get_kb():
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("SET search_path TO public")
    return conn

def load_feed_config(feed_id: str) -> dict:
    conn = get_kb()
    with conn.cursor() as c:
        c.execute(
            "SELECT feed_id, authority, feed_url, feed_type, "
            "default_doc_type, backfill_months, ich_page_hashes, scraper_config "
            "FROM public.feed_config WHERE feed_id = %s", (feed_id,)
        )
        row = c.fetchone()
        cols = [d[0] for d in c.description]
    conn.close()
    if not row:
        raise ValueError(f"feed_id not found: {feed_id}")
    return dict(zip(cols, row))
def is_ingested(url: str) -> bool:
    conn = get_kb()
    with conn.cursor() as c:
        c.execute(
            "SELECT 1 FROM document_registry_ext "
            "WHERE source_url = %s "
            "AND (ingestion_status IN ('success','indexed','unsupported','not_viable') "
            "     OR (ingestion_status = 'pending' "
            "         AND updated_at > NOW() - INTERVAL '10 minutes'))",
            (url,)
        )
        found = c.fetchone() is not None
    conn.close()
    return found
def get_ich_hashes(feed_id: str) -> dict:
    conn = get_kb()
    with conn.cursor() as c:
        c.execute("SELECT ich_page_hashes FROM public.feed_config WHERE feed_id = %s", (feed_id,))
        row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else {}

def update_ich_hashes(feed_id: str, hashes: dict):
    conn = get_kb()
    with conn.cursor() as c:
        c.execute(
            "UPDATE public.feed_config SET ich_page_hashes = %s WHERE feed_id = %s",
            (json.dumps(hashes), feed_id)
        )
    conn.close()

def _extract_ich_items(data: dict) -> list:
    items = []
    for widget in data.get("items",[{}])[0].get("mainWidgets",{}).get("items",[]):
        for inner in widget.get("widgets",{}).get("items",[]):
            if inner.get("entityInfo",{}).get("bundle") != "accordion_group":
                continue
            for accordion in inner.get("accordions",{}).get("items",[]):
                for g in accordion.get("items",[]):
                    code  = g.get("code","")
                    title = g.get("title","")
                    # Extract PDF URL from fileGroups if available
                    pdf_url = ""
                    for fg in g.get("fileGroups", []):
                        files = fg.get("files", [])
                        if files and files[0].get("mimetype") == "application/pdf":
                            pdf_url = files[0].get("uri", "")
                            break
                    # Only ingest items with a direct PDF URL — SPA fallback
                    # URLs (/page/slug) are JavaScript-rendered and unresolvable.
                    if not pdf_url:
                        continue
                    url = pdf_url if pdf_url.startswith("http") else f"https://www.ich.org{pdf_url}"
                    step_date = g.get("details", {}).get("stepDate", "")
                    # Normalise to ISO YYYY-MM-DD
                    pub_date = ""
                    if step_date:
                        try:
                            pub_date = dateparser.parse(step_date).date().isoformat()
                        except Exception:
                            pub_date = ""
                    if title and url:
                        items.append({
                            "url": url,
                            "title": f"{code} — {title}" if code else title,
                            "pub_date": pub_date,
                            "authority": "ICH",
                            "feed_id": "ich_guidelines",
                            "rss_body": "", "feed_item_guid": "",
                        })
    return items

def fetch_ich(feed: dict) -> tuple:
    stored = get_ich_hashes(feed["feed_id"])
    new_hashes, changed = {}, []
    for alias in ICH_SUBDIVISIONS:
        r = requests.get(ICH_API_BASE + alias, headers=HEADERS, timeout=30)
        r.raise_for_status()
        h = hashlib.sha256(r.text.encode()).hexdigest()
        new_hashes[alias] = h
        if stored.get(alias) != h:
            changed.append((alias, r.json()))
        time.sleep(0.5)

    # Check how many ICH items already ingested
    conn = get_kb()
    with conn.cursor() as c:
        c.execute(
            "SELECT COUNT(*) FROM document_registry_ext "
            "WHERE feed_id = %s AND ingestion_status = %s",
            ("ich_guidelines", "success")
        )
        ingested_count = c.fetchone()[0]
    conn.close()

    if ingested_count == 0:
        # First run — fetch all subdivisions regardless of hash
        sources = [
            (alias, requests.get(ICH_API_BASE + alias, headers=HEADERS, timeout=30).json())
            for alias in ICH_SUBDIVISIONS
        ]
    elif not changed:
        update_ich_hashes(feed["feed_id"], new_hashes)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    else:
        sources = changed

    items = []
    total_fetched = 0
    total_skipped = 0
    for alias, data in sources:
        batch = _extract_ich_items(data)
        total_fetched += len(batch)
        new   = [i for i in batch if not is_ingested(i["url"])]
        total_skipped += len(batch) - len(new)
        items.extend(new)

    update_ich_hashes(feed["feed_id"], new_hashes)
    return items, {"items_fetched": total_fetched, "items_new": len(items),
                   "items_skipped": total_skipped}
# ── EMA bulk JSON scraper ──────────────────────────────────────────────────

EMA_JSON_URL = (
    'https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json'
)

def _classify_ema_record(rec: dict) -> str | None:
    """Classify an EMA JSON report record as sci or reg guideline.
    Returns 'ema_sci_guidelines', 'ema_reg_guidance', or None (skip).

    Uses the explicit 'type' field from EMA's JSON schema (June 2026).
    Replaces the old keyword-matching on 'title' which is now 'name'.
    """
    doc_type = rec.get('type', '')
    url = rec.get('document_url', '')

    if not url or url in ('', '#'):
        return None

    if doc_type == 'scientific-guideline':
        return 'ema_sci_guidelines'
    elif doc_type == 'regulatory-procedural-guideline':
        return 'ema_reg_guidance'
    return None
def _fetch_ema_json(target_feed_id: str, months_override: int | None = None, cutoff_date=None) -> list:
    """Download EMA bulk JSON, classify and filter for the target feed.
    Single-file download — ~69K total records (June 2026 schema).
    Each record is classified as sci or reg via the explicit 'type' field;
    only records matching target_feed_id are returned.
    """
    from dateutil import parser as dateparser

    if months_override is not None:
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months_override)
    elif cutoff_date is not None:
        cutoff = cutoff_date
    else:
        cutoff = None

    logger.info("EMA JSON: downloading %s", EMA_JSON_URL)

    for attempt in range(1, 4):
        try:
            if attempt > 1:
                backoff = 5.0 * (2 ** (attempt - 2))
                logger.warning("EMA JSON: retry %d/3 in %.0fs", attempt, backoff)
                time.sleep(backoff)
            r = requests.get(EMA_JSON_URL, headers=EMA_HEADERS, timeout=60)
            r.raise_for_status()
            try:
                data = r.json()
            except json.JSONDecodeError:
                # EMA JSON sometimes has missing commas between records:
                # '}    {' → '},  {'.  Attempt repair before giving up.
                import re as _re
                _raw = _re.sub(r'\}\s*\{', '}, {', r.text)
                logger.warning("EMA JSON: repaired missing commas in JSON")
                data = json.loads(_raw)
            break
        except Exception as e:
            logger.warning("EMA JSON: attempt %d/3 failed: %s", attempt, e)
            if attempt == 3:
                raise
    records = data.get('data', data) if isinstance(data, dict) else data
    logger.info("EMA JSON: %d total records", len(records))

    items = []
    for rec in records:
        feed_id = _classify_ema_record(rec)
        if feed_id != target_feed_id:
            continue

        title = rec.get('name', '')
        url = rec.get('document_url', '')
        if not title or not url:
            continue

        pub_date = ''
        raw_date = rec.get('first_published_date', '')
        if raw_date:
            try:
                dt = dateparser.parse(raw_date, dayfirst=True)
                if dt:
                    pub_date = dt.date().isoformat()
            except Exception:
                pass

        if cutoff and pub_date:
            try:
                d = datetime.fromisoformat(pub_date).replace(tzinfo=timezone.utc)
                if d < cutoff:
                    continue
            except Exception:
                pass

        if not is_ingested(url):
            items.append({
                'url':            url,
                'title':          title,
                'pub_date':       pub_date,
                'authority':      'EMA',
                'feed_id':        feed_id,
                'rss_body':       rec.get('reference_number', ''),
                'feed_item_guid': url,
            })

    logger.info("EMA JSON: %d new items for %s", len(items), target_feed_id)
    return items
def fetch_ema_sci(feed: dict, months_override: int | None = None, cutoff_date=None) -> tuple:
    """Fetch EMA Scientific Guidelines via bulk JSON download."""
    items = _fetch_ema_json('ema_sci_guidelines', months_override=months_override, cutoff_date=cutoff_date)
    return items, {"items_fetched": len(items), "items_new": len(items),
                   "items_skipped": 0}
def fetch_ema_reg(feed: dict, months_override: int | None = None, cutoff_date=None) -> tuple:
    """Fetch EMA Regulatory Guidance via bulk JSON download."""
    items = _fetch_ema_json('ema_reg_guidance', months_override=months_override, cutoff_date=cutoff_date)
    return items, {"items_fetched": len(items), "items_new": len(items),
                   "items_skipped": 0}
# ── FDA press releases scraper ──────────────────────────────────────────────

def fetch_fda_press(feed: dict, months_override: int | None = None, cutoff_date=None) -> tuple:
    """Paginate FDA press announcements archive via BeautifulSoup.
    Stops when article date is older than cutoff or no more pages.
    """
    import re as _re
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    from dateutil import parser as dateparser

    FDA_PRESS_URL = 'https://www.fda.gov/news-events/fda-newsroom/press-announcements'
    DELAY = 2.0
    MAX_RETRIES = 3
    RETRY_BACKOFF = 5.0  # seconds — doubles each retry

    if months_override is not None:
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months_override)
    elif cutoff_date is not None:
        cutoff = cutoff_date
    else:
        cutoff = None

    items = []
    page = 0

    while True:
        url = f'{FDA_PRESS_URL}?page={page}'

        # Fetch page with retry on transient errors (DNS, connection reset, timeout)
        soup = None
        is_404 = False
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if attempt > 1:
                    backoff = RETRY_BACKOFF * (2 ** (attempt - 2))
                    logger.warning(
                        "FDA press page %d — retry %d/%d in %.0fs",
                        page, attempt, MAX_RETRIES, backoff,
                    )
                    time.sleep(backoff)
                else:
                    time.sleep(DELAY)
                r = requests.get(url, headers=HEADERS, timeout=30)
                if r.status_code == 404:
                    is_404 = True
                    break
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "FDA press page %d — attempt %d/%d failed: %s",
                    page, attempt, MAX_RETRIES, e,
                )

        if is_404:
            break
        if soup is None:
            logger.error(
                "FDA press page %d — all %d attempts failed, last error: %s",
                page, MAX_RETRIES, last_error,
            )
            break

        page_items = []
        seen = set()
        for a in soup.select('div.view-content a[href]'):
            href = a.get('href', '')
            text = a.get_text(strip=True)
            if not href or not text or len(text) < 20:
                continue
            full_url = urljoin('https://www.fda.gov', href)
            if full_url in seen or 'press-announcements' not in href:
                continue
            seen.add(full_url)

            pub_date = ''
            date_obj = None
            date_match = _re.match(
                r'^(\w+ \d+,\s*\d{4})\s*[-–]\s*(.+)$', text, _re.DOTALL
            )
            if date_match:
                try:
                    dt = dateparser.parse(date_match.group(1))
                    if dt:
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        date_obj = dt
                        pub_date = dt.date().isoformat()
                    text = date_match.group(2).strip()
                except Exception:
                    pass

            page_items.append({
                'url':            full_url,
                'title':          text,
                'pub_date':       pub_date,
                'date_obj':       date_obj,
                'authority':      'FDA',
                'feed_id':        'fda_press_releases',
                'rss_body':       '',
                'feed_item_guid': full_url,
            })

        if not page_items:
            break

        stop = False
        new_on_page = 0
        for item in page_items:
            dt = item.pop('date_obj', None)
            if cutoff and dt and dt < cutoff:
                stop = True
                break
            if not is_ingested(item['url']):
                items.append(item)
                new_on_page += 1

        if stop:
            break

        # Stop early if every item on this page was already ingested.
        # FDA orders reverse-chronologically — remaining pages are all older.
        if page > 0 and new_on_page == 0:
            logger.info("All %d items on FDA page %d already ingested — stopping pagination early",
                        len(page_items), page)
            break

        page += 1

    logger.info("FDA press scrape complete: %d new items", len(items))
    return items, {"items_fetched": len(items), "items_new": len(items),
                   "items_skipped": 0}

# ── Generic RSS feed reader ─────────────────────────────────────────────────

def fetch_rss(feed: dict, months_override: int | None = None, cutoff_date=None) -> tuple:
    """Read a plain RSS 2.0 feed. Items carry the same flat shape as the FDA
    press scraper so the downstream pipeline treats them identically.
    """
    import feedparser

    if months_override is not None:
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months_override)
    elif cutoff_date is not None:
        cutoff = cutoff_date
    else:
        cutoff = None

    url = feed["feed_url"]
    feed_id = feed["feed_id"]
    items = []
    skipped = 0

    try:
        r = requests.get(url, headers={"User-Agent": "OwnedPulse/1.0"}, timeout=60)
        r.raise_for_status()
    except Exception as e:
        logger.error("RSS fetch failed for %s: %s", feed_id, e)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}

    parsed = feedparser.parse(r.content)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        logger.error("RSS feed %s could not be parsed: %s", feed_id, parsed.get("bozo_exception"))
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}

    for entry in parsed.entries:
        try:
            link = (entry.get("link") or "").strip()
            title = (entry.get("title") or "").strip()
            if not link or not title:
                logger.warning("RSS %s: skipping entry without title or link", feed_id)
                skipped += 1
                continue

            dt = None
            for field in ("published_parsed", "updated_parsed"):
                parsed_time = entry.get(field)
                if parsed_time:
                    dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                    break
            if dt is None and entry.get("published"):
                try:
                    dt = dateparser.parse(entry["published"])
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    dt = None

            if cutoff and dt and dt < cutoff:
                continue
            if is_ingested(link):
                skipped += 1
                continue

            items.append({
                "url":            link,
                "title":          title,
                "pub_date":       dt.date().isoformat() if dt else "",
                "authority":      feed.get("authority") or "FDA",
                "feed_id":        feed_id,
                "rss_body":       (entry.get("summary") or "").strip(),
                "feed_item_guid": (entry.get("id") or link).strip(),
            })
        except Exception as e:
            logger.warning("RSS %s: skipping malformed entry: %s", feed_id, e)
            skipped += 1
            continue

    logger.info("RSS %s: %d entries, %d new, %d skipped", feed_id,
                len(parsed.entries), len(items), skipped)
    return items, {"items_fetched": len(parsed.entries), "items_new": len(items),
                   "items_skipped": skipped}

# ── FDA guidance catalogue scraper ──────────────────────────────────────────

def fetch_fda_guidance_catalogue(feed: dict, months_override: int | None = None, cutoff_date=None) -> tuple:
    """
    Fetches the full FDA guidance document catalogue from the static JSON endpoint.
    Registers ALL records into document_registry with corpus_doc=FALSE (catalogue-only).
    Does NOT download PDFs — download is triggered per-document via app UI or seed_registry.py.
    Returns (items, errors) where items are document_registry upsert dicts.
    """
    import requests as _requests
    from datetime import datetime
    import re, hashlib
    from html.parser import HTMLParser

    class _AnchorText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = ""
        def handle_data(self, data):
            self.text += data

    def _extract_text(html_str: str) -> str:
        p = _AnchorText()
        p.feed(html_str or "")
        return p.text.strip()

    def _parse_date(val: str) -> str | None:
        if not val:
            return None
        try:
            return datetime.strptime(val.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except Exception:
            return None

    def _make_doc_id(title: str, date: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")
        suffix = hashlib.md5((title + (date or "")).encode()).hexdigest()[:6]
        return f"fda-{slug}-{suffix}"

    url = feed["feed_url"]
    items = []
    errors = []

    logger.info("Fetching FDA guidance catalogue from %s", url)
    try:
        r = _requests.get(url, headers={"User-Agent": "OwnedPulse/1.0"}, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error("FDA guidance catalogue fetch failed: %s", e)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0,
                    "errors": [str(e)[:200]]}

    if not isinstance(data, list):
        logger.error("FDA guidance catalogue: unexpected format (expected list, got %s)", type(data).__name__)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0,
                    "errors": ["unexpected-response-format"]}

    logger.info("FDA guidance catalogue: %d raw records", len(data))

    for row in data:
        try:
            title_raw = row.get("title") or ""
            # Extract landing page URL from title anchor <a href="/regulatory-information/...">Title</a>
            landing_url = ""
            m_title = re.search(r'href="([^"]+)"', title_raw)
            if m_title:
                lp = m_title.group(1).strip()
                landing_url = "https://www.fda.gov" + lp if not lp.startswith("http") else lp
            title = _extract_text(title_raw)
            if not title:
                continue

            issue_date_raw = row.get("field_issue_datetime") or ""
            issue_date = _parse_date(issue_date_raw)

            status_raw = (row.get("field_final_guidance_1") or "").strip().lower()
            status = "final" if "final" in status_raw else "draft"

            pdf_raw = row.get("field_associated_media_2") or ""
            if "<" in pdf_raw:
                # Extract href from HTML anchor, e.g. <a href="/media/123/download">PDF (137 KB)</a>
                m = re.search(r'href="([^"]+)"', pdf_raw)
                pdf_path = m.group(1).strip() if m else ""
            else:
                pdf_path = pdf_raw.strip()
            if pdf_path and not pdf_path.startswith("http"):
                pdf_path = "https://www.fda.gov" + pdf_path
            pdf_url = pdf_path or None

            # Records without a PDF get the landing page as HTML source
            source_url = pdf_url or landing_url
            source_format = "pdf" if pdf_url else ("html" if landing_url else None)

            topics = row.get("field_topics") or ""
            org = row.get("field_issuing_office_taxonomy") or ""
            product_area = row.get("field_regulated_product_field") or ""
            doc_type = row.get("field_communication_type") or "guidance"
            docket = row.get("field_docket_number") or ""

            doc_id = _make_doc_id(title, issue_date)

            item = {
                "document_id": doc_id,
                "title": title,
                "issuing_body": "FDA",
                "feed_id": feed["feed_id"],
                "authority": "FDA",
                "document_class": "regulatory-public",
                "document_type": doc_type or "guidance",
                "document_status": status,
                "publication_date": issue_date,
                "source_url": source_url,
                "pdf_url": pdf_url,
                "source_file_format": source_format,
                "topics": topics,
                "organization": org,
                "product_area": product_area,
                "docket": docket,
                "corpus_doc": False,
                "metadata_json": {
                    "title": title,
                    "document_title": title,
                    "issuing_body": "FDA",
                    "source_url": source_url,
                    "source_file_format": source_format,
                    "pdf_url": pdf_url,
                    "topics": topics,
                    "organization": org,
                    "product_area": product_area,
                    "docket": docket,
                },
            }
            items.append(item)
        except Exception as e:
            errors.append(str(e))
            continue

    logger.info("FDA guidance catalogue: %d items parsed, %d errors", len(items), len(errors))
    return items, {"items_fetched": len(data), "items_new": len(items),
                   "items_skipped": len(errors), "errors": errors[:5]}

# ── Dispatcher ───────────────────────────────────────────────────────────────

def fetch_feed(feed_id: str, mode: str = "live", months_override: int = None,
               cutoff_date=None) -> tuple:
    feed = load_feed_config(feed_id)
    if mode == "backfill":
        months = months_override or feed["backfill_months"]
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months)
    elif cutoff_date:
        cutoff = cutoff_date
    else:
        cutoff = None
    ft = feed["feed_type"]
    if ft == "json_api":
        return fetch_ich(feed)
    if ft == "json_bulk":
        if feed_id == "ema_sci_guidelines":
            return fetch_ema_sci(feed, months_override=months_override, cutoff_date=cutoff)
        if feed_id == "ema_reg_guidance":
            return fetch_ema_reg(feed, months_override=months_override, cutoff_date=cutoff)
        logger.warning("Unknown json_bulk feed_id: %s", feed_id)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    if ft == "html_pagination":
        if feed_id == "fda_press_releases":
            return fetch_fda_press(feed, months_override=months_override, cutoff_date=cutoff)
        logger.warning("Unknown html_pagination feed_id: %s", feed_id)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    if ft == "json_static":
        if feed_id == "fda_guidance_catalogue":
            return fetch_fda_guidance_catalogue(feed, months_override=months_override, cutoff_date=cutoff)
        logger.warning("Unknown json_static feed_id: %s", feed_id)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    if ft == "rss":
        return fetch_rss(feed, months_override=months_override, cutoff_date=cutoff)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-id", required=True)
    parser.add_argument("--mode", default="live", choices=["live","backfill"])
    parser.add_argument("--months-override", type=int, default=None)
    parser.add_argument("--trigger-source", default="scheduled",
                        choices=["scheduled","manual","manual_cli","bootstrap_ui"])
    parser.add_argument("--triggered-by", default=None)
    parser.add_argument("--workflow-id", default=None)
    parser.add_argument("--n8n-execution-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-age-days", type=int, default=None,
                        help="In live mode, only fetch items published within this many days")
    args = parser.parse_args()

    parent_trace_id = None
    if not sys.stdin.isatty():
        try:
            stdin = json.load(sys.stdin)
            parent_trace_id = stdin.get("parent_trace_id")
        except Exception:
            pass

    run_id = args.run_id or str(uuid.uuid4())
    start_time = time.time()

    # Open run_log row
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("""
            INSERT INTO run_log (run_id, trigger_source, triggered_by,
                                 workflow_id, n8n_execution_id,
                                 feed_source, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'running')
            ON CONFLICT (run_id) DO NOTHING
        """, (run_id, args.trigger_source, args.triggered_by,
              args.workflow_id, args.n8n_execution_id, args.feed_id))
    conn.close()

    # Compute live-mode date cutoff from --max-age-days (backfill uses months_override instead)
    max_age_cutoff = None
    if args.mode == "live" and args.max_age_days is not None:
        from datetime import timedelta
        max_age_cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)

    try:
        if max_age_cutoff:
            items, stats = fetch_feed(args.feed_id, args.mode, args.months_override,
                                      cutoff_date=max_age_cutoff)
        else:
            items, stats = fetch_feed(args.feed_id, args.mode, args.months_override)
        duration_ms = int((time.time() - start_time) * 1000)

        conn = psycopg2.connect(PG_DSN)
        conn.autocommit = True
        with conn.cursor() as c:
            c.execute("""
                UPDATE run_log SET
                    status = 'running',
                    items_fetched = %s,
                    items_new = %s,
                    items_skipped = %s,
                    error_count = 0,
                    duration_ms = 0
                WHERE run_id = %s
            """, (stats["items_fetched"], stats["items_new"],
                  stats["items_skipped"], run_id))
            c.execute(
                "UPDATE feed_config SET last_run_at = NOW() WHERE feed_id = %s",
                (args.feed_id,)
            )
        conn.close()

        output = {"span_id": None, "items": items} if parent_trace_id else items
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            conn = psycopg2.connect(PG_DSN)
            conn.autocommit = True
            with conn.cursor() as c:
                c.execute("""
                    UPDATE run_log SET
                        status = 'error',
                        completed_at = NOW(),
                        error_detail = %s,
                        duration_ms = %s
                    WHERE run_id = %s
                """, (str(e)[:500], duration_ms, run_id))
            conn.close()
        except Exception:
            pass
        sys.stderr.write(json.dumps({"status":"error","detail":str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
