# /opt/scripts/ingestion/ingest.py
import json, sys, os
from datetime import datetime, timezone
from pathlib import Path
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

# Access canonical trace emitter from API tree (host + Docker paths)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../api"))
sys.path.insert(0, "/app")
from lib.trace_emitter import start_document_span

from .config import QDRANT_COLLECTION
from .registry import load_metadata, update_ingestion_status, pg_conn
from .parsing import parse_document
from .chunking import chunk_document, make_chunk_id
from .extraction import (
    extract_clause_id, extract_cross_refs,
    compute_char_offsets, extract_provenance,
)
from .payload import build_payload
from .chunk_archive import upsert_chunks_pg
from .embedding import embed
from .qdrant_client import get_client


def supersede_old_chunks(doc_id: str, old_version: str, new_version: str) -> int:
    """Mark all chunks of old_version for doc_id as superseded.

    Fetches all chunks at old_version for the document and updates their payload:
        chunk_status   = 'superseded'
        superseded_by  = new_version (semantic reference)
        superseded_at  = now (ISO timestamp)

    Args:
        doc_id: document_id to supersede
        old_version: chunker_version string to supersede
        new_version: replacement chunker_version string

    Returns:
        Number of chunks superseded (0 if none found or all already superseded)

    Idempotent: already-superseded chunks are skipped.
    """
    qdrant = get_client()
    now = datetime.now(timezone.utc).isoformat()

    # Find all chunks at old_version for this document
    pts, _ = qdrant.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(must=[
            FieldCondition(key='document_id', match=MatchValue(value=doc_id)),
            FieldCondition(key='chunker_version', match=MatchValue(value=old_version)),
        ]),
        limit=1000,
        with_payload=True,
        with_vectors=False,
    )

    if not pts:
        print(f'  No chunks found at version {old_version} for {doc_id}')
        return 0

    # Skip already-superseded chunks
    active = [pt for pt in pts if pt.payload.get('chunk_status') != 'superseded']

    if not active:
        print(f'  All {len(pts)} chunks already superseded — nothing to do')
        return 0

    # Mark each active chunk as superseded
    for pt in active:
        qdrant.set_payload(
            collection_name=QDRANT_COLLECTION,
            payload={
                'chunk_status': 'superseded',
                'superseded_by': new_version,
                'superseded_at': now,
            },
            points=[pt.id],
        )

    # Mirror supersede to PostgreSQL — keeps PG in sync with Qdrant
    from .chunk_archive import supersede_chunks_pg
    chunk_ids = [str(pt.id) for pt in active]
    supersede_chunks_pg(chunk_ids)

    print(f'  Superseded {len(active)} chunks: {doc_id} {old_version} -> {new_version}')
    return len(active)


