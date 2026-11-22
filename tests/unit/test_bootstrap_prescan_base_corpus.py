"""C24: 'Missing only' pre-scan in api/routers/bootstrap.py (_bootstrap_worker, redownload check).

Offline. The database, Qdrant, the ingestion lock and ingest_documents are mocked.
A document is skipped when PostgreSQL marks it indexed and Qdrant still has its
vectors (counted in already_ingested). Otherwise it is queued. Base-corpus documents
(corpus_doc = TRUE) follow the same rule.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

# test_extraction_clause and test_toc_rule put scripts/ingestion first on sys.path,
# where its qdrant_client.py shadows the qdrant_client package. Import the real
# package with that directory off the path, then restore it.
_SHADOW_DIR = os.path.join(ROOT, "scripts", "ingestion")
_saved_path = sys.path[:]
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _SHADOW_DIR]
for _name in [m for m in sys.modules if m == "qdrant_client" or m.startswith("qdrant_client.")]:
    del sys.modules[_name]
import routers.bootstrap as bootstrap  # noqa: E402
import lib.db as lib_db  # noqa: E402
import lib.ingest_documents as ingest_mod  # noqa: E402
sys.path[:] = _saved_path


class _Cursor:
    def __init__(self, state):
        self.state = state
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        ids = set(params[0])
        st = self.state
        if "corpus_doc = TRUE" in sql:
            self.rows = [(d,) for d in st["corpus"] if d in ids]
        elif "FROM ingestion_state" in sql:
            self.rows = [(d,) for d in st["indexed"] if d in ids]
        elif "archive_path IS NOT NULL" in sql:
            self.rows = [(d, p) for d, p in st["archive"].items() if d in ids]
        else:
            raise AssertionError("unexpected SQL: " + sql)

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return _Cursor(self.state)

    def close(self):
        pass


@pytest.fixture
def run_prescan(monkeypatch):
    def run(doc_ids, corpus=(), indexed=(), vectors=(), archive=None):
        state = {"corpus": set(corpus), "indexed": set(indexed), "archive": dict(archive or {})}
        queued = []

        def fake_ingest(docs, **kwargs):
            queued.extend(d["doc_id"] for d in docs)
            return {"results": [{"status": "ok", "chunk_count": 0}]}

        session = {"session_id": "s1", "status": "pending", "total": len(doc_ids),
                   "processed": 0, "succeeded": 0, "failed": 0, "skipped": 0,
                   "docs": [], "started_at": "t", "completed_at": None}
        monkeypatch.setattr(bootstrap, "_sessions", {"s1": session})
        monkeypatch.setattr(bootstrap.ingestion_lock, "acquire", lambda *a, **k: True)
        monkeypatch.setattr(bootstrap.ingestion_lock, "release", lambda *a, **k: None)
        monkeypatch.setattr(lib_db, "get_pg_conn", lambda: _Conn(state))
        monkeypatch.setattr(bootstrap, "QdrantClient", lambda **k: None)
        monkeypatch.setattr(bootstrap, "_docs_with_qdrant_chunks",
                            lambda client, ids: {i for i in ids if i in vectors})
        monkeypatch.setattr(ingest_mod, "ingest_documents", fake_ingest)
        bootstrap._bootstrap_worker("s1", [{"doc_id": d} for d in doc_ids], "check")
        return session, queued
    return run


def test_indexed_base_doc_with_vectors_is_skipped(run_prescan):
    session, queued = run_prescan(["BASE-OK"], corpus=["BASE-OK"],
                                  indexed=["BASE-OK"], vectors=["BASE-OK"])
    assert queued == []
    assert session["already_ingested"] == 1


def test_base_doc_without_vectors_is_queued(run_prescan):
    session, queued = run_prescan(["BASE-NOVEC"], corpus=["BASE-NOVEC"], indexed=["BASE-NOVEC"])
    assert queued == ["BASE-NOVEC"]
    assert session["already_ingested"] == 0


def test_unindexed_base_doc_is_queued(run_prescan):
    session, queued = run_prescan(["BASE-UNIDX"], corpus=["BASE-UNIDX"])
    assert queued == ["BASE-UNIDX"]
    assert session["already_ingested"] == 0


def test_mixed_batch_base_and_non_base(run_prescan):
    session, queued = run_prescan(
        ["BASE-OK", "BASE-NOVEC", "BASE-UNIDX", "NB-OK"],
        corpus=["BASE-OK", "BASE-NOVEC", "BASE-UNIDX"],
        indexed=["BASE-OK", "BASE-NOVEC", "NB-OK"],
        vectors=["BASE-OK", "NB-OK"])
    assert queued == ["BASE-NOVEC", "BASE-UNIDX"]
    assert session["already_ingested"] == 2
    assert session["total"] == 2


def test_non_base_rules_unchanged(run_prescan, tmp_path):
    arch = tmp_path / "NB-ARCH"
    arch.mkdir()
    (arch / "source.pdf").write_text("pdf")
    session, queued = run_prescan(
        ["NB-OK", "NB-NOVEC", "NB-UNIDX", "NB-ARCH"],
        indexed=["NB-OK", "NB-NOVEC"], vectors=["NB-OK"],
        archive={"NB-ARCH": str(arch)})
    assert queued == ["NB-NOVEC", "NB-UNIDX"]
    assert session["already_ingested"] == 2
