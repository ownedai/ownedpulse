"""C31: ingestion subprocesses started by the API get ARCHIVE_ROOT=/archive unless it is set."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.archive_root import with_archive_root, ARCHIVE_ROOT_IN_CONTAINER  # noqa: E402


def test_unset_gets_the_bind_mounted_archive():
    out = with_archive_root({"PATH": "/usr/bin"})
    assert out["ARCHIVE_ROOT"] == "/archive" == ARCHIVE_ROOT_IN_CONTAINER
    assert out["PATH"] == "/usr/bin"


def test_existing_value_is_kept():
    assert with_archive_root({"ARCHIVE_ROOT": "/custom"})["ARCHIVE_ROOT"] == "/custom"


def test_empty_value_is_treated_as_unset():
    assert with_archive_root({"ARCHIVE_ROOT": ""})["ARCHIVE_ROOT"] == "/archive"


def test_input_is_not_mutated():
    env = {"A": "1"}
    with_archive_root(env)
    assert env == {"A": "1"}
