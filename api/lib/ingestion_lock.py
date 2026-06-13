"""Shared in-process lock that prevents concurrent ingestion runs.

Both the bootstrap worker (threading) and the ingestion scheduler job (asyncio)
acquire this lock before doing any work. Trigger endpoints check it first
and return 409 if another ingestion is already active.

The lock auto-expires after LOCK_TIMEOUT_MINUTES to prevent permanent stalls
from crashed or abandoned background tasks.
"""

import threading
from datetime import datetime, timezone, timedelta

_lock = threading.Lock()
_state: dict = {
    "active": False,
    "kind": None,    # "bootstrap" | "rss"
    "detail": None,  # session_id or feed_id
    "started_at": None,
}

LOCK_TIMEOUT_MINUTES = 120  # auto-release after 2 hours


def _is_expired() -> bool:
    if not _state["active"] or not _state["started_at"]:
        return False
    try:
        started = datetime.fromisoformat(_state["started_at"])
        return datetime.now(timezone.utc) - started > timedelta(minutes=LOCK_TIMEOUT_MINUTES)
    except (ValueError, TypeError):
        return True  # corrupt timestamp — treat as expired


def acquire(kind: str, detail: str) -> bool:
    """Try to acquire the ingestion lock. Returns True if acquired, False if already held."""
    with _lock:
        if _state["active"] and not _is_expired():
            return False
        # Auto-release expired lock and re-acquire
        if _state["active"]:
            _state["active"] = False
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
        if _state["active"] and _is_expired():
            _state["active"] = False
            _state["kind"] = None
            _state["detail"] = None
            _state["started_at"] = None
        return dict(_state)


def conflict_detail() -> str:
    """Human-readable reason string for 409 responses."""
    with _lock:
        if _state["active"] and _is_expired():
            _state["active"] = False
            _state["kind"] = None
            _state["detail"] = None
            _state["started_at"] = None
        if not _state["active"]:
            return "No ingestion running"
        return (
            f"{_state['kind']} ingestion already running "
            f"(detail={_state['detail']!r}, started={_state['started_at']})"
        )
