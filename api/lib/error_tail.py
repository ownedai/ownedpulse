"""Tail of a subprocess's stderr, for the run_log error_detail column."""

TAIL_CHARS = 2000


def tail_text(data: bytes, limit: int = TAIL_CHARS) -> str:
    """Return the last `limit` characters of stderr. The end is kept because the
    pipeline's failure line is printed last, after any earlier log lines."""
    return data.decode(errors="replace")[-limit:]
