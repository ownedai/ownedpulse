"""
Unified ingestion entry point — single contract for all ingestion paths.

Three-level trace: run_log (trace) → ingestion_doc (document span) → Qdrant chunks.

Two modes:
  Mode A (bulk/bootstrap_ui, 1000+ docs):
      Per-document run_log rows. No shared run envelope.
      Each doc = its own run_log + ingestion_doc span.
      Called when source='bootstrap_ui' or bulk=True.

  Mode B (batch/n8n_rss/single doc):
      One run_log row wrapping all documents in the batch.
      Each doc gets an ingestion_doc span within that run.
      Called when source='n8n_rss' or single doc without bulk flag.

This module only handles trace lifecycle + per-doc subprocess dispatch.
Actual ingestion (parsing, chunking, embedding, upsert) runs in
run_ingest.py subprocesses for per-document error isolation.

Usage:
    from api.lib.ingest_documents import ingest_documents

    results = ingest_documents(
        docs=[{"doc_id": "FDA-123", "phase": "live"}],
        source="n8n_rss",
        triggered_by="n8n-scheduler",
    )
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Optional

from .trace_emitter import (
    start_ingestion_trace,
    start_document_span,
    IngestionTrace,
    DocumentSpan,
)

SCRIPTS_DIR = "/opt/scripts"
RUN_INGEST = f"{SCRIPTS_DIR}/ingestion/run_ingest.py"


def _subprocess_env(extra: dict = None) -> dict:
    env = os.environ.copy()
    # Build PG_DSN from component vars already set correctly in the container env.
    # Do NOT fall back to localhost — that breaks subprocesses launched from Docker.
    pg_host = env.get("POSTGRES_HOST", "postgres")
    pg_port = env.get("POSTGRES_PORT", "5432")
    pg_user = env.get("POSTGRES_USER", "postgres")
    pg_pass = env.get("POSTGRES_PASSWORD", "")
    pg_db   = env.get("POSTGRES_DB", "knowledge_base")
    env.setdefault("PG_DSN", f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}")
    env.setdefault("QDRANT_HOST", env.get("QDRANT_HOST", "qdrant"))
    env.setdefault("QDRANT_PORT", env.get("QDRANT_PORT", "6333"))
    env.setdefault("QDRANT_URL", f"http://{env['QDRANT_HOST']}:{env['QDRANT_PORT']}")
    olla_host = env.get("OLLAMA_HOST", "ollama")
    if not olla_host.startswith("http"):
        olla_host = f"http://{olla_host}:{env.get('OLLAMA_PORT', '11434')}"
    env["OLLAMA_HOST"] = olla_host
    env.setdefault("OLLAMA_URL", olla_host)
    env.setdefault("DOCLING_HOST", env.get("DOCLING_HOST", "http://docling:5001"))
    if not env.get("ARCHIVE_ROOT"):
        env["ARCHIVE_ROOT"] = "/archive"
    if extra:
        env.update(extra)
    return env


def _run_one(doc_id: str, trace_id: str, phase: str = "live",
             timeout: int = 600, redownload: str = "none") -> dict:
    """Run run_ingest.py for one document. Returns result dict."""
    cmd = [
        sys.executable, RUN_INGEST,
        "--doc-id", doc_id,
        "--run-id", trace_id,
        "--phase", phase,
        "--redownload", redownload,
    ]
    env = _subprocess_env()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=SCRIPTS_DIR, env=env,
        )
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                pass
        err = result.stderr.strip() or "Unknown error"
        if len(err) > 500:
            err = err[:500] + "..."
        return {"status": "error", "doc_id": doc_id, "detail": err}
    except subprocess.TimeoutExpired:
        return {"status": "error", "doc_id": doc_id, "detail": f"Timeout ({timeout}s)"}
    except Exception as e:
        return {"status": "error", "doc_id": doc_id, "detail": str(e)}


# -- Mode A: per-document traces (bulk / bootstrap) --------------------------

def _ingest_mode_a(docs: list, *, source: str, triggered_by: str,
                   workflow_id: str = None,
                   workflow_execution_id: str = None,
                   redownload: str = "none") -> list:
    """Each doc gets its own run_log row. No shared run envelope."""
    results = []
    for i, doc in enumerate(docs):
        doc_id = doc["doc_id"]
        phase = doc.get("phase", "live")

        # Per-document trace
        trace = start_ingestion_trace(
            source=source,
            triggered_by=triggered_by,
            workflow_id=workflow_id,
            workflow_execution_id=workflow_execution_id,
        )

        ok, detail = None, None
        try:
            r = _run_one(doc_id, trace.trace_id, phase, redownload=redownload)
            chunk_count = r.get("chunk_count", r.get("chunks", 0))
            status = r.get("status", "error")

            if status == "ok":
                ok = True
                trace.finalize(
                    status="success",
                    doc_count_attempted=1,
                    doc_count_succeeded=1,
                    doc_count_failed=0,
                )
            else:
                ok = False
                detail = r.get("detail", "unknown error")
                trace.finalize(
                    status="error",
                    doc_count_attempted=1,
                    doc_count_succeeded=0,
                    doc_count_failed=1,
                    error_summary=detail,
                )
        except Exception as e:
            ok = False
            detail = str(e)
            try:
                trace.finalize(
                    status="error",
                    doc_count_attempted=1,
                    doc_count_succeeded=0,
                    doc_count_failed=1,
                    error_summary=detail,
                )
            except Exception:
                pass

        results.append({
            "doc_id": doc_id,
            "status": "ok" if ok else "error",
            "trace_id": trace.trace_id,
            "chunk_count": chunk_count if ok else 0,
            "detail": detail,
        })

    return results


# -- Mode B: one run_log wrapping all docs (batch / n8n_rss) -----------------

def _ingest_mode_b(docs: list, *, source: str, triggered_by: str,
                   workflow_id: str = None,
                   workflow_execution_id: str = None,
                   redownload: str = "none") -> dict:
    """One run_log row wraps all documents in the batch."""
    trace = start_ingestion_trace(
        source=source,
        triggered_by=triggered_by,
        workflow_id=workflow_id,
        workflow_execution_id=workflow_execution_id,
    )

    results = []
    succeeded = 0
    failed = 0

    for doc in docs:
        doc_id = doc["doc_id"]
        phase = doc.get("phase", "live")

        ok, detail = None, None
        try:
            r = _run_one(doc_id, trace.trace_id, phase, redownload=redownload)
            chunk_count = r.get("chunk_count", r.get("chunks", 0))
            status = r.get("status", "error")

            if status == "ok":
                ok = True
                succeeded += 1
            else:
                ok = False
                detail = r.get("detail", "unknown error")
                failed += 1
        except Exception as e:
            ok = False
            detail = str(e)
            failed += 1

        results.append({
            "doc_id": doc_id,
            "status": "ok" if ok else "error",
            "trace_id": trace.trace_id,
            "chunk_count": chunk_count if ok else 0,
            "detail": detail,
        })

    run_status = "success" if failed == 0 else ("partial" if succeeded > 0 else "error")
    trace.finalize(
        status=run_status,
        doc_count_attempted=len(docs),
        doc_count_succeeded=succeeded,
        doc_count_failed=failed,
    )

    return {
        "run_id": trace.trace_id,
        "status": run_status,
        "doc_count_attempted": len(docs),
        "doc_count_succeeded": succeeded,
        "doc_count_failed": failed,
        "results": results,
    }


# -- Public API --------------------------------------------------------------

def ingest_documents(docs: list, *, source: str, triggered_by: str,
                     workflow_id: str = None,
                     workflow_execution_id: str = None,
                     bulk: bool = False,
                     redownload: str = "none") -> dict:
    """Unified ingestion entry point — all paths route through here.

    Args:
        docs: List of dicts, each with 'doc_id' (required) and optional 'phase'.
        source: 'n8n_rss', 'manual_cli', or 'bootstrap_ui'.
        triggered_by: Human or system identifier (e.g. 'n8n-scheduler', 'zoran').
        workflow_id: n8n workflow ID (nullable, Mode B only).
        workflow_execution_id: n8n execution ID (nullable, Mode B only).
        bulk: Force Mode A (per-document traces). Auto-set for 'bootstrap_ui'.

    Returns:
        dict with either per-doc results (Mode A) or run-level summary (Mode B).
    """
    if not docs:
        return {"status": "ok", "doc_count_attempted": 0, "results": []}

    is_mode_a = bulk or source == "bootstrap_ui"

    if is_mode_a:
        per_doc_results = _ingest_mode_a(
            docs,
            source=source,
            triggered_by=triggered_by,
            workflow_id=workflow_id,
            workflow_execution_id=workflow_execution_id,
            redownload=redownload,
        )
        return {
            "mode": "A",
            "source": source,
            "doc_count_attempted": len(docs),
            "doc_count_succeeded": sum(1 for r in per_doc_results if r["status"] == "ok"),
            "doc_count_failed": sum(1 for r in per_doc_results if r["status"] == "error"),
            "results": per_doc_results,
        }
    else:
        return _ingest_mode_b(
            docs,
            source=source,
            triggered_by=triggered_by,
            workflow_id=workflow_id,
            workflow_execution_id=workflow_execution_id,
            redownload=redownload,
        )
