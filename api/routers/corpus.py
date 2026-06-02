"""Corpus router — /api/corpus/ routes for document registry and run log."""

import os
import json
from fastapi import APIRouter, HTTPException, Query
from qdrant_client import QdrantClient

router = APIRouter()

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledge_base")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_base")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")


NOCO_DB = os.getenv("NOCO_DB", "nocodb")

def get_pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=POSTGRES_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )

def get_noco_conn():
    import psycopg2
    return psycopg2.connect(
        host=POSTGRES_HOST, port=POSTGRES_PORT,
        dbname=NOCO_DB, user=POSTGRES_USER,
        password=POSTGRES_PASSWORD, connect_timeout=10
    )

def repair_stale_pending(threshold_minutes: int = 30) -> int:
    """Mark pending docs as error if they haven't been updated within threshold.

    A document stuck in 'pending' with no running process means ingestion crashed
    before it could update the status. Returns the number of rows repaired.
    """
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE document_registry
               SET ingestion_status = 'error',
                   ingestion_error   = 'Ingestion process did not complete',
                   updated_at        = NOW()
               WHERE ingestion_status = 'pending'
                 AND updated_at < NOW() - (%s * INTERVAL '1 minute')""",
            (threshold_minutes,)
        )
        count = cur.rowcount
        conn.commit()
        cur.close()
        return count
    finally:
        conn.close()


def get_feed_default_doc_types() -> dict:
    """Return {feed_id: default_doc_type} from feed_config."""
    try:
        conn = get_noco_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT feed_id, default_doc_type FROM feed_config")
            result = {row[0]: row[1] for row in cur.fetchall()}
            cur.close()
            return result
        finally:
            conn.close()
    except Exception:
        return {}


def normalise_agency(agency: str) -> str:
    if agency == "EU-Commission":
        return "EMA"
    return agency


# ── GET /api/corpus/stats ─────────────────────────────────────────────────────

@router.get("/stats")
async def corpus_stats():
    conn = get_pg_conn()
    try:
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM document_registry WHERE ingestion_status = 'indexed'")
        total = cur.fetchone()[0]

        cur.execute("SELECT issuing_body, count(*) FROM document_registry WHERE ingestion_status = 'indexed' GROUP BY issuing_body")
        raw_agency = dict(cur.fetchall())
        per_agency = {}
        for agency, count in raw_agency.items():
            key = normalise_agency(agency)
            per_agency[key] = per_agency.get(key, 0) + count

        cur.execute(
            "SELECT metadata_json->>'document_type', count(*) "
            "FROM document_registry WHERE ingestion_status = 'indexed'"
            " GROUP BY metadata_json->>'document_type'"
        )
        per_doc_type = dict(cur.fetchall())

        cur.execute("SELECT max(last_indexed_at) FROM document_registry")
        last_run = cur.fetchone()[0]
        last_run_iso = last_run.isoformat() if last_run else None

        cur.close()
        return {
            "total_documents": total,
            "per_agency": per_agency,
            "per_document_type": per_doc_type,
            "last_pipeline_run": last_run_iso,
        }
    finally:
        conn.close()


# ── GET /api/corpus/documents ─────────────────────────────────────────────────

@router.get("/documents")
async def corpus_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    issuing_body: str | None = None,
    doc_type: str | None = None,
    ingestion_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    corpus_doc: bool | None = None,
):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        conditions = []
        params = []

        if issuing_body:
            if issuing_body == "EMA":
                conditions.append("issuing_body IN (%s, %s)")
                params.extend(["EMA", "EU-Commission"])
            else:
                conditions.append("issuing_body = %s")
                params.append(issuing_body)

        if doc_type:
            conditions.append("(doc_type = %s OR metadata_json->>'document_type' = %s)")
            doc_type_underscored = doc_type.replace("-", "_")
            params.extend([doc_type_underscored, doc_type])

        if ingestion_status:
            conditions.append("ingestion_status = %s")
            params.append(ingestion_status)

        if date_from:
            conditions.append("metadata_json->>'publication_date' >= %s")
            params.append(date_from)

        if date_to:
            conditions.append("metadata_json->>'publication_date' <= %s")
            params.append(date_to)

        if corpus_doc is not None:
            conditions.append("corpus_doc = %s")
            params.append(corpus_doc)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        cur.execute(f"SELECT count(*) FROM document_registry{where}", params)
        total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        order_clause = "ORDER BY metadata_json->>'publication_date' DESC NULLS LAST" if corpus_doc else "ORDER BY last_indexed_at DESC NULLS LAST"
        cur.execute(
            f"""SELECT document_id, issuing_body, doc_type, ingestion_status,
                       chunk_count, last_indexed_at, run_id,
                       metadata_json->>'document_title' as title,
                       metadata_json->>'publication_date' as pub_date,
                       metadata_json->>'document_version' as version,
                       metadata_json->>'document_type' as regulatory_type,
                       metadata_json->>'source_url' as source_url,
                       document_family_id, corpus_doc
                FROM document_registry{where}
                {order_clause}
                LIMIT %s OFFSET %s""",
            params + [page_size, offset]
        )
        rows = cur.fetchall()
        cur.close()

        items = []
        for row in rows:
            doc_id, ib, dt, status, chunk_count, li, run_id, title, pub_date, version, reg_type, source_url, fam_id, cdoc = row
            items.append({
                "document_id": doc_id,
                "document_title": title or "Untitled",
                "document_type": reg_type or None,
                "doc_type": dt,
                "document_version": version,
                "publication_date": pub_date,
                "issuing_body": normalise_agency(ib),
                "ingestion_status": status,
                "chunk_count": chunk_count or 0,
                "last_indexed_at": li.isoformat() if hasattr(li, 'isoformat') else str(li) if li else None,
                "run_id": run_id,
                "document_family_id": fam_id,
                "corpus_doc": cdoc,
                "source_url": source_url,
            })

        return {"total": total, "page": page, "page_size": page_size, "items": items}
    finally:
        conn.close()


# ── GET /api/corpus/documents/{doc_id} ────────────────────────────────────────

@router.get("/documents/{doc_id}")
async def document_detail(doc_id: str):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT document_id, issuing_body, doc_type, ingestion_status,
                      chunk_count, last_indexed_at, run_id,
                      metadata_json->>'document_title' as title,
                      metadata_json->>'publication_date' as pub_date,
                      metadata_json->>'document_version' as version,
                      metadata_json->>'document_type' as regulatory_type,
                      metadata_json->>'source_url' as source_url,
                      source_hash as pg_source_hash,
                      metadata_json->>'source_file_format' as file_format,
                      metadata_json->>'archive_path' as archive_path_json,
                      document_family_id, archive_path, feed_id, corpus_doc
               FROM document_registry WHERE document_id = %s""",
            (doc_id,)
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            raise HTTPException(status_code=404, detail="Document not found")

        (did, ib, dt, status, chunk_count, li, run_id, title, pub_date, version,
         reg_type, source_url, pg_source_hash, file_format, archive_path_json, fam_id, archive_path, feed_id, corpus_doc) = row

        # Query Qdrant for the first chunk's source_hash and total point count
        qdrant_source_hash = None
        qdrant_point_count = 0
        hash_match = True
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            scroll_result = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter={
                    "must": [{"key": "document_id", "match": {"value": doc_id}}]
                },
                limit=1,
                with_payload=["source_hash"],
            )
            points = scroll_result[0] if scroll_result else []
            if points:
                qdrant_source_hash = points[0].payload.get("source_hash")

            count_result = client.count(
                collection_name=QDRANT_COLLECTION,
                count_filter={
                    "must": [{"key": "document_id", "match": {"value": doc_id}}]
                },
                exact=True,
            )
            qdrant_point_count = count_result.count

            if pg_source_hash and qdrant_source_hash and pg_source_hash != qdrant_source_hash:
                hash_match = False
        except Exception:
            pass

        return {
            "document_id": did,
            "document_title": title or "Untitled",
            "document_type": reg_type or None,
            "doc_type": dt,
            "document_version": version,
            "publication_date": pub_date,
            "issuing_body": normalise_agency(ib),
            "ingestion_status": status,
            "chunk_count": chunk_count or 0,
            "last_indexed_at": li.isoformat() if hasattr(li, 'isoformat') else str(li) if li else None,
            "run_id": run_id,
            "document_family_id": fam_id,
            "source_url": source_url,
            "source_file_format": file_format,
            "archive_path": archive_path,
            "feed_id": feed_id,
            "corpus_doc": corpus_doc,
            "pg_source_hash": pg_source_hash,
            "qdrant_source_hash": qdrant_source_hash,
            "hash_match": hash_match,
            "qdrant_point_count": qdrant_point_count,
        }
    finally:
        conn.close()


