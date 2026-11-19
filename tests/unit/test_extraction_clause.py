"""K3 parser: clause_id for annex-style documents (scripts/ingestion/extraction.py).

Offline. The parser reads chunk text only (not the heading list). Clause id is set
only when the chunk text clearly begins with a clause number.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "ingestion"))

from extraction import _from_annex, annex_clause, extract_clause_id  # noqa: E402


class _Meta:
    def __init__(self, headings):
        self.headings = headings


class _Chunk:
    def __init__(self, text, headings=()):
        self.text = text
        self.meta = _Meta(list(headings))


def test_annex11_section9_text_start():
    assert _from_annex([], "", chunk_text="9. Audit Trails\nThe audit trail should record ...") == "9"


def test_two_component_clause_start():
    assert _from_annex([], "", chunk_text="8.2 For critical systems, the audit trail ...") == "8.2"


def test_prefix_is_applied():
    assert _from_annex([], "X-", chunk_text="4.8 Audit trails are ...") == "X-4.8"


def test_body_text_without_number_is_null():
    assert _from_annex([], "", chunk_text="Audit trails should be considered based on risk ...") is None


def test_four_digit_year_is_not_a_clause():
    assert _from_annex([], "", chunk_text="2011 revision of the annex ...") is None


def test_number_followed_by_digits_is_not_a_clause():
    assert _from_annex([], "", chunk_text="1 000 units were recorded ...") is None


def test_heading_fallback_when_text_has_no_number():
    # Amendment (K3): with no clause number at the start of the text, the first
    # numbered heading is used, as the old parser did.
    assert _from_annex(["8.2 Something"], "", chunk_text="Audit trails should be ...") == "8.2"


def test_heading_fallback_skips_non_numbered_headings():
    assert _from_annex(["Annex 11", "Audit trails"], "", chunk_text="Audit trails should be ...") is None


def test_conflict_text_wins_and_is_counted():
    value, source, conflict = annex_clause(["8.2 Something"], "", chunk_text="9. Audit Trails\nThe audit trail ...")
    assert (value, source, conflict) == ("9", "text", True)


def test_agreement_is_not_a_conflict():
    value, source, conflict = annex_clause(["9 Audit Trails"], "", chunk_text="9. Audit Trails\nThe audit trail ...")
    assert (value, source, conflict) == ("9", "text", False)


def test_heading_only_source_has_no_conflict():
    assert annex_clause(["8.2 Something"], "", chunk_text="Audit trails ...") == ("8.2", "heading", False)


def test_empty_text_uses_heading_and_empty_heading_is_null():
    assert _from_annex(["9 Audit Trails"], "", chunk_text="") == "9"
    assert _from_annex([], "", chunk_text="") is None


def test_extract_clause_id_uses_text_for_annex_documents():
    chunk = _Chunk("9. Audit Trails\nThe audit trail ...", headings=["Annex 11"])
    assert extract_clause_id(chunk, {"document_id": "EU-GMP-Annex11", "clause_id_prefix": ""}) == "9"
    chunk2 = _Chunk("Audit trails should be ...", headings=["8.2 Something"])
    assert extract_clause_id(chunk2, {"document_id": "EU-GMP-Annex11", "clause_id_prefix": ""}) == "8.2"
