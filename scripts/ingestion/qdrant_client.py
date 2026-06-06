# /opt/scripts/ingestion/qdrant_client.py
from qdrant_client import QdrantClient
from .config import QDRANT_HOST, QDRANT_PORT

_CLIENT = None


def get_client() -> QdrantClient:
    """Singleton Qdrant client. Reuses connection across calls."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    return _CLIENT
