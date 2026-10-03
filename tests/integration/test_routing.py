"""
ownedpulse integration tests — routing, query expansion, comprehensive queries.
Changes from previous version:
- retrieval_params sent in every request
- sub_queries tested per routing path
- cited_by_llm split tested (some cited, some not)
- EU-Commission normalisation tested across all queries
- Comprehensive regulatory query set added (11 additional queries)
- Query idempotence tests updated for new response shape
"""

import pytest
from conftest import (
    CONTENT_QUERIES,
    METADATA_QUERIES,
    ALL_VERIFICATION_QUERIES,
    REGULATORY_CONTENT_QUERIES,
)

DEFAULT_PARAMS = {
    "query_depth": "standard",
    "top_k": 10,
    "score_threshold": 0.60
}


# ── Two-path routing ──────────────────────────────────────────────────────────

class TestTwoPathRouting:

    @pytest.mark.parametrize("query", CONTENT_QUERIES)
    def test_content_query_routes_content(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r.status_code == 200
        data = r.json()
        assert data["routing_path"] == "CONTENT", \
            f"Expected CONTENT for: '{query}'\nGot: {data['routing_path']}"

    @pytest.mark.parametrize("query", METADATA_QUERIES)
    def test_metadata_query_routes_metadata(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r.status_code == 200
        data = r.json()
        assert data["routing_path"] == "METADATA", \
            f"Expected METADATA for: '{query}'\nGot: {data['routing_path']}"

    def test_content_path_generates_sub_queries(self, api_client):
        r = api_client.post("/api/query", json={
            "query": CONTENT_QUERIES[0], "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        assert data["routing_path"] == "CONTENT"
        assert len(data["sub_queries"]) > 0, "CONTENT path must generate sub_queries"

    def test_metadata_path_sub_queries_behaviour(self, api_client):
        """METADATA path may have empty sub_queries — this is acceptable."""
        r = api_client.post("/api/query", json={
            "query": METADATA_QUERIES[0], "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        assert data["routing_path"] == "METADATA"
        assert isinstance(data["sub_queries"], list), "sub_queries must be a list even on METADATA"


# ── Six verification queries ──────────────────────────────────────────────────

class TestVerificationQueries:

    @pytest.mark.parametrize("query", ALL_VERIFICATION_QUERIES)
    def test_verification_query_returns_answer(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r.status_code == 200
        data = r.json()
        assert data["answer"], f"Empty answer for: '{query}'"

    @pytest.mark.parametrize("query", ALL_VERIFICATION_QUERIES)
    def test_verification_query_returns_citations(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        assert len(data["citations"]) > 0, f"No citations for: '{query}'"

    @pytest.mark.parametrize("query", CONTENT_QUERIES)
    def test_content_answer_has_citation_markers(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        import re
        has_marker = re.search(r'\[\d+\]', data["answer"]) is not None
        assert has_marker, \
            f"CONTENT answer missing [N] citation marker for: '{query}'"

    @pytest.mark.parametrize("query", ALL_VERIFICATION_QUERIES)
    def test_verification_query_no_eu_commission_in_citations(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        for citation in r.json()["citations"]:
            assert citation["issuing_body"] != "EU-Commission", \
                f"EU-Commission not normalised for query: '{query}'"

    @pytest.mark.parametrize("query", ALL_VERIFICATION_QUERIES)
    def test_verification_query_all_citations_above_threshold(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        threshold = data["retrieval_params_applied"]["score_threshold"]
        for citation in data["citations"]:
            assert citation["score"] >= threshold, \
                f"Citation score {citation['score']} below threshold {threshold}"


# ── cited_by_llm split ────────────────────────────────────────────────────────

class TestCitedByLlmSplit:

    def test_at_least_one_cited_chunk(self, submitted_query):
        cited = [c for c in submitted_query["citations"] if c["cited_by_llm"]]
        assert len(cited) > 0, "No citations marked cited_by_llm=True"

    def test_cited_chunks_referenced_in_answer(self, submitted_query):
        answer = submitted_query["answer"]
        cited = [c for c in submitted_query["citations"] if c["cited_by_llm"]]
        for citation in cited:
            marker = f"[{citation['index']}]"
            assert marker in answer, \
                f"Citation {citation['index']} is cited_by_llm=True but " \
                f"marker {marker} not found in answer"

    def test_uncited_chunks_not_in_answer(self, submitted_query):
        answer = submitted_query["answer"]
        uncited = [c for c in submitted_query["citations"] if not c["cited_by_llm"]]
        for citation in uncited:
            marker = f"[{citation['index']}]"
            assert marker not in answer, \
                f"Citation {citation['index']} is cited_by_llm=False but " \
                f"marker {marker} appears in answer"

    def test_uncited_chunks_above_threshold(self, submitted_query):
        """Uncited chunks must still be above score threshold."""
        threshold = submitted_query["retrieval_params_applied"]["score_threshold"]
        uncited = [c for c in submitted_query["citations"] if not c["cited_by_llm"]]
        for citation in uncited:
            assert citation["score"] >= threshold, \
                f"Uncited chunk score {citation['score']} below threshold — " \
                f"should have been dropped entirely"


# ── Agency coverage ───────────────────────────────────────────────────────────

class TestAgencyCoverage:

    @pytest.mark.parametrize("agency", ["FDA", "EMA", "ICH"])
    def test_agency_filter_returns_results(self, api_client, agency):
        r = api_client.post("/api/query", json={
            "query": "What are the key requirements?",
            "filters": {"agency": agency},
            "retrieval_params": DEFAULT_PARAMS
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["citations"]) > 0, \
            f"No results for agency filter: {agency}"
        for citation in data["citations"]:
            assert citation["issuing_body"] == agency, \
                f"Filter leak: expected {agency}, got {citation['issuing_body']}"


# ── Comprehensive regulatory queries ─────────────────────────────────────────

class TestComprehensiveRegulatoryQueries:
    """
    Extended set of regulatory queries covering GMP, CSV, risk management,
    pharmacovigilance, and cross-regime topics. All must return answers
    with citations. These test real corpus coverage.
    """

    @pytest.mark.parametrize("query", REGULATORY_CONTENT_QUERIES)
    def test_regulatory_query_returns_answer(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r.status_code == 200, f"Query failed: {r.text}"
        data = r.json()
        assert data["answer"], f"Empty answer for: '{query}'"

    @pytest.mark.parametrize("query", REGULATORY_CONTENT_QUERIES)
    def test_regulatory_query_has_citations(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        assert len(data["citations"]) > 0, \
            f"No citations for regulatory query: '{query}'"

    @pytest.mark.parametrize("query", REGULATORY_CONTENT_QUERIES)
    def test_regulatory_query_routes_content(self, api_client, query):
        r = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        assert data["routing_path"] == "CONTENT", \
            f"Regulatory query routed to METADATA unexpectedly: '{query}'"

    def test_annex11_query_returns_ema_citation(self, api_client):
        """Annex 11 is an EMA document — must appear in citations."""
        r = api_client.post("/api/query", json={
            "query": "What are the Annex 11 requirements for audit trails?",
            "filters": {},
            "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        agencies = [c["issuing_body"] for c in data["citations"]]
        assert "EMA" in agencies, \
            f"Annex 11 query returned no EMA citations: {agencies}"

    def test_ich_q9_query_returns_ich_citation(self, api_client):
        """ICH Q9 is an ICH document — must appear in citations."""
        r = api_client.post("/api/query", json={
            "query": "What is the ICH Q9 definition of quality risk management?",
            "filters": {},
            "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        agencies = [c["issuing_body"] for c in data["citations"]]
        assert "ICH" in agencies, \
            f"ICH Q9 query returned no ICH citations: {agencies}"

    def test_cfr_part11_query_returns_fda_citation(self, api_client):
        """21 CFR Part 11 is FDA — must appear in citations."""
        r = api_client.post("/api/query", json={
            "query": "What are the FDA requirements for electronic records under 21 CFR Part 11?",
            "filters": {},
            "retrieval_params": DEFAULT_PARAMS
        })
        data = r.json()
        agencies = [c["issuing_body"] for c in data["citations"]]
        assert "FDA" in agencies, \
            f"21 CFR Part 11 query returned no FDA citations: {agencies}"

    def test_answer_does_not_contain_html(self, api_client):
        """All answers must be plain text — no server-side HTML rendering."""
        for query in REGULATORY_CONTENT_QUERIES[:3]:
            r = api_client.post("/api/query", json={
                "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
            })
            answer = r.json()["answer"]
            assert "<p>" not in answer and "<strong>" not in answer, \
                f"HTML found in answer for: '{query}'"


# ── Idempotence ───────────────────────────────────────────────────────────────

class TestQueryIdempotence:

    def test_same_query_different_query_ids(self, api_client):
        query = CONTENT_QUERIES[0]
        r1 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        r2 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r1.json()["query_id"] != r2.json()["query_id"], \
            "Same query returned identical query_id — not idempotent"

    def test_same_query_consistent_routing(self, api_client):
        query = CONTENT_QUERIES[0]
        r1 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        r2 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        assert r1.json()["routing_path"] == r2.json()["routing_path"], \
            "Same query routed differently on repeat submission"

    def test_same_query_consistent_sub_query_count(self, api_client):
        query = CONTENT_QUERIES[0]
        r1 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        r2 = api_client.post("/api/query", json={
            "query": query, "filters": {}, "retrieval_params": DEFAULT_PARAMS
        })
        count1 = r1.json()["retrieval_params_applied"]["sub_query_count"]
        count2 = r2.json()["retrieval_params_applied"]["sub_query_count"]
        assert count1 == count2, \
            f"Sub-query count inconsistent: {count1} vs {count2}"
