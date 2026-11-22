"""C27: resolve() falls back to the landing page's HTML when the linked PDF cannot be downloaded.

Offline. download_pdf and fetch_html are mocked; TEMP_DIR is a temporary directory.
"""
import os
import sys

import pytest
import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "rss"))

import resolve_landing as rl  # noqa: E402

PAGE_URL = "http://www.fda.gov/about-fda/example-office-page"
PDF_URL = "https://aspe.hhs.gov/system/files/pdf/264126/CARB-National-Action-Plan-2020-2025.pdf"
LONG_BODY = "<p>" + ("Office of infectious diseases research activities and programmes. " * 6) + "</p>"


class _Resp:
    def __init__(self, text):
        self.text = text


def _page(body):
    return (f'<html><head><title>Office page</title></head><body>'
            f'<a href="{PDF_URL}">Plan</a>{body}</body></html>')


@pytest.fixture
def serve(monkeypatch, tmp_path):
    monkeypatch.setattr(rl, "TEMP_DIR", tmp_path / "tmp")

    def setup(body):
        html = _page(body)
        monkeypatch.setattr(rl, "fetch_html",
                            lambda url: (_Resp(html), BeautifulSoup(html, "html.parser")))
        return html
    return setup


def test_pdf_ok_result_unchanged(serve, monkeypatch):
    serve(LONG_BODY)
    calls = []
    monkeypatch.setattr(rl, "download_pdf", lambda url, dest: calls.append(url) or "abc123")
    res = rl.resolve(PAGE_URL, "fda_drugs", "", "FDA")
    assert calls == [PDF_URL]
    assert res["content_type"] == "pdf"
    assert res["pdf_url"] == PDF_URL
    assert res["sha256"] == "abc123"
    assert "resolved_via" not in res
    assert "pdf_url_failed" not in res


def test_pdf_fails_html_used(serve, monkeypatch):
    html = serve(LONG_BODY)

    def boom(url, dest):
        raise requests.HTTPError(f"502 Server Error: Bad Gateway for url: {url}")
    monkeypatch.setattr(rl, "download_pdf", boom)
    res = rl.resolve(PAGE_URL, "fda_drugs", "", "FDA")
    assert res["content_type"] == "html"
    assert res["resolved_via"] == "html_fallback"
    assert res["pdf_url_failed"] == PDF_URL
    assert "pdf_url" not in res
    assert res["file_path"].endswith("source.html")
    with open(res["file_path"], encoding="utf-8") as f:
        assert f.read() == html
    assert res["sha256"]
    assert res["extracted_metadata"]["title"]


def test_pdf_fails_html_too_short_raises_with_both(serve, monkeypatch):
    serve("")

    def boom(url, dest):
        raise requests.HTTPError(f"502 Server Error: Bad Gateway for url: {url}")
    monkeypatch.setattr(rl, "download_pdf", boom)
    with pytest.raises(ValueError) as info:
        rl.resolve(PAGE_URL, "fda_drugs", "", "FDA")
    msg = str(info.value)
    assert "PDF download failed (HTTPError: 502 Server Error" in msg
    assert "HTML fallback rejected: Extracted body too short" in msg


def test_html_page_without_pdf_link_unchanged(serve, monkeypatch):
    html = _page(LONG_BODY).replace(f'<a href="{PDF_URL}">Plan</a>', "")
    monkeypatch.setattr(rl, "fetch_html",
                        lambda url: (_Resp(html), BeautifulSoup(html, "html.parser")))
    monkeypatch.setattr(rl, "download_pdf",
                        lambda url, dest: pytest.fail("no PDF link: download must not run"))
    res = rl.resolve(PAGE_URL, "fda_drugs", "", "FDA")
    assert res["content_type"] == "html"
    assert "resolved_via" not in res
