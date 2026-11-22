"""D1: the PDF prints 1-based pages (chunk page_no is 0-based), for cited and uncited chunks.

Offline. Uses the recorded OQ-03 run 1 response; the citations are replaced by three chunks:
a cited chunk with page_no 0, an uncited chunk with page_no 3, and a cited chunk with page_no None.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.pdf_export import _display_page, generate_query_export_pdf  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
pdftotext = shutil.which("pdftotext")
pytestmark = pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")


@pytest.mark.parametrize("raw,shown", [(0, "1"), (3, "4"), (None, "—"), ("0", "1"), ("", "—")])
def test_display_page(raw, shown):
    assert _display_page(raw) == shown


def _response():
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        resp = json.load(f)
    with open(os.path.join(FIX, "oq03_run1_answer.json"), encoding="utf-8") as f:
        resp["answer"] = json.load(f)["answer"]
    base = resp["citations"][0]
    cited0 = copy.deepcopy(base); cited0.update({"index": 1, "cited_by_llm": True, "page_no": 0, "document_id": "PAGE-ZERO-DOC", "document_title": "PAGE-ZERO-CITED"})
    unc3 = copy.deepcopy(base); unc3.update({"index": 2, "cited_by_llm": False, "page_no": 3, "document_id": "PAGE-THREE-DOC", "document_title": "PAGE-THREE-UNCITED"})
    cnone = copy.deepcopy(base); cnone.update({"index": 3, "cited_by_llm": True, "page_no": None, "document_id": "PAGE-NONE-DOC", "document_title": "PAGE-NONE-CITED"})
    resp["citations"] = [cited0, unc3, cnone]
    return resp


@pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")
def test_pdf_prints_one_based_pages_for_cited_and_uncited():
    """The value sits directly below its "Page" label (same x, about 12 pt lower)."""
    import re
    pdf = generate_query_export_pdf(_response())
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(pdf)
        bbox = subprocess.run([pdftotext, "-bbox", tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)
    words = [(float(a), float(b), w) for a, b, w in re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>', bbox)]
    values = []
    for page_xml in bbox.split("<page ")[1:]:
        words = [(float(a), float(b), w) for a, b, w in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>', page_xml)]
        for x, y, w in words:
            if w != "Page":
                continue
            below = [v for (vx, vy, v) in words if abs(vx - x) < 1.5 and 8 <= (vy - y) <= 20]
            if below:
                values.append(below[0])
    assert "1" in values, "cited page_no 0 should print 1: %r" % values
    assert "4" in values, "uncited page_no 3 should print 4: %r" % values
    assert "—" in values, "page_no None should print a dash: %r" % values
