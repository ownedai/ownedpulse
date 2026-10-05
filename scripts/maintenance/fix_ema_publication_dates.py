#!/usr/bin/env python3
"""
fix_ema_publication_dates.py — repair EMA publication dates stored with the
month and day swapped.

Why
---
EMA publishes `first_published_date` as ISO 8601, e.g. "2026-09-10T10:49:46Z".
Every release before the day-first parse was fixed read that as Y-D-M, so
2026-09-10 was stored as 2026-10-09. Values whose day exceeded 12 could not be
swapped, so dateutil fell back to the correct reading and roughly a third of
EMA records ended up silently wrong.

Where publication_date is stored
--------------------------------
1. `document_registry.publication_date`            (DATE column, indexed)
2. `document_registry.metadata_json->>'publication_date'`
3. archive `metadata.json` sidecar                 (`publication_date`, `pub_date`)
4. Qdrant chunk payload `publication_date`         — NOT touched here

`document_registry_ext` is a view over `document_registry`, so (1) covers it.
`chunks`, `ingestion_doc`, `ingestion_state` and `run_log` carry no
publication date. `query_history.citations` embeds the citation dates of past
answers; that is a historical record and is left alone.

This script repairs stores 1–3. Store 4 is repaired by the reset + Initial
Load that must follow: chunk payloads are rebuilt from the archive sidecar at
ingestion time, and the sidecar is the value this script corrects.

Order of operations
-------------------
    python3 scripts/maintenance/fix_ema_publication_dates.py            # dry run
    python3 scripts/maintenance/fix_ema_publication_dates.py --apply \
            --backup-dir /opt/ownedpulse/backups/date-fix-<ts>
    # then reset the corpus and run Initial Load

Usage
-----
    python3 scripts/maintenance/fix_ema_publication_dates.py
    python3 scripts/maintenance/fix_ema_publication_dates.py --apply --backup-dir DIR

Required for --apply: --backup-dir. Every archive sidecar that will change is
archived into it as a single tar.gz before any write, and a CSV changelog is
written alongside. Database updates run in one transaction. The script is
idempotent: a second run reports zero changes.
"""

import argparse
import csv
import json
import os
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
# scripts/ for the rss package (which owns the date parser), api/ for lib.db.
sys.path.insert(0, str(_HERE.parents[1]))
sys.path.insert(0, str(_HERE.parents[2] / "api"))

# rss.fetch_feed imports ingestion.config, which requires PG_DSN at import time.
# The api container carries POSTGRES_* rather than PG_DSN, so synthesise it.
if not os.environ.get("PG_DSN"):
    _u = os.environ.get("POSTGRES_USER", "postgres")
    _p = os.environ.get("POSTGRES_PASSWORD", "")
    _h = os.environ.get("POSTGRES_HOST", "postgres")
    _port = os.environ.get("POSTGRES_PORT", "5432")
    _db = os.environ.get("POSTGRES_DB", "knowledge_base")
    os.environ["PG_DSN"] = f"postgresql://{_u}:{_p}@{_h}:{_port}/{_db}"

from rss.fetch_feed import EMA_JSON_URL, EMA_HEADERS, parse_feed_date  # noqa: E402
from lib.db import get_pg_conn  # noqa: E402

import requests  # noqa: E402

SAMPLE_ROWS = 10


def fetch_ema_dates() -> dict:
    """Return {document_url: 'YYYY-MM-DD'} from the live EMA bulk JSON."""
    log(f"Fetching {EMA_JSON_URL}")
    r = requests.get(EMA_JSON_URL, headers=EMA_HEADERS, timeout=120)
    r.raise_for_status()
    try:
        data = r.json()
    except json.JSONDecodeError:
        # EMA JSON sometimes has missing commas between records.
        data = json.loads(re.sub(r'\}\s*\{', '}, {', r.text))
    records = data.get("data", data) if isinstance(data, dict) else data

    out = {}
    for rec in records:
        url = (rec.get("document_url") or "").strip()
        if not url:
            continue
        iso = parse_feed_date(rec.get("first_published_date", ""))
        if iso:
            out[url] = iso
    log(f"EMA records with a URL and a parseable date: {len(out)}")
    return out


def log(msg: str) -> None:
    print(msg, flush=True)


def collect_changes(ema_dates: dict) -> tuple[list, dict]:
    """Compare stored EMA dates against the feed. Returns (changes, stats)."""
    overrides = {}
    if os.environ.get("REGULATORY_ARCHIVE_PATH"):
        overrides["/archive"] = os.environ["REGULATORY_ARCHIVE_PATH"]

    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT document_id, publication_date,
               metadata_json->>'publication_date', source_url, archive_path
        FROM document_registry
        WHERE source_url LIKE '%%ema.europa.eu%%'
        ORDER BY document_id
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    changes = []
    stats = {"rows": len(rows), "matched": 0, "unmatched": 0, "already_correct": 0}

    for doc_id, col_date, meta_date, source_url, archive_path in rows:
        want = ema_dates.get((source_url or "").strip())
        if not want:
            stats["unmatched"] += 1
            continue
        stats["matched"] += 1

        col_iso = col_date.isoformat() if hasattr(col_date, "isoformat") else (col_date or None)
        meta_iso = meta_date or None

        sidecar_path = None
        sidecar = {}
        if archive_path:
            p = Path(archive_path) / "metadata.json"
            for container_prefix, host_prefix in overrides.items():
                if str(p).startswith(container_prefix):
                    p = Path(host_prefix + str(p)[len(container_prefix):])
            sidecar_path = p
            if p.exists():
                try:
                    sidecar = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    sidecar = {}

        sc_pub = sidecar.get("publication_date") or None
        sc_pubdate = sidecar.get("pub_date") or None

        entry = {"doc_id": doc_id, "want": want, "sidecar_path": sidecar_path,
                 "sidecar": sidecar, "diffs": []}
        if col_iso != want:
            entry["diffs"].append(("registry_column", col_iso, want))
        if meta_iso != want:
            entry["diffs"].append(("registry_metadata_json", meta_iso, want))
        if sc_pub is not None and sc_pub != want:
            entry["diffs"].append(("archive_sidecar.publication_date", sc_pub, want))
        if sc_pubdate is not None and sc_pubdate != want:
            entry["diffs"].append(("archive_sidecar.pub_date", sc_pubdate, want))

        if entry["diffs"]:
            changes.append(entry)
        else:
            stats["already_correct"] += 1

    return changes, stats


