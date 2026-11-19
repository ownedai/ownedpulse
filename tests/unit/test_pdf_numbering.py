"""K14: PDF export uses the same source numbers as the JSON export.

Offline. Uses a recorded answer (OQ-03 run 1) and the pdftotext tool. Skipped if
pdftotext is not installed.

Checks:
  1. The [N] markers in the PDF answer text equal the markers in the JSON answer
     (no renumbering).
  2. Each source card in the PDF is labelled with the original citation index, and
     its title matches the JSON citation with that index.

Limit: the PDF does not print chunk_id, so the mapping is checked by index plus
document title, not by chunk_id.
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

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "oq03_run1_response.json")

pdftotext = shutil.which("pdftotext")
pytestmark = pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")


def _pdf_text(response):
    from lib.pdf_export import generate_query_export_pdf
    pdf = generate_query_export_pdf(response)
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), "k14_test_%d.pdf" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(pdf)
    try:
        return subprocess.run([pdftotext, "-layout", tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)


def _answer_section(text):
    """Everything before the source-evidence section (the answer is printed there)."""
    end = text.find("SOURCE EVIDENCE")
    return text[:end] if end > 0 else text


def _cards(text):
    """(number, title) for each source card in the SOURCE EVIDENCE section."""
    start = text.find("SOURCE EVIDENCE")
    end = text.find("RETRIEVED BUT NOT CITED")
    section = text[start:end if end > start else None]
    return [(int(m.group(1)), m.group(2).strip())
            for m in re.finditer(r"(?m)^\s*(\d{1,3})\s{2,}(.+?)\s*$", section)]


def test_answer_markers_equal_json():
    with open(FIXTURE, encoding="utf-8") as f:
        response = json.load(f)
    text = _pdf_text(response)
    pdf_markers = set(int(m) for m in re.findall(r"\[(\d+)\]", _answer_section(text)))
    json_markers = set(int(m) for m in re.findall(r"\[(\d+)\]", response["answer"]))
    assert pdf_markers == json_markers, "PDF markers %s != JSON markers %s" % (sorted(pdf_markers), sorted(json_markers))


def test_card_numbers_are_original_indices():
    with open(FIXTURE, encoding="utf-8") as f:
        response = json.load(f)
    text = _pdf_text(response)
    cards = _cards(text)
    cited = {c["index"]: c for c in response["citations"] if c.get("cited_by_llm")}
    assert cards, "no source cards found in the PDF"
    assert sorted(n for n, _ in cards) == sorted(cited), "card numbers %s != cited indices %s" % (sorted(n for n, _ in cards), sorted(cited))
    for n, title in cards:
        json_title = (cited[n].get("document_title") or "")[:40]
        assert json_title and json_title[:30] in title, "card %d title %r does not match JSON index %d (%r)" % (n, title, n, json_title)
