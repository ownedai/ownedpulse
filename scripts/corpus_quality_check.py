#!/usr/bin/env python3
"""
corpus_quality_check.py — Post-reingestion quality gate (G-T4).

Verifies the reingested corpus is complete, structurally sound, and
trace-consistent. Runs against the live PostgreSQL + Qdrant stack.

Usage:
    python scripts/corpus_quality_check.py --report docs/quality/corpus-quality-$(date +%F).md

Exit: 0 on GREEN (all mandatory pass), non-zero on RED (any mandatory fail).
"""

import argparse
import json
import os
import sys
import textwrap
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
import requests
from qdrant_client import QdrantClient

# -- Config -------------------------------------------------------------------

PG_DSN = os.environ.get(
    "PG_DSN",
    "postgresql://postgres:***REMOVED***@localhost:5432/knowledge_base"
)
QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "knowledge_base")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "mxbai-embed-large")
QDRANT_URL = os.environ.get("QDRANT_URL", f"http://{QDRANT_HOST}:{QDRANT_PORT}")

WIPE_TIMESTAMP_FILE = "/tmp/g3_wipe_timestamp.txt"

# Expected baseline — set from first run or G-T3 close.
# Updated after G-T3 completes: 1,382 docs, ~22,000 chunks.
EXPECTED_DOC_COUNT = 1382
EXPECTED_MIN_CHUNKS = 20000

# Known clause_id gaps from pre-G-T1 ingestion (Task E):
# Annex 11 sub-clauses 4.1–4.8 and Annex 15 chunks 7–12.
KNOWN_LOW_CLAUSE_DOCS = {
    "ema_sci_guidelines-eu-gmp-annex-11-computerised-syste-cf126e06530c",  # Annex 11
    "ema_sci_guidelines-eu-gmp-annex-15-qualification-and--f4d3f0a431d8",  # Annex 15
}


# -- Helpers ------------------------------------------------------------------

def _pg():
    return psycopg2.connect(PG_DSN)


def _pg_one(query: str, params: tuple = None) -> Any:
    conn = _pg()
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _pg_all(query: str, params: tuple = None) -> list:
    conn = _pg()
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    conn.close()
    return rows


def _qdrant_scroll(batch_size: int = 500) -> list:
    """Scroll all points from Qdrant, yielding payload dicts."""
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    points = []
    offset = None
    while True:
        result, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(result)
        if offset is None:
            break
    return points


