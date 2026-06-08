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

import os, sys, json, argparse, subprocess, uuid, time, logging
import psycopg2

sys.path.insert(0, "/opt/scripts")
from ingestion.config import PG_DSN

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


def fetch_items(feed_id: str, run_id: str, mode: str, trigger_source: str, triggered_by: str):
    """Call fetch_feed.py. Returns list of items. run_log row created internally."""
    rc, stdout, stderr = run(
        [PYTHON, FETCH_FEED,
         "--feed-id", feed_id,
         "--mode", mode,
         "--run-id", run_id,
         "--trigger-source", trigger_source,
         "--triggered-by", triggered_by],
        timeout=120,
    )
    if rc != 0:
        raise RuntimeError(f"fetch_feed failed rc={rc}: {stderr.decode()[:400]}")
    try:
        data = json.loads(stdout)
        # fetch_feed may return {"span_id": null, "items": [...]} or plain list
        return data.get("items", data) if isinstance(data, dict) else data
    except json.JSONDecodeError as e:
        raise RuntimeError(f"fetch_feed bad JSON: {e} stdout={stdout[:200]}")


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


def ingest_doc(doc_id: str, run_id: str):
    """Call run_ingest.py for an archived document."""
    rc, stdout, stderr = run(
        [PYTHON, RUN_INGEST,
         "--doc-id", doc_id,
         "--run-id", run_id],
        timeout=600,
    )
    if rc != 0:
        raise RuntimeError(f"run_ingest failed rc={rc}: {stderr.decode()[:400]}")


def get_failed_doc_ids(feed_id: str) -> list:
    """Return doc_ids with ingestion_status='failed' for this feed, oldest first.
    Deferred docs (ingestion_status='deferred') are intentionally excluded."""
    try:
        conn = pg_conn()
        with conn.cursor() as c:
            c.execute(
                "SELECT document_id FROM document_registry "
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
    conn = pg_conn()
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO document_registry
               (document_id, source_url, feed_id, issuing_body,
                document_class, document_type, document_status,
                metadata_json, ingestion_status, ingestion_error,
                created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
               ON CONFLICT (document_id) DO UPDATE SET
               ingestion_status = EXCLUDED.ingestion_status,
               ingestion_error = EXCLUDED.ingestion_error,
               updated_at = NOW()
               WHERE document_registry.ingestion_status NOT IN ('indexed','success')""",
            (doc_id,
             item.get("url", ""),
             item.get("feed_id", ""),
             item.get("authority", ""),
             "regulatory",
             item.get("default_doc_type", "other"),
             "final",
             json.dumps({"doc_id": doc_id, "feed_id": item.get("feed_id", "")}),
             "unsupported",
             resolved.get("reason", "Unsupported file format"),
             ),
        )
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-id", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--mode", default="live", choices=["live", "backfill"])
    parser.add_argument("--trigger-source", default="scheduled",
                        choices=["scheduled", "manual", "manual_cli", "bootstrap_ui"])
    parser.add_argument("--triggered-by", default="scheduler")
    args = parser.parse_args()

    run_id = args.run_id or str(uuid.uuid4())
    logger.info(f"Pipeline starting: feed={args.feed_id} run_id={run_id}")

    # Step 1: Fetch — creates run_log row, returns new items
    try:
        items = fetch_items(args.feed_id, run_id, args.mode, args.trigger_source, args.triggered_by)
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        sys.exit(1)

    logger.info(f"Fetched {len(items)} new items for feed={args.feed_id}")

    if not items:
        logger.info("No new items — pipeline complete")
        sys.exit(0)

    succeeded = 0
    failed = 0

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

    update_run_log(run_id, succeeded, failed)
    logger.info(f"Pipeline complete: feed={args.feed_id} succeeded={succeeded} failed={failed}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
