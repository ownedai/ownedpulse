# /opt/scripts/ingestion/embedding.py
import requests
from .config import OLLAMA_HOST, EMBED_MODEL


def embed(text: str) -> list:
    """Generate embedding via Ollama nomic-embed-text.

    Returns:
        list of 1024 floats (mxbai-embed-large vector)
    """
    if not text or not text.strip():
        return [0.0] * 1024
    r = requests.post(
        f'{OLLAMA_HOST}/api/embed',
        json={'model': EMBED_MODEL, 'input': text},
        timeout=60,
    )
    r.raise_for_status()
    emb = r.json()['embeddings']
    if not emb:
        return [0.0] * 1024
    return emb[0]