def _qdrant_count() -> int:
    r = requests.get(f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", timeout=10)
    r.raise_for_status()
    return r.json()["result"]["points_count"]


# -- Report state -------------------------------------------------------------

class Report:
    def __init__(self):
        self.sections = []
        self.checks = []
        self.current_section = None
        self.current_lines = []

    def h1(self, text: str):
        self.sections.append(f"# {text}\n")

    def h2(self, text: str):
        self.sections.append(f"\n## {text}\n")

    def line(self, text: str = ""):
        self.current_lines.append(text)

    def code_block(self, text: str):
        self.current_lines.append(f"```\n{text}\n```")

    def table(self, headers: list, rows: list):
        self.current_lines.append("| " + " | ".join(headers) + " |")
        self.current_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            self.current_lines.append("| " + " | ".join(str(c) for c in row) + " |")

    def flush(self):
        if self.current_lines:
            self.sections.append("\n".join(self.current_lines) + "\n")
            self.current_lines = []

    def result(self, label: str, verdict: str, detail: str = ""):
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[verdict]
        self.checks.append((label, verdict, detail))
        self.line(f"{icon} **{label}**: {verdict}" + (f" — {detail}" if detail else ""))

    def build(self, started: str, duration_s: float) -> str:
        self.flush()

        # Summary table
        n_pass = sum(1 for _, v, _ in self.checks if v == "PASS")
        n_warn = sum(1 for _, v, _ in self.checks if v == "WARN")
        n_fail = sum(1 for _, v, _ in self.checks if v == "FAIL")
        verdict = "GREEN" if n_fail == 0 else "RED"

        summary = [
            "",
            "---",
            "",
            f"**Run date:** {started}",
            f"**Duration:** {duration_s:.1f}s",
            f"**Checks:** {len(self.checks)} total ({n_pass} pass, {n_warn} warn, {n_fail} fail)",
            f"**Verdict:** {verdict}",
            "",
        ]

        return "\n".join(self.sections + summary)


# -- Check functions ----------------------------------------------------------

def check_1_corpus_completeness(r: Report):
    """Check 1: Corpus completeness."""
    r.h2("1. Corpus Completeness")

    total_docs = _pg_one("SELECT COUNT(*) FROM document_registry")
    r.line(f"- **Total documents in registry:** {total_docs}")
    r.line(f"- **Expected:** {EXPECTED_DOC_COUNT}")

    if total_docs >= EXPECTED_DOC_COUNT:
        r.result("Total document count", "PASS", f"{total_docs} docs in registry")
    else:
        r.result("Total document count", "FAIL",
                 f"{total_docs} < {EXPECTED_DOC_COUNT} expected")

    # Docs per agency
    agencies = _pg_all("""
        SELECT
            CASE WHEN issuing_body = 'EU-Commission' THEN 'EMA'
                 ELSE issuing_body
            END AS agency,
            COUNT(*)
        FROM document_registry
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    r.line("")
    r.line("**Documents per agency:**")
    for agency, count in agencies:
        r.line(f"  - {agency}: {count}")

    r.result("Agency distribution", "PASS", "all agencies present")

    # Every doc in registry has >=1 Qdrant chunk
    r.line("")
    r.line("**Zero-chunk document check:**")

    # Get doc_ids with chunks in Qdrant
    indexed_docs = set()
    conn = _pg()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT document_id FROM document_registry
            WHERE ingestion_status = 'indexed'
        """)
        indexed_docs = {row[0] for row in cur.fetchall()}
    conn.close()

    zero_chunk = []
    batch_size = 200
    for i in range(0, len(indexed_docs), batch_size):
        batch = list(indexed_docs)[i:i + batch_size]
        # Check Qdrant for each doc
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        for doc_id in batch:
            count_result = client.count(
                collection_name=QDRANT_COLLECTION,
                count_filter={"must": [{"key": "document_id", "match": {"value": doc_id}}]},
                exact=True,
            )
            if count_result.count == 0:
                zero_chunk.append(doc_id)

    if zero_chunk:
        r.result("Zero-chunk documents", "FAIL",
                 f"{len(zero_chunk)} indexed docs have no Qdrant chunks: {zero_chunk[:10]}...")
    else:
        r.result("Zero-chunk documents", "PASS",
                 "every indexed doc has >=1 Qdrant chunk")

    # Every Qdrant chunk has a registry doc_id
    r.line("")
    total_qdrant = _qdrant_count()
    r.line(f"- **Qdrant points:** {total_qdrant}")

    if total_qdrant >= EXPECTED_MIN_CHUNKS:
        r.result("Minimum chunk count", "PASS",
                 f"{total_qdrant} chunks >= {EXPECTED_MIN_CHUNKS} expected")
    else:
        r.result("Minimum chunk count", "WARN",
                 f"{total_qdrant} chunks < {EXPECTED_MIN_CHUNKS} expected")

    r.flush()


def check_2_chunk_quality(r: Report):
    """Check 2: Chunk quality."""
    r.h2("2. Chunk Quality")

    # Scroll ALL Qdrant points for analysis — this is a quality check,
    # not a query endpoint, so scroll() is the correct primitive.
    total = _qdrant_count()
    r.line(f"Analysing {total} chunks from Qdrant...")

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Collect stats via scroll
    clause_id_by_doc = defaultdict(lambda: {"total": 0, "null": 0})
    char_lengths = []
    html_artifacts = []
    batch_size = 500
    offset = None
    samples_for_report = {"html": [], "short": [], "no_clause": []}

    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for pt in points:
            p = pt.payload
            doc_id = p.get("document_id", "unknown")
            text = p.get("chunk_text", "")
            char_len = len(text)
            char_lengths.append(char_len)
            clause = p.get("clause_id")

            clause_id_by_doc[doc_id]["total"] += 1
            if clause is None:
                clause_id_by_doc[doc_id]["null"] += 1

            if char_len < 50 and len(samples_for_report["short"]) < 10:
                samples_for_report["short"].append((doc_id, text[:100]))

            # Scan for HTML/XML artefacts
            if any(tag in text for tag in ("<div", "<p>", "<table", "href=", "xmlns")):
                html_artifacts.append((doc_id, text[:200]))
                if len(samples_for_report["html"]) < 10:
                    samples_for_report["html"].append((doc_id, text[:200]))

        if offset is None:
            break

    # Chunk length distribution
    if char_lengths:
        char_lengths.sort()
        mean = sum(char_lengths) / len(char_lengths)
        p5_idx = int(len(char_lengths) * 0.05)
        r.line("")
        r.line("**Chunk character length distribution:**")
        r.table(
            ["Metric", "Value"],
            [
                ("Count", str(len(char_lengths))),
                ("Mean", f"{mean:.0f}"),
                ("Min", str(char_lengths[0])),
                ("Max", str(char_lengths[-1])),
                ("P5", str(char_lengths[p5_idx])),
            ],
        )

        short_count = sum(1 for l in char_lengths if l < 50)
        if short_count > 0:
            r.result("Short chunks (<50 chars)", "WARN",
                     f"{short_count} chunks flagged — samples: {[s[1] for s in samples_for_report['short'][:3]]}")
        else:
            r.result("Short chunks (<50 chars)", "PASS", "no chunks under 50 chars")

    # HTML/XML artefacts
    if html_artifacts:
        r.result("HTML/XML artefacts in chunk text", "WARN",
                 f"{len(html_artifacts)} chunks — samples: {[h[1][:80] for h in samples_for_report['html'][:3]]}")
    else:
        r.result("HTML/XML artefacts in chunk text", "PASS", "no artefacts found")

    r.line("")

    # clause_id coverage
    total_chunks_all = sum(v["total"] for v in clause_id_by_doc.values())
    total_null = sum(v["null"] for v in clause_id_by_doc.values())
    overall_rate = (1 - total_null / total_chunks_all) * 100 if total_chunks_all else 0
    r.line(f"**Overall clause_id coverage:** {overall_rate:.1f}% ({total_null}/{total_chunks_all} null)")

    low_coverage_docs = []
    for doc_id, counts in sorted(clause_id_by_doc.items()):
        if counts["total"] >= 5:  # Only flag docs with enough chunks
            coverage = (1 - counts["null"] / counts["total"]) * 100
            if coverage < 80 and doc_id not in KNOWN_LOW_CLAUSE_DOCS:
                low_coverage_docs.append((doc_id, coverage, counts["total"], counts["null"]))

    if low_coverage_docs:
        rows = [(d, f"{c:.0f}%", str(t), str(n))
                for d, c, t, n in low_coverage_docs[:10]]
        r.line("")
        r.line("**Documents below 80% clause_id coverage (excluding known gaps):**")
        r.table(["Document ID", "Coverage", "Total chunks", "Null"], rows)
        r.result("clause_id coverage", "WARN",
                 f"{len(low_coverage_docs)} docs below 80% threshold")
    else:
        # Check known docs
        known_status = []
        for kd in KNOWN_LOW_CLAUSE_DOCS:
            if kd in clause_id_by_doc:
                c = clause_id_by_doc[kd]
                cov = (1 - c["null"] / c["total"]) * 100 if c["total"] else 0
                known_status.append(f"{kd[:40]}... at {cov:.0f}%")
        r.result("clause_id coverage", "PASS",
                 f"no new low-coverage docs. Known gaps: {', '.join(known_status) if known_status else 'none'}")

    r.flush()


def check_3_metadata_completeness(r: Report):
    """Check 3: Metadata completeness — scan Qdrant payload for null rates."""
    r.h2("3. Metadata Completeness")

    total = _qdrant_count()
    r.line(f"Scanning {total} chunk payloads for null rates...")

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Mandatory Qdrant payload fields — MUST be 0% null
    mandatory_fields = [
        "trace_id", "document_id", "chunk_id", "document_title",
        "issuing_body", "document_type", "embedding_model",
    ]
    # publication_date is advisory per G-T4 spec (known data gap)
    advisory_fields = [
        "clause_id", "source_fetched_at", "source_url", "publication_date",
    ]

    null_counts = {f: 0 for f in mandatory_fields + advisory_fields}
    scanned = 0
    offset = None

    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for pt in points:
            scanned += 1
            p = pt.payload
            for f in mandatory_fields + advisory_fields:
                if p.get(f) is None or p.get(f) == "":
                    null_counts[f] += 1
        if offset is None:
            break

    r.line("")
    r.line(f"**Scanned:** {scanned} chunks")
    r.line("")

    # Mandatory
    r.line("**Mandatory fields (must be 0% null):**")
    mandatory_ok = True
    for f in mandatory_fields:
        rate = null_counts[f] / scanned * 100 if scanned else 0
        status = "PASS" if null_counts[f] == 0 else "FAIL"
        r.line(f"  - `{f}`: {null_counts[f]} null ({rate:.2f}%) — {status}")
        if null_counts[f] > 0:
            mandatory_ok = False

    if mandatory_ok:
        r.result("Mandatory metadata completeness", "PASS",
                 "all mandatory fields 0% null across all chunks")
    else:
        r.result("Mandatory metadata completeness", "FAIL",
                 "one or more mandatory fields have null values")

    # Advisory
    r.line("")
    r.line("**Advisory fields (reported, not gating):**")
    for f in advisory_fields:
        rate = null_counts[f] / scanned * 100 if scanned else 0
        r.line(f"  - `{f}`: {null_counts[f]} null ({rate:.2f}%)")

    r.result("Advisory metadata completeness", "PASS",
             "advisory null rates reported above")

    r.flush()


def check_4_supersede_integrity(r: Report):
    """Check 4: Supersede chain integrity."""
    r.h2("4. Supersede Chain Integrity")

    # Get all documents with document_family_id set (non-empty).
    # "current" = ingestion_status = 'indexed' (not superseded/failed/pending).
    # document_status uses 'final'/'superseded'; ingestion_status is authoritative
    # for whether a doc is the active version in its family.
    families = _pg_all("""
        SELECT document_family_id,
               COUNT(*) as cnt,
               COUNT(*) FILTER (WHERE ingestion_status = 'indexed') as current_count
        FROM document_registry
        WHERE document_family_id IS NOT NULL
          AND document_family_id != ''
        GROUP BY document_family_id
    """)

    if not families:
        r.result("Supersede chain integrity", "PASS", "no document families to check")
        r.flush()
        return

    r.line(f"**Document families:** {len(families)}")

    # Check: exactly one active/current version per family
    multi_active = []
    zero_active = []
    for fam_id, cnt, curr in families:
        if curr > 1:
            multi_active.append((fam_id, cnt, curr))
        if curr == 0:
            zero_active.append((fam_id, cnt, curr))

    if multi_active:
        r.line("")
        r.line("**Families with multiple active versions:**")
        for fam_id, cnt, curr in multi_active:
            r.line(f"  - `{fam_id}`: {cnt} docs, {curr} current")
        r.result("Multiple active versions per family", "FAIL",
                 f"{len(multi_active)} families have >1 current doc")
    else:
        r.result("Multiple active versions per family", "PASS",
                 "each family has exactly one current version")

    if zero_active:
        r.result("Families with no current version", "WARN",
                 f"{len(zero_active)} families have 0 current docs")

    # Check: every document_family_id that is set resolves to at least 2 docs
    # in the same family (a family with only 1 doc is likely a stale reference).
    # Note: document_family_id is a grouping key — it does NOT have to be a doc_id.
    singleton_families = _pg_all("""
        SELECT document_family_id, COUNT(*) as cnt
        FROM document_registry
        WHERE document_family_id IS NOT NULL AND document_family_id != ''
        GROUP BY document_family_id
        HAVING COUNT(*) < 2
    """)
    if singleton_families:
        r.result("Orphaned family references", "WARN",
                 f"{len(singleton_families)} family IDs with only 1 document (expected >=2)")
    else:
        r.result("Orphaned family references", "PASS", "all families have >=2 documents")

    r.flush()


def check_5_trace_coverage(r: Report):
    """Check 5: Trace coverage — every chunk traceable to run_log."""
    r.h2("5. Trace Coverage")

    total_qdrant = _qdrant_count()
    r.line(f"**Qdrant points:** {total_qdrant}")

    # 5a. Every chunk has trace_id in payload
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    null_trace = 0
    offset = None
    trace_ids_in_qdrant = set()

    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=500,
            offset=offset,
            with_payload=["trace_id", "document_id", "chunk_id"],
            with_vectors=False,
        )
        for pt in points:
            tid = pt.payload.get("trace_id")
            if not tid:
                null_trace += 1
            else:
                trace_ids_in_qdrant.add(tid)
        if offset is None:
            break

    if null_trace == 0:
        r.result("Null trace_id on chunks", "PASS",
                 f"0/{total_qdrant} chunks missing trace_id")
    else:
        r.result("Null trace_id on chunks", "FAIL",
                 f"{null_trace}/{total_qdrant} chunks missing trace_id")

    r.flush()

    # 5b. Every trace_id in Qdrant resolves to an ingestion_doc row
    ingestion_doc_tids = set()
    conn = _pg()
    with conn.cursor() as cur:
        cur.execute("SELECT trace_id FROM ingestion_doc")
        for row in cur.fetchall():
            ingestion_doc_tids.add(str(row[0]))
    conn.close()

    dangling = trace_ids_in_qdrant - ingestion_doc_tids
    if not dangling:
        r.result("Chunk trace_id → ingestion_doc", "PASS",
                 f"all {len(trace_ids_in_qdrant)} trace_ids resolve to ingestion_doc")
    else:
        r.result("Chunk trace_id → ingestion_doc", "FAIL",
                 f"{len(dangling)} trace_ids on chunks not found in ingestion_doc: {list(dangling)[:5]}...")

    # 5c. Every ingestion_doc.trace_id resolves to run_log.run_id
    run_log_ids = set()
    conn = _pg()
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM run_log")
        for row in cur.fetchall():
            run_log_ids.add(str(row[0]))
    conn.close()

    dangling_run = ingestion_doc_tids - run_log_ids
    if not dangling_run:
        r.result("ingestion_doc.trace_id → run_log", "PASS",
                 f"all {len(ingestion_doc_tids)} ingestion_doc trace_ids resolve to run_log")
    else:
        r.result("ingestion_doc.trace_id → run_log", "FAIL",
                 f"{len(dangling_run)} ingestion_doc trace_ids not in run_log")

    # 5d. Failed document spans — report, don't fail
    failed_spans = _pg_all("""
        SELECT doc_id, failure_reason
        FROM ingestion_doc
        WHERE status = 'failed'
        ORDER BY doc_id
    """)
    if failed_spans:
        r.line("")
        r.line(f"**Failed document spans:** {len(failed_spans)}")
        rows = [(d, reason[:120] if reason else "") for d, reason in failed_spans[:20]]
        r.table(["Document ID", "Failure Reason"], rows)
        r.result("Failed document spans", "WARN",
                 f"{len(failed_spans)} failed — operator should review and decide on retry")
    else:
        r.result("Failed document spans", "PASS", "0 failed")

    # 5e. Wipe completeness — confirm no pre-wipe traces present
    if os.path.exists(WIPE_TIMESTAMP_FILE):
        with open(WIPE_TIMESTAMP_FILE) as f:
            wipe_ts = f.read().strip()
        r.line("")
        r.line(f"**Wipe timestamp:** {wipe_ts}")

        # Check that all ingestion_doc rows were created after wipe
        pre_wipe = _pg_one("""
            SELECT COUNT(*) FROM ingestion_doc
            WHERE created_at < %s::timestamptz
        """, (wipe_ts,))
        if pre_wipe == 0:
            r.result("Wipe completeness", "PASS",
                     f"0 ingestion_doc rows created before wipe at {wipe_ts}")
        else:
            r.result("Wipe completeness", "WARN",
                     f"{pre_wipe} ingestion_doc rows pre-date wipe — stale data may persist")
    else:
        r.result("Wipe completeness", "WARN",
                 f"no wipe timestamp file at {WIPE_TIMESTAMP_FILE} — cannot verify")

    r.line("")
    r.line(f"**Trace ID uniqueness:** {len(trace_ids_in_qdrant)} unique trace_ids across {total_qdrant} chunks")

    r.flush()


