"""K3 line rule (annex-family documents): a chunk with no clause at its start, nothing carried
forward, and no numbered heading takes the first numbered clause line inside the chunk text.
Offline; excerpts of public Annex 11 text."""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    'extraction', os.path.join(_HERE, '..', '..', 'scripts', 'ingestion', 'extraction.py'))
ex = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ex)

ANNEX = {'document_id': 'EU-GMP-Annex11', 'clause_id_prefix': ''}

class _Meta:
    def __init__(self, headings):
        self.headings = list(headings)

class Chunk:
    def __init__(self, text, headings=()):
        self.text = text
        self.meta = _Meta(headings)

CHUNK1 = ('Legal basis for publishing the detailed guidelines: Article 47 of Directive 2001/83/EC on the '
          'Community code relating to medicinal products for human use.\n'
          'Status of the document: revision 1\n'
          'Deadline for coming into operation: 30 June 2011\n'
          'Principle\n'
          'This annex applies to all forms of computerised systems used as part of a GMP regulated activities.\n'
          'General\n'
          '1. Risk Management\n'
          'Risk management should be applied throughout the lifecycle of the computerised system.\n'
          '2. Personnel\n'
          'There should be close cooperation between all relevant personnel.')


def test_chunk1_takes_first_clause_line():
    assert ex.extract_clause_line_fallback(Chunk(CHUNK1), ANNEX) == '1'


def test_parser_itself_is_unchanged_for_chunk1():
    # annex_clause keeps its original result (None); the line rule lives in the carry step only.
    assert ex.annex_clause(['Annex 11: Computerised Systems'], '', CHUNK1) == (None, None, False)


def test_non_annex_document_gets_no_line_rule():
    assert ex.extract_clause_line_fallback(Chunk(CHUNK1), {'document_id': 'ICH-Q9', 'clause_id_prefix': ''}) is None


def test_date_line_is_not_a_clause():
    text = 'Legal basis for publishing the guidelines.\n9 September 2024\nSomething else follows.'
    assert ex.extract_clause_line_fallback(Chunk(text), ANNEX) is None


def test_toc_lines_are_not_clauses():
    text = ('Legal basis for publishing the guidelines.\n'
            '4. Risk Management ........ 12\n'
            '5. Personnel ........ 14')
    assert ex.extract_clause_line_fallback(Chunk(text), ANNEX) is None


def test_two_clause_tokens_on_one_line_is_toc():
    text = 'Legal basis for publishing the guidelines.\n1. Risk Management 2. Personnel'
    assert ex.extract_clause_line_fallback(Chunk(text), ANNEX) is None


def test_chunk_that_starts_with_a_clause_gets_no_line_rule():
    text = ('4. Risk Management ........ 12\n5. Personnel ........ 14\nSome text.\n6. Other Title')
    assert ex.extract_clause_line_fallback(Chunk(text), ANNEX) is None


def test_no_clause_anywhere_stays_none():
    text = 'EUROPEAN COMMISSION\nHEALTH AND CONSUMERS DIRECTORATE-GENERAL\nPublic Health'
    assert ex.extract_clause_line_fallback(Chunk(text), ANNEX) is None


def test_carried_clause_wins_over_line_rule():
    # Earlier chunk has clause 2.3.3.3; the next chunk has no own clause but has a numbered line.
    chunks = [Chunk('2.3.3.3 Some clause text that is long enough to read as a clause.'),
              Chunk('Legal basis for the guidance.\n2. Something else')]
    assert ex.forward_clause_ids(chunks, ANNEX) == ['2.3.3.3', '2.3.3.3']


def test_forward_uses_line_rule_only_before_any_clause():
    chunks = [Chunk('EUROPEAN COMMISSION\nHEALTH'),
              Chunk(CHUNK1),
              Chunk('3.1 When third parties are involved, the regulated user should ensure control.')]
    assert ex.forward_clause_ids(chunks, ANNEX) == [None, '1', '3.1']


def test_forward_leaves_non_annex_documents_empty():
    chunks = [Chunk(CHUNK1)]
    assert ex.forward_clause_ids(chunks, {'document_id': 'ICH-Q9', 'clause_id_prefix': ''}) == [None]
