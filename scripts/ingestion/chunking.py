import hashlib
import uuid
from .config import TOKENIZER_NAME, MAX_TOKENS

_TOKENIZER = None


def get_tokenizer():
    """Singleton tokenizer — nomic-embed-text HuggingFace tokenizer."""
    global _TOKENIZER
    if _TOKENIZER is None:
        from transformers import AutoTokenizer
        _TOKENIZER = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
    return _TOKENIZER


def chunk_document(doc, max_tokens=MAX_TOKENS, merge_peers=True) -> list:
    """Chunk DoclingDocument via HybridChunker.

    - merge_peers=True: merges adjacent small paragraphs under same heading
    - Normalizes None headings to [] to prevent downstream errors
    - Drops document_index (TOC) chunks — not useful for retrieval
    """
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
    chunker = HybridChunker(
        tokenizer=get_tokenizer(),
        max_tokens=max_tokens,
        merge_peers=merge_peers,
    )
    chunks = list(chunker.chunk(doc))
    if not chunks:
        raise RuntimeError('Chunker produced 0 chunks')

    # Normalize None headings — prevents downstream iteration errors
    for c in chunks:
        if c.meta.headings is None:
            c.meta.headings = []

    # Drop TOC chunks — document_index elements not useful for retrieval
    def _is_toc(chunk):
        items = list(getattr(chunk.meta, 'doc_items', []) or [])
        return any(getattr(it, 'label', None) == 'document_index' for it in items)

    before = len(chunks)
    chunks = [c for c in chunks if not _is_toc(c)]
    dropped = before - len(chunks)
    if dropped:
        print(f'  (dropped {dropped} TOC chunks)')

    return chunks


def make_chunk_id(document_id: str, document_version: str,
                  chunk_index: int, chunker_version: str = '') -> str:
    """Generate deterministic chunk UUID.

    Includes chunker_version so re-ingestion with a new version produces
    new chunk IDs, allowing old and new chunks to coexist in Qdrant.
    This enables C9 supersession: old chunks marked superseded,
    new chunks added as active — both remain queryable.

    Args:
        document_id: e.g. 'EU-GMP-Annex11'
        document_version: e.g. 'Rev. 14 (2011-06-30)'
        chunk_index: 0-based position in chunk list
        chunker_version: e.g. 'v0.2.0'

    Returns:
        UUID string
    """
    key = f'{document_id}|{document_version}|{chunk_index}|{chunker_version}'
    digest = hashlib.md5(key.encode('utf-8')).hexdigest()
    return str(uuid.UUID(digest))