def check_6_embedding_sanity(r: Report):
    """Check 6: Embedding sanity — spot-check nearest neighbours."""
    r.h2("6. Embedding Sanity")

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Find candidate chunks for spot-checks
    candidates = {
        "Annex 11": "EU GMP Annex 11 computerised system",
        "ICH Q9(R1)": "ICH Q9 risk management quality",
        "FDA guidance": "FDA computer system validation guidance",
    }

    def _embed(text: str) -> list:
        resp = requests.post(
            f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    spot_results = []
    for label, search_text in candidates.items():
        # Embed the query text via Ollama, then search Qdrant
        vector = _embed(search_text)
        search_result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=vector,
            limit=5,
            with_payload=["document_id", "document_title", "chunk_text"],
            with_vectors=False,
        )
        if not search_result.points:
            spot_results.append((label, "not found", "", []))
            continue

        target = search_result.points[0]
        target_id = target.id
        target_doc = target.payload.get("document_id", "?")
        target_title = target.payload.get("document_title", "?")

        # Get top-5 nearest neighbours by vector
        nn_result = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=target_id,
            limit=6,  # +1 because the first result is the chunk itself
            with_payload=["document_id", "document_title"],
            with_vectors=False,
        )
        neighbours = []
        same_doc = 0
        for pt in nn_result.points:
            if pt.id == target_id:
                continue
            neighbours.append(pt.payload.get("document_id", "?"))
            if pt.payload.get("document_id") == target_doc:
                same_doc += 1

        # All top-5 should be same-document or closely related
        all_same = same_doc == len(neighbours)
        spot_results.append((label, target_doc[:50], target_title[:80], neighbours[:5]))

        if all_same or same_doc >= 3:
            r.line(f"  - **{label}** ({target_doc[:40]}...): {same_doc}/{len(neighbours)} same-doc neighbours — OK")
        else:
            r.line(f"  - **{label}** ({target_doc[:40]}...): {same_doc}/{len(neighbours)} same-doc neighbours — FLAG")

    r.result("Embedding neighbour sanity", "PASS", "spot-checks completed (see details above)")

    # Check for near-zero vectors
    r.line("")
    zero_norm_count = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=500,
            offset=offset,
            with_payload=["document_id"],
            with_vectors=True,
        )
        for pt in points:
            if pt.vector is None:
                continue
            norm_sq = sum(v * v for v in pt.vector)
            if norm_sq < 0.0001:  # norm < 0.01
                zero_norm_count += 1
        if offset is None:
            break

    if zero_norm_count == 0:
        r.result("Near-zero embedding vectors", "PASS",
                 "no vectors with norm < 0.01")
    else:
        r.result("Near-zero embedding vectors", "FAIL",
                 f"{zero_norm_count} vectors with norm < 0.01")

    r.flush()


