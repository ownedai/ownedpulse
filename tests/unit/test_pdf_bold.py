"""D3: **bold** in answer text renders as bold, with no asterisks, in the query export and the audit log.

Offline. Uses the recorded OQ-03 run 1 response; the answer is replaced by a fixed sentence with a bold span and a marker.
Skipped when pdftotext is not installed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.pdf_export import generate_audit_log_pdf, generate_query_export_pdf  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
pdftotext = shutil.which("pdftotext")
pytestmark = pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")

ANSWER = "**Creation of Audit Trails:** text [12]."


def _response():
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        resp = json.load(f)
    resp["answer"] = ANSWER
    return resp


def _text(pdf):
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(pdf)
        return subprocess.run([pdftotext, tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)


def test_query_export_renders_bold_without_asterisks():
    text = _text(generate_query_export_pdf(_response()))
    assert "**" not in text
    assert "Creation of Audit Trails:" in text
    assert "[12]" in text


def test_audit_log_renders_bold_without_asterisks():
    q = _response()
    text = _text(generate_audit_log_pdf(queries=[q], filters_applied={}, corpus_date="-", system_version="test"))
    assert "**" not in text
    assert "Creation of Audit Trails:" in text
    assert "[12]" in text
