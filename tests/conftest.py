"""
ownedpulse test configuration and shared fixtures.
Field names reflect ACTUAL Qdrant payload as documented in
docs/schema/qdrant-fields.md. All old field names (agency, title,
local_file_path, etc.) have been corrected.
"""

import pytest
import httpx
import psycopg2
import os

API_BASE = os.getenv("OWNEDPULSE_API_URL", "http://localhost:8001")
PG_DSN = os.getenv(
    "OWNEDPULSE_PG_DSN",
    "host=localhost port=5432 dbname=knowledge_base user=postgres password="
    + os.getenv("POSTGRES_PASSWORD", "")
)

# ── Required response fields (corrected from debrief) ────────────────────────

QUERY_RESPONSE_REQUIRED_FIELDS = {
    "query_id", "timestamp", "routing_path", "answer", "citations",
    "sub_queries", "retrieval_params_applied", "langfuse_trace_id"
}

RETRIEVAL_PARAMS_REQUIRED_FIELDS = {
    "query_depth", "top_k", "score_threshold", "sub_query_count"
}

# Corrected field names from debrief:
# title → document_title
# agency → issuing_body
# local_file_path → source_local_path
# chunk_idx → chunk_index
# page_number → page_no
CITATION_REQUIRED_FIELDS = {
    "index", "chunk_id", "document_id", "chunk_text",
    "document_title",       # NOT title
    "issuing_body",         # NOT agency
    "document_version",
    "clause_id",
    "publication_date",
    "page_no",              # NOT page_number
    "chunk_index",          # NOT chunk_idx
    "char_offset_start",
    "char_offset_end",
    "chunked_at",
    "score",
    "cited_by_llm",         # NEW — true if LLM cited this chunk
    "superseded",
    "superseded_by",
    "source_local_path",    # NOT local_file_path
    "source_url"
}

EXPORT_REQUIRED_FIELDS = {
    "query_id", "timestamp", "query_text", "routing_path",
    "answer", "filters_applied", "citations", "sub_queries",
    "retrieval_params_applied", "langfuse_trace_id"
}

HISTORY_REQUIRED_FIELDS = {
    "query_id", "query_text", "timestamp", "routing_path",
    "citation_count", "filters_applied", "agency_filter"
}

CORPUS_STATS_REQUIRED_FIELDS = {
    "total_documents", "per_agency", "per_document_type", "last_pipeline_run"
}

CORPUS_DOCUMENT_REQUIRED_FIELDS = {
    "document_id", "document_title", "issuing_body", "document_type",
    "document_version", "publication_date", "is_superseded", "superseded_by",
    "archive_path"
}

HEALTH_REQUIRED_FIELDS = {
    "status", "qdrant", "postgres", "ollama", "langfuse"
}

# ── Verification queries ──────────────────────────────────────────────────────

CONTENT_QUERIES = [
    "What are the Annex 11 requirements for audit trails?",
    "Summarise ICH Q9(R1) changes from the 2005 version.",
    "What FDA guidance applies to computerised system validation?",
]

METADATA_QUERIES = [
    "How many EMA guidelines were published in the last 90 days?",
    "What is the current ICH Q9 version?",
    "List all FDA press releases related to data integrity.",
]

# Extended regulatory query set for comprehensive testing
REGULATORY_CONTENT_QUERIES = [
    # GMP / CSV
    "What are the GAMP 5 category definitions for computerised systems?",
    "What does EU GMP Annex 11 require for electronic signatures?",
    "What are the data integrity requirements in FDA 21 CFR Part 11?",
    "What validation documentation is required for GAMP 5 Category 4 systems?",
    "What are the audit trail requirements under EU GMP Annex 11 section 9?",
    # Risk management
    "What is the ICH Q9 definition of quality risk management?",
    "How should risk assessment be documented according to ICH Q9(R1)?",
    # Pharmacovigilance
    "What are the EMA requirements for pharmacovigilance system master files?",
    # FDA guidance
    "What does FDA guidance say about data integrity in pharmaceutical manufacturing?",
    "What are the FDA requirements for electronic records under 21 CFR Part 11?",
    # Cross-regime
    "What are the differences between EU GMP and FDA requirements for audit trails?",
]

ALL_VERIFICATION_QUERIES = CONTENT_QUERIES + METADATA_QUERIES

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def api_client():
    with httpx.Client(base_url=API_BASE, timeout=90.0) as client:
        yield client


@pytest.fixture(scope="session")
def pg_conn():
    conn = psycopg2.connect(PG_DSN)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def submitted_query(api_client):
    """Submit one CONTENT query with default retrieval params. Cached for session."""
    response = api_client.post("/api/query", json={
        "query": CONTENT_QUERIES[0],
        "filters": {},
        "retrieval_params": {
            "query_depth": "standard",
            "top_k": 10,
            "score_threshold": 0.60
        }
    })
    assert response.status_code == 200, f"Query submission failed: {response.text}"
    return response.json()


@pytest.fixture(scope="session")
def submitted_metadata_query(api_client):
    """Submit one METADATA query. Cached for session."""
    response = api_client.post("/api/query", json={
        "query": METADATA_QUERIES[0],
        "filters": {},
        "retrieval_params": {
            "query_depth": "standard",
            "top_k": 10,
            "score_threshold": 0.60
        }
    })
    assert response.status_code == 200, f"Metadata query failed: {response.text}"
    return response.json()


@pytest.fixture(scope="session")
def submitted_filtered_query(api_client):
    """Submit a query with EMA agency filter. Cached for session."""
    response = api_client.post("/api/query", json={
        "query": CONTENT_QUERIES[0],
        "filters": {"agency": "EMA"},
        "retrieval_params": {
            "query_depth": "standard",
            "top_k": 10,
            "score_threshold": 0.60
        }
    })
    assert response.status_code == 200, f"Filtered query failed: {response.text}"
    return response.json()