def report(changes: list, stats: dict) -> dict:
    per_store = {}
    for c in changes:
        for store, _old, _new in c["diffs"]:
            per_store[store] = per_store.get(store, 0) + 1

    log("")
    log("=== inventory ===")
    log(f"  EMA registry rows examined     : {stats['rows']}")
    log(f"  matched to a feed record       : {stats['matched']}")
    log(f"  unmatched (no feed record)     : {stats['unmatched']}")
    log(f"  already correct                : {stats['already_correct']}")
    log(f"  documents needing a fix        : {len(changes)}")
    log("")
    log("=== changes per store ===")
    for store in ("registry_column", "registry_metadata_json",
                  "archive_sidecar.publication_date", "archive_sidecar.pub_date"):
        log(f"  {store:34s} {per_store.get(store, 0)}")

    if changes:
        log("")
        log("=== sample (doc_id, store, old -> new) ===")
        shown = 0
        for c in changes:
            for store, old, new in c["diffs"]:
                if shown >= SAMPLE_ROWS:
                    break
                log(f"  {c['doc_id'][:46]:46s} {store:34s} {old} -> {new}")
                shown += 1
            if shown >= SAMPLE_ROWS:
                break
    return per_store


def apply_changes(changes: list, backup_dir: Path, csv_path: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 1. Back up every sidecar that will change, before anything is written.
    to_backup = [c["sidecar_path"] for c in changes
                 if c["sidecar_path"] and c["sidecar_path"].exists()
                 and any(s.startswith("archive_sidecar") for s, _, _ in c["diffs"])]
    if to_backup:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        tar_path = backup_dir / f"ema-metadata-sidecars-{ts}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            for p in sorted(set(to_backup)):
                tf.add(str(p), arcname=str(p).lstrip("/"))
        log(f"  sidecars backed up: {len(set(to_backup))} -> {tar_path} "
            f"({tar_path.stat().st_size} bytes)")

    # 2. CSV changelog.
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["document_id", "store", "old", "new"])
        for c in changes:
            for store, old, new in c["diffs"]:
                w.writerow([c["doc_id"], store, old or "", new])
    log(f"  changelog: {csv_path}")

    # 3. Database — one transaction.
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        n = 0
        for c in changes:
            cur.execute(
                """
                UPDATE document_registry
                   SET publication_date = %s::date,
                       metadata_json = jsonb_set(
                           COALESCE(metadata_json, '{}'::jsonb),
                           '{publication_date}', to_jsonb(%s::text), true),
                       updated_at = NOW()
                 WHERE document_id = %s
                """,
                (c["want"], c["want"], c["doc_id"]),
            )
            n += cur.rowcount
        conn.commit()
        cur.close()
        log(f"  registry rows updated: {n}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 4. Archive sidecars.
    written = 0
    for c in changes:
        p = c["sidecar_path"]
        if not p or not p.exists():
            continue
        if not any(s.startswith("archive_sidecar") for s, _, _ in c["diffs"]):
            continue
        data = c["sidecar"]
        if "publication_date" in data:
            data["publication_date"] = c["want"]
        if "pub_date" in data:
            data["pub_date"] = c["want"]
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        written += 1
    log(f"  sidecars rewritten: {written}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default: dry run)")
    ap.add_argument("--backup-dir", default=None,
                    help="required with --apply: archive sidecars are tar.gz'd here first")
    ap.add_argument("--csv", default=None,
                    help="changelog path (default: <backup-dir>/ema-date-changes.csv)")
    args = ap.parse_args()

    if args.apply and not args.backup_dir:
        ap.error("--backup-dir is required with --apply")

    ema_dates = fetch_ema_dates()
    changes, stats = collect_changes(ema_dates)
    per_store = report(changes, stats)

    if not args.apply:
        log("")
        log("DRY RUN — nothing written. Re-run with --apply --backup-dir DIR")
        return 0

    if not changes:
        log("")
        log("Nothing to change — already correct.")
        return 0

    backup_dir = Path(args.backup_dir)
    csv_path = Path(args.csv) if args.csv else backup_dir / "ema-date-changes.csv"
    log("")
    log("=== applying ===")
    apply_changes(changes, backup_dir, csv_path)
    log("")
    log(f"Done. {len(changes)} documents changed. Re-run without --apply to confirm 0 changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
