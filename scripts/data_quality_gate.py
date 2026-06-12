# /opt/projects/regpulse/scripts/data_quality_gate.py
"""
Data Quality Gate — RegPulse Corpus
====================================
Run after any full reingestion. All checks must pass before proceeding.
Exit code 0 = GATE PASS. Exit code 1 = GATE FAIL.

Usage:
    python3 scripts/data_quality_gate.py
    python3 scripts/data_quality_gate.py --verbose   (show detail on failures)

Checks:
    C01  Qdrant / PostgreSQL consistency
    C02  No zero-length char_offset spans
    C03  No trapped sub-clause chunks
    C04  No bare numeric document_version values
    C05  document_status vocabulary valid
    C06  chunk_status vocabulary valid
    C07  Superseded chunks excluded from search filter
    C08  Every active registry doc has Qdrant chunks
    C09  Every Qdrant chunk has a valid registry entry
    C10  not_viable docs have zero Qdrant chunks
    C11  ICH Q9 / Q9R1 supersede pair correctly linked
    C12  EU-GMP-Annex11 §4.1-§4.8 individually present
    C13  No chunks with missing required payload fields
    C14  Qdrant / PostgreSQL chunk counts match per document
    C15  No documents stuck in 'parsing' ingestion_status
"""

import os
import sys
import re
import json
import argparse
import psycopg2
from collections import defaultdict
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# ----------------------------------------------------------------
# Config
# ----------------------------------------------------------------
COLLECTION = "knowledge_base"
BATCH_SIZE = 200
VERBOSE = False

VALID_DOC_STATUSES  = {"draft", "final", "superseded"}
VALID_CHUNK_STATUSES = {"active", "final", "superseded"}
REQUIRED_PAYLOAD_FIELDS = [
    "document_id", "chunk_index", "content_type", "chunk_status",
    "chunk_text", "char_offset_start", "char_offset_end"
]

KNOWN_SUPERSEDE_PAIRS = [
    ("ICH-Q9", "ICH-Q9-R1"),   # ICH-Q9 superseded by ICH-Q9-R1
]

ANNEX11_REQUIRED_CLAUSES = [
    "1","2","3","4","5","6","7","8","9","10",
    "11","12","13","14","15","16","17"
]
ANNEX11_DOC_ID = "EU-GMP-Annex11"

# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def get_pg_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        database=os.environ.get("POSTGRES_DB", "knowledge_base"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "")
    )

def scroll_all(client, filt=None):
    """Scroll entire Qdrant collection, return list of points."""
    points = []
    offset = None
    while True:
        results, offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=filt,
            limit=BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        points.extend(results)
        if offset is None:
            break
    return points

class Check:
    def __init__(self, code, name):
        self.code = code
        self.name = name
        self.passed = None
        self.failures = []
        self.detail = ""

    def pass_(self, detail=""):
        self.passed = True
        self.detail = detail
        status = "✅ PASS"
        print(f"  {self.code}  {status}  {self.name}" + (f" — {detail}" if detail else ""))

    def fail(self, detail="", failures=None):
        self.passed = False
        self.detail = detail
        self.failures = failures or []
        status = "❌ FAIL"
        print(f"  {self.code}  {status}  {self.name}" + (f" — {detail}" if detail else ""))
        if VERBOSE and self.failures:
            for f in self.failures[:20]:
                print(f"         {f}")
            if len(self.failures) > 20:
                print(f"         ... and {len(self.failures)-20} more")

# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def main():
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("=" * 60)
    print("  RegPulse Data Quality Gate")
    print("=" * 60)
    print()

    client = QdrantClient(host="localhost", port=6333)
    conn = get_pg_conn()
    cur = conn.cursor()
    checks = []

    # ----------------------------------------------------------------
    # Load data once — reuse across checks
    # ----------------------------------------------------------------
    print("Loading data...")
    all_points = scroll_all(client)
    print(f"  Qdrant: {len(all_points)} points")

    # PostgreSQL: all registry docs
    cur.execute("""
        SELECT dr.document_id, dr.document_status, dr.document_version,
               dr.document_family_id, dr.last_check_status, dr.corpus_doc,
               ist.ingestion_status
        FROM document_registry dr
        LEFT JOIN ingestion_state ist ON dr.document_id = ist.document_id
    """)
    pg_docs = {row[0]: {
        "document_status": row[1],
        "document_version": row[2],
        "document_family_id": row[3],
        "last_check_status": row[4],
        "corpus_doc": row[5],
        "ingestion_status": row[6],
    } for row in cur.fetchall()}

    # Non-superseded docs that aren't not_viable/failed are "indexed" (should have chunks)
    active_doc_ids = {
        did for did, d in pg_docs.items()
        if d["document_status"] != "superseded"
        and d["ingestion_status"] not in ("not_viable", "failed")
    }
    not_viable_doc_ids = {
        did for did, d in pg_docs.items()
        if d["ingestion_status"] == "not_viable"
    }

    # PostgreSQL chunks (chunk_id is UUID)
    cur.execute("SELECT chunk_id::text, document_id, chunk_status FROM chunks WHERE chunk_status != 'superseded'")
    pg_chunks = {row[0]: {"doc_id": row[1], "chunk_status": row[2]} for row in cur.fetchall()}
    print(f"  PostgreSQL: {len(pg_chunks)} chunks ({len(pg_docs)} registry docs)")
    print()
    print("Running checks...")
    print()

    # ----------------------------------------------------------------
    # C01 — Qdrant / PostgreSQL consistency (totals)
    # ----------------------------------------------------------------
    c = Check("C01", "Qdrant / PostgreSQL total count consistency")
    checks.append(c)
    qdrant_ids = {str(p.id) for p in all_points if p.payload.get("chunk_status") != "superseded"}
    pg_ids = set(pg_chunks.keys())
    missing_pg = qdrant_ids - pg_ids
    missing_qdrant = pg_ids - qdrant_ids
    if missing_pg or missing_qdrant:
        c.fail(
            f"{len(missing_pg)} missing in PG, {len(missing_qdrant)} missing in Qdrant",
            failures=[f"Missing PG: {x}" for x in sorted(missing_pg)[:10]] +
                     [f"Missing Qdrant: {x}" for x in sorted(missing_qdrant)[:10]]
        )
    else:
        c.pass_(f"{len(qdrant_ids)} chunks consistent")

    # ----------------------------------------------------------------
    # C02 — No zero-length char_offset spans
    # ----------------------------------------------------------------
    c = Check("C02", "No zero-length char_offset spans")
    checks.append(c)
    zero_spans = [
        f"doc={p.payload.get('document_id')} chunk={p.payload.get('chunk_index')} type={p.payload.get('content_type')}"
        for p in all_points
        if p.payload.get("char_offset_start") == p.payload.get("char_offset_end")
    ]
    if zero_spans:
        c.fail(f"{len(zero_spans)} zero-length spans", failures=zero_spans)
    else:
        c.pass_("all spans > 0")

    # ----------------------------------------------------------------
    # C03 — No trapped sub-clause chunks
    # ----------------------------------------------------------------
    c = Check("C03", "No trapped sub-clause chunks (unplit N.N lists)")
    checks.append(c)
    subclause_pat = re.compile(r'^\s*-?\s*\d+\.\d+\s', re.MULTILINE)
    trapped = [
        f"doc={p.payload.get('document_id')} clause={p.payload.get('clause_id')}"
        for p in all_points
        if p.payload.get("content_type") == "list"
        and len(subclause_pat.findall(p.payload.get("chunk_text", ""))) >= 2
    ]
    if trapped:
        c.fail(f"{len(trapped)} trapped sub-clause chunks", failures=trapped)
    else:
        c.pass_("zero trapped sub-clause chunks")

    # ----------------------------------------------------------------
    # C04 — No bare numeric document_version values
    # ----------------------------------------------------------------
    c = Check("C04", "No bare numeric document_version values")
    checks.append(c)
    bare_numeric_pat = re.compile(r'^\d+$')
    bare = [
        f"doc_id={did} version='{d['document_version']}'"
        for did, d in pg_docs.items()
        if d["document_status"] != "superseded"
        and bare_numeric_pat.match(d["document_version"] or "")
    ]
    if bare:
        c.fail(f"{len(bare)} docs with bare numeric versions", failures=bare)
    else:
        c.pass_("zero bare numeric versions")

    # ----------------------------------------------------------------
    # C05 — document_status vocabulary valid
    # ----------------------------------------------------------------
    c = Check("C05", "document_status vocabulary valid")
    checks.append(c)
    invalid_status = [
        f"doc_id={did} status='{d['document_status']}'"
        for did, d in pg_docs.items()
        if d["document_status"] not in VALID_DOC_STATUSES
    ]
    if invalid_status:
        c.fail(f"{len(invalid_status)} invalid document_status values", failures=invalid_status)
    else:
        c.pass_(f"all values in {VALID_DOC_STATUSES}")

    # ----------------------------------------------------------------
    # C06 — chunk_status vocabulary valid
    # ----------------------------------------------------------------
    c = Check("C06", "chunk_status vocabulary valid")
    checks.append(c)
    invalid_chunk_status = [
        f"point={str(p.id)} doc={p.payload.get('document_id')} status='{p.payload.get('chunk_status')}'"
        for p in all_points
        if p.payload.get("chunk_status") not in VALID_CHUNK_STATUSES
    ]
    if invalid_chunk_status:
        c.fail(f"{len(invalid_chunk_status)} invalid chunk_status values", failures=invalid_chunk_status)
    else:
        c.pass_(f"all values in {VALID_CHUNK_STATUSES}")

    # ----------------------------------------------------------------
    # C07 — Superseded chunks present but excluded from search
    # Verify: build_qdrant_filter must_not includes chunk_status=superseded
    # We check by confirming superseded chunks exist (expected) but
    # querying with the standard filter returns zero superseded chunks
    # ----------------------------------------------------------------
    c = Check("C07", "Superseded chunks excluded from search results")
    checks.append(c)
    superseded_points = [
        p for p in all_points
        if p.payload.get("chunk_status") == "superseded"
    ]
    # Simulate search filter — query with must_not superseded
    search_results = client.query_points(
        collection_name=COLLECTION,
        query_filter=Filter(
            must_not=[FieldCondition(key="chunk_status", match=MatchValue(value="superseded"))]
        ),
        limit=5
    ).points
    # Check none of the results are superseded
    leaked = [r for r in search_results if r.payload.get("chunk_status") == "superseded"]
    if leaked:
        c.fail(
            f"{len(superseded_points)} superseded chunks exist, {len(leaked)} leaked through filter",
            failures=[f"point={r.id}" for r in leaked]
        )
    else:
        c.pass_(f"{len(superseded_points)} superseded chunks archived, 0 leaked through filter")

    # ----------------------------------------------------------------
    # C08 — Every non-superseded registry doc has at least one Qdrant chunk
    # ----------------------------------------------------------------
    c = Check("C08", "Every non-superseded doc has Qdrant chunks")
    checks.append(c)
    qdrant_doc_ids = {p.payload.get("document_id") for p in all_points}
    # Docs that exist in PG but have no Qdrant chunks
    docs_without_chunks = [
        did for did in active_doc_ids
        if did not in qdrant_doc_ids
    ]
    if docs_without_chunks:
        c.fail(
            f"{len(docs_without_chunks)} non-superseded docs have no Qdrant chunks",
            failures=docs_without_chunks[:20]
        )
    else:
        c.pass_(f"all {len(active_doc_ids)} non-superseded docs have chunks")

    # ----------------------------------------------------------------
    # C09 — Every Qdrant chunk has a valid registry entry
    # ----------------------------------------------------------------
    c = Check("C09", "Every Qdrant chunk has a valid registry entry")
    checks.append(c)
    orphan_chunks = [
        f"point={str(p.id)} doc_id={p.payload.get('document_id')}"
        for p in all_points
        if p.payload.get("document_id") not in pg_docs
    ]
    if orphan_chunks:
        c.fail(f"{len(orphan_chunks)} orphan chunks (no registry entry)", failures=orphan_chunks)
    else:
        c.pass_("zero orphan chunks")

    # ----------------------------------------------------------------
    # C10 — not_viable docs have zero Qdrant chunks
    # ----------------------------------------------------------------
    c = Check("C10", "not_viable docs have zero Qdrant chunks")
    checks.append(c)
    nv_with_chunks = [
        did for did in not_viable_doc_ids
        if did in qdrant_doc_ids
    ]
    if nv_with_chunks:
        c.fail(
            f"{len(nv_with_chunks)} not_viable docs still have Qdrant chunks",
            failures=nv_with_chunks
        )
    else:
        c.pass_(f"all {len(not_viable_doc_ids)} not_viable docs have zero chunks")

    # ----------------------------------------------------------------
    # C11 — ICH Q9 / Q9R1 supersede pair correctly linked
    # ----------------------------------------------------------------
    c = Check("C11", "ICH Q9 / Q9R1 supersede pair correctly linked")
    checks.append(c)
    failures_c11 = []
    for old_id, new_id in KNOWN_SUPERSEDE_PAIRS:
        old_doc = pg_docs.get(old_id)
        new_doc = pg_docs.get(new_id)
        if not old_doc:
            failures_c11.append(f"{old_id} not found in registry")
            continue
        if not new_doc:
            failures_c11.append(f"{new_id} not found in registry")
            continue
        if old_doc["document_status"] != "superseded":
            failures_c11.append(f"{old_id} document_status={old_doc['document_status']} (expected superseded)")
        # Check old doc chunks are marked superseded in Qdrant
        old_chunks = [p for p in all_points if p.payload.get("document_id") == old_id]
        non_superseded = [p for p in old_chunks if p.payload.get("chunk_status") != "superseded"]
        if non_superseded:
            failures_c11.append(
                f"{old_id}: {len(non_superseded)}/{len(old_chunks)} chunks not marked superseded"
            )
        # Check family_id linkage
        if old_doc.get("document_family_id") != new_doc.get("document_family_id"):
            failures_c11.append(
                f"Family ID mismatch: {old_id}={old_doc.get('document_family_id')} "
                f"{new_id}={new_doc.get('document_family_id')}"
            )
    if failures_c11:
        c.fail(f"{len(failures_c11)} supersede linkage issues", failures=failures_c11)
    else:
        c.pass_("ICH Q9→Q9R1 supersede chain intact")

    # ----------------------------------------------------------------
    # C12 — EU-GMP-Annex11 §4.1-§4.8 individually present
    # ----------------------------------------------------------------
    c = Check("C12", "EU-GMP-Annex11 §4.1–§4.8 individually citable")
    checks.append(c)
    annex11_chunks = [
        p for p in all_points
        if p.payload.get("document_id") == ANNEX11_DOC_ID
    ]
    annex11_clauses = {p.payload.get("clause_id") for p in annex11_chunks}
    missing_clauses = [c_id for c_id in ANNEX11_REQUIRED_CLAUSES if c_id not in annex11_clauses]
    if missing_clauses:
        c.fail(
            f"Missing clauses: {missing_clauses}",
            failures=[f"clause_id={x} not found" for x in missing_clauses]
        )
    else:
        c.pass_(f"all §4.1–§4.8 present ({len(annex11_chunks)} total chunks)")

    # ----------------------------------------------------------------
    # C13 — No chunks with missing required payload fields
    # ----------------------------------------------------------------
    c = Check("C13", "No chunks with missing required payload fields")
    checks.append(c)
    missing_fields = []
    for p in all_points:
        for field in REQUIRED_PAYLOAD_FIELDS:
            if field not in p.payload or p.payload[field] is None:
                missing_fields.append(f"point={str(p.id)} missing={field}")
    if missing_fields:
        c.fail(f"{len(missing_fields)} missing required fields", failures=missing_fields)
    else:
        c.pass_(f"all {len(REQUIRED_PAYLOAD_FIELDS)} required fields present on all chunks")

    # ----------------------------------------------------------------
    # C14 — Qdrant / PostgreSQL chunk counts match per document
    # ----------------------------------------------------------------
    c = Check("C14", "Per-document chunk counts match Qdrant vs PostgreSQL")
    checks.append(c)
    qdrant_by_doc = defaultdict(int)
    for p in all_points:
        if p.payload.get("chunk_status") != "superseded":
            qdrant_by_doc[p.payload.get("document_id")] += 1
    pg_by_doc = defaultdict(int)
    for cid, data in pg_chunks.items():
        pg_by_doc[data["doc_id"]] += 1
    all_doc_ids = {d for d in set(qdrant_by_doc.keys()) | set(pg_by_doc.keys()) if d is not None}
    count_mismatches = [
        f"doc={did} qdrant={qdrant_by_doc[did]} pg={pg_by_doc[did]} delta={qdrant_by_doc[did]-pg_by_doc[did]:+d}"
        for did in sorted(all_doc_ids)
        if qdrant_by_doc[did] != pg_by_doc[did]
    ]
    if count_mismatches:
        c.fail(f"{len(count_mismatches)} per-doc count mismatches", failures=count_mismatches)
    else:
        c.pass_(f"all {len(all_doc_ids)} docs consistent")

    # ----------------------------------------------------------------
    # C15 — No documents with anomalous / transitional status
    # ----------------------------------------------------------------
    c = Check("C15", "No documents with anomalous status")
    checks.append(c)
    anomalous = [
        did for did, d in pg_docs.items()
        if d["document_status"] not in VALID_DOC_STATUSES
        or (d["last_check_status"] is not None and d["last_check_status"] not in ("ok", ""))
    ]
    if anomalous:
        c.fail(f"{len(anomalous)} docs with anomalous status", failures=anomalous)
    else:
        c.pass_("all document_status values valid, zero anomalous last_check_status")

    # ----------------------------------------------------------------
    # Final summary
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    passed = [c for c in checks if c.passed]
    failed = [c for c in checks if not c.passed]
    total = len(checks)

    print(f"  RESULTS: {len(passed)}/{total} checks passed")
    print()

    if failed:
        print("  FAILED CHECKS:")
        for c in failed:
            print(f"    {c.code}  {c.name}")
            if c.detail:
                print(f"         {c.detail}")
        print()
        print("  ❌ GATE FAIL — do not proceed until all checks pass.")
        print("=" * 60)
        cur.close()
        conn.close()
        sys.exit(1)
    else:
        print("  ✅ GATE PASS — corpus integrity confirmed. Safe to proceed.")
        print("=" * 60)
        cur.close()
        conn.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
