"""C29: writing run_ingest's metadata keeps the keys written at registration.

Offline. merge_metadata is pure Python; no database.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
# Load the helper by file path: another test module loads a different "ingestion" package.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "metadata_merge", os.path.join(ROOT, "scripts", "ingestion", "metadata_merge.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
merge_metadata = _mod.merge_metadata


def test_fallback_keys_survive_an_ingest_update():
    existing = {"doc_id": "d", "resolved_via": "html_fallback",
                "pdf_url_failed": "https://aspe.hhs.gov/x.pdf", "document_title": "old"}
    run_ingest_meta = {"document_title": "OID Research Activities", "source_file_format": "html"}
    merged = merge_metadata(existing, run_ingest_meta)
    assert merged["resolved_via"] == "html_fallback"
    assert merged["pdf_url_failed"] == "https://aspe.hhs.gov/x.pdf"
    assert merged["document_title"] == "OID Research Activities"
    assert merged["source_file_format"] == "html"
    assert merged["doc_id"] == "d"


def test_updates_win_for_keys_they_set():
    merged = merge_metadata({"source_hash": "old", "x": 1}, {"source_hash": "new"})
    assert merged == {"source_hash": "new", "x": 1}


def test_no_existing_metadata_gives_the_update_alone():
    assert merge_metadata(None, {"a": 1}) == {"a": 1}
    assert merge_metadata("not a dict", {"a": 1}) == {"a": 1}


def test_existing_is_not_mutated():
    existing = {"a": 1}
    merge_metadata(existing, {"b": 2})
    assert existing == {"a": 1}
