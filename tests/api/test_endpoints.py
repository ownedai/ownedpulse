"""
ownedpulse API endpoint tests.
Tests every endpoint for correct HTTP status, response shape, and field
presence. Uses the field names documented in docs/schema/qdrant-fields.md.

Changes from previous version:
- All field names corrected (document_title, issuing_body, source_local_path,
  chunk_index, page_no, chunked_at, chunk_status)
- New response fields: sub_queries, retrieval_params_applied, langfuse_trace_id,
  cited_by_llm
- retrieval_params now sent in every query request
- Filter uses document_type (hyphenated) not doc_type (underscored)
- New endpoints: /api/corpus/documents, /api/trace/{id}, export format param
- /api/health checks langfuse component
- Score threshold filtering tested
- EU-Commission normalisation tested
"""

import pytest
from conftest import (
    QUERY_RESPONSE_REQUIRED_FIELDS,
    CITATION_REQUIRED_FIELDS,
    RETRIEVAL_PARAMS_REQUIRED_FIELDS,
    EXPORT_REQUIRED_FIELDS,
    HISTORY_REQUIRED_FIELDS,
    CORPUS_STATS_REQUIRED_FIELDS,
    CORPUS_DOCUMENT_REQUIRED_FIELDS,
    HEALTH_REQUIRED_FIELDS,
    CONTENT_QUERIES,
    METADATA_QUERIES,
)

DEFAULT_RETRIEVAL_PARAMS = {
    "query_depth": "standard",
    "top_k": 10,
    "score_threshold": 0.60
}


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:

    def test_health_returns_200(self, api_client):
        r = api_client.get("/api/health")
        assert r.status_code == 200

    def test_health_has_required_fields(self, api_client):
        r = api_client.get("/api/health")
        data = r.json()
        missing = HEALTH_REQUIRED_FIELDS - set(data.keys())
        assert not missing, f"Health missing fields: {missing}"

    def test_health_qdrant_ok(self, api_client):
        r = api_client.get("/api/health")
        assert r.json().get("qdrant") == "ok", f"Qdrant unhealthy: {r.json()}"

    def test_health_postgres_ok(self, api_client):
        r = api_client.get("/api/health")
        assert r.json().get("postgres") == "ok", f"PostgreSQL unhealthy: {r.json()}"

    def test_health_ollama_ok(self, api_client):
        r = api_client.get("/api/health")
        assert r.json().get("ollama") == "ok", f"Ollama unhealthy: {r.json()}"

    def test_health_langfuse_ok(self, api_client):
        r = api_client.get("/api/health")
        langfuse_status = r.json().get("langfuse", "")
        assert langfuse_status == "ok" or langfuse_status.startswith("disabled"), \
            f"Langfuse unhealthy: {r.json()}"

    def test_health_overall_status_ok(self, api_client):
        r = api_client.get("/api/health")
        assert r.json().get("status") == "ok"


# ── Query endpoint — response shape ──────────────────────────────────────────

