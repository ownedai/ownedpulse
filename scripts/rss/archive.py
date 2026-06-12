#!/usr/bin/env python3
"""
archive.py — F5a: Archive source file and register in document_registry
Location: /opt/scripts/rss/archive.py

Input:  stdin JSON — merged fetch_feed + resolve_landing output
Output: JSON: {doc_id, archive_path, status}
Exit:   0 on success, 1 on error
"""

import os, sys, json, shutil, psycopg2
from datetime import datetime, timezone
from pathlib import Path

import re as _re
_URL_DATE_PAT = _re.compile(r'[_-](\d{4})[_-](\d{2})(\d{2})?(?:\.[a-z]+)?(?:$|[^0-9])', _re.IGNORECASE)

def _parse_date(val):
    """Return a date object from ISO or free-text string, or None."""
    if not val:
        return None
    try:
        from dateutil import parser as dp
        return dp.parse(str(val), default=datetime(1900, 1, 1)).date()
    except Exception:
        return None

def _date_from_url(url):
    """Extract a date from an ICH-style URL filename: _YYYY_MMDD or _YYYY_MM."""
    if not url:
        return None
    m = _URL_DATE_PAT.search(url)
    if not m:
        return None
    yyyy, mm, dd = m.group(1), m.group(2), m.group(3) or '01'
    try:
        from datetime import date
        return date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return None


import sys
sys.path.insert(0, '/opt/scripts')
from ingestion.config import PG_DSN, ARCHIVE_ROOT as _ARCHIVE_ROOT
ARCHIVE_ROOT = Path(_ARCHIVE_ROOT)


def get_kb():
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("SET search_path TO public")
    return conn


def register(item: dict, archive_dir: Path, content_type: str):
    meta     = item.get('extracted_metadata', {})
    raw_date = meta.get('pub_date') or item.get('pub_date') or None
    pub_date = _parse_date(raw_date) or _date_from_url(item.get('url', ''))
    conn = get_kb()
    with conn.cursor() as c:
        # GATE3b: identity-only upsert — state columns removed
        c.execute(
            'INSERT INTO document_registry '
            '(document_id, source_url, source_hash, source_fetched_at, '
            'archive_path, issuing_body, feed_id, '
            'document_class, document_type, document_status, document_version, '
            'metadata_json, publication_date, created_at, updated_at) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()) '
            'ON CONFLICT (document_id) DO UPDATE SET '
            'source_url=EXCLUDED.source_url, source_hash=EXCLUDED.source_hash, '
            'source_fetched_at=EXCLUDED.source_fetched_at, archive_path=EXCLUDED.archive_path, '
            'publication_date=COALESCE(EXCLUDED.publication_date, document_registry.publication_date), '
            'updated_at=NOW()',
            (
                item['doc_id'], item.get('pdf_url') or item.get('url',''), item.get('sha256',''),
                datetime.now(timezone.utc), str(archive_dir),
                item.get('authority',''), item.get('feed_id',''),
                'regulatory', content_type, 'active',
                meta.get('version',''),
                json.dumps({'doc_id': item['doc_id'], 'feed_id': item.get('feed_id','')}),
                pub_date,
            )
        )
    conn.close()


def archive(item: dict) -> dict:
    doc_id       = item["doc_id"]
    authority    = item.get("authority","unknown").lower()
    file_path    = Path(item["file_path"])
    content_type = item["content_type"]
    sha256       = item["sha256"]
    meta         = item.get("extracted_metadata",{})

    archive_dir = ARCHIVE_ROOT / authority / doc_id
    archive_dir.mkdir(parents=True, exist_ok=True)

    ext  = ".pdf" if content_type == "pdf" else ".html"
    dest = archive_dir / f"source{ext}"
    shutil.copy2(file_path, dest)
    (archive_dir / "source.sha256").write_text(sha256, encoding="utf-8")

    metadata_record = {
        "doc_id":           doc_id,
        "source_url":       item.get("pdf_url") or item.get("url",""),
        "authority":        item.get("authority",""),
        "feed_id":          item.get("feed_id",""),
        "title":            meta.get("title") or item.get("title",""),
        "pub_date":         meta.get("pub_date") or item.get("pub_date",""),
        "version":          meta.get("version",""),
        "content_type":     content_type,
        "sha256":           sha256,
        "archived_at":      datetime.now(timezone.utc).isoformat(),
        "rss_body":         item.get("rss_body",""),
        "feed_item_guid":   item.get("feed_item_guid",""),
        "document_family_id": item.get("document_family_id",""),
    }
    (archive_dir / "metadata.json").write_text(
        json.dumps(metadata_record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    register(item, archive_dir, content_type)
    return {"doc_id": doc_id, "archive_path": str(archive_dir), "status": "ok"}

def main():
    if sys.stdin.isatty():
        sys.stderr.write(json.dumps({"status":"error","detail":"requires stdin JSON"}))
        sys.exit(1)
    try:
        item = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        sys.stderr.write(json.dumps({"status":"error","detail":f"Invalid JSON: {e}"}))
        sys.exit(1)
    missing = [f for f in ["doc_id","file_path","content_type","sha256"] if not item.get(f)]
    if missing:
        sys.stderr.write(json.dumps({"status":"error","detail":f"Missing: {missing}"}))
        sys.exit(1)
    try:
        result = archive(item)
        sys.stdout.write(json.dumps(result)); sys.stdout.flush(); sys.exit(0)
    except Exception as e:
        sys.stderr.write(json.dumps({"status":"error","detail":str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
