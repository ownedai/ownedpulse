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
    assert _from_annex([], "", chunk_text="9. Audit Trails\nThe audit trail should record (text)") == "9"


def test_two_component_clause_start():
    assert _from_annex([], "", chunk_text="8.2 For critical systems, the audit trail (text)") == "8.2"


def test_prefix_is_applied():
    assert _from_annex([], "X-", chunk_text="4.8 Audit trails are (text)") == "X-4.8"


def test_body_text_without_number_is_null():
    assert _from_annex([], "", chunk_text="Audit trails should be considered based on risk (text)") is None


def test_four_digit_year_is_not_a_clause():
    assert _from_annex([], "", chunk_text="2011 revision of the annex (text)") is None


def test_number_followed_by_digits_is_not_a_clause():
    assert _from_annex([], "", chunk_text="1 000 units were recorded (text)") is None


def test_heading_fallback_when_text_has_no_number():
    # Amendment (K3): with no clause number at the start of the text, the first
    # numbered heading is used, as the old parser did.
    assert _from_annex(["8.2 Something"], "", chunk_text="Audit trails should be (text)") == "8.2"


def test_heading_fallback_skips_non_numbered_headings():
    assert _from_annex(["Annex 11", "Audit trails"], "", chunk_text="Audit trails should be (text)") is None


def test_conflict_text_wins_and_is_counted():
    value, source, conflict = annex_clause(["8.2 Something"], "", chunk_text="9. Audit Trails\nThe audit trail (text)")
    assert (value, source, conflict) == ("9", "text", True)


def test_agreement_is_not_a_conflict():
    value, source, conflict = annex_clause(["9 Audit Trails"], "", chunk_text="9. Audit Trails\nThe audit trail (text)")
    assert (value, source, conflict) == ("9", "text", False)


def test_heading_only_source_has_no_conflict():
    assert annex_clause(["8.2 Something"], "", chunk_text="Audit trails (text)") == ("8.2", "heading", False)


def test_empty_text_uses_heading_and_empty_heading_is_null():
    assert _from_annex(["9 Audit Trails"], "", chunk_text="") == "9"
    assert _from_annex([], "", chunk_text="") is None


def test_extract_clause_id_uses_text_for_annex_documents():
    chunk = _Chunk("9. Audit Trails\nThe audit trail (text)", headings=["Annex 11"])
    assert extract_clause_id(chunk, {"document_id": "EU-GMP-Annex11", "clause_id_prefix": ""}) == "9"
    chunk2 = _Chunk("Audit trails should be (text)", headings=["8.2 Something"])
    assert extract_clause_id(chunk2, {"document_id": "EU-GMP-Annex11", "clause_id_prefix": ""}) == "8.2"


# ── K3 conflict rule: reference lists ─────────────────────────────────────────
# Synthetic cases in the form of the EMA-Reflection reference-list chunks (no document text).


def test_reference_list_entries_take_heading_value():
    for text in ["19. Smith J, Title of a paper", "5. Jones K, Another paper", "9. Lee M, Third paper"]:
        value, source, conflict = annex_clause(["6. References"], "", chunk_text=text)
        assert (value, source, conflict) == ("6", "heading", False), text


def test_reference_title_variants():
    assert annex_clause(["7. Bibliography"], "", chunk_text="3. X")[0] == "7"
    assert annex_clause(["8. Reference list"], "", chunk_text="3. X")[0] == "8"


def test_reference_title_must_start_the_title():
    # 'Cross references' is not a reference list: text-first applies, and the conflict is counted.
    value, source, conflict = annex_clause(["6. Cross references in the text"], "", chunk_text="9. Audit Trails")
    assert (value, source, conflict) == ("9", "text", True)


def test_non_reference_conflict_text_wins_synthetic():
    # SYNTHETIC (labelled): a non-reference heading and a text number that differ.
    value, source, conflict = annex_clause(["6. Methods"], "", chunk_text="9. Audit Trails")
    assert (value, source, conflict) == ("9", "text", True)


# ── K3 date rule: a number followed by a month name is not a clause ──────────


def test_date_at_chunk_start_is_not_a_clause():
    # Real chunk start form (EMA-Reflection chunk 0): '9 September 2024 …'.
    assert annex_clause([], "", chunk_text="9 September 2024 EMA/CHMP/CVMP/83833/2023 Committee") == (None, None, False)


def test_date_falls_through_to_heading_fallback():
    value, source, conflict = annex_clause(["8.2 Something"], "", chunk_text="9 September 2024 Committee")
    assert (value, source, conflict) == ("8.2", "heading", False)


def test_abbreviated_month_is_a_date():
    assert annex_clause([], "", chunk_text="9 Sep 2024 Committee")[0] is None
    assert annex_clause([], "", chunk_text="3 Jan 2025 Committee")[0] is None


def test_month_word_inside_a_longer_word_is_still_a_clause():
    # 'Mayor' is not 'May'.
    assert annex_clause([], "", chunk_text="9 Mayor functions are described")[0] == "9"


def test_real_two_component_clause_unchanged():
    assert annex_clause([], "", chunk_text="12.2 Text of the requirement (text)")[0] == "12.2"


def test_single_component_with_full_stop_unchanged():
    assert annex_clause([], "", chunk_text="9. Text of the requirement (text)")[0] == "9"