class TestQueryResponseShape:

    def test_query_returns_200(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 200

    def test_query_has_required_top_level_fields(self, submitted_query):
        missing = QUERY_RESPONSE_REQUIRED_FIELDS - set(submitted_query.keys())
        assert not missing, f"Missing top-level fields: {missing}"

    def test_query_id_is_non_empty(self, submitted_query):
        assert submitted_query["query_id"], "query_id is empty"

    def test_timestamp_is_non_empty(self, submitted_query):
        assert submitted_query["timestamp"], "timestamp is empty"

    def test_routing_path_is_valid(self, submitted_query):
        assert submitted_query["routing_path"] in ("CONTENT", "METADATA"), \
            f"Invalid routing_path: {submitted_query['routing_path']}"

    def test_answer_is_non_empty(self, submitted_query):
        assert submitted_query["answer"], "answer is empty"

    def test_answer_is_plain_text_not_html(self, submitted_query):
        answer = submitted_query["answer"]
        assert "<p>" not in answer and "<strong>" not in answer and "<cite>" not in answer, \
            "Answer contains HTML — must be plain text with [N] markers only"

    def test_citations_is_list(self, submitted_query):
        assert isinstance(submitted_query["citations"], list)

    def test_citations_not_empty(self, submitted_query):
        assert len(submitted_query["citations"]) > 0, "citations list is empty"

    def test_sub_queries_is_list(self, submitted_query):
        assert isinstance(submitted_query["sub_queries"], list), \
            "sub_queries must be a list"

    def test_sub_queries_not_empty_for_content(self, submitted_query):
        assert len(submitted_query["sub_queries"]) > 0, \
            "sub_queries empty for CONTENT path — query expansion not working"

    def test_retrieval_params_applied_has_required_fields(self, submitted_query):
        params = submitted_query.get("retrieval_params_applied", {})
        missing = RETRIEVAL_PARAMS_REQUIRED_FIELDS - set(params.keys())
        assert not missing, f"retrieval_params_applied missing fields: {missing}"

    def test_langfuse_trace_id_present(self, submitted_query):
        assert "langfuse_trace_id" in submitted_query, "langfuse_trace_id missing"

    def test_retrieval_params_applied_reflects_request(self, submitted_query):
        params = submitted_query["retrieval_params_applied"]
        assert params["query_depth"] == "standard"
        assert params["top_k"] == 10
        assert params["score_threshold"] == 0.60


# ── Citation field correctness ────────────────────────────────────────────────

class TestCitationFields:

    def test_citations_have_required_fields(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"]):
            missing = CITATION_REQUIRED_FIELDS - set(citation.keys())
            assert not missing, f"Citation {i} missing fields: {missing}"

    def test_citation_uses_document_title_not_title(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert "document_title" in citation, \
                "Citation uses 'title' — must use 'document_title'"
            assert "title" not in citation, \
                "Citation has old 'title' field — must be 'document_title'"

    def test_citation_uses_issuing_body_not_agency(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert "issuing_body" in citation, \
                "Citation uses 'agency' — must use 'issuing_body'"
            assert "agency" not in citation, \
                "Citation has old 'agency' field — must be 'issuing_body'"

    def test_citation_uses_source_local_path_not_local_file_path(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert "source_local_path" in citation, \
                "Citation must have 'source_local_path'"
            assert "local_file_path" not in citation, \
                "Citation has old 'local_file_path' — must be 'source_local_path'"

    def test_citation_uses_chunk_index_not_chunk_idx(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert "chunk_index" in citation, \
                "Citation must have 'chunk_index'"
            assert "chunk_idx" not in citation, \
                "Citation has old 'chunk_idx' — must be 'chunk_index'"

    def test_citation_uses_page_no_not_page_number(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert "page_no" in citation, "Citation must have 'page_no'"
            assert "page_number" not in citation, \
                "Citation has old 'page_number' — must be 'page_no'"

    def test_citation_has_char_offsets(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"]):
            assert "char_offset_start" in citation, \
                f"Citation {i} missing char_offset_start"
            assert "char_offset_end" in citation, \
                f"Citation {i} missing char_offset_end"

    def test_citation_has_chunked_at(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"]):
            assert "chunked_at" in citation, \
                f"Citation {i} missing chunked_at (ingestion timestamp)"

    def test_citation_has_cited_by_llm(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"]):
            assert "cited_by_llm" in citation, \
                f"Citation {i} missing cited_by_llm"
            assert isinstance(citation["cited_by_llm"], bool), \
                f"cited_by_llm must be bool, got {type(citation['cited_by_llm'])}"

    def test_citation_index_sequential(self, submitted_query):
        for i, citation in enumerate(submitted_query["citations"], start=1):
            assert citation["index"] == i, \
                f"Citation index mismatch: expected {i}, got {citation['index']}"

    def test_citation_score_is_float_in_range(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert isinstance(citation["score"], float), \
                f"score is not float: {citation['score']}"
            assert 0.0 <= citation["score"] <= 1.0, \
                f"score out of range: {citation['score']}"

    def test_citation_superseded_is_bool(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert isinstance(citation["superseded"], bool)

    def test_citation_issuing_body_valid(self, submitted_query):
        valid = {"FDA", "EMA", "ICH"}
        for citation in submitted_query["citations"]:
            assert citation["issuing_body"] in valid, \
                f"Invalid issuing_body: {citation['issuing_body']} — " \
                f"EU-Commission must be normalised to EMA"

    def test_no_eu_commission_in_citations(self, submitted_query):
        for citation in submitted_query["citations"]:
            assert citation["issuing_body"] != "EU-Commission", \
                "EU-Commission not normalised to EMA in citation"

    def test_document_title_has_no_agency_suffix(self, submitted_query):
        for citation in submitted_query["citations"]:
            title = citation.get("document_title", "")
            for suffix in ["| European Medicines Agency", "| EMA", "| FDA", "| ICH"]:
                assert suffix not in title, \
                    f"Title still contains webpage suffix '{suffix}': {title}"


# ── Score threshold enforcement ───────────────────────────────────────────────

class TestScoreThreshold:

    def test_all_citations_above_score_threshold(self, submitted_query):
        threshold = submitted_query["retrieval_params_applied"]["score_threshold"]
        for citation in submitted_query["citations"]:
            assert citation["score"] >= threshold, \
                f"Citation score {citation['score']} below threshold {threshold} — " \
                f"should have been filtered out"

    def test_high_threshold_returns_fewer_results(self, api_client):
        r_low = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "standard", "top_k": 10, "score_threshold": 0.40}
        })
        r_high = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "standard", "top_k": 10, "score_threshold": 0.85}
        })
        assert r_low.status_code == 200
        assert r_high.status_code == 200
        count_low = len(r_low.json()["citations"])
        count_high = len(r_high.json()["citations"])
        assert count_low >= count_high, \
            f"Higher threshold returned more results: low={count_low}, high={count_high}"

    def test_impossible_threshold_returns_empty_with_message(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "standard", "top_k": 10, "score_threshold": 0.90}
        })
        assert r.status_code == 200
        data = r.json()
        if len(data["citations"]) == 0:
            assert data["answer"], "Empty citations must return an explanatory message, not empty answer"
            assert "threshold" in data["answer"].lower() or "no sources" in data["answer"].lower(), \
                f"Empty citations message does not mention threshold: {data['answer']}"


# ── Query expansion (sub-queries) ─────────────────────────────────────────────

class TestQueryExpansion:

    def test_standard_depth_generates_3_sub_queries(self, submitted_query):
        assert submitted_query["retrieval_params_applied"]["sub_query_count"] == 3, \
            f"Standard depth should generate 3 sub-queries, got " \
            f"{submitted_query['retrieval_params_applied']['sub_query_count']}"

    def test_low_depth_generates_2_sub_queries(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "low", "top_k": 10, "score_threshold": 0.60}
        })
        data = r.json()
        assert data["retrieval_params_applied"]["sub_query_count"] == 2, \
            f"Low depth should generate 2 sub-queries"

    def test_deep_depth_generates_5_sub_queries(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "deep", "top_k": 10, "score_threshold": 0.60}
        })
        data = r.json()
        assert data["retrieval_params_applied"]["sub_query_count"] == 5, \
            f"Deep depth should generate 5 sub-queries"

    def test_sub_queries_are_strings(self, submitted_query):
        for i, sq in enumerate(submitted_query["sub_queries"]):
            assert isinstance(sq, str), f"sub_query {i} is not a string"
            assert len(sq) > 10, f"sub_query {i} is too short to be meaningful: {sq}"

    def test_sub_queries_differ_from_original(self, submitted_query):
        original = CONTENT_QUERIES[0].lower().strip()
        for sq in submitted_query["sub_queries"]:
            assert sq.lower().strip() != original, \
                f"Sub-query is identical to original — expansion not working: {sq}"


