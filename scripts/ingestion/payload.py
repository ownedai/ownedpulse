# /opt/scripts/ingestion/payload.py
from datetime import datetime, timezone
from .config import EMBED_MODEL, EMBED_DIM
from .chunking import get_tokenizer

_REQ_CHUNK = [
    'chunk_index', 'chunk_text', 'chunk_token_count',
    'char_offset_start', 'char_offset_end', 'page_no',
    'embedding_model', 'embedding_dim', 'chunker_version', 'chunked_at',
    'trace_id',
]

_REQ_DOC = [
    'document_id', 'document_title', 'document_class', 'document_type',
    'document_status', 'document_version', 'language',
    'source_local_path', 'source_hash', 'source_file_format',
]

_OPTIONAL_DOC = (
    'publication_date', 'effective_date', 'adoption_date',
    'issuing_body', 'jurisdiction', 'regulatory_domain',
    'clause_id_prefix', 'source_url', 'source_fetched_at',
    'feed_source', 'feed_item_guid', 'company_id',
    'gxp_relevance', 'gamp_category',
)


def _token_count(chunk) -> int:
    """Count tokens using nomic-embed-text tokenizer."""
    if hasattr(chunk, 'token_count'):
        return chunk.token_count
    return len(get_tokenizer()(chunk.text)['input_ids'])


def _detect_content_type(chunk) -> str:
    """Classify chunk based on doc_items labels."""
    items = list(getattr(chunk.meta, 'doc_items', []) or [])
    if not items:
        return 'text'
    types = {it.label for it in items if hasattr(it, 'label')}
    if 'table' in types:     return 'table'
    if 'list_item' in types: return 'list'
    if 'figure' in types:    return 'figure'
    if 'formula' in types:   return 'equation'
    return 'text'


def build_payload(chunk, idx: int, meta: dict, clause_id,
                  cross_refs: list, char_offsets: tuple,
                  prov: tuple, chunker_version: str,
                  trace_id: str = "") -> dict:
    """Assemble complete Qdrant payload from C1-C7 outputs.

    Validates all required fields before returning.
    chunk_id is NOT set here — set by orchestrator after calling this function.
    """
    page_no, bbox = prov
    char_start, char_end = char_offsets

    payload = {
        # Chunk-level fields
        'chunk_index':       idx,
        'chunk_text':        chunk.text,
        'chunk_token_count': _token_count(chunk),
        'char_offset_start': char_start,
        'char_offset_end':   char_end,
        'page_no':           page_no,
        'bbox':              bbox,
        'section_path':      list(chunk.meta.headings or []),
        'clause_id':         clause_id,
        'cross_refs':        cross_refs,
        'content_type':      _detect_content_type(chunk),
        'embedding_model':   EMBED_MODEL,
        'embedding_dim':     EMBED_DIM,
        'chunker_version':   chunker_version,
        'chunked_at':        datetime.now(timezone.utc).isoformat(),
        'trace_id':          trace_id,
    }

    # Document-level core (denormalised into every chunk)
    for f in _REQ_DOC:
        payload[f] = meta[f]

    # Document-level optional
    for f in _OPTIONAL_DOC:
        if f in meta:
            payload[f] = meta[f]

    # Seed corpus flag — True when feed_source is absent or empty string.
    # Indexed bool in Qdrant; used by build_qdrant_filter() to scope retrieval.
    payload['corpus_doc'] = not bool(meta.get('feed_source', ''))

    # Validate required fields before returning
    for f in _REQ_CHUNK:
        if f == 'chunk_id':
            continue  # Set by orchestrator after build_payload
        assert payload.get(f) is not None, f'Missing required chunk field: {f}'
    for f in _REQ_DOC:
        assert payload.get(f) is not None, f'Missing required doc field: {f}'
    assert isinstance(payload.get('cross_refs'), list), 'cross_refs must be list'
    if not payload.get('trace_id'):
        raise ValueError('trace_id is required on every chunk — structural guard rail (TI-20)')

    return payload
