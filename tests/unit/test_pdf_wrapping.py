"""PDF export wrapping: long titles, URLs, file paths and IDs are printed in full.

Offline. Uses the recorded OQ-03 run 1 response (tests/fixtures/oq03_run1_response.json)
with its first citation replaced by long values. The extracted PDF text, with all
whitespace removed, must contain each full value, and no ellipsis may be added.
Skipped when pdftotext is not installed (same as test_citation_markers.py).
"""
import copy
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

from lib.pdf_export import generate_query_export_pdf  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
pdftotext = shutil.which("pdftotext")
pytestmark = pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")

LONG_TITLE = ("Draft reflection paper on the clinical investigation of medicinal products "
              "for the treatment of systemic sclerosis")
LONG_URL = ("https://www.ema.europa.eu/en/documents/scientific-guideline/"
            "draft-reflection-paper-clinical-investigation-medicinal-products-"
            "treatment-systemic-sclerosis_en.pdf")
LONG_PATH = ("/archive/ema/ema_sci_guidelines-draft-reflection-paper-clinical-"
             "investigation-75f898ea659e/source.pdf")
LONG_ID = "ema_sci_guidelines-draft-reflection-paper-clinical-investig-75f898ea659e"


def _response(cited_by_llm, metadata=False):
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        resp = json.load(f)
    with open(os.path.join(FIX, "oq03_run1_answer.json"), encoding="utf-8") as f:
        resp["answer"] = json.load(f)["answer"]
    chunk = copy.deepcopy(resp["citations"][0])
    chunk.update({
        "document_id": LONG_ID,
        "document_title": LONG_TITLE,
        "source_url": LONG_URL,
        "source_local_path": LONG_PATH,
        "cited_by_llm": cited_by_llm,
        "index": 1,
    })
    resp["citations"] = [chunk]
    if metadata:
        resp["routing_path"] = "METADATA"
    return resp


def _pdf_bytes(resp):
    return generate_query_export_pdf(resp)


def _pdf_text(pdf):
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(pdf)
        return subprocess.run([pdftotext, tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)


def _squash(s):
    return re.sub(r"\s+", "", s)


def _assert_printed(text, values):
    squashed = _squash(text)
    for value in values:
        assert _squash(value) in squashed, "not printed in full: %r" % value[:60]
    assert "…" not in text, "ellipsis still present in export text"


def test_cited_card_prints_long_title_url_and_path_in_full():
    _assert_printed(_pdf_text(_pdf_bytes(_response(True))), [LONG_TITLE, LONG_URL, LONG_PATH])


def test_uncited_card_prints_long_title_url_and_path_in_full():
    _assert_printed(_pdf_text(_pdf_bytes(_response(False))), [LONG_TITLE, LONG_URL, LONG_PATH])


def test_metadata_card_prints_long_id_in_full_and_stays_on_page():
    """The 72-character document ID wraps in its table cell; no word runs past the 612 pt page."""
    pdf = _pdf_bytes(_response(True, metadata=True))
    _assert_printed(_pdf_text(pdf), [LONG_ID])
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(pdf)
        out = subprocess.run([pdftotext, "-bbox", tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)
    xs = [float(m) for m in re.findall(r'xMax="([0-9.]+)"', out)]
    assert xs, "no words found in bbox output"
    assert max(xs) <= 612.0 - 30.0, "text runs to x=%.1f (page is 612 pt wide)" % max(xs)
