# /opt/scripts/ingestion/config.py

import os

os.environ.setdefault('PG_DSN', 'postgresql://postgres:@postgres:5432/knowledge_base')

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


