"""Langfuse observability — single shared client for the query pipeline."""

import os
import langfuse


def get_langfuse():
    """Return a Langfuse client if configured, else None."""
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "")
    if not pk or not sk or not host:
        return None
    return langfuse.Langfuse(public_key=pk, secret_key=sk, host=host)
