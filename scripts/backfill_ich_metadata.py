#!/usr/bin/env python3
"""
Backfill publication_date into metadata_json and Qdrant chunk payloads for
ICH feed docs where metadata_json->>'publication_date' is empty.

Data source: the PG publication_date column (already correctly populated for
22 of 26 affected docs via the _backfill_pub_date_from_chunks() pipeline step).
The remaining 4 docs have no date anywhere — logged as UNMATCHED.

No Drupal API call is required. _extract_ich_items() in fetch_feed.py already
extracts stepDate for future ingestions (fixed 2026-05-29).

Safe to run multiple times (idempotent).
"""

import argparse
import os

import psycopg2
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue


def get_pg_conn():
    dsn = os.environ.get("PG_DSN")
    if dsn:
        return psycopg2.connect(dsn)
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ.get("POSTGRES_DB", "knowledge_base"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


def get_qdrant_client():
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "qdrant"),
        port=int(os.environ.get("QDRANT_PORT", 6333)),
    )


def scroll_all(client, collection, doc_id):
    """Paginate scroll to collect all point IDs for a document_id."""
    all_points = []
    offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
            ),
            limit=100,
            offset=offset,
            with_payload=False,
        )
        all_points.extend(batch)
        if next_offset is None:
            break
        offset = next_offset
    return [p.id for p in all_points]


def main():
    parser = argparse.ArgumentParser(description="Backfill ICH publication_date into metadata_json and Qdrant")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be updated without writing")
    parser.add_argument("--collection", default="knowledge_base")
    args = parser.parse_args()

    pg = get_pg_conn()
    cur = pg.cursor()

    # Fetch all ICH feed docs with empty metadata_json publication_date
    cur.execute("""
        SELECT document_id,
               publication_date::text AS pg_date,
               metadata_json->>'document_title' AS title
        FROM document_registry
        WHERE feed_id IS NOT NULL
          AND issuing_body = 'ICH'
          AND (metadata_json->>'publication_date' IS NULL
               OR metadata_json->>'publication_date' = '')
        ORDER BY document_id
    """)
    rows = cur.fetchall()

    print(f"Docs with empty metadata_json publication_date: {len(rows)}")

    stats = {"updated_pg": 0, "updated_qdrant_pts": 0, "unmatched": 0, "skipped": 0}
    unmatched = []
    qdrant = get_qdrant_client()

    for doc_id, pg_date, title in rows:
        if not pg_date:
            print(f"  UNMATCHED (no date anywhere): {doc_id}")
            unmatched.append(doc_id)
            stats["unmatched"] += 1
            continue

        print(f"  {doc_id[-50:]} → {pg_date}", end="")

        if args.dry_run:
            print(" [dry-run]")
            continue

        # Update metadata_json in PG
        cur.execute("""
            UPDATE document_registry
            SET metadata_json = metadata_json || jsonb_build_object('publication_date', %s)
            WHERE document_id = %s
              AND (metadata_json->>'publication_date' IS NULL
                   OR metadata_json->>'publication_date' = '')
        """, (pg_date, doc_id))
        pg_updated = cur.rowcount
        stats["updated_pg"] += pg_updated

        # Update Qdrant chunk payloads
        point_ids = scroll_all(qdrant, args.collection, doc_id)
        if point_ids:
            qdrant.set_payload(
                collection_name=args.collection,
                payload={"publication_date": pg_date},
                points=point_ids,
            )
            stats["updated_qdrant_pts"] += len(point_ids)
            print(f" (PG: {pg_updated} row, Qdrant: {len(point_ids)} pts)")
        else:
            print(f" (PG: {pg_updated} row, Qdrant: 0 pts — no chunks found)")

    if not args.dry_run:
        pg.commit()

    pg.close()

    print()
    print("=== Summary ===")
    print(f"  Total inspected:      {len(rows)}")
    print(f"  Updated in PG:        {stats['updated_pg']}")
    print(f"  Updated Qdrant pts:   {stats['updated_qdrant_pts']}")
    print(f"  Unmatched (no date):  {stats['unmatched']}")
    if unmatched:
        print("  Unmatched doc_ids:")
        for d in unmatched:
            print(f"    {d}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")


if __name__ == "__main__":
    main()
