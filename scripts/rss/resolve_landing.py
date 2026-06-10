#!/usr/bin/env python3
"""
resolve_landing.py — F4: Resolve landing page, download content
Location: /opt/scripts/rss/resolve_landing.py

Input:  --url <url>  --feed-id <id>  [--title <t>]  [--authority <a>]
        OR stdin JSON from fetch_feed output
Output: JSON: {doc_id, file_path, content_type, sha256, extracted_metadata}
Exit:   0 on success, 1 on error
"""

import os, sys, re, json, hashlib, argparse, random, time, requests
from dateutil import parser as dateparser
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

HEADERS      = {"User-Agent": "ownedai-regulatory-pipeline/1.0"}
TEMP_DIR     = Path(os.environ.get("RSS_TEMP_DIR", "/tmp/rss_resolve"))
MAX_HTML_SIZE = 5 * 1024 * 1024


def make_doc_id(feed_id: str, url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    path = re.sub(r"[^a-z0-9\-]", "-", path.lower())[:40].strip("-")
    return f"{feed_id}-{path}-{url_hash}" if path else f"{feed_id}-{url_hash}"

BINARY_EXTENSIONS = {'.docx', '.xlsx', '.xls', '.doc', '.pptx', '.ppt', '.zip', '.rar', '.odt', '.ods'}

def is_pdf_url(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf")

def is_binary_url(url: str) -> bool:
    ext = "." + url.lower().split("?")[0].rsplit(".", 1)[-1] if "." in url.split("?")[0] else ""
    return ext in BINARY_EXTENSIONS

def find_pdf_link(soup, base_url: str, authority: str):
    candidates = [urljoin(base_url, a["href"]) for a in soup.find_all("a", href=True)
                  if is_pdf_url(urljoin(base_url, a["href"]))]
    if not candidates:
        return None
    if authority and authority.upper() == "EMA" and len(candidates) > 1:
        return max(candidates, key=len)
    return candidates[0]

def _extract_version_structured(soup, source_url: str = "") -> str:
    """
    Extract document version using structured sources in priority order.
    Returns "" if no reliable version found.
    Never falls back to loose full-page text scan.
    """

    # 1. JSON-LD — schema.org structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else data.get("@graph", [data])
            for item in items:
                for key in ("version", "schemaVersion", "softwareVersion", "edition"):
                    val = item.get(key, "")
                    if val and isinstance(val, str) and len(val.strip()) > 0:
                        return val.strip()
        except Exception:
            pass

    # 2. HTML meta tags
    meta_candidates = [
        ("name",     "DC.description"),
        ("name",     "citation_technical_report_number"),
        ("name",     "citation_series_title"),
        ("property", "og:description"),
        ("name",     "version"),
        ("name",     "document-version"),
        ("name",     "revision"),
    ]
    for attr, val in meta_candidates:
        tag = soup.find("meta", {attr: re.compile(val, re.IGNORECASE)})
        if tag:
            content = tag.get("content", "").strip()
            if content:
                m = re.search(
                    r"(?:revision|version|rev\.?|step|draft|edition)\s*[\d][\d\.\s\-\(\)a-zA-Z]*",
                    content, re.IGNORECASE,
                )
                if m:
                    return m.group(0).strip()

    # 3. Source-specific DOM selectors

    # EMA
    if "ema.europa.eu" in source_url:
        for dt in soup.find_all("dt"):
            label = dt.get_text(strip=True).lower()
            if any(k in label for k in ("revision", "version", "status")):
                dd = dt.find_next_sibling("dd")
                if dd:
                    text = dd.get_text(strip=True)
                    m = re.search(r"(?:revision|rev\.?|version)\s*\d[\d\.]*", text, re.IGNORECASE)
                    if m:
                        return m.group(0).strip()
        for tag in soup.find_all(["h1", "h2", "h3", "p"], limit=5):
            text = tag.get_text(" ", strip=True)
            m = re.search(r"\b(?:revision|rev\.)\s*\d[\d\.]*", text, re.IGNORECASE)
            if m:
                return m.group(0).strip()

    # FDA
    if "fda.gov" in source_url:
        for div in soup.find_all("div", class_=re.compile(r"field--name", re.IGNORECASE)):
            label_tag = div.find(class_=re.compile(r"field--label", re.IGNORECASE))
            value_tag = div.find(class_=re.compile(r"field--item", re.IGNORECASE))
            if label_tag and value_tag:
                label = label_tag.get_text(strip=True).lower()
                if "version" in label or "revision" in label:
                    return value_tag.get_text(strip=True)
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                if "version" in label or "revision" in label:
                    val = cells[1].get_text(strip=True)
                    if val:
                        return val

    # ICH
    if "ich.org" in source_url:
        for tag in soup.find_all(["h1", "h2", "h3", "p"], limit=10):
            text = tag.get_text(" ", strip=True)
            m = re.search(r"\bStep\s*\d[\d\.]*(?:\s*\(\d{4}[^\)]*\))?", text, re.IGNORECASE)
            if m:
                return m.group(0).strip()

    # 4. Heading / title proximity match (h1, h2, title only)
    for tag in soup.find_all(["title", "h1", "h2"], limit=6):
        text = tag.get_text(" ", strip=True)
        m = re.search(
            r"(?:revision|version|rev\.?|step|draft|edition|final\s+rule)\s*"
            r"(\d[\d\.]*(?:\s*\(\d{4}[^\)]*\))?)",
            text, re.IGNORECASE,
        )
        if m:
            return m.group(0).strip()

    return ""


def extract_metadata(soup, fallback_title: str = "", fallback_url: str = "") -> dict:
    meta = {"title": fallback_title, "pub_date": "", "version": ""}
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        meta["title"] = og["content"].strip()
    elif soup.title and soup.title.string:
        meta["title"] = soup.title.string.strip()
    tt = soup.find("time")
    if tt:
        try:
            dt = dateparser.parse(tt.get("datetime") or tt.get_text(strip=True))
            meta["pub_date"] = dt.date().isoformat() if dt else ""
        except Exception:
            pass
    meta["version"] = _extract_version_structured(soup, source_url=fallback_url)
    return meta

def download_pdf(url: str, dest: Path) -> str:
    r = _request_with_retry(url, stream=True, timeout=30, is_ema=("ema.europa.eu" in url))
    sha256 = hashlib.sha256()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk); sha256.update(chunk)
    # Validate the downloaded file is a real PDF — not an error page
    file_size = dest.stat().st_size
    if file_size < 1024:
        dest.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded PDF is too small ({file_size} bytes) — "
            f"likely an error page or empty response. URL: {url}"
        )
    with open(dest, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            dest.unlink(missing_ok=True)
            raise ValueError(
                f"Downloaded file does not have PDF magic bytes — "
                f"likely an HTML error page served with wrong Content-Type. URL: {url}"
            )
    return sha256.hexdigest()

def _request_with_retry(url: str, stream: bool = False, timeout: int = 60,
                        is_ema: bool = False) -> requests.Response:
    """GET with exponential backoff on 429/5xx and connection errors."""
    base_delay = 10 if is_ema else 5
    max_attempts = 5 if is_ema else 4
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout,
                            allow_redirects=True, stream=stream)
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 3)
                time.sleep(delay)
                continue
            raise
        if r.status_code == 429 or r.status_code >= 500:
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 3)
                time.sleep(delay)
                continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def fetch_html(url: str):
    r = _request_with_retry(url, is_ema=("ema.europa.eu" in url))
    return r, BeautifulSoup(r.text[:MAX_HTML_SIZE], "html.parser")

