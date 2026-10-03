#!/usr/bin/env python3
"""
Compares Qdrant collection against PostgreSQL chunks table.
Reports: missing in PG, missing in Qdrant, status mismatches, count mismatches per doc.
Exit code 0 = clean. Exit code 1 = inconsistencies found.
"""

import os
import sys
import json
import psycopg2
from collections import defaultdict
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

COLLECTION = "knowledge_base"
BATCH_SIZE = 200


def get_pg_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ.get("POSTGRES_DB", "knowledge_base"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


def main():
    print("=== Chunk Consistency Check ===\n")
    client = QdrantClient(
        host=os.environ.get("QDRANT_HOST", "qdrant"),
        port=int(os.environ.get("QDRANT_PORT", "6333")),
    )
    conn = get_pg_conn()
    cur = conn.cursor()

    # ----------------------------------------------------------------
    # 1. Scroll all Qdrant points
    # ----------------------------------------------------------------
    print("Scrolling Qdrant...")
    qdrant_chunks = {}
    qdrant_by_doc = defaultdict(set)
    offset = None

    while True:
        results, offset = client.scroll(
            collection_name=COLLECTION,
            limit=BATCH_SIZE, offset=offset,
            with_payload=True, with_vectors=False,
        )
        if not results:
            break
        for point in results:
            cid = str(point.id)
            doc_id = point.payload.get("document_id", "UNKNOWN")
            status = point.payload.get("chunk_status", "MISSING")
            qdrant_chunks[cid] = {"document_id": doc_id, "chunk_status": status}
            qdrant_by_doc[doc_id].add(cid)
        if offset is None:
            break

    print(f"Qdrant: {len(qdrant_chunks)} points across {len(qdrant_by_doc)} documents")

    # ----------------------------------------------------------------
    # 2. Fetch all PostgreSQL chunks
    # ----------------------------------------------------------------
    print("Querying PostgreSQL...")
    cur.execute("SELECT chunk_id::text, document_id, chunk_status FROM chunks")
    pg_rows = cur.fetchall()
    pg_chunks = {row[0]: {"document_id": row[1], "chunk_status": row[2]} for row in pg_rows}
    pg_by_doc = defaultdict(set)
    for cid, data in pg_chunks.items():
        pg_by_doc[data["document_id"]].add(cid)

    print(f"PostgreSQL: {len(pg_chunks)} chunks across {len(pg_by_doc)} documents\n")

    # ----------------------------------------------------------------
    # 3. Find discrepancies
    # ----------------------------------------------------------------
    qdrant_ids = set(qdrant_chunks.keys())
    pg_ids = set(pg_chunks.keys())

    missing_in_pg = qdrant_ids - pg_ids
    missing_in_qdrant = pg_ids - qdrant_ids

    status_mismatches = []
    for cid in qdrant_ids & pg_ids:
        qs = qdrant_chunks[cid]["chunk_status"]
        ps = pg_chunks[cid]["chunk_status"]
        if qs != ps:
            status_mismatches.append({
                "chunk_id": cid,
                "document_id": qdrant_chunks[cid]["document_id"],
                "qdrant_status": qs,
                "pg_status": ps,
            })

    all_docs = set(qdrant_by_doc.keys()) | set(pg_by_doc.keys())
    count_mismatches = []
    for doc_id in sorted(all_docs):
        qc = len(qdrant_by_doc.get(doc_id, set()))
        pc = len(pg_by_doc.get(doc_id, set()))
        if qc != pc:
            count_mismatches.append({
                "document_id": doc_id,
                "qdrant_count": qc,
                "pg_count": pc,
                "delta": qc - pc,
            })

    # ----------------------------------------------------------------
    # 4. Report
    # ----------------------------------------------------------------
    issues = 0

    if missing_in_pg:
        issues += len(missing_in_pg)
        print(f"MISSING IN POSTGRESQL: {len(missing_in_pg)} chunks")
        for cid in sorted(missing_in_pg)[:20]:
            print(f"   {cid} (doc: {qdrant_chunks[cid]['document_id']})")
        if len(missing_in_pg) > 20:
            print(f"   ... and {len(missing_in_pg) - 20} more")
        print()

    if missing_in_qdrant:
        issues += len(missing_in_qdrant)
        print(f"MISSING IN QDRANT: {len(missing_in_qdrant)} chunks")
        for cid in sorted(missing_in_qdrant)[:20]:
            print(f"   {cid} (doc: {pg_chunks[cid]['document_id']})")
        if len(missing_in_qdrant) > 20:
            print(f"   ... and {len(missing_in_qdrant) - 20} more")
        print()

    if status_mismatches:
        issues += len(status_mismatches)
        print(f"STATUS MISMATCHES: {len(status_mismatches)} chunks")
        for m in status_mismatches[:20]:
            print(f"   {m['chunk_id']} ({m['document_id']}): Qdrant={m['qdrant_status']} PG={m['pg_status']}")
        print()

    if count_mismatches:
        issues += len(count_mismatches)
        print(f"PER-DOC COUNT MISMATCHES: {len(count_mismatches)} documents")
        for m in sorted(count_mismatches, key=lambda x: abs(x['delta']), reverse=True)[:20]:
            print(f"   {m['document_id']}: Qdrant={m['qdrant_count']} PG={m['pg_count']} (delta={m['delta']:+d})")
        print()

    # ----------------------------------------------------------------
    # 5. Summary
    # ----------------------------------------------------------------
    print("=== SUMMARY ===")
    print(f"Qdrant points:     {len(qdrant_chunks)}")
    print(f"PostgreSQL chunks: {len(pg_chunks)}")
    print(f"Missing in PG:     {len(missing_in_pg)}")
    print(f"Missing in Qdrant: {len(missing_in_qdrant)}")
    print(f"Status mismatches: {len(status_mismatches)}")
    print(f"Doc count deltas:  {len(count_mismatches)}")
    print()

    if issues == 0:
        print("PASS — Qdrant and PostgreSQL are fully consistent.")
        cur.close()
        conn.close()
        sys.exit(0)
    else:
        print(f"FAIL — {issues} inconsistencies found. Investigate before proceeding.")
        cur.close()
        conn.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
