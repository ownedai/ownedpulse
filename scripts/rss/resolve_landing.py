#!/usr/bin/env python3
"""
resolve_landing.py — F4: Resolve landing page, download content
Location: /opt/scripts/rss/resolve_landing.py

Input:  --url <url>  --feed-id <id>  [--title <t>]  [--authority <a>]
        OR stdin JSON from fetch_feed output
Output: JSON: {doc_id, file_path, content_type, sha256, extracted_metadata}
Exit:   0 on success, 1 on error
"""

import os, sys, re, json, hashlib, argparse, requests
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

def extract_metadata(soup, fallback_title: str = "") -> dict:
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
    vm = re.search(r"(?:revision|version|rev\.?|v\.)\s*(\d[\d\.]*)",
                   soup.get_text(" ", strip=True), re.IGNORECASE)
    if vm:
        meta["version"] = vm.group(1)
    return meta

def download_pdf(url: str, dest: Path) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
    r.raise_for_status()
    sha256 = hashlib.sha256()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk); sha256.update(chunk)
    return sha256.hexdigest()

def fetch_html(url: str):
    r = requests.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
    r.raise_for_status()
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
    if is_pdf_url(url):
        dest = item_dir / "source.pdf"
        sha256 = download_pdf(url, dest)
        pub_date = extract_date_from_filename(url)
        return {"doc_id":doc_id,"file_path":str(dest),"content_type":"pdf",
                "sha256":sha256,"extracted_metadata":{"title":title,
                "pub_date":pub_date,"version":""}}
    if is_binary_url(url):
        raise ValueError("Unsupported file format")
    r, soup = fetch_html(url)
    metadata = extract_metadata(soup, fallback_title=title)
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
