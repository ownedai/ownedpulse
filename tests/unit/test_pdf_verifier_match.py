r"""OQ-07 match in the verifier's own mode, for all 109 corpus documents.

The frozen verifier (op-listing/b2_scripts/verify_oq.py, sha256 468a945a39a6d3238ab2bd9d94bad92903756063ed00965ce35fca2d7a81cec6)
reads the export with pdftotext -layout and, per cited document, checks:

    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    ntxt = norm(txt)
    id_hit = doc.lower() in ntxt
    title_hit = bool(title) and norm(title) in ntxt
    matched = "ID" if id_hit else ("title" if title_hit else None)

The same lines are used here, unchanged. Fixture: tests/fixtures/doc_titles_109.json
(document_id and the title the export prints, from the Qdrant chunk payload; the registry
title matches it wherever the registry has one).

Metadata card (routing METADATA): the document ID is printed in its table cell, so both
the title and the full ID must match. Content card (routing CONTENT): the title must match.
Skipped when pdftotext is not installed.
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

with open(os.path.join(FIX, "doc_titles_109.json"), encoding="utf-8") as f:
    DOCS = json.load(f)


def _response(doc, routing):
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        resp = json.load(f)
    with open(os.path.join(FIX, "oq03_run1_answer.json"), encoding="utf-8") as f:
        resp["answer"] = json.load(f)["answer"]
    chunk = copy.deepcopy(resp["citations"][0])
    chunk.update({"document_id": doc["document_id"], "document_title": doc["document_title"],
                  "cited_by_llm": True, "index": 1})
    resp["citations"] = [chunk]
    resp["routing_path"] = routing
    return resp


def _verifier_match(pdf_bytes, doc_id, title):
    fd, pdf = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        with open(pdf, "wb") as f:
            f.write(pdf_bytes)
        txt = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True,
                             timeout=60).stdout
    finally:
        os.remove(pdf)
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    ntxt = norm(txt)
    id_hit = doc_id.lower() in ntxt
    title_hit = bool(title) and norm(title) in ntxt
    return id_hit, title_hit


def test_metadata_card_title_and_full_id_match_for_all_109():
    misses = []
    for doc in DOCS:
        id_hit, title_hit = _verifier_match(generate_query_export_pdf(_response(doc, "METADATA")),
                                            doc["document_id"], doc["document_title"])
        if not (id_hit and title_hit):
            misses.append((doc["document_id"], id_hit, title_hit))
    assert not misses, "verifier-mode misses (id_hit, title_hit): %r" % misses[:10]


def test_content_card_title_matches_for_all_109():
    misses = []
    for doc in DOCS:
        _, title_hit = _verifier_match(generate_query_export_pdf(_response(doc, "CONTENT")),
                                       doc["document_id"], doc["document_title"])
        if not title_hit:
            misses.append(doc["document_id"])
    assert not misses, "verifier-mode title misses: %r" % misses[:10]
