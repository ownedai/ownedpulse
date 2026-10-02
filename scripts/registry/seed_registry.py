#!/usr/bin/env python3
"""
seed_registry.py — Reads corpus_manifest.json, downloads missing source files,
and upserts base corpus documents into document_registry with corpus_doc=TRUE.

Usage:
    python3 seed_registry.py [--dry-run] [--manifest /path/to/corpus_manifest.json]
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_DEFAULT = "/app/config/corpus_manifest.json"

if not os.environ.get("POSTGRES_PASSWORD"):
    sys.exit("seed_registry: POSTGRES_PASSWORD not set — refusing to run")

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "ownedpulse-postgres"),
    "port": int(os.environ.get("POSTGRES_PORT", 5432)),
    "dbname": os.environ.get("POSTGRES_DB", "ownedpulse"),
    "user": os.environ.get("POSTGRES_USER", "ownedpulse"),
    "password": os.environ["POSTGRES_PASSWORD"],
}

SQL_UPSERT = """
INSERT INTO document_registry (
    document_id, document_class, document_type, document_status,
    document_version, archive_path, source_url, source_hash,
    source_fetched_at, issuing_body, company_id,
    corpus_doc, document_family_id, metadata_json, publication_date
) VALUES (
    %(document_id)s, %(document_class)s, %(document_type)s, %(document_status)s,
    %(document_version)s, %(archive_path)s, %(source_url)s, %(source_hash)s,
    %(source_fetched_at)s, %(issuing_body)s, %(company_id)s,
    TRUE, %(document_family_id)s, %(metadata_json)s::jsonb, %(publication_date)s
)
ON CONFLICT (document_id) DO UPDATE SET
    document_class      = EXCLUDED.document_class,
    document_type       = EXCLUDED.document_type,
    document_status     = EXCLUDED.document_status,
    document_version    = EXCLUDED.document_version,
    archive_path        = EXCLUDED.archive_path,
    source_url          = EXCLUDED.source_url,
    source_hash         = EXCLUDED.source_hash,
    source_fetched_at   = EXCLUDED.source_fetched_at,
    issuing_body        = EXCLUDED.issuing_body,
    corpus_doc          = TRUE,
    document_family_id  = EXCLUDED.document_family_id,
    metadata_json       = EXCLUDED.metadata_json,
    publication_date    = COALESCE(EXCLUDED.publication_date, document_registry.publication_date),
    updated_at          = NOW();
"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


PDF_MAGIC = b"%PDF"
MIN_FILE_SIZE = 1000  # anything smaller is almost certainly an error page


def _validate_download(path: Path, filename: str) -> bool:
    """Return True if the file looks like valid content for its expected type."""
    if not path.exists():
        return False
    size = path.stat().st_size
    if size < MIN_FILE_SIZE:
        return False
    if filename.endswith(".pdf"):
        try:
            with open(path, "rb") as f:
                return f.read(4) == PDF_MAGIC
        except OSError:
            return False
    return True


