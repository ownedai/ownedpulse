#!/usr/bin/env python3
"""
Backfill last_indexed_at for all document_registry rows where it is NULL.

Strategy (in priority order):
  1. Use created_at if populated (best available proxy for ingestion time).
  2. Fall back to NOW() if created_at is also NULL.

Only touches rows where ingestion_status IN ('indexed', 'success') and
last_indexed_at IS NULL.

Safe to run multiple times (idempotent).
"""

import argparse
import os
import sys

import psycopg2


def get_conn():
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


def main():
    parser = argparse.ArgumentParser(description="Backfill last_indexed_at")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print counts without writing anything")
    args = parser.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Count rows that would be affected
    cur.execute("""
        SELECT COUNT(*) FROM document_registry
        WHERE last_indexed_at IS NULL
          AND ingestion_status IN ('indexed', 'success')
    """)
    total_eligible = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM document_registry
        WHERE last_indexed_at IS NULL
          AND ingestion_status IN ('indexed', 'success')
          AND created_at IS NOT NULL
    """)
    has_created_at = cur.fetchone()[0]

    fallback_to_now = total_eligible - has_created_at

    print(f"Eligible rows (NULL last_indexed_at, status indexed/success): {total_eligible}")
    print(f"  Will use created_at:  {has_created_at}")
    print(f"  Will fall back to NOW(): {fallback_to_now}")

    cur.execute("SELECT COUNT(*) FROM document_registry WHERE last_indexed_at IS NOT NULL")
    already_populated = cur.fetchone()[0]
    print(f"Already populated (skipped): {already_populated}")

    if args.dry_run:
        print("\n--dry-run: no changes written.")
        conn.close()
        return

    if total_eligible == 0:
        print("\nNothing to do.")
        conn.close()
        return

    # Update rows that have created_at
    cur.execute("""
        UPDATE document_registry
        SET last_indexed_at = created_at
        WHERE last_indexed_at IS NULL
          AND ingestion_status IN ('indexed', 'success')
          AND created_at IS NOT NULL
    """)
    updated_created_at = cur.rowcount

    # Update rows where created_at is also NULL — use NOW()
    cur.execute("""
        UPDATE document_registry
        SET last_indexed_at = NOW()
        WHERE last_indexed_at IS NULL
          AND ingestion_status IN ('indexed', 'success')
    """)
    updated_now = cur.rowcount

    conn.commit()

    # Verify
    cur.execute("SELECT COUNT(*) FROM document_registry WHERE last_indexed_at IS NULL")
    remaining_null = cur.fetchone()[0]

    print(f"\nUpdated using created_at: {updated_created_at}")
    print(f"Updated using NOW():      {updated_now}")
    print(f"Still NULL after backfill: {remaining_null}")

    if remaining_null == 0:
        print("\nVerification passed: 0 NULL rows remaining.")
    else:
        print(f"\nWARNING: {remaining_null} rows still NULL (likely non-indexed status).")

    conn.close()


if __name__ == "__main__":
    main()
