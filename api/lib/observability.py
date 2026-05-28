"""Langfuse observability — single shared client for the query pipeline."""

import os

# Raise the per-event size cap before the SDK reads it at import time.
# Default is 1 MB which truncates large prompts with full regulatory context.
os.environ.setdefault("LANGFUSE_MAX_EVENT_SIZE_BYTES", "10000000")   # 10 MB
os.environ.setdefault("LANGFUSE_MAX_BATCH_SIZE_BYTES", "25000000")   # 25 MB

import langfuse


def get_langfuse():
    """Return a Langfuse client if configured, else None."""
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "")
    if not pk or not sk or not host:
        return None
    return langfuse.Langfuse(public_key=pk, secret_key=sk, host=host)
