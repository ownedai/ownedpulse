#!/usr/bin/env python3
"""
run_pipeline.py — full RSS ingestion pipeline for one feed.

Replaces n8n workflow: fetch → resolve → archive → ingest

Steps per item:
  1. fetch_feed.py    — get new RSS items (already done, passed via --items-json or auto-fetched)
  2. resolve_landing.py — download source file
  3. archive.py       — register in document_registry + move to archive
  4. run_ingest.py    — parse, chunk, embed, upsert to Qdrant

Run log lifecycle owned by fetch_feed.py (opens the row, closes it with stats).
This script reports additional per-item ingest stats back into that same run_log row.

Usage:
    python run_pipeline.py --feed-id ema_reg_guidance [--run-id <uuid>] [--mode live|backfill]
"""

import os, sys, json, argparse, subprocess, uuid, time, logging, re, hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import psycopg2

sys.path.insert(0, "/opt/scripts")
from ingestion.config import PG_DSN

FEED_AUTHORITY = {
    'fda_drugs': 'FDA',
    'fda_press_releases': 'FDA',
    'ema_sci_guidelines': 'EMA',
    'ema_reg_guidance': 'EMA',
    'ich_guidelines': 'ICH',
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_pipeline")

SCRIPTS_DIR   = "/opt/scripts"
FETCH_FEED    = f"{SCRIPTS_DIR}/rss/fetch_feed.py"
RESOLVE       = f"{SCRIPTS_DIR}/rss/resolve_landing.py"
ARCHIVE       = f"{SCRIPTS_DIR}/rss/archive.py"
RUN_INGEST    = f"{SCRIPTS_DIR}/ingestion/run_ingest.py"
PYTHON        = sys.executable


def pg_conn():
    return psycopg2.connect(PG_DSN)


def run(cmd, stdin_data=None, timeout=120):
    """Run a subprocess, optionally piping stdin_data (bytes). Returns (rc, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def fetch_items(feed_id: str, run_id: str, mode: str, trigger_source: str, triggered_by: str,
                 months_override: int = None, max_age_days: int = None):
    """Call fetch_feed.py. Returns list of items. run_log row created internally."""
    cmd = [PYTHON, FETCH_FEED,
           "--feed-id", feed_id,
           "--mode", mode,
           "--run-id", run_id,
           "--trigger-source", trigger_source,
           "--triggered-by", triggered_by]
    if months_override is not None:
        cmd.extend(["--months-override", str(months_override)])
    if mode == "live" and max_age_days is not None:
        cmd.extend(["--max-age-days", str(max_age_days)])
    rc, stdout, stderr = run(cmd, timeout=120)
    if rc != 0:
        raise RuntimeError(f"fetch_feed failed rc={rc}: {stderr.decode()[:400]}")
    try:
        data = json.loads(stdout)
        # fetch_feed may return {"span_id": null, "items": [...]} or plain list
        return data.get("items", data) if isinstance(data, dict) else data
    except json.JSONDecodeError as e:
        raise RuntimeError(f"fetch_feed bad JSON: {e} stdout={stdout[:200]}")


def _register_feed_items(feed_id: str, items: list) -> int:
    """Upsert all fetched items into document_registry as identity rows only.
    No ingestion, no archiving — just metadata registration.
    Returns count of rows upserted.
    """
    if not items:
        return 0
    authority = FEED_AUTHORITY.get(feed_id, '')

    def _make_doc_id(fid: str, url: str) -> str:
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        path = urlparse(url).path.rstrip("/").split("/")[-1]
        path = re.sub(r"[^a-z0-9\-]", "-", path.lower())[:40].strip("-")
        return f"{fid}-{path}-{url_hash}" if path else f"{fid}-{url_hash}"

    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    count = 0
    try:
        with conn.cursor() as cur:
            for item in items:
                url = item.get('url', '')
                if not url:
                    continue
                doc_id = _make_doc_id(feed_id, url)
                title = item.get('title', '')
                pub_date = item.get('pub_date', '') or None
                if pub_date and isinstance(pub_date, str) and len(pub_date) >= 10:
                    pub_date = pub_date[:10]
                else:
                    pub_date = None

                archive_path = f"/mnt/data/regulatory_archive/{authority.lower()}/{doc_id}" if authority else f"/archive/{doc_id}"

                cur.execute("""
                    INSERT INTO document_registry (
                        document_id, source_url, issuing_body,
                        document_class, document_type, document_status,
                        feed_id, corpus_doc, archive_path,
                        publication_date, metadata_json, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, 'regulatory-public', 'guidance', 'final',
                        %s, FALSE, %s,
                        %s, %s, NOW(), NOW()
                    )
                    ON CONFLICT (document_id) DO NOTHING
                """, (
                    doc_id, url, authority,
                    feed_id, archive_path,
                    pub_date,
                    json.dumps({'document_title': title, 'title': title,
                                'feed_id': feed_id, 'source_url': url}),
                ))
                if cur.rowcount > 0:
                    count += 1
    finally:
        conn.close()
    return count


def resolve_item(item: dict):
    """Call resolve_landing.py for one item. Returns resolved dict."""
    rc, stdout, stderr = run(
        [PYTHON, RESOLVE],
        stdin_data=json.dumps(item).encode(),
        timeout=120,
    )
    if rc != 0:
        raise RuntimeError(f"resolve_landing failed rc={rc}: {stderr.decode()[:300]}")
    return json.loads(stdout)


def archive_item(resolved: dict, original_item: dict):
    """Call archive.py, merging original fetch item into resolved. Returns {doc_id, archive_path}."""
    merged = {**original_item, **resolved}
    rc, stdout, stderr = run(
        [PYTHON, ARCHIVE],
        stdin_data=json.dumps(merged).encode(),
        timeout=60,
    )
    if rc != 0:
        raise RuntimeError(f"archive failed rc={rc}: {stderr.decode()[:300]}")
    return json.loads(stdout)


def ingest_doc(doc_id: str, run_id: str, redownload: str = "none"):
    """Call run_ingest.py for an archived document."""
    cmd = [PYTHON, RUN_INGEST, "--doc-id", doc_id, "--run-id", run_id]
    if redownload != "none":
        cmd.extend(["--redownload", redownload])
    rc, stdout, stderr = run(cmd, timeout=600)
    if rc != 0:
        raise RuntimeError(f"run_ingest failed rc={rc}: {stderr.decode()[:400]}")


def get_failed_doc_ids(feed_id: str) -> list:
    """Return doc_ids with ingestion_status='failed' for this feed, oldest first.
    Deferred docs (ingestion_status='deferred') are intentionally excluded."""
    try:
        conn = pg_conn()
        with conn.cursor() as c:
            c.execute(
                "SELECT document_id FROM document_registry_ext "
                "WHERE feed_id = %s AND ingestion_status = 'failed' "
                "ORDER BY updated_at ASC",
                (feed_id,)
            )
            rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"Could not query failed docs for feed={feed_id}: {e}")
        return []


def update_run_log(run_id: str, items_new: int, error_count: int):
    """Patch run_log with final ingest counts and derived status."""
    if error_count == 0:
        final_status = "success"
    elif items_new == 0:
        final_status = "error"
    else:
        final_status = "partial"
    try:
        conn = pg_conn()
        conn.autocommit = True
        with conn.cursor() as c:
            c.execute(
                """UPDATE run_log
                   SET items_new    = %s,
                       error_count  = %s,
                       status       = %s
                   WHERE run_id = %s""",
                (items_new, error_count, final_status, run_id),
            )
        conn.close()
    except Exception as e:
        logger.warning(f"Could not update run_log counts: {e}")


def _make_doc_id(feed_id: str, url: str) -> str:
    import hashlib, re
    from urllib.parse import urlparse
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    path = re.sub(r"[^a-z0-9\-]", "-", path.lower())[:40].strip("-")
    return f"{feed_id}-{path}-{url_hash}" if path else f"{feed_id}-{url_hash}"


def _register_unsupported(item: dict, resolved: dict, doc_id: str):
    """Register an unsupported document so it is not re-fetched."""
    from datetime import datetime, timezone
    reason = resolved.get("reason", "Unsupported file format")
    conn = pg_conn()
    conn.autocommit = True
    with conn.cursor() as c:
        # GATE3d: identity-only insert — state columns removed
        c.execute(
            """INSERT INTO document_registry
               (document_id, source_url, feed_id, issuing_body,
                document_class, document_type, document_status,
                metadata_json, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
               ON CONFLICT (document_id) DO NOTHING""",
            (doc_id,
             item.get("url", ""),
             item.get("feed_id", ""),
             item.get("authority", ""),
             "regulatory",
             item.get("default_doc_type", "other"),
             "final",
             json.dumps({"doc_id": doc_id, "feed_id": item.get("feed_id", "")}),
             ),
        )
        # GATE3d: write 'unsupported' status to ingestion_state
        c.execute(
            """INSERT INTO ingestion_state (document_id, ingestion_status, ingestion_error, updated_at)
               VALUES (%s, 'unsupported', %s, NOW())
               ON CONFLICT (document_id) DO UPDATE SET
                   ingestion_status = 'unsupported',
                   ingestion_error  = EXCLUDED.ingestion_error,
                   updated_at       = NOW()""",
            (doc_id, reason),
        )
    conn.close()


def recheck_not_viable_docs(feed_id: str, run_id: str) -> int:
    """Re-ingest not_viable docs due for periodic recheck using --redownload force.

    redownload_source() inside run_ingest.py re-fetches the source URL,
    scrapes for PDF links, and replaces the archive file — no separate
    resolve/archive steps needed. Returns count of successfully re-ingested docs.
    """
    from ingestion.registry import get_docs_due_for_not_viable_recheck

    doc_ids = get_docs_due_for_not_viable_recheck(feed_id)
    if not doc_ids:
        return 0

    succeeded = 0
    for doc_id in doc_ids:
        try:
            ingest_doc(doc_id, run_id, redownload="force")
            logger.info(f"Recheck succeeded: doc_id={doc_id}")
            succeeded += 1
        except Exception as e:
            logger.warning(f"Recheck failed for doc_id={doc_id}: {e}")

    logger.info(f"Not-viable recheck: {succeeded}/{len(doc_ids)} succeeded for feed={feed_id}")
    return succeeded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--mode", default="live", choices=["live", "backfill"])
    parser.add_argument("--trigger-source", default="scheduled",
                        choices=["scheduled", "manual", "manual_cli", "bootstrap_ui"])
    parser.add_argument("--triggered-by", default="scheduler")
    parser.add_argument("--months-override", type=int, default=None,
                        help="Override backfill depth in months (forwarded to fetch_feed.py)")
    parser.add_argument("--max-age-days", type=int, default=30,
                        help="In live mode, only fetch items within this many days (default: 30)")
    args = parser.parse_args()

    run_id = args.run_id or str(uuid.uuid4())
    logger.info(f"Pipeline starting: feed={args.feed_id} run_id={run_id}")

    # Step 1: Full fetch — get ALL items from the feed (no date limit).
    # This populates document_registry with complete metadata for every
    # known document. Ingestion is scoped separately (see Step 1b).
    try:
        all_items = fetch_items(args.feed_id, run_id, args.mode, args.trigger_source, args.triggered_by,
                                months_override=args.months_override, max_age_days=None)
    except Exception as e:
        logger.error(f"Full fetch failed: {e}")
        sys.exit(1)

    registered = _register_feed_items(args.feed_id, all_items)
    logger.info(f"Registry: {registered} new | {len(all_items)} total in source for feed={args.feed_id}")

    # Step 1b: Filter to the ingestion window (default 30 days in live mode,
    # no limit in backfill mode).
    if args.mode == "live" and args.max_age_days and args.max_age_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)
        cutoff_str = cutoff.strftime('%Y-%m-%d')
        items = [i for i in all_items if i.get('pub_date','') and i['pub_date'] >= cutoff_str]
        logger.info(f"Ingestion window: {len(items)} items within {args.max_age_days} days (since {cutoff_str})")
    else:
        items = all_items  # backfill mode — ingest everything

    succeeded = 0
    failed = 0

    if items:
        for item in items:
            url = item.get("url", "?")
            try:
                # Step 2: Resolve (download)
                resolved = resolve_item(item)

                if resolved.get("status") == "unsupported":
                    doc_id = resolved.get("doc_id") or _make_doc_id(item.get("feed_id", ""), url)
                    _register_unsupported(item, resolved, doc_id)
                    logger.info(f"Skipped (unsupported): doc_id={doc_id} reason={resolved.get('reason')}")
                    continue

                doc_id = resolved.get("doc_id") or item.get("doc_id")
                logger.info(f"Resolved: doc_id={doc_id} url={url[:80]}")

                # Step 3: Archive
                archived = archive_item(resolved, item)
                doc_id = archived.get("doc_id", doc_id)
                logger.info(f"Archived: doc_id={doc_id}")

                # Step 4: Ingest
                ingest_doc(doc_id, run_id)
                logger.info(f"Ingested: doc_id={doc_id}")
                succeeded += 1

            except Exception as e:
                logger.error(f"Pipeline failed for url={url[:80]}: {e}")
                failed += 1

    # Retry previously failed documents for this feed
    failed_doc_ids = get_failed_doc_ids(args.feed_id)
    if failed_doc_ids:
        logger.info(f"Retrying {len(failed_doc_ids)} previously failed doc(s) for feed={args.feed_id}")
        for doc_id in failed_doc_ids:
            try:
                ingest_doc(doc_id, run_id)
                logger.info(f"Retry succeeded: doc_id={doc_id}")
                succeeded += 1
            except Exception as e:
                logger.error(f"Retry failed for doc_id={doc_id}: {e}")
                failed += 1

    # Recheck not_viable documents due for periodic re-evaluation
    nv_succeeded = recheck_not_viable_docs(args.feed_id, run_id)
    if nv_succeeded:
        succeeded += nv_succeeded

    update_run_log(run_id, succeeded, failed)
    logger.info(f"Pipeline complete: feed={args.feed_id} succeeded={succeeded} failed={failed}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
