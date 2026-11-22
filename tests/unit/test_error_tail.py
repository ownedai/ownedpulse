"""C27: scheduler keeps the last 2000 characters of a failed pipeline's stderr."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "api"))

from lib.error_tail import tail_text, TAIL_CHARS  # noqa: E402


def test_short_stderr_returned_whole():
    assert tail_text(b"short error") == "short error"


def test_long_stderr_keeps_the_end():
    head = ("early log line\n" * 400).encode()
    tail = b"2026-11-22 INFO Resolved: doc_id=x\n2026-11-22 ERROR Pipeline failed doc_id=x url=u\n"
    out = tail_text(head + tail)
    assert len(out) == TAIL_CHARS == 2000
    assert out.endswith("Pipeline failed doc_id=x url=u\n")


def test_cut_inside_multibyte_character_does_not_raise():
    data = ("é" * 2500).encode()  # 2 bytes per character; 2500 characters, 5000 bytes
    out = tail_text(data)
    assert len(out) == 2000
    assert set(out) <= {"é"}
