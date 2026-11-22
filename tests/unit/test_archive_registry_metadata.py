"""C30: re-archiving an existing registry row keeps its keys and sets or removes the fallback keys.

Offline. get_kb is replaced by a fake connection that records the SQL parameters.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "rss"))

import archive  # noqa: E402

FALLBACK_ITEM = {"doc_id": "d", "sha256": "new-sha", "resolved_via": "html_fallback",
                 "pdf_url_failed": "https://aspe.hhs.gov/x.pdf"}
PDF_ITEM = {"doc_id": "d", "sha256": "new-sha"}


def test_fallback_keys_added_to_an_existing_row():
    existing = {"doc_id": "d", "document_title": "old title", "source_hash": "old-sha"}
    merged = archive.registry_metadata_on_reregister(existing, FALLBACK_ITEM)
    assert merged["resolved_via"] == "html_fallback"
    assert merged["pdf_url_failed"] == "https://aspe.hhs.gov/x.pdf"
    assert merged["source_hash"] == "new-sha"


def test_other_keys_preserved():
    existing = {"doc_id": "d", "document_title": "t", "superseded_by": "", "regulatory_domain": ["GMP"]}
    merged = archive.registry_metadata_on_reregister(existing, FALLBACK_ITEM)
    assert merged["document_title"] == "t"
    assert merged["superseded_by"] == ""
    assert merged["regulatory_domain"] == ["GMP"]


def test_fallback_keys_removed_when_the_item_resolves_via_pdf():
    existing = {"doc_id": "d", "resolved_via": "html_fallback",
                "pdf_url_failed": "https://aspe.hhs.gov/x.pdf", "document_title": "t"}
    merged = archive.registry_metadata_on_reregister(existing, PDF_ITEM)
    assert "resolved_via" not in merged
    assert "pdf_url_failed" not in merged
    assert merged["document_title"] == "t"


def test_no_existing_row_metadata():
    assert archive.registry_metadata_on_reregister(None, PDF_ITEM) == {"source_hash": "new-sha"}


class _Cur:
    def __init__(self, existing, calls):
        self.existing, self.calls = existing, calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.existing


class _Conn:
    def __init__(self, existing):
        self.existing = existing
        self.calls = []

    def cursor(self):
        return _Cur(self.existing, self.calls)

    def close(self):
        pass


def _register_with(monkeypatch, existing, item):
    conn = _Conn(existing)
    monkeypatch.setattr(archive, "get_kb", lambda: conn)
    archive.register(item, archive.Path("/tmp/x"), "html" if "resolved_via" in item else "pdf")
    # the INSERT ... ON CONFLICT is the last execute; its last parameter is the conflict metadata
    return json.loads(conn.calls[-1][1][-1])


def test_register_writes_fallback_keys_on_conflict(monkeypatch):
    existing = ({"doc_id": "d", "document_title": "t"},)
    meta = _register_with(monkeypatch, existing, FALLBACK_ITEM)
    assert meta["resolved_via"] == "html_fallback"
    assert meta["document_title"] == "t"


def test_register_removes_fallback_keys_on_conflict(monkeypatch):
    existing = ({"doc_id": "d", "resolved_via": "html_fallback",
                 "pdf_url_failed": "https://aspe.hhs.gov/x.pdf"},)
    meta = _register_with(monkeypatch, existing, PDF_ITEM)
    assert "resolved_via" not in meta
    assert "pdf_url_failed" not in meta
