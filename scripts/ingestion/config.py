# /opt/scripts/ingestion/config.py

import os

_pg_host = os.environ.get("POSTGRES_HOST", "postgres")
_pg_port = os.environ.get("POSTGRES_PORT", "5432")
_pg_user = os.environ.get("POSTGRES_USER", "postgres")
_pg_pass = os.environ.get("POSTGRES_PASSWORD", "")
_pg_db   = os.environ.get("POSTGRES_DB", "knowledge_base")
os.environ.setdefault("PG_DSN", f"postgresql://{_pg_user}:{_pg_pass}@{_pg_host}:{_pg_port}/{_pg_db}")

ARCHIVE_ROOT      = os.environ.get('ARCHIVE_ROOT', '/mnt/data/regulatory_archive')
INTERNAL_ARCHIVE  = os.environ.get('INTERNAL_ARCHIVE', '/mnt/data/internal_archive')

PG_DSN            = os.environ['PG_DSN']
QDRANT_HOST       = os.environ.get('QDRANT_HOST', 'qdrant')
QDRANT_PORT       = int(os.environ.get('QDRANT_PORT', '6333'))
QDRANT_COLLECTION = os.environ.get('QDRANT_COLLECTION', 'knowledge_base')

_ollama_host = os.environ.get('OLLAMA_HOST', 'http://ollama:11434')
OLLAMA_HOST = _ollama_host if _ollama_host.startswith('http') else f'http://{_ollama_host}:11434'
EMBED_MODEL = 'mxbai-embed-large'
TOKENIZER_NAME    = 'nomic-ai/nomic-embed-text-v1'

DOCLING_HOST	  = os.environ.get('DOCLING_HOST', 'http://docling:5001')

MAX_TOKENS        = 400
EMBED_DIM = 1024