def ingest_document(doc_id: str, chunker_version: str = 'v0.1.0',
                    old_version: str = None,
                    trace_id: str = "") -> dict:
    """Ingest one document end-to-end: parse, chunk, embed, upsert to Qdrant.

    Args:
        doc_id: Primary key in document_registry (e.g. 'EU-GMP-Annex11')
        chunker_version: Semantic version string — bump when chunking logic changes
        old_version: Previous chunker_version to supersede (None = no supersession)
                     When provided, old chunks are marked superseded BEFORE new
                     chunks are upserted, enabling versioned coexistence in Qdrant.

    Returns:
        dict with doc_id, chunks count, and jsonl path

    Registry status progression:
        parsing -> chunking -> embedding -> indexed (or failed)

    Chunk ID includes chunker_version — re-ingestion with new version creates
    new point IDs, allowing old (superseded) and new (active) to coexist.
    """
    try:
        # C1 — Load metadata
        update_ingestion_status(doc_id, 'parsing')
        meta = load_metadata(doc_id)
        print(f'C1: Metadata loaded')

        # Open document span if trace_id provided (G-T2 traced path)
        doc_span = None
        if trace_id:
            doc_span = start_document_span(
                trace_id, doc_id=doc_id,
                source_url=meta.get('source_url', ''),
            )
            print(f'  ingestion_doc span: {doc_span.span_id}')

        # C2 — Parse document
        doc, extracted_text = parse_document(meta)
        print(f'C2: Parsed ({len(extracted_text)} chars)')

        # C3 — Chunk document
        update_ingestion_status(doc_id, 'chunking')
        max_tok = 200 if meta.get('document_id') == '21-CFR-Part-11' else None
        chunks = chunk_document(doc, max_tokens=max_tok) if max_tok else chunk_document(doc)
        print(f'C3: {len(chunks)} chunks')

        # C3b — Split trapped sub-clauses (B-DV1)
        from .subclause_splitter import split_trapped_subclauses
        chunks = split_trapped_subclauses(chunks)

        # ── Post-chunking quality gate ────────────────────────────────────
        from .chunk_quality import evaluate_chunk_quality
        quality = evaluate_chunk_quality(chunks)
        if not quality["gate_pass"]:
            print(f"  [quality-gate] FAILED — {quality['gate_reason']} "
                  f"bad={quality['bad']}/{quality['total']} flags={quality['by_flag']}",
                  file=sys.stderr)
            from .registry import mark_document_not_viable
            mark_document_not_viable(doc_id, quality["gate_reason"])
            if doc_span:
                doc_span.finalize(
                    status="not_viable", chunk_count=quality["total"],
                    failure_reason=quality["gate_reason"],
                )
            return {
                'doc_id':      doc_id,
                'chunks':      quality['total'],
                'jsonl':       None,
                'gate_reason': quality['gate_reason'],
                'status':      'not_viable',
            }
        else:
            print(f"  [quality-gate] PASS — chunks={quality['total']} "
                  f"bad={quality['bad_pct']}%", file=sys.stderr)
        # ── End quality gate ──────────────────────────────────────────────

    # Carry-forward clause_id for sub-heading chunks (Annex 15 pattern)
        # Sub-sections with text-only headings inherit nearest preceding numbered clause
        last_clause = None
        clause_ids_forward = []
        for chunk in chunks:
            cid = extract_clause_id(chunk, meta)
            if cid:
                last_clause = cid
            clause_ids_forward.append(cid if cid else last_clause)


        # C9 — Supersede old chunks BEFORE upserting new ones
        if old_version:
            n = supersede_old_chunks(doc_id, old_version, chunker_version)
            print(f'C9: {n} old chunks superseded')

        # C4-C8 — Per-chunk metadata extraction + embedding
        update_ingestion_status(doc_id, 'embedding')
        points = []
        jsonl_lines = []
        search_start = 0
        _offset_warnings = []

        for i, chunk in enumerate(chunks):
            if not chunk.text or not chunk.text.strip():
                continue
            clause_id  = clause_ids_forward[i]
            cross_refs = extract_cross_refs(chunk.text)
            offsets    = compute_char_offsets(chunk.text, extracted_text, search_start)
            search_start = offsets[1]
            if (offsets[1] - offsets[0]) < 50:
                anchor = repr(chunk.text[:60])
                print(f'WARNING: char_offset span={offsets[1]-offsets[0]} doc={meta["document_id"]} chunk_index={i} anchor={anchor}')
                _offset_warnings.append((meta['document_id'], i, offsets[1] - offsets[0], chunk.text[:60]))
            prov       = extract_provenance(chunk)

            payload = build_payload(
                chunk, i, meta, clause_id, cross_refs,
                offsets, prov, chunker_version, trace_id,
            )
            # Mark new chunks as active
            payload['chunk_status'] = 'active'

            chunk_id = make_chunk_id(
                meta['document_id'], meta['document_version'], i, chunker_version
            )
            payload['chunk_id'] = chunk_id

            vector = embed(chunk.text)
            points.append(PointStruct(id=chunk_id, vector=vector, payload=payload))
            jsonl_lines.append(json.dumps(payload))

            if (i + 1) % 5 == 0 or i == len(chunks) - 1:
                print(f'  [{i+1}/{len(chunks)}] {clause_id or "—"}')

        # Post-pass: fix zero-length char_offset spans (table chunks where extraction fell through)
        for j in range(len(points)):
            cs = points[j].payload['char_offset_start']
            ce = points[j].payload['char_offset_end']
            if cs == ce:
                # Try next chunk's start; fall back to cs + 1 as minimum span
                if j + 1 < len(points) and points[j + 1].payload['char_offset_start'] > cs:
                    points[j].payload['char_offset_end'] = points[j + 1].payload['char_offset_start']
                else:
                    points[j].payload['char_offset_end'] = cs + 1

        # Batch upsert to Qdrant
        get_client().upsert(collection_name=QDRANT_COLLECTION, points=points)
        upsert_chunks_pg(points)
        print(f'Qdrant: {len(points)} upserted (+ PG)')
        if _offset_warnings:
            print(f'WARNING: char_offset — {len(_offset_warnings)} chunk(s) with span < 50 in {meta["document_id"]}:')
            for doc_id, idx, span, anchor in _offset_warnings:
                print(f'  chunk_index={idx} span={span} anchor={repr(anchor)}')

        # Write JSONL replay file
        chunks_dir = Path(meta['archive_path']) / 'chunks'
        chunks_dir.mkdir(exist_ok=True, parents=True)
        jsonl_path = chunks_dir / f'chunks_{chunker_version}.jsonl'
        jsonl_path.write_text('\n'.join(jsonl_lines))
        print(f'JSONL: {jsonl_path}')

        update_ingestion_status(doc_id, 'indexed', chunk_count=len(points))

        if doc_span:
            doc_span.finalize(
                status="success", chunk_count=len(points),
                embedding_model="mxbai-embed-large",
            )

        return {'doc_id': doc_id, 'chunks': len(points), 'jsonl': str(jsonl_path)}

    except Exception as e:
        if doc_span:
            doc_span.finalize(
                status="failed", chunk_count=0,
                failure_reason=f'{type(e).__name__}: {str(e)[:200]}',
            )
        update_ingestion_status(
            doc_id, 'failed',
            ingestion_error=f'{type(e).__name__}: {str(e)[:200]}'
        )
        raise


