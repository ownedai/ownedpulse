#!/usr/bin/env python3
"""
RSS vs Archive Pipeline Dry-Run Comparison

Compares document coverage between RSS feeds and archive scrapers.
No DB writes. No file downloads. No data modification.
Live HTTP only — reads metadata/URLs from endpoints.
"""
import sys
import re
import json
import time
import hashlib
import argparse
import warnings
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse
from collections import defaultdict

import requests
import feedparser
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

TIMEOUT = 15
DELAY_FDA = 2.0
DELAY_ICH = 0.5
MAX_FDA_PAGES = 30
MAX_EMA_PAGES = 50
HEADERS = {
    "User-Agent": "RegPulse/1.0 (RSS-Archive comparison; sovereign RAG pipeline; contact zoran@ownedai.dev)"
}

# ── URL sources ────────────────────────────────────────────────────────────────

RSS_FEEDS = {
    "fda_press_releases": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    "ema_sci_guidelines": "https://www.ema.europa.eu/en/scientific-guidelines.xml",
    "ema_reg_guidance":  "https://www.ema.europa.eu/en/regulatory-and-procedural-guideline.xml",
    "ich_guidelines":    "https://admin.ich.org/api/v1/nodes",
}

EMA_JSON_URL = "https://www.ema.europa.eu/en/documents/report/general-json-report_en.json"

FDA_BASE = "https://www.fda.gov/news-events/newsroom/press-announcements"

ICH_API_BASE = "https://admin.ich.org/api/v1/nodes?loadEntities%5B%5D=paragraph&alias="
ICH_ALIASES = [
    "/page/quality-guidelines",
    "/page/safety-guidelines",
    "/page/efficacy-guidelines",
    "/page/multidisciplinary-guidelines",
]


# ── URL normalisation ──────────────────────────────────────────────────────────

