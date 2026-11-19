"""K3 TOC rule (scripts/ingestion/extraction.py).

Recorded fixtures: tests/fixtures/toc_recorded.json (verbatim payload copies; the nine TOC chunks
must give None because their headings are not numbered; the two real clauses are unchanged).
Synthetic cases are labelled SYNTHETIC.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "ingestion"))

from extraction import annex_clause  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "toc_recorded.json"), encoding="utf-8") as f:
    FIX = json.load(f)["chunks"]
TOC = [c for c in FIX if "must give None" in c["label"]]
REAL = [c for c in FIX if "must be unchanged" in c["label"]]


def test_fixture_count_and_instrument():
    assert len(TOC) == 9
    assert len(REAL) == 2
    for c in TOC:
        t = c["chunk_text"][:120]
        has_leader = re.search(r"\.{3,}|\.(?:\s\.){2,}", t) is not None
        has_second = re.search(r"\s\d{1,2}\.\s+[A-Z]", t[len(re.match(r"^\s*\d+(?:\.\d+)*", t).group(0)):]) is not None
        assert has_leader or has_second, "instrument: no TOC evidence in " + c["chunk_id"]


def test_recorded_toc_chunks_give_none():
    for c in TOC:
        value, source, conflict = annex_clause(c["section_path"], "", chunk_text=c["chunk_text"])
        assert value is None, "TOC chunk %s gave %r" % (c["chunk_id"][:8], value)


def test_recorded_real_clauses_unchanged():
    expect = {"51adcdb4": "3.1", "43793210": "12.4"}
    for c in REAL:
        value, source, conflict = annex_clause(c["section_path"], "", chunk_text=c["chunk_text"])
        assert value == expect[c["chunk_id"][:8]], (c["chunk_id"][:8], value)
        assert source == "text"


def test_synthetic_dot_leader_is_toc():
    # SYNTHETIC: dot leader after the number.
    assert annex_clause([], "", chunk_text="9. Audit trails . . . . . 4")[0] is None


def test_synthetic_second_clause_token_is_toc():
    # SYNTHETIC: a second numbered entry in the first 120 characters.
    assert annex_clause([], "", chunk_text="9. Audit trails 10. Records of changes")[0] is None


def test_synthetic_toc_uses_numbered_heading_when_present():
    # SYNTHETIC: the heading fallback applies to a TOC line.
    assert annex_clause(["6 Introduction"], "", chunk_text="1. Introduction ........ 3")[0] == "6"


def test_synthetic_single_clause_unchanged():
    # SYNTHETIC: one clause token, no leader.
    assert annex_clause([], "", chunk_text="9. Audit trails should be read in context")[0] == "9"