# ── GET /api/corpus/documents/{doc_id}/chunks ─────────────────────────────────

@router.get("/documents/{doc_id}/chunks")
async def document_chunks(
    doc_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    try:
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        total = client.count(
            collection_name=QDRANT_COLLECTION,
            count_filter={
                "must": [{"key": "document_id", "match": {"value": doc_id}}]
            },
            exact=True,
        ).count

        if total == 0:
            return {"document_id": doc_id, "total": 0, "items": []}

        offset = (page - 1) * page_size
        scroll_result = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter={
                "must": [{"key": "document_id", "match": {"value": doc_id}}]
            },
            limit=page_size,
            offset=offset,
            with_payload=[
                "chunk_id", "chunk_index", "clause_id", "chunk_status",
                "char_offset_start", "char_offset_end", "cross_refs", "chunk_text",
            ],
        )
        points = scroll_result[0] if scroll_result else []

        items = []
        for pt in points:
            p = pt.payload
            items.append({
                "chunk_id": pt.id,
                "chunk_index": p.get("chunk_index"),
                "clause_id": p.get("clause_id"),
                "chunk_status": p.get("chunk_status"),
                "char_offset_start": p.get("char_offset_start"),
                "char_offset_end": p.get("char_offset_end"),
                "cross_refs": p.get("cross_refs", []),
                "chunk_text": p.get("chunk_text", ""),
            })
        items.sort(key=lambda x: x["chunk_index"] if x["chunk_index"] is not None else 0)

        return {"document_id": doc_id, "total": total, "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Qdrant error: {str(e)}")


