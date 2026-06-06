#!/usr/bin/env python3
"""
Backfill document_family_id into Qdrant chunk payloads for the ich-q9 family.

Reads family assignments from PostgreSQL document_registry and applies them
to all matching Qdrant points via set_payload(). Safe to run multiple times.
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


def main():
    parser = argparse.ArgumentParser(description="Backfill document_family_id into Qdrant payloads")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print counts without writing anything")
    parser.add_argument("--collection", default="knowledge_base")
    args = parser.parse_args()

    pg = get_pg_conn()
    cur = pg.cursor()
    cur.execute("""
        SELECT document_id, document_family_id
        FROM document_registry
        WHERE document_family_id IS NOT NULL
    """)
    family_assignments = cur.fetchall()
    cur.close()
    pg.close()

    if not family_assignments:
        print("No document_family_id assignments found in registry. Nothing to do.")
        return

    print(f"Found {len(family_assignments)} documents with family assignments:")
    for doc_id, fam_id in family_assignments:
        print(f"  {doc_id} → {fam_id}")
    print()

    client = get_qdrant_client()

    for doc_id, family_id in family_assignments:
        # Scroll all points for this document_id
        all_points = []
        offset = None
        while True:
            batch, next_offset = client.scroll(
                collection_name=args.collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
                ),
                limit=100,
                offset=offset,
                with_payload=["document_family_id"],
            )
            all_points.extend(batch)
            if next_offset is None:
                break
            offset = next_offset

        point_ids = [p.id for p in all_points]
        already_set = sum(
            1 for p in all_points
            if p.payload and p.payload.get("document_family_id") == family_id
        )

        print(f"{doc_id}: {len(point_ids)} points, {already_set} already correct")

        if args.dry_run:
            continue

        if point_ids:
            client.set_payload(
                collection_name=args.collection,
                payload={"document_family_id": family_id},
                points=point_ids,
            )
            print(f"  → set document_family_id={family_id!r} on {len(point_ids)} points")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