def supersede_by_family_id(new_doc_id: str, family_id: str,
                            new_chunker_version: str) -> int:
    """Supersede all chunks from the same document family, excluding the new document.

    Called after ingesting a new version of a document. Finds all chunks
    sharing document_family_id that do NOT belong to new_doc_id and marks
    them chunk_status=superseded.

    Args:
        new_doc_id: The document_id just ingested (excluded from supersession)
        family_id: The document_family_id shared by the document group
        new_chunker_version: chunker_version of the new document (stored as superseded_by)

    Returns:
        Number of chunks superseded.
    """
    qdrant = get_client()
    now = datetime.now(timezone.utc).isoformat()

    pts, _ = qdrant.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=Filter(must=[
            FieldCondition(
                key='document_family_id',
                match=MatchValue(value=family_id)
            ),
            FieldCondition(
                key='chunk_status',
                match=MatchValue(value='active')
            ),
        ], must_not=[
            FieldCondition(
                key='document_id',
                match=MatchValue(value=new_doc_id)
            ),
        ]),
        limit=5000,
        with_payload=True,
        with_vectors=False,
    )

    if not pts:
        print(f'  No active chunks to supersede in family {family_id!r} '
              f'(excluding {new_doc_id})')
        return 0

    for pt in pts:
        qdrant.set_payload(
            collection_name=QDRANT_COLLECTION,
            payload={
                'chunk_status':   'superseded',
                'superseded_by':  new_doc_id,
                'superseded_at':  now,
            },
            points=[pt.id],
        )

    # Also mark superseded documents in PostgreSQL
    superseded_doc_ids = set()
    for pt in pts:
        doc_id = pt.payload.get("document_id")
        if doc_id and doc_id != new_doc_id:
            superseded_doc_ids.add(doc_id)

    for doc_id in superseded_doc_ids:
        try:
            with pg_conn() as conn:
                with conn.cursor() as cur:
                    # GATE3c: write superseded status to ingestion_state
                    cur.execute(
                        "INSERT INTO ingestion_state (document_id, ingestion_status, updated_at) "
                        "VALUES (%s, 'superseded', NOW()) "
                        "ON CONFLICT (document_id) DO UPDATE SET "
                        "ingestion_status = 'superseded', "
                        "updated_at = NOW()",
                        (doc_id,),
                    )
        except Exception as e:
            print(f"  Warning: failed to update ingestion_status for {doc_id}: {e}")

    print(f'  supersede_by_family_id: {len(pts)} chunks superseded '
          f'(family={family_id!r}, new={new_doc_id})')
    return len(pts)
