"""Audit-log PDF (history export) numbers cited sources with their original index (K14 equivalent).

Offline. Uses the recorded OQ-03 run 1 answer and its citations (fixture). Skipped if pdftotext
is not installed.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))
FIX = os.path.join(ROOT, "tests", "fixtures")
pdftotext = shutil.which("pdftotext")
pytestmark = pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")


def _text():
    from lib.pdf_export import generate_audit_log_pdf
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        r = json.load(f)
    query = {
        "query_id": r["query_id"], "query_text": "How do EU GMP Annex 11 and 21 CFR Part 11 differ?",
        "timestamp": r.get("timestamp") or "2026-11-19T00:00:00+00:00", "routing_path": "CONTENT",
        "prompt_version": "v11", "answer": r["answer"], "citations": r["citations"], "langfuse_trace_id": "",
    }
    pdf = generate_audit_log_pdf(queries=[query], filters_applied={}, corpus_date="-", system_version="test")
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), "audit_test_%d.pdf" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(pdf)
    try:
        return subprocess.run([pdftotext, "-layout", tmp, "-"], capture_output=True, text=True, check=True).stdout, r
    finally:
        os.remove(tmp)


def test_cited_source_numbers_are_original_indices():
    text, r = _text()
    cited = sorted(c["index"] for c in r["citations"] if c.get("cited_by_llm"))
    assert cited == [6, 16, 23, 33, 34], "instrument: recorded cited indices changed"
    section = text[text.find("CITED SOURCES"):]
    numbers = sorted(int(m) for m in re.findall(r"(?m)^\s*\[(\d+)\]\s", section))
    assert numbers == cited, "source numbers in audit PDF %s != JSON cited indices %s" % (numbers, cited)


def test_answer_markers_match_the_listed_sources():
    text, r = _text()
    answer_markers = sorted(set(int(m) for m in re.findall(r"\[(\d+)\]", r["answer"])))
    assert set(answer_markers) <= {c["index"] for c in r["citations"]}, "instrument: answer markers"
    section = text[text.find("CITED SOURCES"):]
    listed = set(int(m) for m in re.findall(r"(?m)^\s*\[(\d+)\]\s", section))
    assert set(answer_markers) & {6, 16, 23, 33, 34} <= listed