def normalise_url(url: str) -> str:
    """Lowercase, strip trailing slash, drop query params."""
    if not url:
        return ""
    parsed = urlparse(url.lower().strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def normalise_title(title: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    if not title:
        return ""
    t = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", t).strip()


# ── RSS collection ─────────────────────────────────────────────────────────────

def collect_rss_feed(name: str, url: str) -> list[dict]:
    """Fetch and parse an RSS feed. Return list of normalized item dicts."""
    items = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        for entry in feed.entries:
            link = entry.get("link", "")
            if not link:
                continue
            items.append({
                "title": (entry.get("title", "") or "").strip(),
                "url": normalise_url(link),
                "raw_url": link,
                "guid": entry.get("id", ""),
                "pub_date": entry.get("published", ""),
                "feed_name": name,
            })
    except Exception as e:
        print(f"  RSS {name}: ERROR — {e}", file=sys.stderr)
    return items


# ── EMA JSON archive collector ─────────────────────────────────────────────────

def _classify_ema(title: str, url: str) -> str | None:
    """Mirror _classify_ema_record from fetch_feed.py."""
    t = title.lower()
    SKIP = (
        "/en/human-regulatory-overview/", "/en/veterinary-regulatory-overview/",
        "/en/about-us/", "/en/committees/", "/en/partners-networks/",
        "/en/medicines/", "/en/news", "/en/events/",
    )
    if any(url.lower().startswith("https://www.ema.europa.eu" + p) for p in SKIP):
        return None
    if "scientific guideline" in t:
        return "ema_sci_guidelines"
    if any(x in t for x in ("regulatory", "procedural", "guidance")):
        return "ema_reg_guidance"
    return None


def collect_ema_archive() -> list[dict]:
    """Download EMA bulk JSON, classify, return normalized items."""
    items = []
    try:
        r = requests.get(EMA_JSON_URL, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        records = data.get("data", []) if isinstance(data, dict) else data
        for rec in records:
            url = rec.get("general_url", "")
            if not url or url == "#":
                continue
            title = rec.get("title", "").strip()
            if not title:
                continue
            feed_id = _classify_ema(title, url)
            if not feed_id:
                continue
            items.append({
                "title": title,
                "url": normalise_url(url),
                "raw_url": url,
                "pub_date": rec.get("first_published_date", ""),
                "feed_name": feed_id,
                "source": "ema_archive",
            })
    except Exception as e:
        print(f"  EMA archive: ERROR — {e}", file=sys.stderr)
    return items


# ── FDA archive collector ──────────────────────────────────────────────────────

def collect_fda_archive() -> list[dict]:
    """Paginate FDA press announcements, extract title + URL, return normalized."""
    items = []
    seen = set()
    for page in range(MAX_FDA_PAGES):
        try:
            url = f"{FDA_BASE}?page={page}"
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                break
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "html.parser")
            links = soup.select("div.view-content a[href]")
            if not links:
                break
            page_items = 0
            for a in links:
                href = a.get("href", "")
                text = (a.get_text(strip=True) or "").strip()
                if len(text) < 20:
                    continue
                if "press-announcements" not in href:
                    continue
                full_url = urljoin("https://www.fda.gov", href)
                if full_url in seen:
                    continue
                seen.add(full_url)
                # Parse "Month DD, YYYY - Title" pattern
                m = re.match(r"^(\w+ \d+,\s*\d{4})\s*[-–]\s*(.+)$", text)
                title = m.group(2).strip() if m else text
                pub_date = m.group(1) if m else ""
                items.append({
                    "title": title,
                    "url": normalise_url(full_url),
                    "raw_url": full_url,
                    "pub_date": pub_date,
                    "feed_name": "fda_press_releases",
                    "source": "fda_archive",
                })
                page_items += 1
            if page_items == 0:
                break
            time.sleep(DELAY_FDA)
        except Exception as e:
            print(f"  FDA archive page {page}: ERROR — {e}", file=sys.stderr)
            break
    return items


# ── ICH archive collector ──────────────────────────────────────────────────────

def collect_ich_archive() -> list[dict]:
    """Hit ICH API subdivision endpoints, extract items, return normalized."""
    items = []
    for alias in ICH_ALIASES:
        try:
            url = ICH_API_BASE + alias
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            # Navigate to accordion items through page node
            page_node = (data.get("items") or [{}])[0]
            main_widgets = page_node.get("mainWidgets") or {}
            for widget_row in main_widgets.get("items", []):
                # widget_row is a list of widgets in this row
                row_items = widget_row if isinstance(widget_row, list) else [widget_row]
                for widget in row_items:
                    for accordion_group in widget.get("widgets", {}).get("items", []):
                        for accordion in accordion_group.get("accordions", {}).get("items", []):
                            for g in accordion.get("items", []):
                                if g.get("entityInfo", {}).get("bundle") != "accordion_group":
                                    continue
                                title_parts = []
                                code = g.get("code", "")
                                if code:
                                    title_parts.append(code.strip())
                                gtitle = g.get("title", "")
                                if gtitle:
                                    title_parts.append(gtitle.strip())
                                title = " — ".join(title_parts)
                                # Find PDF URL
                                pdf_url = ""
                                for fg in g.get("fileGroups", []):
                                    for f in fg.get("files", []):
                                        if f.get("mimetype") == "application/pdf":
                                            pdf_url = f.get("uri", "")
                                            break
                                    if pdf_url:
                                        break
                                if not pdf_url:
                                    continue
                                if pdf_url.startswith("/"):
                                    pdf_url = "https://www.ich.org" + pdf_url
                                items.append({
                                    "title": title,
                                    "url": normalise_url(pdf_url),
                                    "raw_url": pdf_url,
                                    "pub_date": g.get("details", {}).get("stepDate", ""),
                                    "feed_name": "ich_guidelines",
                                    "source": "ich_archive",
                                })
            time.sleep(DELAY_ICH)
        except Exception as e:
            print(f"  ICH archive {alias}: ERROR — {e}", file=sys.stderr)
    return items


# ── Matching logic ─────────────────────────────────────────────────────────────

def fuzzy_match(title_a: str, title_b: str) -> bool:
    """True if normalized titles share >80% token overlap."""
    ta = set(normalise_title(title_a).split())
    tb = set(normalise_title(title_b).split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    return overlap / max(len(ta), len(tb)) > 0.8


def compare_feeds(rss_items: list[dict], archive_items: list[dict]) -> dict:
    """Match RSS items against archive items by URL (exact) then title (fuzzy)."""
    archive_urls = {a["url"]: a for a in archive_items}
    archive_titles = [(a["title"], a) for a in archive_items]

    exact, fuzzy, no_match = [], [], []
    matched_archive_urls = set()

    for ritem in rss_items:
        # Exact URL match
        if ritem["url"] in archive_urls:
            exact.append(ritem)
            matched_archive_urls.add(ritem["url"])
            continue
        # Fuzzy title match
        found = False
        for atitle, aitem in archive_titles:
            if aitem["url"] in matched_archive_urls:
                continue
            if fuzzy_match(ritem["title"], atitle):
                fuzzy.append({"rss": ritem, "archive": aitem})
                matched_archive_urls.add(aitem["url"])
                found = True
                break
        if not found:
            no_match.append(ritem)

    return {"exact": exact, "fuzzy": fuzzy, "no_match": no_match}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RSS vs Archive dry-run comparison")
    parser.add_argument("--feed", help="Only check a single feed")
    parser.add_argument("--no-archive", action="store_true", help="Skip archive collection (RSS only)")
    parser.add_argument("--no-rss", action="store_true", help="Skip RSS collection (archive only)")
    args = parser.parse_args()

    print("=== RSS vs ARCHIVE DRY-RUN COMPARISON ===")
    print(f"Run date/time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Timeouts: {TIMEOUT}s per request\n")

    # ── RSS Collection ──────────────────────────────────────────────────────
    all_rss = {}
    feeds_to_check = {args.feed: RSS_FEEDS[args.feed]} if args.feed else RSS_FEEDS

    if not args.no_rss:
        print("[RSS FEEDS COLLECTED]")
        for name, url in feeds_to_check.items():
            items = collect_rss_feed(name, url)
            all_rss[name] = items
            dates = [i["pub_date"] for i in items if i["pub_date"]]
            dr = f"  Date range: {min(dates)} – {max(dates)}" if dates else ""
            print(f"  Feed: {name}  Items: {len(items)}{dr}")
        print()

    # ── Archive Collection ──────────────────────────────────────────────────
    all_archive = {}
    if not args.no_archive:
        print("[ARCHIVE ENDPOINTS COLLECTED]")
        # EMA JSON
        ema_items = collect_ema_archive()
        ema_reg = [i for i in ema_items if i["feed_name"] == "ema_reg_guidance"]
        ema_sci = [i for i in ema_items if i["feed_name"] == "ema_sci_guidelines"]
        all_archive["ema_reg_guidance"] = ema_reg
        all_archive["ema_sci_guidelines"] = ema_sci
        print(f"  EMA JSON:  {len(ema_items)} items  (reg={len(ema_reg)}, sci={len(ema_sci)})")

        # FDA
        fda_items = collect_fda_archive()
        all_archive["fda_press_releases"] = fda_items
        print(f"  FDA:       {len(fda_items)} items")

        # ICH
        ich_items = collect_ich_archive()
        all_archive["ich_guidelines"] = ich_items
        print(f"  ICH:       {len(ich_items)} items")
        print()

    if args.no_rss or args.no_archive:
        # Dump raw data if running single side
        for name, items in (all_rss or all_archive).items():
            print(f"\n{name} items:")
            for i in items[:20]:
                print(f"  {i['title'][:80]} | {i.get('raw_url', i.get('url',''))}")
        return

    # ── Overlap Analysis ────────────────────────────────────────────────────
    print("[OVERLAP ANALYSIS BY RSS FEED]")
    total_at_risk = 0
    all_no_match = {}

    for name in feeds_to_check:
        rss = all_rss.get(name, [])
        archive = all_archive.get(name, [])
        if not rss:
            print(f"\n  Feed: {name}\n    No RSS items collected — skipping")
            continue
        if not archive:
            print(f"\n  Feed: {name}\n    No archive items collected — all {len(rss)} RSS items at risk")

        result = compare_feeds(rss, archive)
        total = len(rss)
        exact_n = len(result["exact"])
        fuzzy_n = len(result["fuzzy"])
        no_n = len(result["no_match"])
        total_at_risk += no_n
        all_no_match[name] = result["no_match"]

        print(f"\n  Feed: {name}")
        print(f"    Total RSS items:   {total}")
        print(f"    Exact matches:     {exact_n}  ({exact_n/total*100:.1f}%)" if total else "    Exact matches:     0")
        print(f"    Fuzzy matches:     {fuzzy_n}  ({fuzzy_n/total*100:.1f}%)" if total else "    Fuzzy matches:     0")
        print(f"    No match (AT RISK): {no_n}  ({no_n/total*100:.1f}%)" if total else "    No match (AT RISK): 0")

    # ── No-Match Items ──────────────────────────────────────────────────────
    if total_at_risk > 0:
        print(f"\n[NO-MATCH ITEMS — POTENTIAL INFORMATION LOSS] ({total_at_risk} total)")
        for name, items in all_no_match.items():
            if not items:
                continue
            print(f"\n  Feed: {name} ({len(items)} items)")
            for i in sorted(items, key=lambda x: x.get("pub_date", ""), reverse=True)[:50]:
                print(f"    - {i['title'][:100]} | {i.get('raw_url', i['url'])[:100]} | {i.get('pub_date', '')}")

    # ── Archive-Only ────────────────────────────────────────────────────────
    print("\n[ARCHIVE-ONLY ITEMS — NOT A LOSS RISK]")
    for name in feeds_to_check:
        rss_urls = {i["url"] for i in all_rss.get(name, [])}
        archive_only = [a for a in all_archive.get(name, []) if a["url"] not in rss_urls]
        print(f"  {name} archive items not in RSS: {len(archive_only)}")

    # ── Verdict ─────────────────────────────────────────────────────────────
    print(f"\n[VERDICT]")
    if total_at_risk == 0:
        print("  RSS feeds safe to drop: YES")
    elif total_at_risk < 20:
        print(f"  RSS feeds safe to drop: CONDITIONAL — {total_at_risk} at-risk items")
    else:
        print(f"  RSS feeds safe to drop: NO — {total_at_risk} at-risk items")
    print(f"  At-risk item count: {total_at_risk}")


if __name__ == "__main__":
    main()