# ── Filter tests ──────────────────────────────────────────────────────────────

class TestFilters:

    def test_agency_filter_ema_returns_only_ema(self, submitted_filtered_query):
        for citation in submitted_filtered_query["citations"]:
            assert citation["issuing_body"] == "EMA", \
                f"EMA filter leaked: got issuing_body={citation['issuing_body']}"

    def test_agency_filter_fda(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {"agency": "FDA"},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 200
        for citation in r.json()["citations"]:
            assert citation["issuing_body"] == "FDA", \
                f"FDA filter leaked: {citation['issuing_body']}"

    def test_agency_filter_ich(self, api_client):
        r = api_client.post("/api/query", json={
            "query": "ICH quality risk management guidelines",
            "filters": {"agency": "ICH"},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 200
        for citation in r.json()["citations"]:
            assert citation["issuing_body"] == "ICH", \
                f"ICH filter leaked: {citation['issuing_body']}"

    def test_document_type_filter_uses_hyphenated_value(self, api_client):
        """Filter must use document_type (hyphenated) field, not doc_type (underscored)."""
        r = api_client.post("/api/query", json={
            "query": "regulatory guidance on data integrity",
            "filters": {"document_type": "guidance"},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 200, f"document_type filter failed: {r.text}"

    def test_press_release_filter_hyphenated(self, api_client):
        """press-release (hyphenated) must work — this was broken in v1."""
        r = api_client.post("/api/query", json={
            "query": "FDA press releases",
            "filters": {"document_type": "press-release"},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 200, f"press-release filter failed: {r.text}"

    def test_empty_query_returns_422(self, api_client):
        r = api_client.post("/api/query", json={
            "query": "",
            "filters": {},
            "retrieval_params": DEFAULT_RETRIEVAL_PARAMS
        })
        assert r.status_code == 422

    def test_missing_query_field_returns_422(self, api_client):
        r = api_client.post("/api/query", json={"filters": {}})
        assert r.status_code == 422

    def test_invalid_query_depth_returns_422(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0],
            "filters": {},
            "retrieval_params": {"query_depth": "extreme", "top_k": 10, "score_threshold": 0.60}
        })
        assert r.status_code == 422


# ── Query history ─────────────────────────────────────────────────────────────

class TestQueryHistory:

    def test_history_returns_200(self, api_client):
        r = api_client.get("/api/query/history")
        assert r.status_code == 200

    def test_history_returns_list(self, api_client):
        r = api_client.get("/api/query/history")
        assert isinstance(r.json(), list)

    def test_history_items_have_required_fields(self, api_client, submitted_query):
        r = api_client.get("/api/query/history")
        items = r.json()
        assert len(items) > 0, "History empty after submitting a query"
        for item in items:
            missing = HISTORY_REQUIRED_FIELDS - set(item.keys())
            assert not missing, f"History item missing fields: {missing}"

    def test_submitted_query_in_history(self, api_client, submitted_query):
        r = api_client.get("/api/query/history?limit=50")
        ids = [item["query_id"] for item in r.json()]
        assert submitted_query["query_id"] in ids, \
            "Submitted query not found in history"

    def test_history_default_limit_10(self, api_client):
        r = api_client.get("/api/query/history")
        assert len(r.json()) <= 10, "Default history limit should be 10"

    def test_history_pagination(self, api_client):
        r = api_client.get("/api/query/history?limit=5&offset=0")
        assert r.status_code == 200
        assert len(r.json()) <= 5


# ── Export endpoint ───────────────────────────────────────────────────────────

class TestExportEndpoint:

    def test_json_export_returns_200(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        assert r.status_code == 200

    def test_pdf_export_returns_200(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=pdf")
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", ""), \
            "PDF export must return application/pdf content-type"

    def test_json_export_has_required_fields(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        missing = EXPORT_REQUIRED_FIELDS - set(data.keys())
        assert not missing, f"Export missing fields: {missing}"

    def test_json_export_answer_is_plain_text(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        answer = r.json().get("answer", "")
        assert "<p>" not in answer, "Export answer must be plain text, not HTML"

    def test_json_export_contains_sub_queries(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert "sub_queries" in data and len(data["sub_queries"]) > 0, \
            "Export missing sub_queries"

    def test_json_export_contains_retrieval_params(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert "retrieval_params_applied" in data, \
            "Export missing retrieval_params_applied"

    def test_json_export_has_uncited_chunks_section(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        assert "uncited_chunks" in data, \
            "Export missing uncited_chunks section"

    def test_json_export_citations_have_full_provenance(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        data = r.json()
        for i, citation in enumerate(data["citations"]):
            missing = CITATION_REQUIRED_FIELDS - set(citation.keys())
            assert not missing, \
                f"Export citation {i} missing provenance fields: {missing}"

    def test_json_export_filename_header(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export?format=json")
        cd = r.headers.get("content-disposition", "")
        assert f"ownedpulse-export-{qid}" in cd, \
            f"Export filename wrong: {cd}"

    def test_export_unknown_id_returns_404(self, api_client):
        r = api_client.get(
            "/api/query/00000000-0000-0000-0000-000000000000/export?format=json"
        )
        assert r.status_code == 404

    def test_export_default_format_is_json(self, api_client, submitted_query):
        qid = submitted_query["query_id"]
        r = api_client.get(f"/api/query/{qid}/export")
        assert r.status_code == 200


# ── Corpus stats ──────────────────────────────────────────────────────────────

class TestCorpusStats:

    def test_stats_returns_200(self, api_client):
        r = api_client.get("/api/corpus/stats")
        assert r.status_code == 200

    def test_stats_has_required_fields(self, api_client):
        r = api_client.get("/api/corpus/stats")
        missing = CORPUS_STATS_REQUIRED_FIELDS - set(r.json().keys())
        assert not missing, f"Stats missing fields: {missing}"

    def test_stats_total_documents_gt_zero(self, api_client):
        r = api_client.get("/api/corpus/stats")
        assert r.json()["total_documents"] > 0

    def test_stats_has_all_agencies(self, api_client):
        r = api_client.get("/api/corpus/stats")
        per_agency = r.json()["per_agency"]
        for agency in ("FDA", "EMA", "ICH"):
            assert agency in per_agency, f"Missing agency in stats: {agency}"

    def test_stats_no_eu_commission_key(self, api_client):
        r = api_client.get("/api/corpus/stats")
        per_agency = r.json()["per_agency"]
        assert "EU-Commission" not in per_agency, \
            "EU-Commission not normalised to EMA in corpus stats"

    def test_stats_agency_counts_positive(self, api_client):
        r = api_client.get("/api/corpus/stats")
        for agency, count in r.json()["per_agency"].items():
            assert count > 0, f"Agency {agency} has zero documents"


# ── Corpus documents ──────────────────────────────────────────────────────────

class TestCorpusDocuments:

    def test_corpus_documents_returns_200(self, api_client):
        r = api_client.get("/api/corpus/documents")
        assert r.status_code == 200

    def test_corpus_documents_has_total_and_list(self, api_client):
        r = api_client.get("/api/corpus/documents")
        data = r.json()
        assert "total" in data, "Missing 'total' in corpus documents response"
        assert "documents" in data, "Missing 'documents' in corpus documents response"
        assert isinstance(data["documents"], list)

    def test_corpus_documents_items_have_required_fields(self, api_client):
        r = api_client.get("/api/corpus/documents?limit=5")
        data = r.json()
        for i, doc in enumerate(data["documents"]):
            missing = CORPUS_DOCUMENT_REQUIRED_FIELDS - set(doc.keys())
            assert not missing, f"Document {i} missing fields: {missing}"

    def test_corpus_documents_filter_by_agency(self, api_client):
        r = api_client.get("/api/corpus/documents?agency=FDA")
        assert r.status_code == 200
        for doc in r.json()["documents"]:
            assert doc["issuing_body"] == "FDA", \
                f"Agency filter leaked: {doc['issuing_body']}"

    def test_corpus_documents_no_eu_commission(self, api_client):
        r = api_client.get("/api/corpus/documents")
        for doc in r.json()["documents"]:
            assert doc["issuing_body"] != "EU-Commission", \
                "EU-Commission not normalised in corpus documents"

    def test_corpus_documents_pagination(self, api_client):
        r = api_client.get("/api/corpus/documents?limit=10&offset=0")
        assert r.status_code == 200
        assert len(r.json()["documents"]) <= 10


# ── PDF page endpoint ─────────────────────────────────────────────────────────

class TestPdfEndpoint:

    def test_pdf_invalid_path_returns_404(self, api_client):
        r = api_client.get("/api/pdf/page", params={
            "file_path": "/nonexistent/file.pdf",
            "page_no": 0
        })
        assert r.status_code == 404

    def test_pdf_missing_params_returns_422(self, api_client):
        r = api_client.get("/api/pdf/page")
        assert r.status_code == 422

    def test_pdf_uses_page_no_not_page_number(self, api_client):
        """Parameter must be page_no (not page_number) — corrected from debrief."""
        r = api_client.get("/api/pdf/page", params={
            "file_path": "/nonexistent/file.pdf",
            "page_number": 0
        })
        assert r.status_code == 422, \
            "Endpoint should reject 'page_number' param — must use 'page_no'"


# ── Langfuse trace proxy ──────────────────────────────────────────────────────

class TestLangfuseTrace:

    def test_trace_endpoint_exists(self, api_client, submitted_query):
        trace_id = submitted_query.get("langfuse_trace_id")
        if not trace_id:
            pytest.skip("No langfuse_trace_id in query response")
        r = api_client.get(f"/api/trace/{trace_id}")
        assert r.status_code in (200, 404), \
            f"Unexpected status from trace endpoint: {r.status_code}"

    def test_trace_unknown_id_returns_404(self, api_client):
        r = api_client.get("/api/trace/nonexistent-trace-id-00000")
        assert r.status_code == 404

    def test_trace_response_has_structure(self, api_client, submitted_query):
        trace_id = submitted_query.get("langfuse_trace_id")
        if not trace_id:
            pytest.skip("No langfuse_trace_id in query response")
        r = api_client.get(f"/api/trace/{trace_id}")
        if r.status_code == 200:
            data = r.json()
            assert "trace_id" in data or "id" in data, \
                "Trace response missing trace_id field"
