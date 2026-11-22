"""C27: the pipeline's per-item failure line names the doc_id, the full URL, and the exception."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "rss"))

from item_failure import describe_item_failure  # noqa: E402


def test_line_has_doc_id_url_type_and_message():
    url = "http://www.fda.gov/about-fda/center-drug-evaluation-and-research-cder/office-infectious-diseases-research-activities"
    exc = RuntimeError("resolve_landing failed rc=1: 502 Server Error: Bad Gateway")
    line = describe_item_failure("fda_drugs-office-x-abc", url, exc)
    assert line == ("Pipeline failed doc_id=fda_drugs-office-x-abc url=" + url +
                    " error=RuntimeError: resolve_landing failed rc=1: 502 Server Error: Bad Gateway")
    assert url in line  # the full URL, not cut at 80 characters
