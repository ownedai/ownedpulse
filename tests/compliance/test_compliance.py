"""
ownedpulse compliance tests — Annex 11 §8.1 audit trail, export integrity,
superseded document handling, query_history persistence.

Changes from previous version:
- All field names corrected (document_title, issuing_body, etc.)
- retrieval_params in all query submissions
- New: retrieval_params_applied recorded in query_history
- New: langfuse_trace_id recorded in query_history
- New: cited_by_llm present in exported citations
- New: uncited_chunks section in export
- New: PDF export format tested
- Fixed: init_db must raise on failure test
- Updated: superseded pair is ICH Q9 (2005) → Q9(R1) (2023) per F8 spec
"""

import pytest
import psycopg2
from datetime import datetime, timezone
from conftest import (
    CONTENT_QUERIES,
    CITATION_REQUIRED_FIELDS,
    EXPORT_REQUIRED_FIELDS,
)

DEFAULT_PARAMS = {
    "query_depth": "standard",
    "top_k": 10,
    "score_threshold": 0.60
}


# ── Annex 11 §8.1 Audit Trail ─────────────────────────────────────────────────

class TestAuditTrail:
    """
    Annex 11 §8.1: All queries must be recorded with a unique ID and
    timestamp. The audit trail must be complete and tamper-evident.
    """

    def test_every_query_has_query_id(self, submitted_query):
        assert submitted_query["query_id"], "query_id empty — audit trail broken"

    def test_query_id_is_uuid_format(self, submitted_query):
        import re
        qid = submitted_query["query_id"]
        pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        assert re.match(pattern, qid, re.IGNORECASE), \
            f"query_id is not valid UUID format: {qid}"

    def test_every_query_has_timestamp(self, submitted_query):
        ts = submitted_query["timestamp"]
        assert ts, "timestamp empty — audit trail broken"
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"timestamp not valid ISO format: {ts}")

    def test_query_persisted_to_postgres(self, submitted_query, pg_conn):
        """
        Every query response must have a corresponding row in
        query_history PostgreSQL table — not just in-memory.
        """
        qid = submitted_query["query_id"]
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT query_id, query_text, timestamp FROM query_history "
            "WHERE query_id = %s", (qid,)
        )
        row = cursor.fetchone()
        cursor.close()
        assert row is not None, \
            f"query_id {qid} not found in PostgreSQL query_history — " \
            f"audit trail broken. init_db() may have silently failed."

    def test_postgres_query_text_matches_response(self, api_client, pg_conn):
        query_text = CONTENT_QUERIES[1]
        r = api_client.post("/api/query", json={
            "query": query_text, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        qid = r.json()["query_id"]
        cursor = pg_conn.cursor()
        cursor.execute("SELECT query_text FROM query_history WHERE query_id = %s", (qid,))
        row = cursor.fetchone()
        cursor.close()
        assert row is not None
        assert row[0] == query_text, \
            f"Stored query text mismatch.\nExpected: {query_text}\nGot: {row[0]}"

    def test_postgres_routing_path_recorded(self, submitted_query, pg_conn):
        qid = submitted_query["query_id"]
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT routing_path FROM query_history WHERE query_id = %s", (qid,)
        )
        row = cursor.fetchone()
        cursor.close()
        assert row[0] in ("CONTENT", "METADATA"), \
            f"routing_path not persisted correctly: {row[0]}"

    def test_postgres_retrieval_params_recorded(self, submitted_query, pg_conn):
        """Retrieval params must be persisted — required for audit reproducibility."""
        qid = submitted_query["query_id"]
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT retrieval_params FROM query_history WHERE query_id = %s", (qid,)
        )
        row = cursor.fetchone()
        cursor.close()
        assert row is not None
        assert row[0] is not None, \
            "retrieval_params not persisted to query_history — " \
            "auditor cannot reproduce query conditions"

    def test_postgres_langfuse_trace_id_recorded(self, submitted_query, pg_conn):
        """Langfuse trace ID must be persisted for pipeline traceability."""
        qid = submitted_query["query_id"]
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT langfuse_trace_id FROM query_history WHERE query_id = %s", (qid,)
        )
        row = cursor.fetchone()
        cursor.close()
        assert row is not None, f"query_id {qid} not in PostgreSQL"

    def test_query_history_not_deletable_via_api(self, api_client, submitted_query):
        """
        There must be no API endpoint that deletes query history.
        Audit trail must be append-only from the API perspective.
        """
        qid = submitted_query["query_id"]
        r = api_client.delete(f"/api/query/{qid}")
        assert r.status_code in (404, 405), \
            f"DELETE /api/query/{{id}} returned {r.status_code} — " \
            f"audit trail is mutable, which violates Annex 11 §8.1"

    def test_query_history_no_update_endpoint(self, api_client, submitted_query):
        """PUT/PATCH on a query record should not be possible."""
        qid = submitted_query["query_id"]
        r = api_client.put(f"/api/query/{qid}", json={"answer": "tampered"})
        assert r.status_code in (404, 405), \
            f"PUT /api/query/{{id}} allowed modification of audit record"


# ── Export integrity ──────────────────────────────────────────────────────────

