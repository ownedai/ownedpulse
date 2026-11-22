"""C36: supersede data comes from the registry, not the Qdrant payload.

Offline. The database connection is a fake; api/main.py is imported with the
apscheduler package stubbed when it is not installed.
"""
import logging
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

try:
    import apscheduler  # noqa: F401
except ModuleNotFoundError:
    for _name in ["apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.asyncio",
                  "apscheduler.triggers", "apscheduler.triggers.cron", "apscheduler.triggers.date"]:
        sys.modules[_name] = types.ModuleType(_name)
    sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = type("AsyncIOScheduler", (), {})
    sys.modules["apscheduler.triggers.cron"].CronTrigger = type("CronTrigger", (), {})
    sys.modules["apscheduler.triggers.date"].DateTrigger = type("DateTrigger", (), {})

import main  # noqa: E402

# (document_id, document_family_id, document_status, document_version, title) as in the registry
REGISTRY = [
    ("ICH-Q9", "ICH-Q9", "superseded", "Step 4 (2005)", "ICH Q9 - Quality Risk Management (2005)"),
    ("ICH-Q9-R1", "ICH-Q9", "final", "Step 4 (R1, 2023)", "ICH Q9(R1) - Quality Risk Management"),
    ("EMA-Reflection-AI", "", "final", "Final (2024)", "Reflection paper"),
]


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.rows = []

    def execute(self, sql, params=None):
        self.db["sql"].append(" ".join(sql.split()))
        if self.db["fail"]:
            raise RuntimeError("registry unavailable")
        if "WHERE document_id = ANY" in sql:
            ids = set(params[0])
            self.rows = [(d, f, s) for (d, f, s, _v, _t) in REGISTRY if d in ids]
        elif "WHERE document_family_id = %s" in sql:
            self.rows = [(d, f, s, v, t) for (d, f, s, v, t) in REGISTRY if f == params[0]]
        else:
            raise AssertionError("unexpected SQL: " + sql)

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _Conn:
    def __init__(self, fail=False):
        self.db = {"sql": [], "fail": fail}

    def cursor(self):
        return _Cursor(self.db)

    def close(self):
        pass


def _chunk(doc_id, cid):
    # The Qdrant payload family is empty for ICH documents (C35); the registry supplies it.
    return {"document_id": doc_id, "chunk_id": cid, "score": 0.8,
            "document_family_id": "", "chunk_text": "text", "clause_id": None}


def test_superseded_document_is_flagged_and_family_detected():
    chunks = [_chunk("ICH-Q9", "a"), _chunk("ICH-Q9-R1", "b")]
    conn = _Conn()
    ctx = main.apply_registry_supersede(chunks, conn, "q-superseded")
    assert chunks[0]["superseded"] is True
    assert chunks[1]["superseded"] is False
    assert ctx is not None and ctx["family_id"] == "ICH-Q9"
    assert {m["document_id"]: m["status"] for m in ctx["members"]} == {"ICH-Q9": "superseded", "ICH-Q9-R1": "final"}
    # one batched lookup for the chunks, plus one for the family members
    assert sum("WHERE document_id = ANY" in s for s in conn.db["sql"]) == 1


def test_non_superseded_document_is_not_flagged():
    chunks = [_chunk("ICH-Q9-R1", "b"), _chunk("EMA-Reflection-AI", "c")]
    ctx = main.apply_registry_supersede(chunks, _Conn(), "q-final")
    assert chunks[0]["superseded"] is False
    assert chunks[1]["superseded"] is False
    assert ctx is not None  # the family has two members, so the context exists


def test_lookup_failure_logs_with_query_id_and_does_not_crash(caplog):
    chunks = [_chunk("ICH-Q9", "a"), _chunk("ICH-Q9-R1", "b")]
    with caplog.at_level(logging.ERROR, logger="ownedpulse.api"):
        ctx = main.apply_registry_supersede(chunks, _Conn(fail=True), "q-fail-123")
    assert ctx is None  # previous behaviour: the payload family is empty, so no pair
    assert all("superseded" not in c or c["superseded"] is False for c in chunks)
    assert any(r.levelno == logging.ERROR and "query_id=q-fail-123" in r.getMessage() for r in caplog.records)
