"""
Canonical ingestion trace emitter — single contract for all ingestion paths.

Three-level trace: run_log (trace) → ingestion_doc (document span) → Qdrant chunk payload.

Usage:
    from api.lib.trace_emitter import start_ingestion_trace, start_document_span

    trace = start_ingestion_trace(
        source="n8n_rss", triggered_by="n8n-scheduler",
        workflow_id="wf-123", workflow_execution_id="exec-456",
    )
    # trace.trace_id is the run_log.run_id UUID — stamp on every chunk

    for doc in documents:
        span = start_document_span(trace.trace_id, doc_id=doc.id, source_url=doc.url)
        # ... ingest chunks, stamp trace.trace_id on each ...
        span.finalize(status="success", chunk_count=42)

    trace.finalize(
        status="success",
        doc_count_attempted=10, doc_count_succeeded=9, doc_count_failed=1,
    )
"""
import os
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


def _pg_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "knowledge_base"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        connect_timeout=10,
    )


# -- Trace-level ----------------------------------------------------------

@dataclass
class IngestionTrace:
    trace_id: str
    source: str
    triggered_by: str
    workflow_id: Optional[str]
    workflow_execution_id: Optional[str]
    _started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def finalize(self, *, status: str,
                 doc_count_attempted: int = 0,
                 doc_count_succeeded: int = 0,
                 doc_count_failed: int = 0,
                 error_summary: Optional[str] = None):
        conn = _pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE run_log SET
                    status = %s,
                    completed_at = NOW(),
                    items_fetched = %s,
                    items_new = %s,
                    error_count = %s,
                    error_detail = %s
                WHERE run_id = %s
            """, (status, doc_count_attempted, doc_count_succeeded,
                  doc_count_failed, error_summary, self.trace_id))
            conn.commit()
            cur.close()
        finally:
            conn.close()


def start_ingestion_trace(*, source: str, triggered_by: str,
                          workflow_id: Optional[str] = None,
                          workflow_execution_id: Optional[str] = None,
                          doc_id: Optional[str] = None,
                          session_id: Optional[str] = None) -> IngestionTrace:
    """Create a run_log row and return an IngestionTrace handle.

    Args:
        source: One of 'n8n_rss', 'manual_cli', 'bootstrap_ui'.
        triggered_by: Human or system identifier (e.g. 'n8n-scheduler', 'zoran').
        workflow_id: n8n workflow ID (nullable).
        workflow_execution_id: n8n execution ID (nullable).
        doc_id: document_registry.document_id for per-document traces (nullable).
        session_id: Ingestion run group ID — shared by all docs in one run (nullable).

    Returns:
        IngestionTrace with .trace_id (UUID str) to stamp on every chunk.
    """
    trace_id = str(uuid.uuid4())
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO run_log (run_id, trigger_source, triggered_by,
                                 workflow_id, n8n_execution_id, doc_id, status,
                                 session_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'running', %s::uuid)
        """, (trace_id, source, triggered_by, workflow_id, workflow_execution_id, doc_id,
              session_id))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return IngestionTrace(
        trace_id=trace_id,
        source=source,
        triggered_by=triggered_by,
        workflow_id=workflow_id,
        workflow_execution_id=workflow_execution_id,
    )


# -- Document-span level -------------------------------------------------

@dataclass
class DocumentSpan:
    span_id: str
    trace_id: str
    doc_id: str
    _fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def finalize(self, *, status: str, chunk_count: int = 0,
                 embedding_model: str = "",
                 failure_reason: Optional[str] = None):
        conn = _pg_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ingestion_doc SET
                    status = %s,
                    chunk_count = %s,
                    embedding_model = %s,
                    failure_reason = %s,
                    parsed_at = NOW()
                WHERE span_id = %s
            """, (status, chunk_count, embedding_model, failure_reason, self.span_id))
            conn.commit()
            cur.close()
        finally:
            conn.close()


def start_document_span(trace_id: str, *, doc_id: str,
                        source_url: str = "") -> DocumentSpan:
    """Create or reset an ingestion_doc row and return a DocumentSpan handle.

    One row per document — upserted in place. No history accumulation.
    For public regulatory documents, current state is all that matters.
    (SOPs in Project 2 will use a separate audit trail mechanism.)

    Args:
        trace_id: The ingestion trace (run_log.run_id) this document belongs to.
        doc_id: document_registry.document_id for this document.
        source_url: Original source URL of the document.

    Returns:
        DocumentSpan with .span_id (UUID str) for per-document lifecycle tracking.
    """
    span_id = str(uuid.uuid4())
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ingestion_doc (span_id, trace_id, doc_id, source_url,
                                       fetched_at, status, chunk_count,
                                       failure_reason, created_at)
            VALUES (%s, %s, %s, %s, NOW(), 'pending', 0, NULL, NOW())
            ON CONFLICT (doc_id) DO UPDATE SET
                span_id        = EXCLUDED.span_id,
                trace_id       = EXCLUDED.trace_id,
                source_url     = COALESCE(EXCLUDED.source_url, ingestion_doc.source_url),
                fetched_at     = NOW(),
                status         = 'pending',
                chunk_count    = 0,
                failure_reason = NULL,
                created_at     = ingestion_doc.created_at
        """, (span_id, trace_id, doc_id, source_url or None))
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return DocumentSpan(span_id=span_id, trace_id=trace_id, doc_id=doc_id)
