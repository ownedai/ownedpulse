# /opt/scripts/ingestion/embedding.py
import sys
import time
from pathlib import Path

import requests

from .config import OLLAMA_HOST, EMBED_MODEL

_DEBUG_LOG = Path('/tmp/ingest_debug.log')


def _dbg(msg: str) -> None:
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] [embed] {msg}\n'
    sys.stderr.write(line)
    sys.stderr.flush()
    try:
        with _DEBUG_LOG.open('a') as f:
            f.write(line)
    except Exception:
        pass


def embed(text: str, chunk_index: int = -1) -> list:
    """Generate embedding via Ollama mxbai-embed-large.

    Retries on connection errors (BrokenPipeError, ConnectionError) which
    occur when Ollama closes a keep-alive TCP connection between chunks.
    """
    if not text or not text.strip():
        return [0.0] * 1024

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        t0 = time.monotonic()
        try:
            r = requests.post(
                f'{OLLAMA_HOST}/api/embed',
                json={'model': EMBED_MODEL, 'input': text},
                timeout=60,
            )
            elapsed = time.monotonic() - t0
            if elapsed > 5 or chunk_index % 10 == 0:
                _dbg(f'chunk {chunk_index}: {elapsed:.1f}s ({len(text)} chars)')
            r.raise_for_status()
            emb = r.json()['embeddings']
            if not emb:
                return [0.0] * 1024
            return emb[0]
        except (BrokenPipeError, ConnectionError, requests.exceptions.ConnectionError) as e:
            if attempt < max_attempts:
                delay = 2 ** attempt
                _dbg(f'chunk {chunk_index}: connection error on attempt {attempt}, retrying in {delay}s: {e}')
                time.sleep(delay)
            else:
                _dbg(f'chunk {chunk_index}: connection error after {max_attempts} attempts: {e}')
                raise


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list]:
    """Embed multiple texts in batches. Returns list of vectors in same order.
    Falls back to zero vector for empty strings.
    Uses Ollama /api/embed with input array for batch processing.
    """
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        non_empty = [(j, t) for j, t in enumerate(batch) if t and t.strip()]
        batch_results = [[0.0] * 1024] * len(batch)
        if not non_empty:
            results.extend(batch_results)
            continue
        indices, input_texts = zip(*non_empty)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            t0 = time.monotonic()
            try:
                r = requests.post(
                    f'{OLLAMA_HOST}/api/embed',
                    json={'model': EMBED_MODEL, 'input': list(input_texts)},
                    timeout=120,
                )
                elapsed = time.monotonic() - t0
                _dbg(f'batch {i//batch_size}: {len(input_texts)} chunks in {elapsed:.1f}s')
                r.raise_for_status()
                embeddings = r.json()['embeddings']
                for idx, vec in zip(indices, embeddings):
                    batch_results[idx] = vec
                break
            except (BrokenPipeError, ConnectionError, requests.exceptions.ConnectionError) as e:
                if attempt < max_attempts:
                    delay = 2 ** attempt
                    _dbg(f'batch {i//batch_size}: connection error, retrying in {delay}s: {e}')
                    time.sleep(delay)
                else:
                    _dbg(f'batch {i//batch_size}: failed after {max_attempts} attempts: {e}')
                    raise
        results.extend(batch_results)
    return results
