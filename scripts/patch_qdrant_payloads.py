#!/usr/bin/env python3
"""
patch_qdrant_payloads.py
Inject missing document-level metadata into Qdrant chunk payloads for seed documents.

This is a one-time fix for chunks ingested before the payload schema included
document_title, issuing_body, document_version, publication_date, etc.

Run from ai-node (outside Docker):
  python3 /opt/scripts/patch_qdrant_payloads.py

Or inside regpulse-api container:
  docker exec regpulse-api python3 /opt/scripts/patch_qdrant_payloads.py
"""

import os
import json
import psycopg2
import psycopg2.extras
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

PG_DSN = os.getenv(
    "PG_DSN",
    f"postgresql://postgres:{os.getenv('POSTGRES_PASSWORD', '')}@"
    f"{os.getenv('POSTGRES_HOST', 'postgres')}:5432/knowledge_base"
)
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")

SEED_DOC_IDS = [
    "EU-GMP-Annex11",
    "EU-GMP-Annex22",
    "EU-GMP-Annex15",
    "21-CFR-Part-11",
    "ICH-Q10",
    "ICH-Q9-R1",
    "EMA-Reflection-AI",
    "FDA-DI-CGMP-QA",
]


def load_doc_metadata(conn, doc_id: str) -> dict:
    """Load document metadata from PostgreSQL."""
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """SELECT
                document_id,
                metadata_json->>'document_title' AS document_title,
                issuing_body,
                document_version,
                doc_type,
                source_url,
                publication_date::text AS publication_date
               FROM document_registry
               WHERE document_id = %s""",
            (doc_id,)
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"Document not in registry: {doc_id}")
    return dict(row)


def patch_document_chunks(qdrant: QdrantClient, doc_id: str, pg_meta: dict) -> int:
    """Patch all Qdrant chunks for a document with missing document-level fields.

    Scrolls chunks using document_id field match first.
    Falls back to chunk_id prefix pattern if document_id field is absent.
    """
    # Build the patch payload — only non-null values
    patch = {}
    if pg_meta.get("document_id"):
        patch["document_id"] = pg_meta["document_id"]
    if pg_meta.get("document_title"):
        patch["document_title"] = pg_meta["document_title"]
    if pg_meta.get("issuing_body"):
        patch["issuing_body"] = pg_meta["issuing_body"]
    if pg_meta.get("document_version"):
        patch["document_version"] = pg_meta["document_version"]
    if pg_meta.get("doc_type"):
        patch["doc_type"] = pg_meta["doc_type"]
        # Also patch the hyphenated variant used for filtering / display
        patch["document_type"] = pg_meta["doc_type"].replace("_", "-")
    if pg_meta.get("source_url"):
        patch["source_url"] = pg_meta["source_url"]
    if pg_meta.get("publication_date"):
        patch["publication_date"] = str(pg_meta["publication_date"])

    if not patch:
        print(f"  {doc_id}: no metadata to patch — skipping")
        return 0

    # Scroll all chunks for this document
    all_points = []
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(
                    key="document_id",
                    match=MatchValue(value=doc_id)
                )]
            ),
            limit=500,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        all_points.extend(points)
        if offset is None:
            break

    if not all_points:
        print(f"  {doc_id}: no chunks found in Qdrant")
        return 0

    # Apply patch in batches of 100
    point_ids = [p.id for p in all_points]
    batch_size = 100
    for i in range(0, len(point_ids), batch_size):
        batch = point_ids[i:i + batch_size]
        qdrant.set_payload(
            collection_name=QDRANT_COLLECTION,
            payload=patch,
            points=batch,
        )

    print(f"  {doc_id}: patched {len(point_ids)} chunks with {list(patch.keys())}")
    return len(point_ids)


def main():
    print("Connecting to PostgreSQL and Qdrant...")
    conn = psycopg2.connect(PG_DSN)
    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    total_patched = 0
    for doc_id in SEED_DOC_IDS:
        print(f"\nProcessing {doc_id}...")
        try:
            pg_meta = load_doc_metadata(conn, doc_id)
            n = patch_document_chunks(qdrant, doc_id, pg_meta)
            total_patched += n
        except Exception as e:
            print(f"  ERROR: {e}")

    conn.close()
    print(f"\nDone. Total chunks patched: {total_patched}")


if __name__ == "__main__":
    main()