def download_file(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success.
    Routes EMA URLs through EMA_PROXY if set (SOCKS5 proxy for geo-blocked regions).
    """
    import requests as _requests
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        is_ema = "ema.europa.eu" in url
        _proxy = os.environ.get("EMA_PROXY") if is_ema else None
        _proxies = {"http": _proxy, "https": _proxy} if _proxy else None
        if is_ema:
            # CloudFront CDN requires browser-like headers with Referer
            _headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/pdf,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.ema.europa.eu/en/search",
            }
        else:
            _headers = {"User-Agent": "OwnedPulse/1.0"}
        if _proxy:
            _headers["Accept-Encoding"] = "identity"
        r = _requests.get(url, headers=_headers, timeout=60,
                          proxies=_proxies, allow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  [ERROR] Download failed for {url}: {e}", file=sys.stderr)
        return False


def connect_db(config: dict):
    try:
        import psycopg2
        return psycopg2.connect(**config)
    except ImportError:
        print("psycopg2 not installed.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"DB connection failed: {e}", file=sys.stderr)
        sys.exit(1)


def build_row(doc: dict, source_path: Path, fetch_time: datetime) -> dict:
    raw_date = doc.get("publication_date")
    pub_date = None
    if raw_date:
        try:
            from dateutil import parser as dp
            pub_date = dp.parse(str(raw_date), default=datetime(1900, 1, 1)).date()
        except Exception:
            pass

    source_hash = sha256_file(source_path) if source_path.exists() else None

    metadata = {
        "document_id": doc["document_id"],
        "document_title": doc.get("title"),
        "title": doc.get("title"),
        "document_class": doc["document_class"],
        "document_type": doc["document_type"],
        "document_status": doc["document_status"],
        "document_version": doc.get("document_version"),
        "issuing_body": doc.get("issuing_body"),
        "source_url": doc.get("source_url"),
        "source_hash": source_hash,
        "corpus_doc": True,
    }

    return {
        "document_id": doc["document_id"],
        "document_class": doc["document_class"],
        "document_type": doc["document_type"],
        "document_status": doc["document_status"],
        "document_version": doc.get("document_version"),
        "archive_path": doc["archive_path"],
        "source_url": doc.get("source_url"),
        "source_hash": source_hash,
        "source_fetched_at": fetch_time if source_hash else None,
        "issuing_body": doc.get("issuing_body"),
        "company_id": None,
        "document_family_id": doc.get("document_family_id"),
        "metadata_json": json.dumps(metadata),
        "publication_date": pub_date,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=MANIFEST_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    docs = manifest["documents"]
    print(f"Manifest: {len(docs)} documents\n")

    fetch_time = datetime.now(timezone.utc)
    rows = []

    for doc in docs:
        doc_id = doc["document_id"]
        archive_path = Path(doc["archive_path"])
        source_filename = doc.get("source_filename", "source.pdf")
        source_path = archive_path / source_filename
        download_url = doc.get("download_url")

        print(f"[{doc_id}]")
        print(f"  archive_path : {archive_path}")
        print(f"  source_file  : {source_path}")

        if source_path.exists():
            size = source_path.stat().st_size
            valid = _validate_download(source_path, source_filename)
            if valid:
                print(f"  file         : EXISTS ({size:,} bytes)")
            else:
                print(f"  file         : EXISTS but invalid ({size:,} bytes) — re-downloading")
                source_path.unlink()
                ok = download_file(download_url, source_path) if download_url else False
                if ok:
                    size = source_path.stat().st_size
                    print(f"  file         : re-downloaded ({size:,} bytes)")
                else:
                    print(f"  file         : REDOWNLOAD FAILED — skipping DB registration")
                    continue
        elif download_url and not args.dry_run:
            print(f"  file         : MISSING — downloading from {download_url}")
            ok = download_file(download_url, source_path)
            if ok:
                size = source_path.stat().st_size
                print(f"  file         : downloaded ({size:,} bytes)")
            else:
                print(f"  file         : DOWNLOAD FAILED — skipping DB registration")
                continue
        else:
            if args.dry_run:
                print(f"  file         : MISSING (dry-run, would download from {download_url})")
            else:
                print(f"  file         : MISSING and no download_url — skipping")
                continue

        row = build_row(doc, source_path, fetch_time)
        rows.append(row)
        print(f"  corpus_doc   : TRUE  |  hash={row['source_hash'] and row['source_hash'][:12]}...")
        print()

    print(f"Total rows to upsert: {len(rows)}")

    if args.dry_run:
        print("\nDRY RUN — no changes written.")
        return

    conn = connect_db(DB_CONFIG)
    cur = conn.cursor()
    success = 0
    for row in rows:
        try:
            cur.execute(SQL_UPSERT, row)
            success += 1
        except Exception as e:
            print(f"  [ERROR] {row.get('document_id', '?')}: {e}", file=sys.stderr)
            conn.rollback()
    conn.commit()
    cur.close()
    conn.close()

    print(f"\nDone. {success}/{len(rows)} documents upserted (corpus_doc=TRUE).")


if __name__ == "__main__":
    main()
