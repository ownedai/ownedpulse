# /opt/scripts/ingestion/extraction.py
import re

# ── C4: Clause ID extraction ──────────────────────────────────────────────────

_RE_ANNEX    = re.compile(r'^\s*(\d+(?:\.\d+)*)')
_RE_PART11   = re.compile(r'§\s*(11\.\d+(?:\([a-z]\))?)')
_RE_ROMAN    = re.compile(r'^\s*(I{1,3}|IV|VI{0,3}|IX|X{1,3})\.\s+', re.IGNORECASE)
_RE_LETTER_Q = re.compile(r'^\s*([a-z])\.\s+\w')

_RE_PART11_SEC  = re.compile(r'§\s*(11\.\d+(?:\([a-z]\))?)')   # existing
_RE_PART11_TEXT = re.compile(r'§\s*(11\.\d+(?:\([a-z]\))?)')   # same pattern, on text

def _clause_from_part11(headings, prefix, chunk_text=""):
    # Primary: headings (works for PDF sources)
    for h in reversed(headings):
        m = _RE_PART11_SEC.search(h)
        if m:
            return f'21-CFR-Part11-§{m.group(1)}'
    # Fallback: scan chunk_text (required for eCFR XML source)
    if chunk_text:
        m = _RE_PART11_TEXT.search(chunk_text)
        if m:
            return f'21-CFR-Part11-§{m.group(1)}'
    return None


# Clause number at the start of the chunk text: '9. Audit Trails', '8.2 For critical ...'.
# Up to two digits per component; the full stop after the number is optional; a
# capital letter must follow. '2011 revision' and '1 000 units' do not match.
_RE_CLAUSE_START = re.compile(r'^\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s+[A-Z]')


def annex_clause(h: list, p: str, chunk_text: str = ""):
    """EU GMP Annex / ICH style clause for one chunk. Returns (value, source, conflict).

    1. The chunk text clearly starts with a clause number ('9. Audit Trails') -> source 'text'.
    2. Otherwise the first numbered heading in the heading list (the old parser's
       rule) -> source 'heading'.
    3. Otherwise (None, None, False).
    If both 1 and 2 give a value and they differ, the text value wins and conflict is True.
    """
    m_text = _RE_CLAUSE_START.match(chunk_text or "")
    text_num = m_text.group(1) if m_text else None
    head_num = None
    for heading in h or []:
        m = _RE_ANNEX.match(heading)
        if m:
            head_num = m.group(1)
            break
    conflict = bool(text_num and head_num and text_num != head_num)
    if text_num:
        return f'{p}{text_num}', 'text', conflict
    if head_num:
        return f'{p}{head_num}', 'heading', False
    return None, None, False


def _from_annex(h: list, p: str, chunk_text: str = "", **kwargs) -> str:
    """EU GMP Annex / ICH style: the clause value from annex_clause (text first, then heading)."""
    return annex_clause(h, p, chunk_text)[0]


def _from_part11(h: list, p: str) -> str:
    """21 CFR Part 11 style: '§ 11.10(a)' -> '21-CFR-Part11-§11.10(a)'"""
    if not h:
        return None
    for x in reversed(h):
        m = _RE_PART11.search(x)
        if m:
            return f'21-CFR-Part11-§{m.group(1)}'
    return None


def _from_cgmp_qa(h: list, p: str, **kwargs) -> str:
    """FDA CGMP Q&A style: Roman numerals + letter/number questions."""
    if not h:
        return None
    section = question = None
    for x in h:
        m = _RE_ROMAN.match(x)
        if m:
            section = m.group(1).upper()
        m = _RE_LETTER_Q.match(x)
        if m:
            question = m.group(1)
        m = _RE_ANNEX.match(x)
        if m:
            question = m.group(1)
    if question and section:
        return f'{p}{section}-{question}'
    if section:
        return f'{p}{section}'
    if question:
        return f'{p}{question}'
    return None


_DISPATCH = {
    'EU-GMP-Annex11':    _from_annex,
    'EU-GMP-Annex15':    _from_annex,
    'EU-GMP-Annex22':    _from_annex,
    'ICH-Q10':           _from_annex,
    'EMA-Reflection-AI': _from_annex,
    '21-CFR-Part-11':    _clause_from_part11,
    'FDA-DI-CGMP-QA':    _from_cgmp_qa,
}