# ── GET /api/corpus/feed-runs ─────────────────────────────────────────────────

@router.get("/feed-runs")
async def feed_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    status: str | None = None,
    feed_source: str | None = None,
):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)

        if feed_source:
            conditions.append("feed_source = %s")
            params.append(feed_source)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        cur.execute(f"SELECT count(*) FROM run_log{where}", params)
        total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        cur.execute(
            f"""SELECT run_id, triggered_at, completed_at, trigger_source,
                       feed_source, status, items_fetched, items_new,
                       items_skipped, error_count, duration_ms, error_detail,
                       n8n_execution_id
                FROM run_log{where}
                ORDER BY triggered_at DESC
                LIMIT %s OFFSET %s""",
            params + [page_size, offset]
        )
        rows = cur.fetchall()
        cur.close()

        items = []
        for row in rows:
            run_id, triggered_at, completed_at, trigger_source, feed_source, status, \
                fetched, new, skipped, err_count, dur, err_detail, n8n_exec = row
            items.append({
                "run_id": run_id,
                "triggered_at": triggered_at.isoformat() if hasattr(triggered_at, 'isoformat') else str(triggered_at) if triggered_at else None,
                "completed_at": completed_at.isoformat() if hasattr(completed_at, 'isoformat') else str(completed_at) if completed_at else None,
                "trigger_source": trigger_source,
                "feed_source": feed_source,
                "status": status,
                "items_fetched": fetched,
                "items_new": new,
                "items_skipped": skipped,
                "error_count": err_count,
                "duration_ms": dur,
                "error_detail": err_detail,
                "n8n_execution_id": n8n_exec,
            })

        return {"total": total, "page": page, "page_size": page_size, "items": items}
    finally:
        conn.close()


# ── GET /api/corpus/feed-runs/{run_id} ────────────────────────────────────────

