#!/usr/bin/env python3
"""
observability.py — F6: Langfuse wrapper library
Location: /opt/scripts/lib/observability.py

All functions are no-ops if Langfuse keys are missing or module unavailable.
"""

import os, time
from datetime import datetime, timezone
from typing import Any, Callable

_client = None
_enabled = False

def _get_client():
    global _client, _enabled
    if _client is not None:
        return _client
    host = os.environ.get("LANGFUSE_HOST","http://langfuse:3000")
    pk   = os.environ.get("LANGFUSE_PUBLIC_KEY","")
    sk   = os.environ.get("LANGFUSE_SECRET_KEY","")
    if not pk or not sk:
        _enabled = False; return None
    try:
        from langfuse import Langfuse
        _client  = Langfuse(host=host, public_key=pk, secret_key=sk)
        _enabled = True
    except Exception:
        _enabled = False; _client = None
    return _client

def init_item_trace(daily_trace_id: str, feed_id: str, doc_id: str) -> dict:
    client = _get_client()
    if not client or not _enabled:
        return {"span_id": f"noop-{doc_id}"}
    try:
        trace     = client.trace(id=daily_trace_id, name="daily-ingestion",
                                  tags=["pipeline","ingestion"])
        feed_span = trace.span(name=f"feed:{feed_id}", input={"feed_id":feed_id})
        item_span = feed_span.span(name=f"item:{doc_id}",
                                   input={"doc_id":doc_id,"feed_id":feed_id})
        client.flush()
        return {"span_id": item_span.id}
    except Exception:
        return {"span_id": f"noop-{doc_id}"}

def trace_step(parent_trace_id: str, name: str, input_data: Any, fn: Callable) -> Any:
    client = _get_client()
    start  = time.time()
    if not client or not _enabled:
        return fn()
    span = None
    try:
        span = client.trace(id=parent_trace_id).span(
            name=name, input=str(input_data),
            start_time=datetime.now(timezone.utc))
    except Exception:
        pass
    result = None; error = None
    try:
        result = fn(); return result
    except Exception as e:
        error = str(e); raise
    finally:
        if span:
            try:
                span.end(output=str(result) if result else None,
                         level="ERROR" if error else "DEFAULT",
                         status_message=error,
                         metadata={"latency_ms": int((time.time()-start)*1000)})
                client.flush()
            except Exception:
                pass

def log_classify(parent_span_id: str, prompt: str, response: str,
                 model: str, usage: dict = None) -> None:
    client = _get_client()
    if not client or not _enabled: return
    try:
        client.trace(id=parent_span_id).generation(
            name="classify", model=model,
            input=prompt, output=response, usage=usage)
        client.flush()
    except Exception: pass

def log_embed(parent_span_id: str, chunk_count: int, latency_ms: int) -> None:
    client = _get_client()
    if not client or not _enabled: return
    try:
        client.trace(id=parent_span_id).generation(
            name="embed", model=os.environ.get("EMBED_MODEL","mxbai-embed-large"),
            input=f"{chunk_count} chunks", output=f"vectors:{chunk_count}",
            metadata={"chunk_count":chunk_count,"latency_ms":latency_ms})
        client.flush()
    except Exception: pass

def log_event(parent_span_id: str, event_name: str, metadata: dict = None) -> None:
    client = _get_client()
    if not client or not _enabled: return
    try:
        client.trace(id=parent_span_id).event(name=event_name, metadata=metadata or {})
        client.flush()
    except Exception: pass


class ItemTrace:
    def __init__(self, daily_trace_id, feed_id, doc_id, phase="live"):
        self.daily_trace_id = daily_trace_id
        self.feed_id = feed_id; self.doc_id = doc_id
        self.phase = phase; self.span_id = None

    def __enter__(self):
        self.span_id = init_item_trace(
            self.daily_trace_id, self.feed_id, self.doc_id).get("span_id")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            log_event(self.span_id, "failed",
                      {"error": str(exc_val), "doc_id": self.doc_id})
        return False

    def step(self, name, input_data, fn):
        return trace_step(self.span_id, name, input_data, fn)

    def log_classify(self, prompt, response, model, usage=None):
        log_classify(self.span_id, prompt, response, model, usage)

    def log_embed(self, chunk_count, latency_ms):
        log_embed(self.span_id, chunk_count, latency_ms)

    def event(self, event_name, metadata=None):
        log_event(self.span_id, event_name, metadata)