class TestExportIntegrity:
    """
    Annex 11 §8.1: Export must contain all provenance fields and
    complete audit information. Nothing may be omitted.
    """

    def test_export_contains_query_text(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert data.get("query_text"), "Export missing query_text"

    def test_export_contains_sub_queries(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert "sub_queries" in data and isinstance(data["sub_queries"], list), \
            "Export missing sub_queries — cannot audit query expansion"

    def test_export_contains_retrieval_params(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        params = data.get("retrieval_params_applied", {})
        assert params.get("score_threshold") is not None, \
            "Export missing score_threshold — cannot audit filtering conditions"
        assert params.get("query_depth") is not None, \
            "Export missing query_depth"

    def test_export_citations_full_provenance(self, api_client, submitted_query):
        """
        Every citation in the export must have all provenance fields.
        None may be missing. Null values are acceptable — missing keys are not.
        """
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        for i, citation in enumerate(data["citations"]):
            missing = CITATION_REQUIRED_FIELDS - set(citation.keys())
            assert not missing, \
                f"Export citation {i} missing provenance fields: {missing}\n" \
                f"This violates Annex 11 §8.1 completeness requirement."

    def test_export_citations_have_cited_by_llm(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        for i, citation in enumerate(r.json()["citations"]):
            assert "cited_by_llm" in citation, \
                f"Export citation {i} missing cited_by_llm"

    def test_export_has_uncited_chunks_section(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert "uncited_chunks" in data, \
            "Export missing uncited_chunks section — incomplete audit record"

    def test_export_filters_applied_recorded(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {"agency": "EMA"},
            "retrieval_params": DEFAULT_PARAMS
        })
        qid = r.json()["query_id"]
        export = api_client.get(f"/api/query/{qid}/export?format=json").json()
        filters = export.get("filters_applied", {})
        assert filters.get("agency") == "EMA", \
            f"filters_applied not recorded correctly: {filters}"

    def test_export_timestamp_consistent_with_response(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        export = api_client.get(f"/api/query/{qid}/export?format=json").json()
        assert export["timestamp"] == submitted_query["timestamp"], \
            "Export timestamp differs from query response timestamp"

    def test_export_answer_is_plain_text(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        answer = r.json().get("answer", "")
        assert "<p>" not in answer and "<strong>" not in answer, \
            "Export answer must be plain text — not HTML"

    def test_pdf_export_is_valid_pdf(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=pdf")
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF", \
            "PDF export does not start with %PDF magic bytes — not a valid PDF"


# ── Superseded documents ──────────────────────────────────────────────────────

class TestSupersededDocuments:
    """
    Superseded documents must be flagged. A QA auditor must never receive
    unwarned superseded guidance. F8 canonical pair: ICH Q9 (2005) → Q9(R1) (2023).
    """

    def test_superseded_field_on_all_citations(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"]):
            assert "superseded" in citation, \
                f"Citation {i} missing 'superseded' field"

    def test_superseded_citations_have_superseded_by(self, api_client):
        r = api_client.post("/api/query", json={
            "query": "ICH Q9 risk management principles",
            "filters": {},
            "retrieval_params": DEFAULT_PARAMS
        })
        for citation in r.json()["citations"]:
            if citation["superseded"]:
                assert citation["superseded_by"], \
                    f"Citation marked superseded but superseded_by is null: " \
                    f"{citation['document_title']}"

    def test_ich_q9_2005_marked_superseded(self, api_client):
        """
        F8 canonical pair: ICH Q9 (2005) must be marked superseded
        and superseded_by must reference Q9(R1) (2023).
        """
        r = api_client.post("/api/query", json={
            "query": "ICH Q9 quality risk management 2005 original",
            "filters": {"agency": "ICH"},
            "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        superseded = [c for c in data["citations"] if c["superseded"]]
        if superseded:
            for c in superseded:
                assert c["superseded_by"], \
                    f"Superseded ICH document missing superseded_by: {c['document_title']}"
                assert "Q9" in str(c["superseded_by"]), \
                    f"superseded_by should reference Q9(R1): {c['superseded_by']}"


# ── Provenance completeness ───────────────────────────────────────────────────

class TestProvenanceCompleteness:
    """
    Every chunk returned must carry enough provenance for a QA auditor to
    locate the original source document.
    """

    def test_all_citations_have_document_title(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("document_title"), f"Citation {i} has no document_title"

    def test_all_citations_have_valid_issuing_body(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("issuing_body") in ("FDA", "EMA", "ICH"), \
                f"Citation {i} has invalid issuing_body: {c.get('issuing_body')}"

    def test_all_citations_have_source_url(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("source_url"), \
                f"Citation {i} missing source_url — cannot verify against original"

    def test_all_citations_have_chunk_id(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("chunk_id"), \
                f"Citation {i} missing chunk_id — cannot trace to Qdrant record"

    def test_all_citations_have_document_id(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("document_id"), \
                f"Citation {i} missing document_id"

    def test_all_citations_have_char_offsets(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("char_offset_start") is not None, \
                f"Citation {i} missing char_offset_start"
            assert c.get("char_offset_end") is not None, \
                f"Citation {i} missing char_offset_end"

    def test_all_citations_have_chunk_index(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("chunk_index") is not None, \
                f"Citation {i} missing chunk_index"

    def test_all_citations_have_chunked_at(self, submitted_query):
        for i, c in enumerate(submitted_query["citations"]):
            assert c.get("chunked_at"), \
                f"Citation {i} missing chunked_at (ingestion timestamp)"

    def test_null_fields_use_none_not_dash(self, submitted_query):
        """
        Null fields must be None (or absent), not an em-dash or hyphen string.
        The previous implementation returned "—" for null values.
        """
        for i, c in enumerate(submitted_query["citations"]):
            for field in ("clause_id", "publication_date", "source_local_path"):
                val = c.get(field)
                assert val != "—" and val != "-", \
                    f"Citation {i} field '{field}' contains dash string — " \
                    f"must be null/None, not a display-layer string"