def extract_clause_id(chunk, meta: dict) -> str:
    """Extract formal clause identifier from chunk heading hierarchy.

    Returns canonical clause_id or None for preamble/glossary chunks.
    """
    h = list(getattr(chunk.meta, 'headings', []) or [])
    parser = _DISPATCH.get(meta['document_id'])
    return parser(h, meta.get('clause_id_prefix', ''), chunk_text=getattr(chunk, 'text', '')) if parser else None


# ── C5: Cross-reference extraction ───────────────────────────────────────────

_XREF_PATTERNS = [
    (re.compile(r'21\s*CFR\s*(\d+\.\d+(?:\([a-z]\))?)'),
     lambda m: f'21-CFR-Part{m.group(1).split(".")[0]}-§{m.group(1)}'),
    (re.compile(r'Annex\s*(\d+)'),
     lambda m: f'EU-GMP-Annex{m.group(1)}'),
    (re.compile(r'ICH\s*Q(\d+[A-Z]?)'),
     lambda m: f'ICH-Q{m.group(1)}'),
    (re.compile(r'GAMP\s*([5-9])'),
     lambda m: f'GAMP-{m.group(1)}'),
    (re.compile(r'§\s*11\.(\d+(?:\([a-z]\))?)'),
     lambda m: f'21-CFR-Part11-§11.{m.group(1)}'),
]


def extract_cross_refs(chunk_text: str) -> list:
    """Extract canonical cross-references from chunk text. Returns sorted list."""
    found = set()
    for pattern, norm in _XREF_PATTERNS:
        for m in pattern.finditer(chunk_text):
            found.add(norm(m))
    return sorted(found)


# ── C6: Character offsets ────────────────────────────────────────────────────

def compute_char_offsets(chunk_text: str, full_text: str, search_start: int = 0) -> tuple:
    """Find chunk position in full document text.

    Strategy:
    1. Exact match (fast path)
    2. Flexible whitespace regex (handles newline differences between HybridChunker and export_to_text)
    3. Meaningful-words fallback (handles table/document_index serialization mismatches)
    4. Zero-length span fallback with warning (last resort — offset will be approximate)
    """
    # Fast path: exact match
    pos = full_text.find(chunk_text, search_start)
    if pos != -1:
        return pos, pos + len(chunk_text)

    # Flexible whitespace — any whitespace sequence matches any whitespace sequence
    parts = chunk_text.split()
    if parts:
        pattern = r'\s+'.join(re.escape(p) for p in parts)
        m = re.search(pattern, full_text[search_start:])
        if m:
            return search_start + m.start(), search_start + m.end()

    # Meaningful-words fallback (tables, document_index elements)
    meaningful = [p for p in parts if len(p) > 4][:5]
    if meaningful:
        pattern = r'.{0,50}'.join(re.escape(p) for p in meaningful[:2])
        m = re.search(pattern, full_text[search_start:])
        if m:
            return search_start + m.start(), search_start + m.end()

    # Last resort — offset will be approximate
    print(f'  WARNING: chunk offset not found, using search_start={search_start} as fallback')
    return search_start, search_start


# ── C7: Provenance ───────────────────────────────────────────────────────────

def extract_provenance(chunk) -> tuple:
    """Extract page number and bounding box from chunk doc_items.

    Returns:
        tuple (page_no: int, bbox: list[float] or None)
        bbox format: [x0, y0, x1, y1] in PDF points (1/72 inch, origin top-left)
    """
    items = list(getattr(chunk.meta, 'doc_items', []) or [])
    if not items:
        return (1, None)
    first_prov = items[0].prov[0] if items[0].prov else None
    if not first_prov:
        return (1, None)
    page_no = first_prov.page_no
    page_items = [it for it in items if it.prov and it.prov[0].page_no == page_no]
    bboxes = [it.prov[0].bbox for it in page_items if it.prov[0].bbox]
    if not bboxes:
        return (page_no, None)
    x0 = min(b.l for b in bboxes)
    y0 = min(b.t for b in bboxes)
    x1 = max(b.r for b in bboxes)
    y1 = max(b.b for b in bboxes)
    return (page_no, [x0, y0, x1, y1])
