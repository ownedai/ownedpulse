"""K12: citation display rule (api/lib/citation_markers.py).

Offline. Reads the shared case file tests/fixtures/marker_cases.json (also read by
ui/test/citationMarkers.test.js) and the recorded OQ-03 answers (B9 runs 1-3).

Instrument check: each recorded answer must contain the original marker text
before the rule is judged on it.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.citation_markers import normalise_markers  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
with open(os.path.join(FIX, "marker_cases.json"), encoding="utf-8") as f:
    CASES = json.load(f)

REAL = [
    ("oq03_run1_answer.json", ["[36-37]"], [("[36-37]", "[36][37]")]),
    ("oq03_run2_answer.json", ["[36(e), 37(e)]", "[36(g)]"],
     [("[36(e), 37(e)]", "[36][37]"), ("[36(g)]", "[36]")]),
    ("oq03_run3_answer.json", ["[11.10(d)]", "[11.10(f)]", "[11.300(b)]"], []),
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_case(case):
    got = normalise_markers(case["input"], range(1, case["valid_max"] + 1))
    assert got == case["expected"]


@pytest.mark.parametrize("fname,must_contain,replacements", REAL, ids=[r[0] for r in REAL])
def test_recorded_answer(fname, must_contain, replacements):
    with open(os.path.join(FIX, fname), encoding="utf-8") as f:
        data = json.load(f)
    for m in must_contain:
        assert m in data["answer"], "instrument: original marker %r not in fixture %s" % (m, fname)
    expected = data["answer"]
    for old, new in replacements:
        expected = expected.replace(old, new)
    assert normalise_markers(data["answer"], range(1, data["valid_max"] + 1)) == expected


pdftotext = shutil.which("pdftotext")


@pytest.mark.skipif(pdftotext is None, reason="pdftotext not installed")
def test_pdf_uses_the_rule():
    """The PDF shows the rule's output: run 1 answer ([36-37]) with its real citations."""
    from lib.pdf_export import generate_query_export_pdf
    import re
    with open(os.path.join(FIX, "oq03_run1_response.json"), encoding="utf-8") as f:
        response = json.load(f)
    with open(os.path.join(FIX, "oq03_run1_answer.json"), encoding="utf-8") as f:
        response["answer"] = json.load(f)["answer"]
    assert "[36-37]" in response["answer"], "instrument: marker missing from fixture"
    pdf = generate_query_export_pdf(response)
    tmp = os.path.join(os.environ.get("TMPDIR", "/tmp"), "k12_test_%d.pdf" % os.getpid())
    with open(tmp, "wb") as f:
        f.write(pdf)
    try:
        text = subprocess.run([pdftotext, "-layout", tmp, "-"], capture_output=True, text=True, check=True).stdout
    finally:
        os.remove(tmp)
    answer_part = text[: text.find("SOURCE EVIDENCE")]
    assert "[36][37]" in re.sub(r"\s+", "", answer_part) or ("[36]" in answer_part and "[37]" in answer_part)
    assert "[36-37]" not in answer_part
