#!/usr/bin/env python3
"""
reingest_pending.py — Retry ingestion for all pending documents.

Two-phase approach to avoid CUDA OOM:
  Phase 1: Classify all pending docs (phi4 loads once, stays loaded)
  Phase 2: Unload phi4 → ingest all sequentially (Docling gets full VRAM)

Usage:
  python /opt/scripts/ingestion/reingest_pending.py
  python /opt/scripts/ingestion/reingest_pending.py --dry-run
  python /opt/scripts/ingestion/reingest_pending.py --phase backfill

Place this file at: /opt/scripts/ingestion/reingest_pending.py
"""

import sys, json, time, random, requests, argparse
sys.path.insert(0, "/opt/scripts")

from pathlib import Path
from ingestion.registry import pg_conn
from ingestion.run_ingest import (
    classify, build_rss_meta, write_meta_json,
    ingest_html_document, post_inject,
    write_phase_f_archive, update_registry_phase_f,
    OLLAMA_URL, CHUNKER_VERSION,
)
from ingestion.ingest import ingest_document


# ── helpers ───────────────────────────────────────────────────────────────────

def get_pending_docs(interleave: bool = False) -> list:
    with pg_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
                SELECT document_id, archive_path, feed_id
                FROM document_registry_ext
                WHERE ingestion_status = 'pending'
                ORDER BY document_id
            """)
            rows = c.fetchall()
    if not interleave:
        return [(r[0], r[1]) for r in rows]
    # Round-robin interleave by feed so same-host requests are spaced apart
    # (e.g. EMA, FDA, ICH, EMA, FDA, ICH, ... instead of all-EMA-then-all-FDA)
    from collections import defaultdict
    groups = defaultdict(list)
    for doc_id, archive_path, feed_id in rows:
        groups[feed_id or "_unknown"].append((doc_id, archive_path))
    interleaved = []
    group_lists = list(groups.values())
    max_len = max(len(g) for g in group_lists)
    for i in range(max_len):
        for g in group_lists:
            if i < len(g):
                interleaved.append(g[i])
    return interleaved


def unload_model(model: str):
    print(f"  Unloading {model} from VRAM...")
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=30,
        )
        r.raise_for_status()
        print(f"  {model} unloaded.")
    except Exception as e:
        print(f"  WARNING: unload failed for {model}: {e}")


def check_vram():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/ps", timeout=10)
        models = r.json().get("models", [])
        if models:
            names = [m["name"] for m in models]
            print(f"  WARNING — models still in VRAM: {names}")
            return False
        print("  VRAM clear.")
        return True
    except Exception as e:
        print(f"  Could not check VRAM: {e}")
        return True  # proceed anyway


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Reingest all pending documents.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print pending docs and exit without processing.")
    parser.add_argument("--phase", default="live",
                        choices=["live", "backfill", "manual"],
                        help="Phase label written to Qdrant payload (default: live).")
    parser.add_argument("--interleave", action="store_true",
                        help="Round-robin documents by feed to space out same-host requests.")
    args = parser.parse_args()

    # ── list pending ──────────────────────────────────────────────────────────
    pending = get_pending_docs(interleave=args.interleave)
    if not pending:
        print("No pending documents. Nothing to do.")
        sys.exit(0)

    print(f"\nPending documents ({len(pending)}):")
    for doc_id, _ in pending:
        print(f"  {doc_id}")

    if args.dry_run:
        sys.exit(0)

    # ── phase 1: classify ─────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"PHASE 1 — Classification ({len(pending)} documents)")
    print(f"{'─'*60}")

    classified = []
    class_failed = []

    for doc_id, archive_path in pending:
        try:
            meta_path = Path(archive_path) / "metadata.json"
            with open(meta_path) as f:
                metadata = json.load(f)

            feed_id   = metadata.get("feed_id", "")
            authority = metadata.get("authority", "")
            title     = metadata.get("title", "")
            excerpt   = metadata.get("rss_body", "").strip() or title
            ct        = metadata.get("content_type", "pdf")

            print(f"\n  [{ct.upper()}] {doc_id}")
            cls = classify(title, excerpt, feed_id, authority)
            meta_built = build_rss_meta(doc_id, Path(archive_path), metadata, cls)
            write_meta_json(doc_id, meta_built)

            classified.append((doc_id, archive_path, metadata, meta_built, cls, ct, feed_id))
            print(f"    → {cls['doc_type']}  confidence={cls['classifier_confidence']:.2f}")

        except Exception as e:
            print(f"    ✗ Classification failed: {e}")
            class_failed.append((doc_id, str(e)))

    print(f"\nClassification complete: {len(classified)} ok, {len(class_failed)} failed.")

    if not classified:
        print("Nothing to ingest. Exiting.")
        sys.exit(1)

    # ── unload phi4 before Docling ────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print("Unloading phi4 before Docling ingestion")
    print(f"{'─'*60}")
    unload_model("phi4:14b-q8_0")
    time.sleep(5)
    check_vram()

    # ── phase 2: ingest ───────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"PHASE 2 — Ingestion ({len(classified)} documents)")
    print(f"{'─'*60}")

    results = []

    for doc_id, archive_path, metadata, meta_built, cls, ct, feed_id in classified:
        # Rate-limiting: space out EMA requests to avoid 429s
        if feed_id and "ema" in feed_id.lower():
            time.sleep(3 + random.uniform(0, 2))
        print(f"\n  [{ct.upper()}] {doc_id}")
        try:
            if ct == "html":
                result = ingest_html_document(
                    doc_id, Path(archive_path), meta_built, cls, feed_id, args.phase
                )
                chunk_count = result["chunks"]
            else:
                result = ingest_document(doc_id, chunker_version=CHUNKER_VERSION)
                chunk_count = result.get("chunks", 0)
                n = post_inject(doc_id, cls, meta_built, feed_id, args.phase)
                print(f"    Post-inject: {n} points updated")

            write_phase_f_archive(Path(archive_path), doc_id, cls, feed_id, args.phase)
            update_registry_phase_f(doc_id, cls)

            results.append({"doc_id": doc_id, "status": "ok", "chunks": chunk_count})
            print(f"    ✓ {chunk_count} chunks")

        except Exception as e:
            results.append({"doc_id": doc_id, "status": "failed", "error": str(e)})
            print(f"    ✗ FAILED: {e}")

    # ── summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("SUMMARY")
    print(f"{'═'*60}")

    ok     = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "failed"]

    print(f"Ingested:  {len(ok)}/{len(results)}")
    for r in ok:
        print(f"  ✓ {r['doc_id']}  ({r['chunks']} chunks)")

    if class_failed:
        print(f"\nClassification failures: {len(class_failed)}")
        for doc_id, err in class_failed:
            print(f"  ✗ {doc_id}: {err}")

    if failed:
        print(f"\nIngestion failures: {len(failed)}")
        for r in failed:
            print(f"  ✗ {r['doc_id']}: {r['error']}")

    sys.exit(0 if not failed and not class_failed else 1)


if __name__ == "__main__":
    main()
