"""D2: the PDF header count is the indexed-document count shown on the screen.

Offline: a fake cursor, no database. The guard test reads api/routers/corpus.py and checks that the
stats endpoint still uses the same SQL, so the PDF and the screen cannot drift apart.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.pdf_export import INDEXED_DOCUMENT_SQL, indexed_document_count  # noqa: E402


class FakeCursor:
    """Answers the indexed query with 109 and any registry-row query with 6869."""

    def __init__(self):
        self.sql = []
        self._last = None

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self._last = 109 if "ingestion_status" in sql else 6869

    def fetchone(self):
        return (self._last,)


def test_count_helper_returns_indexed_documents_not_registry_rows():
    cur = FakeCursor()
    assert indexed_document_count(cur) == 109
    assert cur.sql == [INDEXED_DOCUMENT_SQL]
    assert "document_registry_ext" in INDEXED_DOCUMENT_SQL
    assert "ingestion_status = 'indexed'" in INDEXED_DOCUMENT_SQL


def test_sql_matches_the_screen_stats_endpoint():
    with open(os.path.join(ROOT, "api", "routers", "corpus.py"), encoding="utf-8") as f:
        corpus_src = f.read()
    assert INDEXED_DOCUMENT_SQL in corpus_src, "PDF count SQL no longer matches GET /api/corpus/stats"
