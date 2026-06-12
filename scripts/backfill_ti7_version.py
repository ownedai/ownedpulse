#!/usr/bin/env python3
"""
TI-7 targeted version backfill — re-extracts document_version from landing pages
using the new structured extractor, updates PG metadata_json + Qdrant payloads.
Does NOT re-run Docling, chunking, or embedding.
"""

import os, sys, re, json, time, requests
from bs4 import BeautifulSoup
from pathlib import Path

# Add scripts path so we can import the new extractor
sys.path.insert(0, "/opt/scripts/rss")
from resolve_landing import _extract_version_structured, HEADERS

SCRIPTS = Path("/opt/scripts")

import psycopg2
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, SetPayload

PG_DSN = os.environ.get(
    "PG_DSN",
    f"host={os.environ.get('POSTGRES_HOST', 'postgres')} "
    f"port={os.environ.get('POSTGRES_PORT', '5432')} "
    f"dbname={os.environ.get('POSTGRES_DB', 'knowledge_base')} "
    f"user={os.environ.get('POSTGRES_USER', 'postgres')} "
    f"password={os.environ.get('POSTGRES_PASSWORD', '')}"
)

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

BATCH_SIZE = 20
DELAY_BETWEEN = 1.5  # seconds between fetches to avoid rate limiting


def get_docs_to_fix(conn):
    with conn.cursor() as c:
        c.execute("""
            SELECT document_id, metadata_json->>'document_version', source_url
            FROM document_registry_ext
            WHERE metadata_json->>'document_version' ~ '^\d+$'
            AND ingestion_status NOT IN ('not_viable', 'failed')
            ORDER BY document_id
        """)
        return [(r[0], r[1], r[2]) for r in c.fetchall()]


def extract_version_from_page(url):
    """Fetch landing page and extract version using the new structured extractor."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text[:5_000_000], "html.parser")
        return _extract_version_structured(soup, source_url=url)
    except Exception as e:
        return f"__error__:{e}"


def main():
    conn = psycopg2.connect(PG_DSN)
    qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    docs = get_docs_to_fix(conn)
    total = len(docs)
    print(f"Docs to fix: {total}")

    updated = 0
    errors = 0
    empty = 0
    new_values = {}

    for batch_start in range(0, total, BATCH_SIZE):
        batch = docs[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        print(f"\n--- Batch {batch_num} ({batch_start + 1}-{min(batch_start + BATCH_SIZE, total)} of {total}) ---")

        for doc_id, old_version, source_url in batch:
            print(f"  {doc_id[:60]}: old={old_version} ", end="", flush=True)

            new_version = extract_version_from_page(source_url)

            if new_version.startswith("__error__:"):
                err = new_version.split(":", 1)[1]
                print(f"→ ERROR: {err[:60]}")
                errors += 1
                continue

            if not new_version:
                print("→ (empty — no structured version found)")
                empty += 1
            else:
                print(f"→ \"{new_version}\"")

            # Update PostgreSQL metadata_json
            with conn.cursor() as c:
                c.execute("""
                    UPDATE document_registry
                    SET metadata_json = jsonb_set(
                        COALESCE(metadata_json, '{}'::jsonb),
                        '{document_version}',
                        %s::jsonb
                    )
                    WHERE document_id = %s
                """, (json.dumps(new_version), doc_id))

            # Update Qdrant chunk payloads
            try:
                qdrant.set_payload(
                    collection_name="knowledge_base",
                    payload={"document_version": new_version},
                    points=Filter(
                        must=[FieldCondition(
                            key="document_id",
                            match=MatchValue(value=doc_id)
                        )]
                    ),
                )
            except Exception as e:
                print(f"    Qdrant update warning: {e}")

            conn.commit()
            updated += 1
            new_values[new_version] = new_values.get(new_version, 0) + 1

            time.sleep(DELAY_BETWEEN)

    conn.close()

    print(f"\n=== Results ===")
    print(f"Total processed: {updated}")
    print(f"Errors: {errors}")
    print(f"Empty (no version found): {empty}")
    print(f"\nNew version distribution:")
    for v, c in sorted(new_values.items(), key=lambda x: -x[1]):
        print(f"  \"{v if v else '(empty)'}\": {c}")


if __name__ == "__main__":
    main()
