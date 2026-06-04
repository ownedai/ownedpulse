"""
Branded regpulse query export PDF generator.
Matches the ownedai design spec: dark shell header, warning band, query/answer,
parameters box, source evidence cards with provenance metadata.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
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
    _text(c, wx, wy_word, "regpulse", "Inter-SemiBold", 18, C_WHITE)
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
    _text(c, wx, wy, "regpulse", "Inter-SemiBold", 14, C_WHITE)
    right_txt = f"Export ID {export_id}  ·  Source Evidence (cont.)"
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
    _text(c, PAGE_W - MARGIN_X, cy + 2, "Confidential — Internal Use",
          "Inter", 8.5, C_INK_SEC, align="right")


# ── section header helper ──────────────────────────────────────────────────────

def _section_header(c: canvas.Canvas, x, y, label: str, index_label: str = "") -> float:
    """Draw blue-rule section header, return y after it."""
    _text(c, x, y, label.upper(), "Inter-SemiBold", 9, C_ACCENT)
    if index_label:
        _text(c, x + CONTENT_W, y, index_label, "Mono", 8.5, C_INK_TER, align="right")
    y -= 5
    _line(c, x, y, x + CONTENT_W, y, C_ACCENT, lw=2.0)
    return y - 10


# ── citation marker inline rendering (plain-text fallback) ────────────────────

def _strip_citation_markers(text: str) -> str:
    return re.sub(r"\[(\d+)\]", r"[\1]", text)


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
    Build branded regpulse query export PDF.
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
    timestamp_iso = query_response.get("timestamp") or datetime.now(timezone.utc).isoformat()

    cited_chunks   = [c for c in citations if c.get("cited_by_llm")]
    uncited_chunks = [c for c in citations if not c.get("cited_by_llm")]
    all_chunks     = cited_chunks + uncited_chunks

    routing_label = "Metadata lookup" if routing_path == "METADATA" else "Semantic search"

    # ── export metadata ────────────────────────────────────────────────────────
    now_utc  = datetime.now(timezone.utc)
    short_id = query_id[:8] if len(query_id) >= 8 else query_id
    export_id = f"QRY-{now_utc.strftime('%Y-%m-%d')}-{short_id}"
    exported  = now_utc.strftime("%d/%m/%Y %H:%M UTC")

    # Try to get system info from DB; fall back gracefully
    corpus_snapshot = "—"
    generation_model = retrieval.get("model") or "phi4:14b-q8_0"
    embedding_model  = "mxbai-embed-large"
    prompt_version   = "V6"
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
        generation_model  = cfg.get("active_llm_model", generation_model)
        corpus_snapshot   = cfg.get("corpus_snapshot_date", "2026-06-01")
        prompt_version    = cfg.get("prompt_version", "V6")
        _conn.close()
    except Exception:
        pass

    system_str = f"regpulse v1.0 · {embedding_model} · {generation_model}"

    # ── two-pass render: pass 1 counts pages; pass 2 renders with correct total ─
    def _render(total_pages_known: int) -> tuple["canvas.Canvas", BytesIO, int]:
        rbuf = BytesIO()
        rc = canvas.Canvas(rbuf, pagesize=letter)
        rc.setTitle(f"regpulse Export — {short_id}")
        rc.setAuthor("ownedai / regpulse")
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

        clean_answer = _strip_citation_markers(answer)
        for para in [p.strip() for p in clean_answer.split("\n\n") if p.strip()]:
            h = _measure_wrapped(rc, para, "Inter", 10.5, CONTENT_W, 17.5)
            cy = chk(cy, h + 8, fp)
            cy = _wrapped_text(rc, MARGIN_X, cy, para, "Inter", 10.5, C_INK, CONTENT_W, 17.5)
            cy -= 8

        cy -= 4
        meta = (
            f"{query_id[:8]}  ·  {routing_label}  ·  "
            f"retrieved {len(citations)} chunks  ·  cited {len(cited_chunks)} chunks  ·  {generation_model}"
        )
        _text(rc, MARGIN_X, cy, meta, "Mono", 8, C_INK_TER)
        cy -= 20

        if sub_queries:
            cy = chk(cy, 30, fp)
            _text(rc, MARGIN_X, cy, "Query Expansion", "Inter-SemiBold", 8.5, C_INK_SEC)
            cy -= 12
            for sq in sub_queries:
                h = _measure_wrapped(rc, f"· {sq}", "Mono", 8, CONTENT_W - 10, 12.5)
                cy = chk(cy, h + 4, fp)
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
            ("Langfuse trace",   langfuse_id[:24] if langfuse_id != "—" else "—"),
        ]
        box_h = max(len(left_rows), len(right_rows)) * 14 + 36
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
        cy = cy - box_h - 16

        if all_chunks:
            new_page(is_first=False)
            cy = BODY_TOP_CONT
            cy = _section_header(rc, MARGIN_X, cy,
                                 f"Source Evidence — {len(all_chunks)} Sources",
                                 f"{len(cited_chunks)} cited · {len(uncited_chunks)} retrieved only")
            cy -= 4
            intro = (
                f"This export contains {len(cited_chunks)} source{'s' if len(cited_chunks) != 1 else ''} "
                f"cited by the AI and {len(uncited_chunks)} retrieved but not cited. "
                f"Provenance metadata is reproduced exactly as recorded at ingestion; "
                f"verify currency against the live corpus before relying on any source."
            )
            cy = _wrapped_text(rc, MARGIN_X, cy, intro, "Inter", 9.5, C_INK_SEC, CONTENT_W, 14.5)
            cy -= 14

            for idx, chunk in enumerate(all_chunks):
                superseded = chunk.get("superseded", False)
                title_c    = (chunk.get("document_title") or "—")[:80]
                agency     = chunk.get("issuing_body") or "—"
                version    = chunk.get("document_version") or "—"
                clause     = chunk.get("clause_id") or "Not available"
                pub_date   = chunk.get("publication_date") or "Not available"
                page_no    = str(chunk.get("page_no") or "—")
                doc_type   = chunk.get("doc_type") or chunk.get("document_type") or "—"
                chunk_txt  = chunk.get("chunk_text") or ""
                score      = chunk.get("score")
                trace_id   = chunk.get("trace_id") or chunk.get("chunk_id") or "—"
                chunked_at = chunk.get("chunked_at") or "—"
                source_url = chunk.get("source_url") or "—"
                cited_c    = chunk.get("cited_by_llm", False)

                max_ln     = 8
                chunk_lines = chunk_txt.split("\n") if chunk_txt else []
                display_txt = "\n".join(chunk_lines[:max_ln])
                truncated   = len(chunk_lines) > max_ln or len(chunk_txt) > 900
                if truncated and not display_txt:
                    display_txt = chunk_txt[:600]

                ctxt_h = _measure_wrapped(rc, display_txt or "—", "Mono", 8.5,
                                          CONTENT_W - 24, 13.5) if display_txt else 14
                ctxt_h = min(ctxt_h, max_ln * 13.5)
                card_h = 22 + 40 + ctxt_h + 30 + (14 if truncated else 0) + 24

                cy = chk(cy, card_h + 12, fp)

                bg = C_WHITE if idx % 2 == 0 else C_ROW_ALT
                _rect(rc, MARGIN_X, cy - card_h, CONTENT_W, card_h, fill=bg, stroke=C_BORDER, lw=0.75)

                head_y = cy - 16
                bx = MARGIN_X + 14
                rc.saveState()
                rc.setFillColorRGB(*C_ACCENT)
                rc.circle(bx, head_y, 8.0, fill=1, stroke=0)
                rc.setFillColorRGB(*C_WHITE)
                rc.setFont("Inter-Bold", 7.5)
                rc.drawCentredString(bx, head_y - 2.5, str(idx + 1))
                rc.restoreState()

                _text(rc, MARGIN_X + 28, head_y - 3, title_c, "Inter-SemiBold", 10.5, C_INK)

                badge_txt = "● SUPERSEDED" if superseded else "● ACTIVE"
                badge_fg  = C_WARN_TEXT if superseded else C_STATUS_OK
                badge_bg  = C_STATUS_AMB_BG if superseded else C_STATUS_OK_BG
                bw, bh = 60, 13
                bx2 = MARGIN_X + CONTENT_W - bw - 6
                by2 = head_y - 11
                _rect(rc, bx2, by2, bw, bh, fill=badge_bg, stroke=None, radius=3)
                _text(rc, bx2 + bw / 2, by2 + 3, badge_txt, "Inter-SemiBold", 7, badge_fg, align="center")
                if not cited_c:
                    cw2, cx2 = 70, bx2 - 74
                    _rect(rc, cx2, by2, cw2, bh, fill=_rgb("F1F5F9"), stroke=C_BORDER_STR, lw=0.5, radius=3)
                    _text(rc, cx2 + cw2 / 2, by2 + 3, "NOT CITED", "Inter-SemiBold", 7, C_INK_SEC, align="center")

                meta_y = cy - 30
                cells = [
                    ("Agency", agency), ("Version", version), ("Doc type", doc_type),
                    ("Published", pub_date), ("Clause ID", clause), ("Page", page_no),
                ]
                col_w3 = CONTENT_W / 3
                for ci, (k, v) in enumerate(cells[:6]):
                    cx3 = MARGIN_X + (ci % 3) * col_w3 + 8
                    row_y = meta_y - (ci // 3) * 17
                    _text(rc, cx3, row_y, k, "Mono", 7.5, C_INK_TER)
                    _text(rc, cx3, row_y - 10, (v or "—")[:30], "Mono", 8.5, C_INK)

                chunk_y = meta_y - 38
                ctxt_pad = 7
                ctxt_box_h = ctxt_h + ctxt_pad * 2 + (12 if truncated else 0)
                _rect(rc, MARGIN_X + 8, chunk_y - ctxt_box_h, CONTENT_W - 16, ctxt_box_h,
                      fill=C_ROW_ALT, stroke=C_BORDER, lw=0.5)
                _wrapped_text(rc, MARGIN_X + 14, chunk_y - ctxt_pad - 10,
                              (display_txt or "—").replace("\n", " "), "Mono", 8.5,
                              _rgb("1E293B"), CONTENT_W - 28, 13.5)
                if truncated:
                    _text(rc, MARGIN_X + 14, chunk_y - ctxt_box_h + ctxt_pad,
                          f"▾ chunk continues — {len(chunk_txt)} chars total, "
                          f"showing first {max_ln} lines (full text in source document)",
                          "Mono", 7.5, C_INK_TER)

                trace_y = chunk_y - ctxt_box_h - 6
                _text(rc, MARGIN_X + 8, trace_y,
                      f"trace_id  {trace_id[:32]}   "
                      f"Ingested  {chunked_at[:10]}   "
                      f"Source  {source_url[:60]}",
                      "Mono", 7.5, C_INK_TER)
                cy -= card_h + 8

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
