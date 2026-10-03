"""
Backfill issuing_body in Qdrant payload for all RSS-ingested chunks where issuing_body is empty.
Derives issuing_body from feed_id prefix if not in PostgreSQL document_registry.
Run: python3 scripts/maintenance/backfill_issuing_body.py [--dry-run]
"""
import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from lib.db import get_pg_conn

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "knowledge_base"

FEED_ID_TO_ISSUING_BODY = {
    "ema_sci_guidelines": "EMA",
    "ema_reg_guidance": "EU-Commission",
    "fda_drugs": "FDA",
    "ich_guidelines": "ICH",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = QdrantClient(url=QDRANT_URL)
    conn = get_pg_conn()
    cur = conn.cursor()

    # Build document_id → issuing_body map from PostgreSQL
    cur.execute("""
        SELECT document_id,
               COALESCE(metadata_json->>'issuing_body', '') as issuing_body,
               feed_id
        FROM document_registry
        WHERE feed_id IS NOT NULL
    """)
    rows = cur.fetchall()

    doc_to_issuing_body = {}
    for doc_id, issuing_body, feed_id in rows:
        if issuing_body:
            doc_to_issuing_body[doc_id] = issuing_body
        elif feed_id:
            for prefix, body in FEED_ID_TO_ISSUING_BODY.items():
                if feed_id.startswith(prefix):
                    doc_to_issuing_body[doc_id] = body
                    break

    print(f"Built issuing_body map for {len(doc_to_issuing_body)} documents")

    # Scroll all chunks with empty issuing_body
    updated = 0
    skipped = 0
    offset = None

    while True:
        results, next_offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(key="issuing_body", match=MatchValue(value=""))]
            ),
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not results:
            break

        for point in results:
            doc_id = point.payload.get("document_id", "")
            resolved = doc_to_issuing_body.get(doc_id, "")

            if resolved:
                if not args.dry_run:
                    client.set_payload(
                        collection_name=COLLECTION,
                        payload={"issuing_body": resolved},
                        points=[point.id],
                    )
                updated += 1
            else:
                skipped += 1

        print(f"  Processed batch: updated={updated}, skipped={skipped}")

        if next_offset is None:
            break
        offset = next_offset

    print(f"\nDone. Updated: {updated}, Skipped (no mapping): {skipped}")
    if args.dry_run:
        print("DRY RUN — no changes written to Qdrant")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
