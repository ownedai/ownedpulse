"""K2: refusal answers without markers mark no chunk as cited (api/lib/text_utils.py).

Offline. Fixtures: the six recorded refusals (OQ-05 runs 1-3, KB-2 runs 1-3) must
match; a recorded normal marker-less answer (OQ-03 run 1, reference) and a
labelled synthetic partial answer must not match.

Instrument check: each fixture must contain the original wording before the verdict.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.text_utils import is_marker_less_refusal, REFUSAL_OPENING_PATTERN  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "refusals_recorded.json"), encoding="utf-8") as f:
    ITEMS = json.load(f)
REFUSALS = [i for i in ITEMS if i["kind"] == "refusal"]
NOT_REFUSALS = [i for i in ITEMS if i["kind"] != "refusal"]


def test_fixture_counts():
    assert len(REFUSALS) == 6
    assert len(NOT_REFUSALS) == 2


def test_instrument_wording_present():
    for item in REFUSALS:
        assert "does not contain" in item["answer"], "instrument: wording missing in " + item["source"]


def test_recorded_refusals_match():
    for item in REFUSALS:
        assert is_marker_less_refusal(item["answer"]), "no match: " + item["source"]


def test_normal_marker_less_answer_does_not_match():
    item = [i for i in NOT_REFUSALS if i["kind"] == "normal_marker_less"][0]
    assert "does not contain" not in item["answer"][:200]
    assert not is_marker_less_refusal(item["answer"]), "matched: " + item["source"]


def test_partial_answer_with_content_first_does_not_match():
    item = [i for i in NOT_REFUSALS if i["kind"] == "synthetic_partial_must_not_match"][0]
    assert "does not contain sufficient information" in item["answer"], "instrument: wording missing"
    assert not is_marker_less_refusal(item["answer"]), "matched: " + item["source"]


def test_marker_present_is_not_a_marker_less_refusal():
    text = "The retrieved context does not contain sufficient information about X [3]."
    assert not is_marker_less_refusal(text)


def test_pattern_is_named_constant():
    assert "retrieved|provided" in REFUSAL_OPENING_PATTERN
