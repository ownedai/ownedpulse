"""D4: the chunk date is labelled "Chunked" (it is the chunk creation date), not "Ingested".

Offline. Uses the recorded OQ-03 run 1 response with chunked_at set; checks the cited and the uncited card.
"""
import copy
import json
import re
import os
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


def _response():
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        resp = json.load(f)
    with open(os.path.join(FIX, "oq03_run1_answer.json"), encoding="utf-8") as f:
        resp["answer"] = json.load(f)["answer"]
    base = resp["citations"][0]
    cited = copy.deepcopy(base); cited.update({"index": 1, "cited_by_llm": True, "document_id": "CHUNK-CITED-DOC", "chunked_at": "2026-11-18T12:43:35.713811+00:00"})
    unc = copy.deepcopy(base); unc.update({"index": 2, "cited_by_llm": False, "document_id": "CHUNK-UNCITED-DOC", "chunked_at": "2026-11-17T09:01:00+00:00"})
    resp["citations"] = [cited, unc]
    return resp


def _bbox_words(pdf):
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(pdf)
        out = subprocess.run([pdftotext, "-bbox", tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)
    pages = []
    for page_xml in out.split("<page ")[1:]:
        pages.append([(float(a), float(b), w) for a, b, w in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)</word>', page_xml)])
    return pages


def _label_then_date(words, date):
    """True when the word 'Chunked' sits on the same line as the date, to its right."""
    for x, y, w in words:
        if w != "Chunked":
            continue
        if any(v == date and abs(vy - y) < 0.5 and vx > x for vx, vy, v in words):
            return True
    return False


def test_chunk_date_is_labelled_chunked_and_not_ingested():
    pdf = generate_query_export_pdf(_response())
    pages = _bbox_words(pdf)
    all_words = [w for page in pages for w in page]
    assert "Ingested" not in [w for _, _, w in all_words]
    assert any(_label_then_date(page, "2026-11-18") for page in pages), "cited card: Chunked + date not on one line"
    assert any(_label_then_date(page, "2026-11-17") for page in pages), "uncited card: Chunked + date not on one line"