@router.get("/feed-runs/{run_id}")
async def feed_run_detail(run_id: str):
    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT run_id, triggered_at, completed_at, trigger_source,
                      feed_source, status, items_fetched, items_new,
                      items_skipped, error_count, duration_ms, error_detail,
                      n8n_execution_id
               FROM run_log WHERE run_id = %s""",
            (run_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")

        (rid, triggered_at, completed_at, trigger_source, feed_source, status,
         fetched, new, skipped, err_count, dur, err_detail, n8n_exec) = row

        run = {
            "run_id": rid,
            "triggered_at": triggered_at.isoformat() if hasattr(triggered_at, 'isoformat') else str(triggered_at) if triggered_at else None,
            "completed_at": completed_at.isoformat() if hasattr(completed_at, 'isoformat') else str(completed_at) if completed_at else None,
            "trigger_source": trigger_source,
            "feed_source": feed_source,
            "status": status,
            "items_fetched": fetched,
            "items_new": new,
            "items_skipped": skipped,
            "error_count": err_count,
            "duration_ms": dur,
            "error_detail": err_detail,
            "n8n_execution_id": n8n_exec,
        }

        # Find documents ingested in this run.
        # Primary: match by run_id (set when run_ingest.py writes it back).
        # Fallback: if no rows, match by feed_id + created_at window — archive.py
        # registers docs after fetch_feed.py completes, so created_at > triggered_at.
        cur.execute(
            """SELECT document_id,
                      metadata_json->>'document_title' as title,
                      metadata_json->>'document_type' as doc_type,
                      metadata_json->>'publication_date' as pub_date,
                      chunk_count, ingestion_status, archive_path, source_url
               FROM document_registry WHERE run_id = %s
               ORDER BY created_at ASC""",
            (run_id,)
        )
        doc_rows = cur.fetchall()

        if not doc_rows and run.get("feed_source") and run.get("triggered_at"):
            # Fallback: find docs registered during this run's time window
            cur.execute(
                """SELECT document_id,
                          metadata_json->>'document_title' as title,
                          metadata_json->>'document_type' as doc_type,
                          metadata_json->>'publication_date' as pub_date,
                          chunk_count, ingestion_status, archive_path, source_url
                   FROM document_registry
                   WHERE feed_id = %s
                     AND created_at >= %s
                     AND created_at <= %s::timestamptz + INTERVAL '1 hour'
                     AND run_id IS NULL
                   ORDER BY created_at ASC""",
                (run["feed_source"], run["triggered_at"],
                 run.get("completed_at") or run["triggered_at"])
            )
            doc_rows = cur.fetchall()
        cur.close()

        feed_doc_types = get_feed_default_doc_types()
        feed_source = run.get("feed_source")

        documents = []
        for dr in doc_rows:
            doc_id, title, doc_type, pub_date, chunk_count, status, archive_path, source_url = dr

            # For pending docs, metadata_json is sparse — read archive metadata.json
            if not title and archive_path:
                try:
                    import pathlib
                    container_path = archive_path.replace("/mnt/data/regulatory_archive", "/archive")
                    meta_file = pathlib.Path(container_path) / "metadata.json"
                    if meta_file.exists():
                        arc_meta = json.loads(meta_file.read_text())
                        title = arc_meta.get("title") or arc_meta.get("document_title")
                        pub_date = pub_date or arc_meta.get("pub_date") or arc_meta.get("publication_date")
                        doc_type = doc_type or arc_meta.get("document_type")
                except Exception:
                    pass

            # Fall back to feed's default_doc_type when classification hasn't run yet
            if not doc_type and feed_source:
                doc_type = feed_doc_types.get(feed_source)

            documents.append({
                "document_id": doc_id,
                "document_title": title or source_url or "Untitled",
                "document_type": doc_type,
                "publication_date": pub_date,
                "chunk_count": chunk_count or 0,
                "ingestion_status": status,
            })

        return {"run": run, "documents": documents}
    finally:
        conn.close()


# ── GET /api/corpus/supersede/{document_family_id} ────────────────────────────

@router.get("/supersede/{document_family_id}")
async def supersede_chain(document_family_id: str):
    if not document_family_id:
        raise HTTPException(status_code=400, detail="document_family_id is required")

    conn = get_pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT document_id, document_family_id,
                      metadata_json->>'document_title' as title,
                      metadata_json->>'document_version' as version,
                      metadata_json->>'publication_date' as pub_date,
                      chunk_count, ingestion_status,
                      metadata_json->>'document_type' as doc_type
               FROM document_registry
               WHERE document_family_id = %s
               ORDER BY metadata_json->>'publication_date' ASC NULLS LAST""",
            (document_family_id,)
        )
        rows = cur.fetchall()
        cur.close()

        if not rows:
            raise HTTPException(status_code=404, detail="Document family not found")

        chain = []
        for row in rows:
            doc_id, fam_id, title, version, pub_date, chunk_count, status, doc_type = row
            is_superseded = status == "superseded"
            chain.append({
                "document_id": doc_id,
                "document_title": title or "Untitled",
                "document_version": version,
                "publication_date": pub_date,
                "document_type": doc_type,
                "chunk_count": chunk_count or 0,
                "ingestion_status": status,
                "document_family_id": fam_id,
                "is_superseded": is_superseded,
            })

        return {"document_family_id": document_family_id, "chain": chain}
    finally:
        conn.close()
