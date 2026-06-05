"""Shared in-process lock that prevents concurrent ingestion runs.

Both the bootstrap worker (threading) and the RSS scheduler job (asyncio)
acquire this lock before doing any work. Trigger endpoints check it first
and return 409 if another ingestion is already active.
"""

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_state: dict = {
    "active": False,
    "kind": None,    # "bootstrap" | "rss"
    "detail": None,  # session_id or feed_id
    "started_at": None,
}


def acquire(kind: str, detail: str) -> bool:
    """Try to acquire the ingestion lock. Returns True if acquired, False if already held."""
    with _lock:
        if _state["active"]:
            return False
        _state["active"] = True
        _state["kind"] = kind
        _state["detail"] = detail
        _state["started_at"] = datetime.now(timezone.utc).isoformat()
        return True


def release() -> None:
    with _lock:
        _state["active"] = False
        _state["kind"] = None
        _state["detail"] = None
        _state["started_at"] = None


def state() -> dict:
    """Return a snapshot of current lock state (safe to call from any thread)."""
    with _lock:
        return dict(_state)


def conflict_detail() -> str:
    """Human-readable reason string for 409 responses."""
    with _lock:
        if not _state["active"]:
            return "No ingestion running"
        return (
            f"{_state['kind']} ingestion already running "
            f"(detail={_state['detail']!r}, started={_state['started_at']})"
        )
