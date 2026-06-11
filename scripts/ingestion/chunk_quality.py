"""
chunk_quality.py

Shared chunk quality assessment utilities.
Used by: run_ingest.py (post-chunking gate), corpus_quality_check.py (audit).

Version: 1.0
"""

# Thresholds — single source of truth
BAD_CHUNK_RATE_THRESHOLD = 40.0   # percent — gate triggers if bad rate exceeds this
MIN_CHUNK_COUNT          = 3      # gate triggers if chunk count below this
BAD_CHUNK_PCT_FLAG       = 20.0   # for audit: flag document if >20% bad (not_viable gate)


def is_line_number_artefact(text: str) -> bool:
    """True if chunk is a pure sequence of line numbers (e.g. '111\n112\n113')."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    numeric_lines = sum(1 for l in lines if l.isnumeric())
    return len(text) < 200 and (numeric_lines / len(lines)) > 0.6


def is_header_only(text: str) -> bool:
    """True if chunk is just a short document header with no substantive content."""
    header_markers = [
        "EMA/", "CVMP/", "CHMP/", "EMA CVMP", "Committee for",
        "European Medicines", "U.S. Department", "Guidance for Industry",
        "December 20", "January 20", "February 20",
    ]
    if len(text) > 150:
        return False
    return any(marker in text for marker in header_markers)


def assess_chunk(chunk_text: str) -> dict:
    """Assess a single chunk. Returns dict of flags and ok status."""
    text = chunk_text.strip() if chunk_text else ""
    flags = {
        "empty":                len(text) == 0,
        "too_short":            0 < len(text) < 50,
        "numeric_only":         len(text) > 0 and text.replace("\n","").replace(" ","").isnumeric(),
        "line_number_artefact": is_line_number_artefact(text),
        "header_only":          is_header_only(text),
    }
    flags["ok"] = not any(flags.values())
    return flags


def evaluate_chunk_quality(chunks: list) -> dict:
    """
    Evaluate quality of a document's chunk list.

    Args:
        chunks: list of chunk dicts, each with a 'text' key (or 'chunk_text').
                Accepts either key name.

    Returns:
        {
            "total": int,
            "bad": int,
            "bad_pct": float,
            "by_flag": dict,
            "gate_pass": bool,
            "gate_reason": str or None,   # None if gate passes
        }
    """
    total = len(chunks)
    bad = 0
    by_flag = {}

    for chunk in chunks:
        # Handle both dict-style chunks (HTML path) and DocChunk objects (PDF/Docling path)
        if isinstance(chunk, dict):
            text = chunk.get("text") or chunk.get("chunk_text") or ""
        else:
            text = getattr(chunk, "text", "") or ""
        result = assess_chunk(text)
        if not result["ok"]:
            bad += 1
            for flag, val in result.items():
                if val and flag != "ok":
                    by_flag[flag] = by_flag.get(flag, 0) + 1

    bad_pct = round((bad / total * 100) if total > 0 else 0.0, 1)

    reasons = []
    if total < MIN_CHUNK_COUNT:
        reasons.append(f"chunk_count={total} (minimum {MIN_CHUNK_COUNT})")
    if bad_pct > BAD_CHUNK_RATE_THRESHOLD:
        reasons.append(f"bad_chunk_rate={bad_pct}% (threshold {BAD_CHUNK_RATE_THRESHOLD}%)")

    gate_pass = len(reasons) == 0
    gate_reason = "Quality gate failed: " + ", ".join(reasons) if reasons else None

    return {
        "total":       total,
        "bad":         bad,
        "bad_pct":     bad_pct,
        "by_flag":     by_flag,
        "gate_pass":   gate_pass,
        "gate_reason": gate_reason,
    }
