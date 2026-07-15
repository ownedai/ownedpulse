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
import logging
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

# Empirically measured: first batch of 1,870 docs took 43,505s wall-clock (23.3s/doc).
# Steady-state (after ramp-up, excluding failure-heavy first hour): 17.4s/doc.
# Using 20s/doc for ETA calculations — conservative enough for mixed feeds + embedding.
SECONDS_PER_DOC = 20

# Intermediate statuses that should never persist after a run ends
_INTERMEDIATE_DOC_STATUSES = ('parsing', 'chunking', 'embedding', 'uploading', 'running')


def _resolve_stale_spans(doc_id: str, trace_id: str, reason: str):
    """After a subprocess error, mark any lingering pending/intermediate rows as failed.

    run_ingest.py sets ingestion_doc.status='pending' and ingestion_state.ingestion_status
    to intermediate values at start. If the subprocess crashes or times out, those rows
    are never finalised. This cleans them up so the document shows a terminal state.
    """
    import psycopg2
    from .trace_emitter import _pg_conn
    short_reason = reason[:500] if reason else "Subprocess did not complete"
    try:
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute(
            """UPDATE ingestion_doc SET status = 'failed', failure_reason = %s
               WHERE doc_id = %s AND trace_id::text = %s AND status = 'pending'""",
            (short_reason, doc_id, trace_id),
        )
        # GATE3b: write error state to ingestion_state
        cur.execute(
            """UPDATE ingestion_state
               SET ingestion_status = 'error', ingestion_error = %s, updated_at = NOW()
               WHERE document_id = %s AND ingestion_status = ANY(%s)""",
            (short_reason, doc_id, list(_INTERMEDIATE_DOC_STATUSES)),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # best-effort — don't mask the original error


def _subprocess_env(extra: dict = None) -> dict:
    env = os.environ.copy()
    # Explicitly forward PG credentials so subprocesses always have them,
    # even if the parent process started without docker-compose env injection.
    env.setdefault("POSTGRES_HOST", "postgres")
    env.setdefault("POSTGRES_PORT", "5432")
    env.setdefault("POSTGRES_DB", "knowledge_base")
    env.setdefault("POSTGRES_USER", "postgres")
    env.setdefault("POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))
    # Build PG_DSN from the now-guaranteed component vars.
    pg_host = env["POSTGRES_HOST"]
    pg_port = env["POSTGRES_PORT"]
    pg_user = env["POSTGRES_USER"]
    pg_pass = env["POSTGRES_PASSWORD"]
    pg_db   = env["POSTGRES_DB"]
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
    # Force HuggingFace offline — tokenizer is cached locally. Without this,
    # HybridChunker makes an outbound hub check that hangs when unreachable.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    if extra:
        env.update(extra)
    return env


def _run_one(doc_id: str, trace_id: str, phase: str = "live",
             timeout: int = 1200, redownload: str = "none",
             cancel_event=None) -> dict:
    """Run run_ingest.py for one document. Returns result dict.

    If cancel_event is set during execution, sends SIGTERM → SIGKILL to
    the subprocess and returns a cancelled error so the caller can stop cleanly.

    Stderr is written to a temp file rather than a pipe to prevent the 64 KB
    pipe buffer deadlock that occurs when the subprocess produces more progress
    output than the pipe can buffer while the parent is only polling.
    """
    import threading as _threading
    import tempfile
    cmd = [
        sys.executable, RUN_INGEST,
        "--doc-id", doc_id,
        "--run-id", trace_id,
        "--phase", phase,
        "--redownload", redownload,
    ]
    env = _subprocess_env()
    popen_timeout = timeout
    proc = None
    stderr_path = None
    try:
        stderr_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False,
            prefix=f'ingest_stderr_{doc_id[:20]}_', suffix='.log',
            dir='/tmp',
        )
        stderr_path = stderr_file.name
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=stderr_file, text=True,
            cwd=SCRIPTS_DIR, env=env,
        )
        stderr_file.close()
        # Poll with cancel check every 2s
        poll_interval = 2
        elapsed = 0
        stdout_data = ""
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                _kill_proc(proc)
                detail = "Cancelled by user"
                _resolve_stale_spans(doc_id, trace_id, detail)
                return {"status": "error", "doc_id": doc_id, "detail": detail}
            if elapsed >= popen_timeout:
                _kill_proc(proc)
                detail = f"Timeout ({popen_timeout}s)"
                _resolve_stale_spans(doc_id, trace_id, detail)
                return {"status": "error", "doc_id": doc_id, "detail": detail}
            _threading.Event().wait(min(poll_interval, popen_timeout - elapsed))
            elapsed += poll_interval
        stdout_data, _ = proc.communicate(timeout=10)
        rc = proc.returncode

        # Successful JSON output on stdout — normal completion
        if stdout_data and stdout_data.strip():
            try:
                parsed = json.loads(stdout_data.strip())
                if parsed.get("status") not in ("ok", "skipped", "not_viable"):
                    _resolve_stale_spans(doc_id, trace_id, parsed.get("detail", ""))
                return parsed
            except json.JSONDecodeError:
                pass

        # Process exited without valid JSON — diagnose the failure
        detail_parts = [f"exit_code={rc}"]
        if rc < 0:
            import signal as _signal
            sig_name = _signal.Signals(-rc).name if hasattr(_signal, 'Signals') else f"signal={-rc}"
            detail_parts.append(f"killed_by={sig_name}")

        # Get the TAIL of stderr from the temp file for error context
        err_text = ""
        if stderr_path:
            try:
                import os as _os
                with open(stderr_path, 'r', errors='replace') as fh:
                    lines = fh.readlines()
                tail_lines = lines[-10:] if len(lines) > 10 else lines
                err_text = "".join(tail_lines).strip()
                if len(err_text) > 400:
                    err_text = err_text[-400:]
            except Exception:
                pass
        if err_text:
            detail_parts.append(err_text)
        else:
            detail_parts.append("no stderr output")

        err = " | ".join(detail_parts)
        if len(err) > 500:
            err = err[:497] + "..."
        logging.warning(f"ingest subprocess exited abnormally: doc_id={doc_id} {err}")
        _resolve_stale_spans(doc_id, trace_id, err)
        return {"status": "error", "doc_id": doc_id, "detail": err}
    except Exception as e:
        if proc and proc.poll() is None:
            _kill_proc(proc)
        _resolve_stale_spans(doc_id, trace_id, str(e))
        return {"status": "error", "doc_id": doc_id, "detail": str(e)}
    finally:
        if stderr_path:
            try:
                import os as _os
                _os.unlink(stderr_path)
            except Exception:
                pass


