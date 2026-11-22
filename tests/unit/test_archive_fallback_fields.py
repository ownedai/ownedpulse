"""C27: archive.py records resolved_via and pdf_url_failed in metadata.json, only when present.

Offline. register() (the database write) is replaced by a no-op.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "rss"))

import archive  # noqa: E402


def _run(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(archive, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(archive, "register", lambda item, d, ct: None)
    src = tmp_path / "source.html"
    src.write_text("<html>x</html>", encoding="utf-8")
    item = {"doc_id": "fda_drugs-test-abc", "file_path": str(src), "content_type": "html",
            "sha256": "deadbeef", "authority": "FDA", "feed_id": "fda_drugs",
            "url": "http://www.fda.gov/page", "extracted_metadata": {"title": "t"}, **extra}
    archive.archive(item)
    return json.loads((tmp_path / "archive" / "fda" / "fda_drugs-test-abc" / "metadata.json").read_text())


def test_fallback_fields_written(tmp_path, monkeypatch):
    meta = _run(tmp_path, monkeypatch, {"resolved_via": "html_fallback",
                                        "pdf_url_failed": "https://aspe.hhs.gov/x.pdf"})
    assert meta["resolved_via"] == "html_fallback"
    assert meta["pdf_url_failed"] == "https://aspe.hhs.gov/x.pdf"
    assert meta["content_type"] == "html"


def test_normal_html_metadata_has_no_fallback_keys(tmp_path, monkeypatch):
    meta = _run(tmp_path, monkeypatch, {})
    assert "resolved_via" not in meta
    assert "pdf_url_failed" not in meta
