"""
Branded ownedpulse query export PDF generator.
Matches the ownedai design spec: dark shell header, warning band, query/answer,
parameters box, source evidence cards with provenance metadata.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# ── font registration ──────────────────────────────────────────────────────────

_FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

_FONT_MAP = {
    "Inter":            "Inter-Regular.ttf",
    "Inter-Medium":     "Inter-Medium.ttf",
    "Inter-SemiBold":   "Inter-SemiBold.ttf",
    "Inter-Bold":       "Inter-Bold.ttf",
    "Inter-Italic":     "Inter-Italic.ttf",
    "Inter-BoldItalic": "Inter-BoldItalic.ttf",
    "Mono":             "JetBrainsMono-Regular.ttf",
    "Mono-Bold":        "JetBrainsMono-Bold.ttf",
}

_fonts_registered = False


def _register_fonts() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    for name, filename in _FONT_MAP.items():
        path = _FONTS_DIR / filename
        if path.exists():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    _fonts_registered = True


# ── colour palette ─────────────────────────────────────────────────────────────

def _rgb(hex_str: str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


C_SHELL_BG    = _rgb("0F172A")
C_SHELL_SURF  = _rgb("1E293B")
C_SHELL_MUTED = _rgb("94A3B8")
C_ACCENT      = _rgb("2563EB")
C_ACCENT_L    = _rgb("60A5FA")
C_INK         = _rgb("0F172A")
C_INK_SEC     = _rgb("475569")
C_INK_TER     = _rgb("94A3B8")
C_BORDER      = _rgb("E2E8F0")
C_BORDER_STR  = _rgb("CBD5E1")
C_ROW_ALT     = _rgb("F8FAFC")
C_WHITE       = (1.0, 1.0, 1.0)
C_WARN_BG     = _rgb("FEF3C7")
C_WARN_BORDER = _rgb("FCD34D")
C_WARN_TEXT   = _rgb("92400E")
C_WARN_ICON   = _rgb("F59E0B")
C_STATUS_OK   = _rgb("16A34A")
C_STATUS_OK_BG = _rgb("DCFCE7")
C_STATUS_AMB  = _rgb("F59E0B")
C_STATUS_AMB_BG = _rgb("FEF3C7")
C_BLUE_KEY    = _rgb("64748B")
C_BLUE_VAL    = _rgb("E2E8F0")


# ── page geometry ──────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter   # 612 × 792 pt
MARGIN_X = 42.0           # ~56px scaled
CONTENT_W = PAGE_W - 2 * MARGIN_X

HEADER_H_P1   = 80.0     # page-1 full header
HEADER_H_CONT = 38.0     # continuation pages slim header
WARN_H        = 22.0
FOOTER_H      = 26.0

BODY_TOP_P1   = PAGE_H - HEADER_H_P1 - WARN_H - 16.0
BODY_TOP_CONT = PAGE_H - HEADER_H_CONT - 16.0
BODY_BOT      = FOOTER_H + 8.0


# ── low-level drawing helpers ──────────────────────────────────────────────────

def _rect(c: canvas.Canvas, x, y, w, h, fill=None, stroke=None, radius=0, lw=0.5):
    c.saveState()
    if fill:
        c.setFillColorRGB(*fill)
    if stroke:
        c.setStrokeColorRGB(*stroke)
        c.setLineWidth(lw)
    if radius:
        c.roundRect(x, y, w, h, radius, fill=1 if fill else 0, stroke=1 if stroke else 0)
    else:
        c.rect(x, y, w, h, fill=1 if fill else 0, stroke=1 if stroke else 0)
    c.restoreState()


def _line(c: canvas.Canvas, x1, y1, x2, y2, color, lw=0.5):
    c.saveState()
    c.setStrokeColorRGB(*color)
    c.setLineWidth(lw)
    c.line(x1, y1, x2, y2)
    c.restoreState()


def _text(c: canvas.Canvas, x, y, text, font, size, color, align="left"):
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)
    c.restoreState()


def _wrapped_text(c: canvas.Canvas, x, y, text, font, size, color, max_w,
                  line_height=None) -> float:
    """Draw wrapped text, return final y after last line."""
    if line_height is None:
        line_height = size * 1.55
    c.saveState()
    c.setFont(font, size)
    c.setFillColorRGB(*color)
    words = text.split()
    line = ""
    cy = y
    for word in words:
        test = (line + " " + word).strip()
        if c.stringWidth(test, font, size) <= max_w:
            line = test
        else:
            if line:
                c.drawString(x, cy, line)
                cy -= line_height
            line = word
    if line:
        c.drawString(x, cy, line)
        cy -= line_height
    c.restoreState()
    return cy


def _logo_mark(c: canvas.Canvas, x, y, size=22.0):
    """Draw ownedai logo: square outline + filled inner circle."""
    c.saveState()
    c.setStrokeColorRGB(*C_ACCENT_L)
    c.setLineWidth(1.2)
    c.rect(x, y - size, size, size, fill=0, stroke=1)
    inset = size * 0.22
    cw = size - 2 * inset
    c.setFillColorRGB(*C_ACCENT_L)
    c.ellipse(x + inset, y - size + inset, x + inset + cw, y - inset, fill=1, stroke=0)
    c.restoreState()


# ── multi-line text measurement ───────────────────────────────────────────────

def _measure_wrapped(c: canvas.Canvas, text: str, font: str, size: float,
                     max_w: float, line_height: float = None) -> float:
    if line_height is None:
        line_height = size * 1.55
    words = text.split()
    line = ""
    lines = 0
    for word in words:
        test = (line + " " + word).strip()
        if c.stringWidth(test, font, size) <= max_w:
            line = test
        else:
            if line:
                lines += 1
            line = word
    if line:
        lines += 1
    return lines * line_height


# ── header drawing ─────────────────────────────────────────────────────────────

def _draw_header_p1(c: canvas.Canvas, export_id: str, exported: str,
                    corpus_snapshot: str, system_str: str):
    _rect(c, 0, PAGE_H - HEADER_H_P1, PAGE_W, HEADER_H_P1, fill=C_SHELL_BG)
    lx = MARGIN_X
    logo_size = 30.0
    logo_y = PAGE_H - HEADER_H_P1 / 2 + logo_size / 2
    _logo_mark(c, lx, logo_y, logo_size)
    wx = lx + logo_size + 8
    wy_word = PAGE_H - HEADER_H_P1 / 2 + 5
    _text(c, wx, wy_word, "ownedpulse", "Inter-SemiBold", 18, C_WHITE)
    _text(c, wx, wy_word - 15, "REGULATORY INTELLIGENCE · OWNEDAI", "Mono", 7, C_SHELL_MUTED)

    rx = PAGE_W - MARGIN_X
    lines = [
        ("Export ID", export_id),
        ("Exported",  exported),
        ("Corpus",    corpus_snapshot),
        ("System",    system_str),
    ]
    ry = PAGE_H - 16
    for key, val in lines:
        _text(c, rx - c.stringWidth(val, "Mono", 8.5), ry, val, "Mono", 8.5, C_BLUE_VAL)
        _text(c, rx - c.stringWidth(val, "Mono", 8.5) - 4
              - c.stringWidth(key + "  ", "Mono", 8.5),
              ry, key, "Mono", 8.5, C_BLUE_KEY)
        ry -= 14


def _draw_header_cont(c: canvas.Canvas, export_id: str, page_num: int):
    _rect(c, 0, PAGE_H - HEADER_H_CONT, PAGE_W, HEADER_H_CONT, fill=C_SHELL_BG)
    lx = MARGIN_X
    logo_size = 22.0
    logo_y = PAGE_H - HEADER_H_CONT / 2 + logo_size / 2
    _logo_mark(c, lx, logo_y, logo_size)
    wx = lx + logo_size + 7
    wy = PAGE_H - HEADER_H_CONT / 2 + 4
    _text(c, wx, wy, "ownedpulse", "Inter-SemiBold", 14, C_WHITE)
    right_txt = f"Export ID {export_id}  ·  Query Export (cont.)"
    _text(c, PAGE_W - MARGIN_X, PAGE_H - HEADER_H_CONT / 2 - 4, right_txt,
          "Mono", 8.5, C_SHELL_MUTED, align="right")


def _draw_warning_band(c: canvas.Canvas):
    y = PAGE_H - HEADER_H_P1 - WARN_H
    _rect(c, 0, y, PAGE_W, WARN_H, fill=C_WARN_BG)
    _line(c, 0, y, PAGE_W, y, C_WARN_BORDER, lw=1.0)
    msg = "▲  This output is informational. Human review required before any GxP decision."
    c.saveState()
    c.setFont("Inter-Medium", 9.5)
    c.setFillColorRGB(*C_WARN_TEXT)
    c.drawString(MARGIN_X, y + 7, msg)
    c.restoreState()


def _draw_footer(c: canvas.Canvas, export_id: str, exported: str,
                 page_num: int, total_pages: int):
    _line(c, 0, FOOTER_H, PAGE_W, FOOTER_H, C_BORDER, lw=0.75)
    cy = FOOTER_H / 2 - 4

    logo_size = 13.0
    _logo_mark(c, MARGIN_X, cy + logo_size, logo_size)
    _text(c, MARGIN_X + logo_size + 5, cy + 2, "ownedai", "Inter", 8.5, C_INK_SEC)

    total_str = str(total_pages) if total_pages else "?"
    centre = (
        f"Page {page_num} of {total_str}  |  Export ID: {export_id}  |  "
        f"Exported: {exported}"
    )
    _text(c, PAGE_W / 2, cy + 2, centre, "Mono", 8, C_INK_TER, align="center")


# ── section header helper ──────────────────────────────────────────────────────

def _section_header(c: canvas.Canvas, x, y, label: str, index_label: str = "") -> float:
    """Draw blue-rule section header, return y after it."""
    _text(c, x, y, label.upper(), "Inter-SemiBold", 9, C_ACCENT)
    if index_label:
        _text(c, x + CONTENT_W, y, index_label, "Mono", 8.5, C_INK_TER, align="right")
    y -= 5
    _line(c, x, y, x + CONTENT_W, y, C_ACCENT, lw=2.0)
    return y - 10


# ── answer text renderer with blue [N] citation markers ──────────────────────

_MARKER_RE   = re.compile(r'(\[\d+\])')
_C_MARKER    = _rgb("2563EB")
_ATTACH_LEFT = frozenset('.,;:!?)}]')  # punctuation that attaches to the preceding token


def _wrapped_text_marked(c: canvas.Canvas, x, y, text, font, size, color,
                         max_w, line_height=None) -> float:
    """Render wrapped text; [N] citation markers are drawn in blue Inter-SemiBold.

    Punctuation tokens that start with an attach-left character (.,;:) are placed
    directly after the preceding token with no inter-word space, so '[1].' renders
    without a gap between the marker and the period.
    """
    if line_height is None:
        line_height = size * 1.55
    space_w = c.stringWidth(" ", font, size)

    # Tokenise: split on marker boundaries, then on spaces within prose segments
    tokens = []  # (word, is_marker)
    for seg in _MARKER_RE.split(text):
        if _MARKER_RE.fullmatch(seg):
            tokens.append((seg, True))
        else:
            for w in seg.split():
                tokens.append((w, False))

    line_items: list[tuple[str, bool]] = []
    line_w = 0.0
    cy = y

    def _render_line(items):
        dx = x
        for i, (w, is_m) in enumerate(items):
            f = "Inter-SemiBold" if is_m else font
            col = _C_MARKER if is_m else color
            c.saveState()
            c.setFont(f, size)
            c.setFillColorRGB(*col)
            c.drawString(dx, cy, w)
            c.restoreState()
            dx += c.stringWidth(w, f, size)
            if i < len(items) - 1:
                next_w = items[i + 1][0]
                if not (next_w and next_w[0] in _ATTACH_LEFT):
                    dx += space_w

    for word, is_m in tokens:
        f = "Inter-SemiBold" if is_m else font
        ww = c.stringWidth(word, f, size)
        # No leading space for attach-left punctuation (e.g. '.' after '[1]')
        gap = (space_w if line_items else 0.0) if not (word and word[0] in _ATTACH_LEFT) else 0.0
        if line_items and line_w + gap + ww > max_w:
            _render_line(line_items)
            cy -= line_height
            line_items = [(word, is_m)]
            line_w = ww
        else:
            line_items.append((word, is_m))
            line_w += gap + ww

    if line_items:
        _render_line(line_items)
        cy -= line_height

    return cy


# ── main PDF builder ───────────────────────────────────────────────────────────

class _PageState:
    def __init__(self):
        self.num = 0
        self.total = 1  # updated after two-pass


def generate_query_export_pdf(
    query_response: dict,
    output_path: str | None = None,
) -> bytes:
    """
    Build branded ownedpulse query export PDF.
    Returns PDF bytes; optionally writes to output_path.
    """
    _register_fonts()

    # ── unpack data ────────────────────────────────────────────────────────────
    query_id      = query_response.get("query_id") or "—"
    query_text    = query_response.get("query_text") or "—"
    routing_path  = query_response.get("routing_path") or "CONTENT"
    answer        = query_response.get("answer") or ""
    citations     = query_response.get("citations") or []
    sub_queries   = query_response.get("sub_queries") or []
    retrieval     = query_response.get("retrieval_params_applied") or {}
    filters_raw   = query_response.get("filters_applied") or {}
    langfuse_id   = query_response.get("langfuse_trace_id") or "—"
    classifier    = query_response.get("classifier") or "—"
    timestamp_iso = query_response.get("timestamp") or datetime.now(timezone.utc).isoformat()

    cited_chunks   = [c for c in citations if     c.get("cited_by_llm")]
    uncited_chunks = [c for c in citations if not c.get("cited_by_llm")]

    routing_label = "Metadata lookup" if routing_path == "METADATA" else "Semantic search"

    # ── export metadata ────────────────────────────────────────────────────────
    now_utc  = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        _now_local = datetime.now(ZoneInfo("Europe/Brussels"))
    except Exception:
        from datetime import timedelta as _td
        _now_local = now_utc + _td(hours=1)
    short_id  = query_id[:8] if len(query_id) >= 8 else query_id
    export_id = f"QRY-{now_utc.strftime('%Y-%m-%d')}-{short_id}"
    exported  = _now_local.strftime("%d.%m.%Y %H:%M") + " CET"

    # Try to get system info from DB; fall back gracefully
    corpus_snapshot = "—"
    generation_model = retrieval.get("model") or "phi4:14b-q8_0"
    embedding_model  = "mxbai-embed-large"
    prompt_version   = "V8"
    try:
        import psycopg2
        pg_dsn = os.environ.get("POSTGRES_DSN") or (
            f"host=postgres port=5432 dbname=knowledge_base user=postgres "
            f"password={os.environ.get('POSTGRES_PASSWORD', '')}"
        )
        _conn = psycopg2.connect(pg_dsn)
        _cur = _conn.cursor()
        _cur.execute("SELECT key, value FROM system_config")
        cfg = dict(_cur.fetchall())
        generation_model = cfg.get("active_llm_model", generation_model)
        _snap_raw        = cfg.get("corpus_snapshot_date", "2026-06-01")
        try:
            corpus_snapshot = datetime.strptime(_snap_raw, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            corpus_snapshot = _snap_raw
        prompt_version   = cfg.get("prompt_version", "V8")
        _conn.close()
    except Exception:
        pass

    try:
        from main import APP_VERSION as _APP_VERSION
    except Exception:
        _APP_VERSION = "dev"
    system_str = f"ownedpulse v{_APP_VERSION} · {embedding_model} · {generation_model}"

    # ── two-pass render: pass 1 counts pages; pass 2 renders with correct total ─
    def _render(total_pages_known: int) -> tuple["canvas.Canvas", BytesIO, int]:
        rbuf = BytesIO()
        rc = canvas.Canvas(rbuf, pagesize=letter)
        rc.setTitle(f"ownedpulse Export — {short_id}")
        rc.setAuthor("ownedai / ownedpulse")
        rc.setSubject("Regulatory intelligence query export")

        st = _PageState()

        def new_page(is_first: bool = False) -> None:
            st.num += 1
            if st.num > 1:
                rc.showPage()
            if is_first:
                _draw_header_p1(rc, export_id, exported, corpus_snapshot, system_str)
                _draw_warning_band(rc)
            else:
                _draw_header_cont(rc, export_id, st.num)
            _draw_footer(rc, export_id, exported, st.num, total_pages_known)

        def chk(cy: float, needed: float, fp: list) -> float:
            if cy - needed < BODY_BOT:
                new_page(is_first=False)
                fp[0] = False
                return BODY_TOP_CONT
            return cy

        new_page(is_first=True)
        cy = BODY_TOP_P1
        fp = [True]

        cy = _section_header(rc, MARGIN_X, cy, "Query", routing_label)
        cy -= 4

        q_pad = 10
        q_inner_w = CONTENT_W - 2 * q_pad - 3
        q_lines_h = _measure_wrapped(rc, query_text, "Inter-Medium", 12, q_inner_w, 16.5)
        q_box_h = q_lines_h + q_pad * 2
        _rect(rc, MARGIN_X, cy - q_box_h, CONTENT_W, q_box_h, fill=C_ROW_ALT, stroke=C_BORDER, lw=0.75)
        _rect(rc, MARGIN_X, cy - q_box_h, 3, q_box_h, fill=C_ACCENT)
        _wrapped_text(rc, MARGIN_X + 3 + q_pad, cy - q_pad - 12,
                      query_text, "Inter-Medium", 12, C_INK, q_inner_w, 16.5)
        cy -= q_box_h + 16

        cy = chk(cy, 40, fp)
        cy = _section_header(rc, MARGIN_X, cy, "Generated Answer")
        cy -= 6

        for para in [p.strip() for p in answer.split("\n\n") if p.strip()]:
            h = _measure_wrapped(rc, para, "Inter", 10.5, CONTENT_W, 17.5)
            cy = chk(cy, h + 8, fp)
            cy = _wrapped_text_marked(rc, MARGIN_X, cy, para, "Inter", 10.5, C_INK,
                                      CONTENT_W, 17.5)
            cy -= 8

        cy -= 4
        n_above = len(cited_chunks) + len(uncited_chunks)
        n_cited = len(cited_chunks)
        meta = (
            f"{query_id[:8]}  ·  {routing_label}  ·  "
            f"{n_above} chunks above threshold  ·  {n_cited} cited  ·  {generation_model}"
        )
        _text(rc, MARGIN_X, cy, meta, "Mono", 8, C_INK_TER)
        cy -= 28

        if sub_queries:
            _SQ_NOTE = ("These sub-queries were generated automatically by the system "
                        "to broaden retrieval. They were not entered by the user.")
            _sq_note_h    = _measure_wrapped(rc, _SQ_NOTE, "Inter", 9.5, CONTENT_W, 14.5)
            _sq_bullets_h = sum(
                _measure_wrapped(rc, f"· {sq}", "Mono", 8, CONTENT_W - 10, 12.5) + 4
                for sq in sub_queries
            )
            _sq_total_h = 30 + 4 + _sq_note_h + 10 + _sq_bullets_h + 8
            cy = chk(cy, _sq_total_h, fp)
            cy = _section_header(rc, MARGIN_X, cy, "Query Expansion",
                                 f"{len(sub_queries)} sub-queries generated")
            cy -= 4
            cy = _wrapped_text(rc, MARGIN_X, cy, _SQ_NOTE, "Inter", 9.5, C_INK_SEC,
                               CONTENT_W, 14.5)
            cy -= 10
            for sq in sub_queries:
                cy = _wrapped_text(rc, MARGIN_X + 8, cy, f"· {sq}", "Mono", 8,
                                   C_INK_SEC, CONTENT_W - 10, 12.5)
                cy -= 4
            cy -= 8

        cy = chk(cy, 120, fp)
        cy = _section_header(rc, MARGIN_X, cy, "Retrieval & Generation Parameters")
        cy -= 8

        col_w = (CONTENT_W - 1) / 2
        left_rows = [
            ("Retrieval mode",  retrieval.get("query_depth", "standard").title()),
            ("Top-K",           str(retrieval.get("top_k", 10))),
            ("Min similarity",  str(retrieval.get("score_threshold", 0.60))),
            ("Sub-queries",     str(retrieval.get("sub_query_count", 3))),
            ("Agency filter",   filters_raw.get("agency") or "All"),
            ("Doc type filter", filters_raw.get("document_type") or "All"),
            ("Date from",       filters_raw.get("date_from") or "—"),
            ("Date to",         filters_raw.get("date_to") or "—"),
        ]
        right_rows = [
            ("Generation model", generation_model),
            ("Prompt version",   prompt_version),
            ("Embedding model",  embedding_model),
            ("Inference",        "Ollama (local)"),
            ("Query expansion",  "Enabled" if sub_queries else "Disabled"),
            ("Trace ID",         langfuse_id),
            ("Routing Path",     routing_label),
            ("Classifier",       classifier),
        ]
        box_h = max(len(left_rows), len(right_rows)) * 13 + 30
        cy = chk(cy, box_h + 20, fp)
        _rect(rc, MARGIN_X, cy - box_h, CONTENT_W, box_h, fill=C_WHITE, stroke=C_BORDER, lw=0.75)
        _line(rc, MARGIN_X + col_w, cy - box_h, MARGIN_X + col_w, cy, C_BORDER, lw=0.75)
        lcy = cy - 14
        _text(rc, MARGIN_X + 10, lcy, "RETRIEVAL", "Inter-SemiBold", 7.5, C_ACCENT)
        _line(rc, MARGIN_X + 10, lcy - 3, MARGIN_X + col_w - 10, lcy - 3, C_ACCENT, lw=0.75)
        lcy -= 16
        for key, val in left_rows:
            _text(rc, MARGIN_X + 10, lcy, key, "Mono", 8.5, C_INK_TER)
            _text(rc, MARGIN_X + col_w - 10, lcy, val, "Mono", 8.5, C_INK, align="right")
            lcy -= 13
        rcy = cy - 14
        rx0 = MARGIN_X + col_w + 10
        _text(rc, rx0, rcy, "GENERATION", "Inter-SemiBold", 7.5, C_ACCENT)
        _line(rc, rx0, rcy - 3, MARGIN_X + CONTENT_W - 10, rcy - 3, C_ACCENT, lw=0.75)
        rcy -= 16
        for key, val in right_rows:
            _text(rc, rx0, rcy, key, "Mono", 8.5, C_INK_TER)
            _text(rc, MARGIN_X + CONTENT_W - 10, rcy, val, "Mono", 8.5, C_INK, align="right")
            rcy -= 13
        cy = cy - box_h - 28

        if cited_chunks:
            is_metadata_citation = (routing_path == "METADATA")

            section_heading = (
                "Referenced Documents"
                if is_metadata_citation else
                f"Source Evidence — {len(cited_chunks)} Cited Source{'s' if len(cited_chunks) != 1 else ''}"
            )
            cy = chk(cy, 80, fp)
            cy = _section_header(rc, MARGIN_X, cy, section_heading, "")
            cy -= 4
            if is_metadata_citation:
                intro = (
                    f"{len(cited_chunks)} document{'s' if len(cited_chunks) != 1 else ''} matched from the "
                    f"document registry. These are document-level references, not retrieved text chunks. "
                    f"Verify currency against the live corpus before relying on any source."
                )
            else:
                intro = (
                    f"This export contains {len(cited_chunks)} source{'s' if len(cited_chunks) != 1 else ''} "
                    f"cited by the AI in its answer. "
                    f"Provenance metadata is reproduced exactly as recorded at ingestion; "
                    f"verify currency against the live corpus before relying on any source."
                )
            cy = _wrapped_text(rc, MARGIN_X, cy, intro, "Inter", 9.5, C_INK_SEC, CONTENT_W, 14.5)
            cy -= 14

            for idx, chunk in enumerate(cited_chunks):
                superseded = chunk.get("superseded", False)
                title_c    = (chunk.get("document_title") or "—")[:80]
                agency     = chunk.get("issuing_body") or "—"
                version_raw = chunk.get("document_version") or ""
                version    = version_raw if (version_raw and version_raw != "1.0") else "—"
                clause     = chunk.get("clause_id") or "Not available"
                pub_date   = chunk.get("publication_date") or "Not available"
                page_no    = str(chunk.get("page_no") or "—")
                doc_type   = chunk.get("doc_type") or chunk.get("document_type") or "Not classified"
                chunk_txt  = chunk.get("chunk_text") or ""
                score      = chunk.get("score")
                score_str  = f"{score:.3f}" if score is not None else "—"
                trace_id   = chunk.get("trace_id") or chunk.get("chunk_id") or "—"
                chunked_at = chunk.get("chunked_at") or "—"
                source_url   = chunk.get("source_url") or "—"
                source_local = chunk.get("source_local_path") or ""
                DISPLAY_CHARS = 700
                max_ln        = 8
                truncated     = len(chunk_txt) > DISPLAY_CHARS
                display_txt   = chunk_txt[:DISPLAY_CHARS] if truncated else chunk_txt

                META_ROW_H    = 22
                META_ROWS     = 3
                HEAD_TOP      = 22
                HEAD_META_GAP = 24

                if is_metadata_citation:
                    # Compact card: head + metadata grid + footer line — no chunk text, no traces
                    FOOTER_H   = 16
                    card_h = HEAD_TOP + HEAD_META_GAP + META_ROWS * META_ROW_H + FOOTER_H
                else:
                    draw_w  = CONTENT_W - 28
                    ctxt_h  = _measure_wrapped(rc, display_txt or "—", "Mono", 8.5,
                                               draw_w, 13.5) if display_txt else 14
                    ctxt_h  = min(ctxt_h, max_ln * 13.5)
                    trunc_row     = 14 if truncated else 0
                    META_CHUNK_GAP = 8
                    ctxt_pad      = 9
                    LBL_H         = 12
                    ctxt_box_h    = ctxt_h + ctxt_pad * 2 + trunc_row + LBL_H
                    src_display = source_url[:90] + ("…" if len(source_url) > 90 else "")
                    loc_display = source_local[:80] + ("…" if len(source_local) > 80 else "")
                    trace_max_w   = CONTENT_W - 20
                    src2_h = _measure_wrapped(rc, f"Source  {src_display}", "Mono", 7.5, trace_max_w, 11)
                    src3_h = (_measure_wrapped(rc, f"File  {loc_display}", "Mono", 7.5, trace_max_w, 11)
                              if source_local else 0)
                    TRACE_BLOCK = 8 + 10 + 11 + src2_h + (11 + src3_h if source_local else 0) + 10
                    card_h = (HEAD_TOP + HEAD_META_GAP + META_ROWS * META_ROW_H
                              + META_CHUNK_GAP + ctxt_box_h + TRACE_BLOCK)

                cy = chk(cy, card_h + 18, fp)

                card_is_alt = (idx % 2 == 1)
                bg     = C_ROW_ALT if card_is_alt else C_WHITE
                box_bg = _rgb("E8EEF4")
                _rect(rc, MARGIN_X, cy - card_h, CONTENT_W, card_h, fill=bg, stroke=C_BORDER, lw=0.75)

                # ── head row ──────────────────────────────────────────────────
                head_y = cy - HEAD_TOP
                bx = MARGIN_X + 14
                rc.saveState()
                rc.setFillColorRGB(*C_ACCENT)
                rc.circle(bx, head_y, 9.0, fill=1, stroke=0)
                rc.setFillColorRGB(*C_WHITE)
                rc.setFont("Inter-Bold", 8.0)
                rc.drawCentredString(bx, head_y - 2.8, str(idx + 1))
                rc.restoreState()

                _text(rc, MARGIN_X + 30, head_y - 3, title_c, "Inter-SemiBold", 10.5, C_INK)

                badge_txt = "● SUPERSEDED" if superseded else "● ACTIVE"
                badge_fg  = C_WARN_TEXT if superseded else C_STATUS_OK
                badge_bg  = C_STATUS_AMB_BG if superseded else C_STATUS_OK_BG
                bw, bh = 64, 14
                bx2 = MARGIN_X + CONTENT_W - bw - 8
                by2 = head_y - 12
                _rect(rc, bx2, by2, bw, bh, fill=badge_bg, stroke=None, radius=3)
                _text(rc, bx2 + bw / 2, by2 + 3.5, badge_txt, "Inter-SemiBold", 7.5,
                      badge_fg, align="center")

                # ── metadata grid 3×3 ─────────────────────────────────────────
                meta_y = cy - HEAD_TOP - HEAD_META_GAP
                if is_metadata_citation:
                    doc_id = chunk.get("document_id") or "—"
                    cells = [
                        ("Agency",      agency),     ("Version",   version[:32]),  ("Doc type",  doc_type),
                        ("Published",   pub_date),   ("Clause ID", clause),        ("Page",      page_no),
                        ("Document ID", doc_id[:32]),("",          ""),            ("",          ""),
                    ]
                else:
                    cells = [
                        ("Agency",      agency),     ("Version",   version[:32]),  ("Doc type",  doc_type),
                        ("Published",   pub_date),   ("Clause ID", clause),        ("Page",      page_no),
                        ("Similarity",  score_str),  ("",          ""),            ("",          ""),
                    ]
                col_w3 = CONTENT_W / 3
                for ci, (k, v) in enumerate(cells):
                    if not k:
                        continue
                    cx3   = MARGIN_X + (ci % 3) * col_w3 + 10
                    row_y = meta_y - (ci // 3) * META_ROW_H
                    _text(rc, cx3, row_y, k, "Mono", 7.5, C_INK_TER)
                    _text(rc, cx3, row_y - 12, (v or "—")[:32], "Mono", 9.0, C_INK)

                if is_metadata_citation:
                    # ── document registry reference footer ────────────────────
                    footer_y = meta_y - META_ROWS * META_ROW_H - 6
                    _text(rc, MARGIN_X + 14, footer_y,
                          "Document registry reference  ·  No chunk text retrieved",
                          "Mono", 7.5, C_INK_TER)
                else:
                    # ── chunk text box ────────────────────────────────────────
                    chunk_y = meta_y - META_ROWS * META_ROW_H - META_CHUNK_GAP
                    _rect(rc, MARGIN_X + 8, chunk_y - ctxt_box_h, CONTENT_W - 16, ctxt_box_h,
                          fill=box_bg, stroke=C_BORDER, lw=0.75)
                    # "Chunk text" label at top of box
                    _text(rc, MARGIN_X + 14, chunk_y - 12,
                          "Chunk text", "Inter-SemiBold", 8.0, C_INK_TER)
                    txt_draw_y = chunk_y - LBL_H - ctxt_pad - 2
                    if truncated:
                        _text(rc, MARGIN_X + 16, txt_draw_y,
                              f"[Truncated — first {DISPLAY_CHARS} of {len(chunk_txt)} chars shown."
                              f" Full text in source document.]",
                              "Mono", 7.5, C_INK_TER)
                        txt_draw_y -= 18
                    _wrapped_text(rc, MARGIN_X + 16, txt_draw_y,
                                  (display_txt or "—").replace("\n", " "), "Mono", 8.5,
                                  _rgb("1E293B"), draw_w - 4, 13.5)

                    # ── trace lines (tight below text box) ────────────────────
                    tl1_y = chunk_y - ctxt_box_h - 8
                    _text(rc, MARGIN_X + 10, tl1_y,
                          f"Ingested  {chunked_at[:10]}   Trace ID  {trace_id}",
                          "Mono", 7.5, C_INK_TER)
                    _wrapped_text(rc, MARGIN_X + 10, tl1_y - 11,
                                  f"Source  {src_display}",
                                  "Mono", 7.5, C_INK_TER, trace_max_w, 11)
                    if source_local:
                        _wrapped_text(rc, MARGIN_X + 10, tl1_y - 11 - src2_h,
                                      f"File  {loc_display}",
                                      "Mono", 7.5, C_INK_TER, trace_max_w, 11)
                cy -= card_h + 18

            _line(rc, MARGIN_X, cy + 4, MARGIN_X + CONTENT_W, cy + 4, C_BORDER)

        if uncited_chunks:
            cy -= 20
            cy = chk(cy, 80, fp)
            n_unc = len(uncited_chunks)
            cy = _section_header(
                rc, MARGIN_X, cy,
                f"Retrieved but Not Cited — {n_unc} chunk{'s' if n_unc != 1 else ''}",
            )
            cy -= 4
            unc_note = (
                "These chunks were retrieved by the system but were not used by the model "
                "to generate the answer. Included for audit completeness."
            )
            cy = _wrapped_text(rc, MARGIN_X, cy, unc_note, "Inter", 9.5, C_INK_SEC,
                               CONTENT_W, 14.5)
            cy -= 10

            _UNC_META_ROW_H    = 22
            _UNC_META_ROWS     = 3
            _UNC_HEAD_TOP      = 22
            _UNC_HEAD_META_GAP = 24

            for idx, chunk in enumerate(uncited_chunks):
                uc_title    = (chunk.get("document_title") or "—")[:80]
                uc_agency   = chunk.get("issuing_body") or "—"
                uc_version_raw = chunk.get("document_version") or ""
                uc_version  = uc_version_raw if (uc_version_raw and uc_version_raw != "1.0") else "—"
                uc_pub_date = chunk.get("publication_date") or "Not available"
                uc_clause   = chunk.get("clause_id") or "Not available"
                uc_page_no  = str(chunk.get("page_no") or "—")
                uc_doc_type = chunk.get("doc_type") or chunk.get("document_type") or "Not classified"
                uc_score    = chunk.get("score")
                uc_score_str = f"{uc_score:.3f}" if uc_score is not None else "—"
                uc_trace_id  = chunk.get("trace_id") or chunk.get("chunk_id") or "—"
                uc_chunked   = chunk.get("chunked_at") or "—"
                uc_url       = chunk.get("source_url") or "—"
                uc_local     = chunk.get("source_local_path") or ""

                uc_src_disp = uc_url[:90] + ("…" if len(uc_url) > 90 else "")
                uc_loc_disp = uc_local[:80] + ("…" if len(uc_local) > 80 else "")
                uc_trace_max_w = CONTENT_W - 20
                uc_src2_h   = _measure_wrapped(rc, f"Source  {uc_src_disp}", "Mono", 7.5, uc_trace_max_w, 11)
                uc_src3_h   = (_measure_wrapped(rc, f"File  {uc_loc_disp}", "Mono", 7.5, uc_trace_max_w, 11)
                               if uc_local else 0)
                _UNC_TRACE_BLOCK = 8 + 10 + 11 + uc_src2_h + (11 + uc_src3_h if uc_local else 0) + 10
                unc_card_h = (_UNC_HEAD_TOP + _UNC_HEAD_META_GAP
                              + _UNC_META_ROWS * _UNC_META_ROW_H + _UNC_TRACE_BLOCK)

                cy = chk(cy, unc_card_h + 18, fp)

                uc_alt = (idx % 2 == 1)
                uc_bg  = C_ROW_ALT if uc_alt else C_WHITE
                _rect(rc, MARGIN_X, cy - unc_card_h, CONTENT_W, unc_card_h,
                      fill=uc_bg, stroke=C_BORDER, lw=0.75)

                # head row — muted badge to distinguish from cited
                uc_head_y = cy - _UNC_HEAD_TOP
                rc.saveState()
                rc.setFillColorRGB(*C_INK_TER)
                rc.circle(MARGIN_X + 14, uc_head_y, 9.0, fill=1, stroke=0)
                rc.setFillColorRGB(*C_WHITE)
                rc.setFont("Inter-Bold", 8.0)
                rc.drawCentredString(MARGIN_X + 14, uc_head_y - 2.8, str(idx + 1))
                rc.restoreState()
                _text(rc, MARGIN_X + 30, uc_head_y - 3, uc_title, "Inter-SemiBold", 10.5, C_INK_SEC)

                # metadata grid 3×3
                uc_meta_y = cy - _UNC_HEAD_TOP - _UNC_HEAD_META_GAP
                uc_cells = [
                    ("Agency",     uc_agency),    ("Version",   uc_version[:32]),  ("Doc type",  uc_doc_type),
                    ("Published",  uc_pub_date),  ("Clause ID", uc_clause),        ("Page",      uc_page_no),
                    ("Similarity", uc_score_str), ("",          ""),               ("",          ""),
                ]
                uc_col_w3 = CONTENT_W / 3
                for ci, (k, v) in enumerate(uc_cells):
                    if not k:
                        continue
                    uc_cx = MARGIN_X + (ci % 3) * uc_col_w3 + 10
                    uc_ry = uc_meta_y - (ci // 3) * _UNC_META_ROW_H
                    _text(rc, uc_cx, uc_ry, k, "Mono", 7.5, C_INK_TER)
                    _text(rc, uc_cx, uc_ry - 12, (v or "—")[:32], "Mono", 9.0, C_INK)

                # trace lines (tight below metadata grid)
                uc_tl1_y = uc_meta_y - _UNC_META_ROWS * _UNC_META_ROW_H - 8
                _text(rc, MARGIN_X + 10, uc_tl1_y,
                      f"Ingested  {uc_chunked[:10]}   Trace ID  {uc_trace_id}",
                      "Mono", 7.5, C_INK_TER)
                _wrapped_text(rc, MARGIN_X + 10, uc_tl1_y - 11,
                              f"Source  {uc_src_disp}",
                              "Mono", 7.5, C_INK_TER, uc_trace_max_w, 11)
                if uc_local:
                    _wrapped_text(rc, MARGIN_X + 10, uc_tl1_y - 11 - uc_src2_h,
                                  f"File  {uc_loc_disp}",
                                  "Mono", 7.5, C_INK_TER, uc_trace_max_w, 11)

                cy -= unc_card_h + 18

            _line(rc, MARGIN_X, cy + 4, MARGIN_X + CONTENT_W, cy + 4, C_BORDER)

        rc.save()
        return rbuf, st.num

    # pass 1 — count pages
    _, total_pages = _render(total_pages_known=0)
    # pass 2 — render with correct total
    final_buf, _ = _render(total_pages_known=total_pages)
    pdf_bytes = final_buf.getvalue()

    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    return pdf_bytes


# ── Compact Audit Log PDF ─────────────────────────────────────────────────────

def generate_audit_log_pdf(
    queries: list[dict],
    filters_applied: dict,
    corpus_date: str,
    system_version: str,
) -> bytes:
    """
    Generate a compact audit log PDF covering multiple queries.

    Each query occupies one page maximum. No retrieval parameters,
    no chunk text. Designed for inspector review of a session.
    """
    import html as _html
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak,
        HRFlowable, KeepTogether, BaseDocTemplate, PageTemplate, Frame,
    )
    from reportlab.platypus.flowables import HRFlowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from io import BytesIO

    _register_fonts()

    buffer = BytesIO()

    A4_W, A4_H = A4  # 595.27 x 841.89 pt
    MARGIN = 20 * mm  # ~56.7 pt
    CONT_W = A4_W - 2 * MARGIN

    # ── styles ──────────────────────────────────────────────────────────────────
    MUTED     = _rgb("6B7280")
    BRAND_BG  = _rgb("0F172A")

    style_cover_title = ParagraphStyle(
        "AuditCoverTitle", fontName="Inter-Bold", fontSize=18,
        textColor=C_INK, spaceAfter=6, leading=22,
    )
    style_cover_sub = ParagraphStyle(
        "AuditCoverSub", fontName="Mono", fontSize=8,
        textColor=C_INK_TER, spaceAfter=2, leading=13,
    )
    style_cover_body = ParagraphStyle(
        "AuditCoverBody", fontName="Inter", fontSize=9.5,
        textColor=C_INK_SEC, spaceAfter=3, leading=14,
    )
    style_cover_disclaimer = ParagraphStyle(
        "AuditDisclaimer", fontName="Inter-Medium", fontSize=8.5,
        textColor=C_WARN_TEXT, spaceAfter=0, leading=13,
    )
    style_query_meta = ParagraphStyle(
        "AuditQMeta", fontName="Mono", fontSize=7.5,
        textColor=C_INK_TER, spaceAfter=4, leading=11,
    )
    style_query_label = ParagraphStyle(
        "AuditQLabel", fontName="Mono", fontSize=7,
        textColor=MUTED, spaceAfter=3, leading=10,
    )
    style_query_text = ParagraphStyle(
        "AuditQText", fontName="Inter-SemiBold", fontSize=10,
        textColor=C_INK, spaceAfter=8, leading=14,
    )
    style_answer = ParagraphStyle(
        "AuditAnswer", fontName="Inter", fontSize=9,
        textColor=C_INK, spaceAfter=8, leading=13,
    )
    style_answer_label = ParagraphStyle(
        "AuditALabel", fontName="Mono", fontSize=7,
        textColor=MUTED, spaceAfter=3, leading=10,
    )
    style_sources_label = ParagraphStyle(
        "AuditSrcLabel", fontName="Mono", fontSize=7,
        textColor=MUTED, spaceAfter=3, leading=10,
    )
    style_source_line = ParagraphStyle(
        "AuditSrcLine", fontName="Inter", fontSize=8,
        textColor=C_INK_SEC, spaceAfter=1, leading=11,
    )
    style_no_src = ParagraphStyle(
        "AuditNoSrc", fontName="Inter-Italic", fontSize=8,
        textColor=C_INK_TER, spaceAfter=4, leading=11,
    )
    style_trace = ParagraphStyle(
        "AuditTrace", fontName="Mono", fontSize=7,
        textColor=C_INK_TER, spaceAfter=0, leading=10,
    )

    export_ts = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        _local = datetime.now(ZoneInfo("Europe/Brussels"))
    except Exception:
        _local = export_ts
    export_ts_str = _local.strftime("%d.%m.%Y %H:%M") + " CET"
    export_id = f"AUDIT-{export_ts.strftime('%Y%m%d-%H%M%S')}"

    def _esc(text: str) -> str:
        return _html.escape(text or "", quote=False)

    # ── build filter summary string ────────────────────────────────────────────
    filter_parts = []
    df = filters_applied.get("date_from")
    dt = filters_applied.get("date_to")
    if df or dt:
        filter_parts.append(f"{df or '—'} to {dt or '—'}")
    if filters_applied.get("search"):
        filter_parts.append(f'Search: "{filters_applied["search"]}"')
    rp = filters_applied.get("routing_path")
    if rp:
        filter_parts.append(f"Routing: {rp}")
    pv = filters_applied.get("prompt_version")
    if pv:
        filter_parts.append(f"Prompt: {pv}")
    filter_str = " · ".join(filter_parts) if filter_parts else "No filters — full history"

    story = []

    # ═══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 32 * mm))
    story.append(Paragraph("ownedpulse", style_cover_title))
    story.append(Paragraph("REGULATORY INTELLIGENCE · OWNEDAI", style_cover_sub))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_rgb("2563EB"),
                             spaceAfter=6*mm))
    story.append(Paragraph("Query Session Audit Log", ParagraphStyle(
        "AuditTitle2", parent=style_cover_title, fontSize=14, fontName="Inter-SemiBold",
    )))
    story.append(Spacer(1, 6 * mm))

    cover_rows = [
        ("Export ID",  export_id),
        ("Generated",  export_ts_str),
        ("Corpus date", corpus_date),
        ("System",     f"ownedpulse {system_version}"),
        ("Filters",    filter_str),
        ("Total queries", str(len(queries))),
    ]
    for label, value in cover_rows:
        story.append(Paragraph(
            f'<font color="#6B7280">{label}:</font>  {_esc(value)}',
            style_cover_body,
        ))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER,
                             spaceAfter=4*mm))
    story.append(Paragraph(
        "▲ This output is informational. Human review required before any GxP decision.",
        style_cover_disclaimer,
    ))
    story.append(PageBreak())

    # ── page geometry constants (shared with header/footer callbacks) ───────
    hdr_h = 18 * mm
    ftr_y = 14 * mm

    # ═══════════════════════════════════════════════════════════════════════════
    # QUERY PAGES
    # ═══════════════════════════════════════════════════════════════════════════
    for idx, q in enumerate(queries):
        ts = q.get("timestamp", "")
        if ts:
            try:
                dt_val = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                ts_str = dt_val.strftime("%d.%m.%Y %H:%M UTC")
            except Exception:
                ts_str = str(ts)[:19]
        else:
            ts_str = "—"

        qid_short = str(q.get("query_id", ""))[:8]
        routing = q.get("routing_path") or "—"
        prompt_ver = q.get("prompt_version") or "—"
        routing_label = "Metadata lookup" if routing == "METADATA" else "Semantic search"

        # Header bar
        header_text = (
            f"[{_esc(qid_short)}]  {_esc(ts_str)}  ·  "
            f"{_esc(routing_label)}  ·  {_esc(prompt_ver)}"
        )

        # Answer — full text since each query has its own page
        answer_display = _esc(q.get("answer") or "")

        # Cited sources — one line each, max 10
        citations = q.get("citations") or []
        cited = [c for c in citations if c.get("cited_by_llm")]

        source_blocks = []
        for i, c in enumerate(cited[:10]):
            title = (c.get("document_title") or c.get("document_id") or "Unknown")[:70]
            issuing = (c.get("issuing_body") or "").strip()
            pub_date = str(c.get("publication_date") or "")[:4]
            clause = (c.get("clause_id") or "").strip()
            score = c.get("score")

            parts = [f"[{i + 1}] {_esc(title)}"]
            if issuing:
                parts.append(_esc(issuing))
            if pub_date and pub_date != "None":
                parts.append(pub_date)
            if clause and clause != "Not available":
                parts.append(f"§{_esc(clause)}")
            if score is not None:
                parts.append(f"sim={score:.3f}")

            source_blocks.append(Paragraph(" · ".join(parts), style_source_line))

        trace_id = str(q.get("langfuse_trace_id") or "")[:36]

        # Assemble query block
        block_items = [
            HRFlowable(width="100%", thickness=1, color=C_ACCENT, spaceAfter=4),
            Paragraph(_esc(header_text), style_query_meta),
            Spacer(1, 2 * mm),
            Paragraph("QUERY", style_query_label),
            Paragraph(_esc(q.get("query_text", "")), style_query_text),
            Paragraph("ANSWER", style_answer_label),
            Paragraph(answer_display, style_answer),
        ]

        if source_blocks:
            block_items.append(Paragraph("CITED SOURCES", style_sources_label))
            block_items.extend(source_blocks)
            block_items.append(Spacer(1, 2 * mm))
        else:
            block_items.append(Paragraph(
                "No sources cited", style_no_src,
            ))

        if trace_id:
            block_items.append(Paragraph(
                f"Trace: {_esc(trace_id)}", style_trace,
            ))

        story.append(KeepTogether(block_items))

        if idx < len(queries) - 1:
            story.append(PageBreak())

    # ── header / footer callbacks ──────────────────────────────────────────────
    def _on_page(canvas_obj, doc):
        canvas_obj.saveState()

        # Header — branded bar at top
        hdr_h = 18 * mm
        canvas_obj.setFillColorRGB(*BRAND_BG)
        canvas_obj.rect(0, A4_H - hdr_h, A4_W, hdr_h, fill=1, stroke=0)

        canvas_obj.setFont("Inter-SemiBold", 10)
        canvas_obj.setFillColorRGB(*C_WHITE)
        canvas_obj.drawString(MARGIN, A4_H - 10 * mm, "ownedpulse  AUDIT LOG")

        canvas_obj.setFont("Mono", 7)
        canvas_obj.setFillColorRGB(*C_SHELL_MUTED)
        canvas_obj.drawString(MARGIN, A4_H - 14 * mm, export_id)
        canvas_obj.drawRightString(
            A4_W - MARGIN, A4_H - 14 * mm,
            f"Generated: {export_ts_str}",
        )
        canvas_obj.setStrokeColorRGB(*C_BORDER)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(MARGIN, A4_H - hdr_h, A4_W - MARGIN, A4_H - hdr_h)

        # Footer
        ftr_y = 14 * mm
        canvas_obj.line(MARGIN, ftr_y, A4_W - MARGIN, ftr_y)
        canvas_obj.setFont("Mono", 7)
        canvas_obj.setFillColorRGB(*C_INK_TER)
        canvas_obj.drawString(
            MARGIN, ftr_y - 5 * mm,
            f"Page {canvas_obj.getPageNumber()}  ·  {export_id}  ·  {export_ts_str}",
        )
        canvas_obj.drawRightString(
            A4_W - MARGIN, ftr_y - 5 * mm,
            "Confidential — Internal Use",
        )

        canvas_obj.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=hdr_h + 4 * mm,
        bottomMargin=ftr_y,
    )

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

    buffer.seek(0)
    return buffer.read()
