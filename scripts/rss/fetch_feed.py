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

import os, sys, json, time, hashlib, argparse, uuid
import feedparser, psycopg2, requests
from datetime import datetime, timezone
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
NOCO_DSN = PG_DSN.replace('/knowledge_base', '/nocodb')

# Then replace all:


def get_kb():
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("SET search_path TO public")
    return conn

def get_noco():
    conn = psycopg2.connect(NOCO_DSN)
    conn.autocommit = True
    return conn

def load_feed_config(feed_id: str) -> dict:
    conn = get_noco()
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
    conn = get_noco()
    with conn.cursor() as c:
        c.execute("SELECT ich_page_hashes FROM public.feed_config WHERE feed_id = %s", (feed_id,))
        row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else {}

def update_ich_hashes(feed_id: str, hashes: dict):
    conn = get_noco()
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

def fetch_feed(feed_id: str, mode: str = "live", months_override: int = None) -> tuple:
    feed = load_feed_config(feed_id)
    cutoff = None
    if mode == "backfill":
        months = months_override or feed["backfill_months"]
        cutoff = datetime.now(timezone.utc) - relativedelta(months=months)
    if feed["feed_type"] == "json_api":
        return fetch_ich(feed)
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
                    status = 'success',
                    completed_at = NOW(),
                    items_fetched = %s,
                    items_new = %s,
                    items_skipped = %s,
                    error_count = 0,
                    duration_ms = %s
                WHERE run_id = %s
            """, (stats["items_fetched"], stats["items_new"],
                  stats["items_skipped"], duration_ms, run_id))
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
