"""C23: /api/sources/bootstrap archive handling per redownload value.

Offline. The database, Qdrant, the worker thread and the scope lookup are mocked;
the archive root is a temporary directory, so the real deletions are checked.

  none  (use local files): archives kept, worker gets "none", selected vectors and state removed
  force (re-download):     archives deleted, worker gets "force"
  check (missing only):    archives kept, no Qdrant or state change, worker gets "check"
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

# test_extraction_clause and test_toc_rule put scripts/ingestion first on sys.path,
# where its qdrant_client.py shadows the qdrant_client package that routers.sources
# imports. Import the real package with that directory off the path, then restore it.
_SHADOW_DIR = os.path.join(ROOT, "scripts", "ingestion")
_saved_path = sys.path[:]
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _SHADOW_DIR]
for _name in [m for m in sys.modules if m == "qdrant_client" or m.startswith("qdrant_client.")]:
    del sys.modules[_name]
import routers.sources as sources  # noqa: E402
import routers.bootstrap as bootstrap  # noqa: E402
sys.path[:] = _saved_path


class _Cursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(sql)

    def close(self):
        pass


class _Conn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return _Cursor(self.log)

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    rec = {"sql": [], "qdrant_deletes": 0, "worker_args": None}
    archive = tmp_path / "archive"
    (archive / "EMA" / "DOC-A").mkdir(parents=True)
    (archive / "EMA" / "DOC-A" / "source.pdf").write_text("pdf")

    class FakeQdrant:
        def __init__(self, *a, **k):
            pass

        def delete(self, collection_name, points_selector):
            rec["qdrant_deletes"] += 1

    class FakeThread:
        def __init__(self, target, args, daemon):
            rec["worker_args"] = args

        def start(self):
            pass

    monkeypatch.setattr(sources, "ARCHIVE_ROOT", archive)
    monkeypatch.setattr(sources.ingestion_lock, "state", lambda: {"active": False})
    monkeypatch.setattr(sources, "_build_doc_list_from_scope",
                        lambda base, feeds: [{"doc_id": "DOC-A"}, {"doc_id": "DOC-B"}])
    monkeypatch.setattr(sources, "get_pg_conn", lambda: _Conn(rec["sql"]))
    monkeypatch.setattr(sources, "QdrantClient", FakeQdrant)
    monkeypatch.setattr(sources.threading, "Thread", FakeThread)
    monkeypatch.setattr(bootstrap, "_sessions", {})
    return rec, archive


def _run(redownload):
    body = sources.BootstrapRequest(
        mode="wipe_and_reload",
        redownload=redownload,
        base_corpus=[],
        ingestion_sources=[sources.FeedSelection(feed_id="ema_reg_guidance")],
    )
    return asyncio.run(sources.sources_bootstrap(body))


def test_none_keeps_archives_and_reembeds(env):
    rec, archive = env
    _run("none")
    assert (archive / "EMA" / "DOC-A" / "source.pdf").exists()
    assert rec["worker_args"][2] == "none"
    assert rec["qdrant_deletes"] == 1
    assert any("DELETE FROM ingestion_state" in s for s in rec["sql"])


def test_force_deletes_archives_and_redownloads(env):
    rec, archive = env
    _run("force")
    assert not (archive / "EMA" / "DOC-A").exists()
    assert rec["worker_args"][2] == "force"
    assert rec["qdrant_deletes"] == 1


def test_check_keeps_archives_and_state(env):
    rec, archive = env
    _run("check")
    assert (archive / "EMA" / "DOC-A" / "source.pdf").exists()
    assert rec["worker_args"][2] == "check"
    assert rec["qdrant_deletes"] == 0
    assert not any("ingestion_state" in s for s in rec["sql"])