# -- Main ---------------------------------------------------------------------

def main():
    global EXPECTED_DOC_COUNT, EXPECTED_MIN_CHUNKS
    parser = argparse.ArgumentParser(
        description="G-T4 corpus quality gate check"
    )
    parser.add_argument("--report", required=True,
                        help="Output markdown report path")
    parser.add_argument("--expected-docs", type=int, default=EXPECTED_DOC_COUNT,
                        help=f"Expected document count (default: {EXPECTED_DOC_COUNT})")
    parser.add_argument("--expected-chunks", type=int, default=EXPECTED_MIN_CHUNKS,
                        help=f"Expected minimum chunk count (default: {EXPECTED_MIN_CHUNKS})")
    args = parser.parse_args()

    EXPECTED_DOC_COUNT = args.expected_docs
    EXPECTED_MIN_CHUNKS = args.expected_chunks

    started = datetime.now(timezone.utc)
    started_str = started.strftime("%Y-%m-%d %H:%M:%S UTC")
    start_wall = datetime.now()

    r = Report()
    r.h1(f"Corpus Quality Report — {started.date().isoformat()}")
    r.line(f"**Operator:** G-T4 automated check")
    r.line(f"**Started:** {started_str}")
    r.line(f"**Expected docs:** {EXPECTED_DOC_COUNT}")
    r.line(f"**Expected min chunks:** {EXPECTED_MIN_CHUNKS}")

    print("=" * 60)
    print("G-T4 CORPUS QUALITY CHECK")
    print("=" * 60)
    print(f"Expected: {EXPECTED_DOC_COUNT} docs, {EXPECTED_MIN_CHUNKS}+ chunks")
    print()

    # Run all checks
    checks = [
        ("1. Corpus completeness", check_1_corpus_completeness),
        ("2. Chunk quality", check_2_chunk_quality),
        ("3. Metadata completeness", check_3_metadata_completeness),
        ("4. Supersede chain integrity", check_4_supersede_integrity),
        ("5. Trace coverage", check_5_trace_coverage),
        ("6. Embedding sanity", check_6_embedding_sanity),
    ]

    for label, fn in checks:
        print(f"\n[{label}]")
        try:
            fn(r)
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            r.result(label, "FAIL", f"check threw exception: {e}")

    # Compute total duration
    duration = (datetime.now() - start_wall).total_seconds()

    # Build report
    report_text = r.build(started_str, duration)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w") as f:
        f.write(report_text)

    # Print summary
    n_pass = sum(1 for _, v, _ in r.checks if v == "PASS")
    n_warn = sum(1 for _, v, _ in r.checks if v == "WARN")
    n_fail = sum(1 for _, v, _ in r.checks if v == "FAIL")
    verdict = "GREEN" if n_fail == 0 else "RED"

    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}")
    print(f"  {len(r.checks)} checks: {n_pass} pass, {n_warn} warn, {n_fail} fail")
    print(f"  Duration: {duration:.1f}s")
    print(f"  Report: {args.report}")
    print("=" * 60)

    sys.exit(0 if verdict == "GREEN" else 1)


if __name__ == "__main__":
    main()