def _kill_proc(proc):
    """Graceful → force kill a subprocess. Drains pipes after kill."""
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass
    finally:
        # Drain stdout/stderr to prevent pipe leaks
        try:
            proc.communicate(timeout=1)
        except Exception:
            pass


# -- Mode A: per-document traces (bulk / bootstrap) --------------------------

def _ingest_mode_a(docs: list, *, source: str, triggered_by: str,
                   workflow_id: str = None,
                   workflow_execution_id: str = None,
                   redownload: str = "none",
                   cancel_event=None,
                   session_id: str = None,
                   feed_source: str = None) -> list:
    """Each doc gets its own run_log row, all sharing session_id."""
    results = []
    for i, doc in enumerate(docs):
        doc_id = doc["doc_id"]
        phase = doc.get("phase", "live")

        # Per-document trace — all docs in this batch share session_id
        trace = start_ingestion_trace(
            source=source,
            triggered_by=triggered_by,
            workflow_id=workflow_id,
            workflow_execution_id=workflow_execution_id,
            doc_id=doc_id,
            session_id=session_id,
            feed_source=doc.get("feed_id") or feed_source,
        )

        ok, detail = None, None
        try:
            r = _run_one(doc_id, trace.trace_id, phase, redownload=redownload,
                         cancel_event=cancel_event)
            chunk_count = r.get("chunk_count", r.get("chunks", 0))
            status = r.get("status", "error")

            if status == "ok" and (r.get("note") or "").startswith("already ingested"):
                ok = None
                detail = r.get("note")
                trace.finalize(
                    status="skipped",
                    doc_count_attempted=1,
                    doc_count_succeeded=0,
                    doc_count_failed=0,
                )
            elif status == "ok":
                ok = True
                trace.finalize(
                    status="success",
                    doc_count_attempted=1,
                    doc_count_succeeded=1,
                    doc_count_failed=0,
                )
            elif status == "skipped":
                ok = None
                detail = r.get("detail")
                trace.finalize(
                    status="skipped",
                    doc_count_attempted=1,
                    doc_count_succeeded=0,
                    doc_count_failed=0,
                )
            elif status == "not_viable":
                ok = None
                detail = r.get("gate_reason") or r.get("detail", "")
                trace.finalize(
                    status="skipped",
                    doc_count_attempted=1,
                    doc_count_succeeded=0,
                    doc_count_failed=0,
                    error_summary=detail,
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
            "status": "ok" if ok is True else ("skipped" if ok is None else "error"),
            "trace_id": trace.trace_id,
            "chunk_count": chunk_count if ok is True else 0,
            "detail": detail,
        })

    return results


# -- Mode B: one run_log wrapping all docs (batch / n8n_rss) -----------------

def _ingest_mode_b(docs: list, *, source: str, triggered_by: str,
                   workflow_id: str = None,
                   workflow_execution_id: str = None,
                   redownload: str = "none",
                   cancel_event=None,
                   session_id: str = None,
                   feed_source: str = None) -> dict:
    """One run_log row wraps all documents in the batch."""
    # Collect unique feed_ids from all docs for the run_log trace
    feed_ids = {d.get("feed_id") for d in docs if d.get("feed_id")}
    fs = feed_source or (",".join(sorted(feed_ids)) if feed_ids else None)
    trace = start_ingestion_trace(
        source=source,
        triggered_by=triggered_by,
        workflow_id=workflow_id,
        workflow_execution_id=workflow_execution_id,
        session_id=session_id,
        feed_source=fs,
    )

    results = []
    succeeded = 0
    failed = 0

    for doc in docs:
        doc_id = doc["doc_id"]
        phase = doc.get("phase", "live")

        ok, detail = None, None
        try:
            r = _run_one(doc_id, trace.trace_id, phase, redownload=redownload,
                         cancel_event=cancel_event)
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
                     redownload: str = "none",
                     cancel_event=None,
                     session_id: str = None,
                     feed_source: str = None) -> dict:
    """Unified ingestion entry point — all paths route through here.

    Args:
        docs: List of dicts, each with 'doc_id' (required) and optional 'phase'.
        source: 'n8n_rss', 'manual_cli', or 'bootstrap_ui'.
        triggered_by: Human or system identifier (e.g. 'n8n-scheduler', 'zoran').
        workflow_id: n8n workflow ID (nullable, Mode B only).
        workflow_execution_id: n8n execution ID (nullable, Mode B only).
        bulk: Force Mode A (per-document traces). Auto-set for 'bootstrap_ui'.
        session_id: Groups all docs in this call into one ingestion run (nullable).
        cancel_event: threading.Event — set to cancel running subprocess.

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
            cancel_event=cancel_event,
            session_id=session_id,
            feed_source=feed_source,
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
            cancel_event=cancel_event,
            feed_source=feed_source,
            session_id=session_id,
        )
