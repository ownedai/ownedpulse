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
import feedparser, psycopg2, requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
from dateutil.relativedelta import relativedelta
from dateutil import parser as dateparser
from dateutil.tz import tzoffset
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "ownedai-regulatory-pipeline/1.0"}

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

def fetch_rss(feed: dict, cutoff_date=None) -> tuple:
    r = requests.get(feed["feed_url"], headers=HEADERS, timeout=30)
    r.raise_for_status()
    parsed = feedparser.parse(r.text)
    items = []
    total_fetched = 0
    total_skipped = 0
    for entry in parsed.entries:
        url = entry.get("link", "")
        if not url:
            continue
        total_fetched += 1
        pub_date_raw = entry.get("published", "")
        pub_date = None
        if pub_date_raw:
            try:
                pub_date = dateparser.parse(pub_date_raw, tzinfos=TZINFOS)
                if pub_date and pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        if cutoff_date and pub_date and pub_date < cutoff_date:
            total_skipped += 1
            continue
        if is_ingested(url):
            total_skipped += 1
            continue
        items.append({
            "url":            url,
            "title":          entry.get("title", ""),
            "pub_date":       pub_date.date().isoformat() if pub_date else "",
            "authority":      feed["authority"],
            "feed_id":        feed["feed_id"],
            "rss_body":       entry.get("summary", ""),
            "feed_item_guid": entry.get("id", ""),
        })
    return items, {"items_fetched": total_fetched, "items_new": len(items),
                   "items_skipped": total_skipped}

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
    'https://www.ema.europa.eu/en/documents/report/general-json-report_en.json'
)


def _classify_ema_record(rec: dict) -> str | None:
    """Classify an EMA JSON report record as sci or reg guideline.
    Returns 'ema_sci_guidelines', 'ema_reg_guidance', or None (skip).
    """
    title = rec.get('title', '').lower()
    url = rec.get('general_url', '')

    if not url or url in ('', '#'):
        return None

    # Exclude all non-document URL prefixes
    SKIP_PREFIXES = (
        '/en/human-regulatory-overview/',
        '/en/veterinary-regulatory-overview/',
        '/en/about-us/',
        '/en/committees/',
        '/en/partners-networks/',
        '/en/medicines/',
        '/en/news',
        '/en/events/',
    )
    if any(url.startswith('https://www.ema.europa.eu' + p) for p in SKIP_PREFIXES):
        return None

    is_sci = 'scientific guideline' in title
    is_reg = any(x in title for x in ('regulatory', 'procedural', 'guidance'))

    if is_sci:
        return 'ema_sci_guidelines'   # sci wins on overlap
    elif is_reg:
        return 'ema_reg_guidance'
    return None


def _fetch_ema_json(target_feed_id: str, months_override: int | None = None) -> list:
    """Download EMA bulk JSON, classify and filter for the target feed.
    Single-file download — 2,046 total records. Each record is classified
    as sci or reg; only records matching target_feed_id are returned.
    """
    from dateutil import parser as dateparser

    if months_override is not None:
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months_override)
    else:
        cutoff = None

    logger.info("EMA JSON: downloading %s", EMA_JSON_URL)
    r = requests.get(EMA_JSON_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    records = data.get('data', data) if isinstance(data, dict) else data
    logger.info("EMA JSON: %d total records", len(records))

    items = []
    for rec in records:
        feed_id = _classify_ema_record(rec)
        if feed_id != target_feed_id:
            continue

        title = rec.get('title', '')
        url = rec.get('general_url', '')
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
                'rss_body':       rec.get('summary', ''),
                'feed_item_guid': url,
            })

    logger.info("EMA JSON: %d new items for %s", len(items), target_feed_id)
    return items


def fetch_ema_sci(feed: dict, months_override: int | None = None) -> tuple:
    """Fetch EMA Scientific Guidelines via bulk JSON download."""
    items = _fetch_ema_json('ema_sci_guidelines', months_override=months_override)
    return items, {"items_fetched": len(items), "items_new": len(items),
                   "items_skipped": 0}


def fetch_ema_reg(feed: dict, months_override: int | None = None) -> tuple:
    """Fetch EMA Regulatory Guidance via bulk JSON download."""
    items = _fetch_ema_json('ema_reg_guidance', months_override=months_override)
    return items, {"items_fetched": len(items), "items_new": len(items),
                   "items_skipped": 0}


# ── FDA press releases scraper ──────────────────────────────────────────────

def fetch_fda_press(feed: dict, months_override: int | None = None) -> tuple:
    """Paginate FDA press announcements archive via BeautifulSoup.
    Stops when article date is older than cutoff or no more pages.
    """
    import re as _re
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    from dateutil import parser as dateparser

    FDA_PRESS_URL = 'https://www.fda.gov/news-events/newsroom/press-announcements'
    DELAY = 2.0

    if months_override is not None:
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months_override)
    else:
        cutoff = None

    items = []
    page = 0

    while True:
        url = f'{FDA_PRESS_URL}?page={page}'
        try:
            time.sleep(DELAY)
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                break
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
        except Exception as e:
            logger.error(f"FDA press error page {page}: {e}")
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


# ── Dispatcher ───────────────────────────────────────────────────────────────

def fetch_feed(feed_id: str, mode: str = "live", months_override: int = None) -> tuple:
    feed = load_feed_config(feed_id)
    cutoff = None
    if mode == "backfill":
        months = months_override or feed["backfill_months"]
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months)
    ft = feed["feed_type"]
    if ft == "json_api":
        return fetch_ich(feed)
    if ft == "json_bulk":
        if feed_id == "ema_sci_guidelines":
            return fetch_ema_sci(feed, months_override=months_override)
        if feed_id == "ema_reg_guidance":
            return fetch_ema_reg(feed, months_override=months_override)
        logger.warning("Unknown json_bulk feed_id: %s", feed_id)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    if ft == "html_pagination":
        if feed_id == "fda_press_releases":
            return fetch_fda_press(feed, months_override=months_override)
        logger.warning("Unknown html_pagination feed_id: %s", feed_id)
        return [], {"items_fetched": 0, "items_new": 0, "items_skipped": 0}
    return fetch_rss(feed, cutoff_date=cutoff)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-id", required=True)
    parser.add_argument("--mode", default="live", choices=["live","backfill"])
    parser.add_argument("--months-override", type=int, default=None)
    parser.add_argument("--trigger-source", default="scheduled",
                        choices=["scheduled","manual","n8n_rss","manual_cli","bootstrap_ui"])
    parser.add_argument("--triggered-by", default=None)
    parser.add_argument("--workflow-id", default=None)
    parser.add_argument("--n8n-execution-id", default=None)
    parser.add_argument("--run-id", default=None)
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

    try:
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
