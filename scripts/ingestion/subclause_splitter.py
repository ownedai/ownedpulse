"""
subclause_splitter.py

Post-HybridChunker splitter that detects list chunks containing multiple N.M
sub-clause boundaries and splits them into individual chunks before embedding.

Detection: content_type would be 'list' AND text contains 2+ lines matching
           ^d+.d+ at line start. Only N.M format — avoids false positives on
           bullet points, plain numbers, or section headers.

Inserted between HybridChunker output and the embed loop in ingest.py.
"""

import re
import logging

logger = logging.getLogger(__name__)

_SUBCLAUSE_RE = re.compile(r'^\s*-?\s*(\d+\.\d+)\s', re.MULTILINE)


class _Meta:
    """Minimal meta wrapper matching the interface expected by build_payload."""
    def __init__(self, headings=None, doc_items=None):
        self.headings = list(headings or [])
        self.doc_items = list(doc_items or [])


class _Chunk:
    """Minimal chunk wrapper matching the interface expected by the embed loop.
    Provides .text and .meta.headings / .meta.doc_items."""
    def __init__(self, text, meta):
        self.text = text
        self.meta = meta


def _has_trapped_subclauses(chunk) -> bool:
    """Check whether a chunk is a list with trapped N.M sub-clauses."""
    text = getattr(chunk, 'text', '') or ''
    if not text:
        return False
    # Check doc_items for list type
    items = list(getattr(getattr(chunk, 'meta', None), 'doc_items', []) or [])
    labels = {getattr(it, 'label', None) for it in items if hasattr(it, 'label')}
    if 'list_item' not in labels and 'list' not in labels:
        return False
    # Must have 2+ sub-clause boundaries
    return len(_SUBCLAUSE_RE.findall(text)) >= 2


def _split(chunk) -> list:
    """Split a trapped list chunk into individual sub-clause _Chunk objects."""
    text = getattr(chunk, 'text', '') or ''
    matches = list(_SUBCLAUSE_RE.finditer(text))

    if len(matches) < 2:
        return [chunk]

    try:
        meta = _Meta(
            headings=getattr(getattr(chunk, 'meta', None), 'headings', None),
            doc_items=getattr(getattr(chunk, 'meta', None), 'doc_items', None),
        )
        sub_chunks = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sub_text = text[start:end].strip()
            if sub_text.startswith('- '):
                sub_text = sub_text[2:]
            sub_chunks.append(_Chunk(text=sub_text, meta=meta))
        return sub_chunks

    except Exception:
        logger.warning(
            "subclause_splitter: failed to split chunk — returning original",
            exc_info=True,
        )
        return [chunk]


def split_trapped_subclauses(chunks: list) -> list:
    """Detect and split trapped sub-clause chunks. Returns expanded chunk list."""
    result = []
    for chunk in chunks:
        if _has_trapped_subclauses(chunk):
            result.extend(_split(chunk))
        else:
            result.append(chunk)
    if len(result) > len(chunks):
        logger.info(
            "subclause_splitter: %d chunks → %d chunks (%d sub-clause splits)",
            len(chunks), len(result), len(result) - len(chunks),
        )
    return result