def extract_date_from_filename(url: str) -> str:
    decoded = unquote(url)
    # Pattern 1: _YYYY_MMDD or _YYYY_MM
    m = re.search(r'_(\d{4})_(\d{2})(\d{2})?', decoded)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3) or "01"
        return f"{y}-{mo}-{d}"
    # Pattern 2: _DD Month YYYY_
    m = re.search(r'_(\d{1,2}\s+\w+\s+\d{4})_', decoded)
    if m:
        try:
            return dateparser.parse(m.group(1)).date().isoformat()
        except Exception:
            pass
    # Pattern 3: year only _YYYY. or _YYYY_0
    m = re.search(r'_(\d{4})(?:_0|\.pdf)', decoded)
    if m:
        return f"{m.group(1)}-01-01"
    return ""


def resolve(url: str, feed_id: str, title: str = "", authority: str = "") -> dict:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    doc_id   = make_doc_id(feed_id, url)
    item_dir = TEMP_DIR / doc_id
    item_dir.mkdir(parents=True, exist_ok=True)
    # Rate-limiting: EMA aggressively 429s. Delay between requests with jitter.
    if 'ema.europa.eu' in url:
        time.sleep(5 + random.uniform(0, 3))
    if is_pdf_url(url):
        dest = item_dir / "source.pdf"
        sha256 = download_pdf(url, dest)
        pub_date = extract_date_from_filename(url)
        return {"doc_id":doc_id,"file_path":str(dest),"content_type":"pdf",
                "sha256":sha256,"extracted_metadata":{"title":title,
                "pub_date":pub_date,"version":""}}
    if is_binary_url(url):
        ext = "." + url.lower().split("?")[0].rsplit(".", 1)[-1]
        return {"status": "unsupported", "doc_id": doc_id,
                "reason": f"Binary file format: {ext}"}
    r, soup = fetch_html(url)
    metadata = extract_metadata(soup, fallback_title=title, fallback_url=url)
    pdf_url  = find_pdf_link(soup, url, authority)
    if pdf_url:
        dest = item_dir / "source.pdf"
        sha256 = download_pdf(pdf_url, dest)
        return {"doc_id":doc_id,"file_path":str(dest),"content_type":"pdf",
                "sha256":sha256,"extracted_metadata":metadata,"pdf_url":pdf_url}
    # Reject pages that yielded no substantive content — typically JS-rendered
    # pages where requests.get() only retrieved a bare HTML shell (e.g. ICH
    # navigation pages that produce only their <title> text, ~27 chars).
    MIN_BODY_CHARS = 200
    body_text = soup.get_text(" ", strip=True)
    if len(body_text) < MIN_BODY_CHARS:
        raise ValueError(
            f"Extracted body too short ({len(body_text)} chars, minimum {MIN_BODY_CHARS}): "
            f"likely a JavaScript-rendered page with no static content. "
            f"URL: {url}"
        )
    # Write raw HTML so downstream ingestion can re-parse it with newlines
    # preserved — extracting to text here loses structure needed for chunking.
    dest   = item_dir / "source.html"
    dest.write_text(r.text, encoding="utf-8")
    sha256 = hashlib.sha256(r.text.encode()).hexdigest()
    return {"doc_id":doc_id,"file_path":str(dest),"content_type":"html",
            "sha256":sha256,"extracted_metadata":metadata}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None)
    parser.add_argument("--feed-id", default=None)
    parser.add_argument("--title", default="")
    parser.add_argument("--authority", default="")
    args = parser.parse_args()
    url = args.url; feed_id = args.feed_id
    title = args.title; authority = args.authority
    if not url and not sys.stdin.isatty():
        try:
            stdin = json.load(sys.stdin)
            url       = url       or stdin.get("url")
            feed_id   = feed_id   or stdin.get("feed_id")
            title     = title     or stdin.get("title","")
            authority = authority or stdin.get("authority","")
        except Exception:
            pass
    if not url or not feed_id:
        sys.stderr.write(json.dumps({"status":"error","detail":"--url and --feed-id required"}))
        sys.exit(1)
    try:
        result = resolve(url, feed_id, title, authority)
        sys.stdout.write(json.dumps(result)); sys.stdout.flush(); sys.exit(0)
    except Exception as e:
        sys.stderr.write(json.dumps({"status":"error","detail":str(e),"url":url}))
        sys.exit(1)

if __name__ == "__main__":
    main()
